import requests
import os
from dotenv import load_dotenv

load_dotenv()
RAPID_API_KEY = os.getenv("RAPID_API_KEY")
RAPID_API_HOST = os.getenv("RAPID_API_HOST", "sofascore6.p.rapidapi.com")
headers = {
    "x-rapidapi-host": RAPID_API_HOST,
    "x-rapidapi-key": RAPID_API_KEY
}

res = requests.get(f"https://{RAPID_API_HOST}/api/sofascore/v1/team/players", headers=headers, params={"team_id": 48})
if res.status_code == 200:
    names = [p.get('name') for p in res.json().get('players', [])]
    print(f"Total: {len(names)}")
    print(", ".join(names))
