#!/bin/bash
set -e

echo "==========================================="
echo " OmniBet AI EC2 Deployment Script"
echo "==========================================="

# 1. Update system and install dependencies
echo ">> Installing system dependencies (Nginx, Node, Python, SQLite, Redis)..."
sudo apt update
sudo apt install -y nginx python3-venv python3-pip curl git sqlite3 redis-server

# Enable and start Redis
sudo systemctl enable redis-server
sudo systemctl start redis-server

# Install Node.js 20 (LTS)
if ! command -v node >/dev/null 2>&1; then
    curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
    sudo apt install -y nodejs
fi

# 2. Build Frontend
echo ">> Building React Frontend..."
cd frontend
npm install
# Build with absolute path mapping so Nginx can reverse proxy
VITE_API_URL=/api npm run build
cd ..

# 3. Setup Python Backend Environment
echo ">> Setting up Python virtual environment..."
if [ ! -d ".venv" ]; then
    python3 -m venv .venv
fi
source .venv/bin/activate
pip install -r requirements.txt

# 4. Configure Nginx Reverse Proxy
echo ">> Configuring Nginx..."
# Grant Nginx permission to traverse the home directory
sudo chmod 755 /home/ubuntu

# Ensure backend data and asset directories exist and are writable
mkdir -p data/logos
mkdir -p assets/templates
mkdir -p assets/temp_cards
chmod -R 777 data
chmod -R 777 assets

sudo cp omnibet.nginx /etc/nginx/sites-available/omnibet
sudo ln -sf /etc/nginx/sites-available/omnibet /etc/nginx/sites-enabled/
# Remove default nginx welcome page
sudo rm -f /etc/nginx/sites-enabled/default
# Test and reload
sudo nginx -t
sudo systemctl restart nginx

# 5. Configure Systemd Daemon for FastAPI
echo ">> Configuring Systemd Service for Uvicorn..."
# IMPORTANT: Adjust user from User=ubuntu in omnibet.service if cloning as a different user
sudo cp omnibet.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable omnibet.service
sudo systemctl restart omnibet.service

# 6. Configure Systemd Daemon for Celery Worker
echo ">> Configuring Systemd Service for Celery Worker..."
sudo cp omnibet-celery.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable omnibet-celery.service
sudo systemctl restart omnibet-celery.service

echo "==========================================="
echo " Deployment Complete! 🚀"
echo " The frontend is running on Port 80."
echo " The backend is running via Systemd on Port 8000."
echo " To view API logs:    sudo journalctl -u omnibet.service -f"
echo " To view Celery logs: sudo journalctl -u omnibet-celery.service -f"
echo "==========================================="
