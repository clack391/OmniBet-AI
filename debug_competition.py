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

match_id = 14023941 # The ID we resolved for Everton vs Burnley
url = f"https://{RAPID_API_HOST}/api/sofascore/v1/match/details"
params = {"match_id": match_id}

res = requests.get(url, headers=headers, params=params)
if res.status_code == 200:
    data = res.json()
    tournament = data.get('uniqueTournament', {}).get('name')
    category = data.get('uniqueTournament', {}).get('category', {}).get('name')
    print(f"Match ID {match_id}: {tournament} ({category})")
else:
    print(f"Error {res.status_code}")
