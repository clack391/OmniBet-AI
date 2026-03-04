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

match_id = 14023941
url = f"https://{RAPID_API_HOST}/api/sofascore/v1/match/details"
params = {"match_id": match_id}

res = requests.get(url, headers=headers, params=params)
if res.status_code == 200:
    data = res.json()
    h = data.get('homeTeam', {})
    a = data.get('awayTeam', {})
    print(f"Match {match_id}: {h.get('name')} (ID {h.get('id')}) vs {a.get('name')} (ID {a.get('id')})")
