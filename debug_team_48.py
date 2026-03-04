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

url = f"https://{RAPID_API_HOST}/api/sofascore/v1/team/details"
res = requests.get(url, headers=headers, params={"team_id": 48})
if res.status_code == 200:
    print(json.dumps(res.json().get('team', {}), indent=2))
