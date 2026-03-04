import requests
import os
import json
from dotenv import load_dotenv
from datetime import datetime

load_dotenv()
RAPID_API_KEY = os.getenv("RAPID_API_KEY")
RAPID_API_HOST = os.getenv("RAPID_API_HOST", "sofascore6.p.rapidapi.com")
headers = {
    "x-rapidapi-host": RAPID_API_HOST,
    "x-rapidapi-key": RAPID_API_KEY
}

# The Sofascore API usually has a schedule endpoint by date
test_date = "2026-03-03" # Matches our test payload

paths_to_test = [
    f"/api/sofascore/v1/sport/football/scheduled-events/{test_date}",
    f"/api/sofascore/v1/category/1/events/{test_date}", 
    f"/api/sofascore/v1/matches/live",
    f"/api/sofascore/v1/sport/-/scheduled-events/{test_date}"
]

for p in paths_to_test:
    test_url = f"https://{RAPID_API_HOST}{p}"
    print(f"\nTesting {p}")
    test_res = requests.get(test_url, headers=headers)
    print(f"Status: {test_res.status_code}")
    if test_res.status_code == 200:
        data = test_res.json()
        print("Keys:", list(data.keys()))
        if 'events' in data and len(data['events']) > 0:
            print("First Event:", json.dumps(data['events'][0], indent=2)[:300])
        elif isinstance(data, list) and len(data) > 0:
            print("First Item:", json.dumps(data[0], indent=2)[:300])
        else:
            print(json.dumps(data, indent=2)[:300])
