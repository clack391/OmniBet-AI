import requests
import os
import json
from dotenv import load_dotenv

load_dotenv()
RAPID_API_KEY = os.getenv("RAPID_API_KEY")
RAPID_API_HOST = os.getenv("RAPID_API_HOST", "sofascore6.p.rapidapi.com")
headers = {
    "x-rapidapi-host": RAPID_API_HOST,
    "x-rapidapi-key": RAPID_API_KEY
}

# The ID we just found for Everton vs Burnley
sofascore_match_id = 14023941

event_url = f"https://{RAPID_API_HOST}/api/sofascore/v1/match/details"
event_res = requests.get(event_url, headers=headers, params={"match_id": sofascore_match_id})

if event_res.status_code == 200:
    data = event_res.json()
    print("Keys:", list(data.keys()))
    if 'event' in data:
         print(json.dumps(data['event'], indent=2)[:1000])
    elif 'data' in data:
         print(json.dumps(data['data'], indent=2)[:1000])
    else:
         print(json.dumps(data, indent=2)[:1000])
else:
    print("Failed:", event_res.status_code)
