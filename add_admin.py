import sqlite3
from src.utils.auth import get_password_hash
import sys

def add_admin(username, password):
    conn = sqlite3.connect('omnibet.db')
    cursor = conn.cursor()
    hashed_password = get_password_hash(password)

    cursor.execute('SELECT id FROM users WHERE username = ?', (username,))
    if cursor.fetchone():
        cursor.execute('UPDATE users SET password_hash = ?, role = ? WHERE username = ?', (hashed_password, 'admin', username))
        print(f"Updated existing user '{username}' to admin with new password.")
    else:
        cursor.execute('INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)', (username, hashed_password, 'admin'))
        print(f"Created new admin user '{username}'.")

    conn.commit()
    conn.close()

if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python add_admin.py <username> <password>")
        sys.exit(1)
    
    add_admin(sys.argv[1], sys.argv[2])
