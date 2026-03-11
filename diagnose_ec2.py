import os
import sqlite3
import requests
import json
from datetime import datetime
from dotenv import load_dotenv

def diagnose():
    load_dotenv()
    print("=== OmniBet EC2 Diagnostic Tool ===\n")

    # 1. Environment & Time
    print(f"Server Time (UTC): {datetime.utcnow()}")
    print(f"Project Dir: {os.getcwd()}")
    
    db_exists = os.path.exists("omnibet.db")
    print(f"Database Found: {db_exists}")

    # 2. Database Settings
    if db_exists:
        try:
            conn = sqlite3.connect("omnibet.db")
            cursor = conn.cursor()
            cursor.execute("SELECT value FROM app_settings WHERE key = 'primary_provider'")
            provider = cursor.fetchone()
            print(f"Primary Provider (DB): {provider[0] if provider else 'football-data (default)'}")
            
            cursor.execute("SELECT COUNT(*) FROM daily_fixtures")
            count = cursor.fetchone()[0]
            print(f"Cached Days in DB: {count}")
            conn.close()
        except Exception as e:
            print(f"DB Error: {e}")

    # 3. API Keys
    fd_key = os.getenv("FOOTBALL_DATA_API_KEY")
    rapid_key = os.getenv("RAPID_API_KEY")
    gemini_key = os.getenv("GEMINI_API_KEY")
    
    print(f"\nAPI Keys Configured:")
    print(f"- Football-Data: {'✅ Set' if fd_key else '❌ MISSING'}")
    print(f"- RapidAPI: {'✅ Set' if rapid_key else '❌ MISSING (Required for Grading)'}")
    print(f"- Gemini: {'✅ Set' if gemini_key else '❌ MISSING'}")

    # 4. Connectivity Test
    print("\nConnectivity Tests:")
    
    # Football-Data
    try:
        fd_res = requests.get("https://api.football-data.org/v4/competitions", headers={"X-Auth-Token": fd_key or ""}, timeout=10)
        print(f"- Football-Data.org: {fd_res.status_code} ({'Unauthorized' if fd_res.status_code == 401 else 'OK' if fd_res.status_code == 200 else 'Error'})")
    except Exception as e:
        print(f"- Football-Data.org: ❌ Failed ({e})")

    # SofaScore (Web API)
    try:
        from curl_cffi import requests as cffi_requests
        sf_res = cffi_requests.get("https://api.sofascore.com/api/v1/sport/football/scheduled-events/2026-03-12", impersonate="chrome120", timeout=10)
        print(f"- SofaScore (via curl_cffi): {sf_res.status_code} ({'BLOCKED' if sf_res.status_code == 403 else 'OK' if sf_res.status_code == 200 else 'Error'})")
    except ImportError:
        print("- SofaScore (via curl_cffi): ❌ curl_cffi NOT INSTALLED")
    except Exception as e:
        print(f"- SofaScore: ❌ Failed ({e})")

    print("\n=== End of Diagnostic ===")

if __name__ == "__main__":
    diagnose()
