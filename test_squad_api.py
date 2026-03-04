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

team_id = 48 
url = f"https://{RAPID_API_HOST}/api/sofascore/v1/team/players"
params = {"team_id": team_id}

res = requests.get(url, headers=headers, params=params)
if res.status_code == 200:
    data = res.json()
    print(json.dumps(data.get('players', [])[0], indent=2))
