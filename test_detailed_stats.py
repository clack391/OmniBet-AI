import requests
import os
from dotenv import load_dotenv
import json

load_dotenv()

API_KEY = os.getenv("FOOTBALL_DATA_API_KEY")
BASE_URL = "https://api.football-data.org/v4"

def test_historical_match_details(match_id):
    url = f"{BASE_URL}/matches/{match_id}"
    headers = {"X-Auth-Token": API_KEY}
    
    print(f"Fetching detailed stats for historical match {match_id}...")
    try:
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            data = response.json()
            # Check for detailed stats like shots, cards, etc.
            # Usually football-data.org free tier (TIER_ONE) only gives basic score/status
            # TIER_ONE might restrict 'statistics' field.
            
            print("Top Level Keys:", data.keys())
            
            if 'score' in data:
                print("Score Data:", json.dumps(data['score'], indent=2))
                
            if 'statistics' in data:
                print("Statistics found!", json.dumps(data['statistics'], indent=2))
            else:
                print("No 'statistics' field found in response.")
                
            if 'referees' in data:
                print("Referees:", json.dumps(data['referees'], indent=2))

        else:
            print(f"Error {response.status_code}: {response.text}")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    # Use a known completed match ID from previous H2H output: 
    # 2025-09-20 match between Vitoria and Braga
    # We don't have that ID directly, let's grab one from the H2H output we saw earlier or assume one.
    # Actually, let's query H2H again quickly to get a valid past match ID.
    test_historical_match_details(545906) # This was the scheduled match, let's see what it has (likely minimal)
    
    # We need a COMPLETED match to check for stats like 'shots on target'.
    # Let's try to fetch a completed match from the premier league (ID 2021) or similar if possible.
    # For now, I'll rely on the user understanding if the API doesn't support it on free tier.
    # But I will try to fetch a known past ID if I can guess one or just use the current one to see structure.
    # Better: Search for a completed match.
    
    url = f"{BASE_URL}/competitions/PL/matches?status=FINISHED&limit=1"
    headers = {"X-Auth-Token": API_KEY}
    try:
        r = requests.get(url, headers=headers)
        if r.status_code == 200:
            match = r.json()['matches'][0]
            print(f"\nTesting with finished PL match: {match['id']} ({match['homeTeam']['name']} vs {match['awayTeam']['name']})")
            test_historical_match_details(match['id'])
    except:
        pass
