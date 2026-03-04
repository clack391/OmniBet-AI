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

def get_team_info(tid):
    url = f"https://{RAPID_API_HOST}/api/sofascore/v1/team/details"
    res = requests.get(url, headers=headers, params={"team_id": tid})
    if res.status_code == 200:
        return res.json().get('team', {}).get('name')
    return f"Error {res.status_code}"

print(f"ID 6: {get_team_info(6)}")
print(f"ID 4471: {get_team_info(4471)}")
print(f"ID 17: {get_team_info(17)}") # Expected Man City?
