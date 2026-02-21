import requests
import os
from dotenv import load_dotenv
import json

load_dotenv()

API_KEY = os.getenv("FOOTBALL_DATA_API_KEY")
BASE_URL = "https://api.football-data.org/v4"

def test_h2h(match_id):
    url = f"{BASE_URL}/matches/{match_id}/head2head"
    headers = {"X-Auth-Token": API_KEY}
    
    print(f"Fetching H2H for match {match_id}...")
    try:
        # Limit to 3 matches to save data size
        params = {"limit": 3}
        response = requests.get(url, headers=headers, params=params)
        print(f"Status: {response.status_code}")
        if response.status_code == 200:
            data = response.json()
            print("H2H Keys:", data.keys())
            if 'aggregates' in data:
                print("Aggregates found:", json.dumps(data['aggregates'], indent=2))
            if 'matches' in data:
                print(f"Previous matches found: {len(data['matches'])}")
                for m in data['matches']:
                    print(f"- {m['utcDate']}: {m['homeTeam']['name']} {m['score']['fullTime']['home']} - {m['score']['fullTime']['away']} {m['awayTeam']['name']}")
        else:
            print(response.text)
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    test_h2h(545906)
