import requests
import os
from dotenv import load_dotenv
import json
from datetime import datetime, timedelta

load_dotenv()

API_KEY = os.getenv("FOOTBALL_DATA_API_KEY")
BASE_URL = "https://api.football-data.org/v4"

def find_and_inspect_match(team_name="Barcelona"):
    headers = {"X-Auth-Token": API_KEY}
    
    # Search for the team first to get matches
    # We'll search for matches involving this team in a wide date range
    print(f"Searching for matches involving {team_name}...")
    
    today = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.now() - timedelta(days=5)).strftime("%Y-%m-%d")
    end_date = (datetime.now() + timedelta(days=5)).strftime("%Y-%m-%d")
    
    url = f"{BASE_URL}/matches"
    params = {"dateFrom": start_date, "dateTo": end_date}
    
    try:
        response = requests.get(url, headers=headers, params=params)
        if response.status_code == 200:
            data = response.json()
            matches = data.get('matches', [])
            
            target_match = None
            for m in matches:
                if team_name.lower() in m['homeTeam']['name'].lower() or team_name.lower() in m['awayTeam']['name'].lower():
                    print(f"Found match: {m['homeTeam']['name']} vs {m['awayTeam']['name']} (ID: {m['id']})")
                    target_match = m
                    break
            
            if target_match:
                print("\n--- RAW MATCH DATA ---")
                print(json.dumps(target_match, indent=2))
                
                # Check status specifically
                print(f"\nStatus: {target_match['status']}")
                print(f"Score: {target_match['score']}")
                print(f"Last Updated: {target_match['lastUpdated']}")
            else:
                print("No match found for that team in range.")
        else:
            print(f"Error {response.status_code}: {response.text}")
            
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    find_and_inspect_match("Barcelona SC")
