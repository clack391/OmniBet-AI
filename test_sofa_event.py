import os
import requests
from dotenv import load_dotenv

load_dotenv()

RAPID_API_KEY = os.getenv("RAPID_API_KEY")
RAPID_API_HOST = os.getenv("RAPID_API_HOST", "sofascore6.p.rapidapi.com")

event_url = f"https://{RAPID_API_HOST}/api/sofascore/v1/events/detail"
headers = {
    "x-rapidapi-key": RAPID_API_KEY,
    "x-rapidapi-host": RAPID_API_HOST
}
# Using a known completed match ID or any recent ID (e.g., 11406749)
querystring = {"event_id": 12431776} # Random recent match from earlier

try:
    res = requests.get(event_url, headers=headers, params=querystring)
    data = res.json()
    print("KEYS IN ROOT:", list(data.keys()))
    if 'startTimestamp' in data:
        print("ROOT startTimestamp:", data['startTimestamp'])
    if 'event' in data:
        print("KEYS IN EVENT:", list(data['event'].keys()))
        print("EVENT startTimestamp:", data['event'].get('startTimestamp'))
except Exception as e:
    print(e)
