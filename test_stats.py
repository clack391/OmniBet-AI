import requests
import os
from dotenv import load_dotenv
import json

load_dotenv()

API_KEY = os.getenv("FOOTBALL_DATA_API_KEY")
BASE_URL = "https://api.football-data.org/v4"

def test_match_stats(match_id):
    url = f"{BASE_URL}/matches/{match_id}"
    headers = {"X-Auth-Token": API_KEY}
    
    print(f"Fetching stats for match {match_id}...")
    try:
        response = requests.get(url, headers=headers)
        print(f"Status: {response.status_code}")
        if response.status_code == 200:
            data = response.json()
            # print keys to see what we have
            print("Top level keys:", data.keys())
            
            if 'head2head' in data:
                print("Head2Head found!")
                print(json.dumps(data['head2head'], indent=2)[:500] + "...")
            else:
                print("No Head2Head data found in default response.")
                
            # Check for any form data in homeTeam/awayTeam
            print("\nHome Team Data:")
            print(json.dumps(data.get('homeTeam'), indent=2))
            
        else:
            print(response.text)
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    # Use a known match ID (e.g. from the previous curl output or a random valid one)
    # The user previously saw matches, I need a valid ID.
    # I'll rely on the user's previous context or try to find a valid ID.
    # Earlier I saw match ID 545906 (Braga vs Vitoria) in Step 354 output.
    test_match_stats(545906)
