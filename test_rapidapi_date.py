import requests
import json
import os
from dotenv import load_dotenv
from pyparsing import Word, alphas

load_dotenv()
RAPID_API_KEY = os.getenv("RAPID_API_KEY")
RAPID_API_HOST = os.getenv("RAPID_API_HOST", "sofascore6.p.rapidapi.com")
headers = {
    "x-rapidapi-host": RAPID_API_HOST,
    "x-rapidapi-key": RAPID_API_KEY
}

# The football-data.org API returns upcoming matches, let's say "2026-03-03"
test_date = "2026-03-03"

paths_to_test = [
    f"/api/sofascore/v1/matches/schedule?date={test_date}",
    f"/api/sofascore/v1/matches/feed?date={test_date}",
    f"/api/sofascore/v1/events/schedule?date={test_date}",
    f"/schedule?date={test_date}"
]

for p in paths_to_test:
    url = f"https://{RAPID_API_HOST}{p}"
    res = requests.get(url, headers=headers)
    print(f"Path: {p} -> Status {res.status_code}")
    if res.status_code == 200:
        print("FOUND SCHEDULE!")
        break
