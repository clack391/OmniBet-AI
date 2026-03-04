import requests
import os
from dotenv import load_dotenv

load_dotenv()
API_KEY = os.getenv("FOOTBALL_DATA_API_KEY")
headers = {"X-Auth-Token": API_KEY}

# Everton's ID in football-data.org is usually 62 (not 48)
url = "https://api.football-data.org/v4/teams/62"
res = requests.get(url, headers=headers)
if res.status_code == 200:
    data = res.json()
    squad = data.get('squad', [])
    names = [p.get('name') for p in squad]
    print(f"Total: {len(names)}")
    print(", ".join(names))
else:
    print(f"Error {res.status_code}")
