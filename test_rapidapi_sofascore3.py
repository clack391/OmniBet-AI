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
team_id = 42210
tournament_id = 463
season_id = 77010

params_to_test = [
    {"team_id": team_id, "tournament_id": tournament_id, "season_id": season_id},
    {"teamId": team_id, "uniqueTournamentId": tournament_id, "seasonId": season_id},
    {"id": team_id, "tournamentId": tournament_id, "seasonId": season_id},
    {"team_id": team_id, "unique_tournament_id": tournament_id, "season_id": season_id}
]

print("Testing /api/sofascore/v1/team/statistics ...")
for p in params_to_test:
    test_url = f"https://{RAPID_API_HOST}/api/sofascore/v1/team/statistics"
    test_res = requests.get(test_url, headers=headers, params=p)
    print(f"\nParams: {p}")
    print(f"Status: {test_res.status_code}")
    print(f"Response: {test_res.text[:200]}")
    if test_res.status_code == 200:
        print("SUCCESS!!!")
        break
