import requests
import json
import os
from dotenv import load_dotenv

load_dotenv()
RAPID_API_KEY = os.getenv("RAPID_API_KEY")

# Let's test sportscore1 API which is another popular SofaScore wrapper
# Or simply use the sofascore-football-api wrapper if the user hasn't paid for it.
# Actually, wait - can we hit the sofascore graphql API? 
headers = {
    "x-rapidapi-host": "sportscore1.p.rapidapi.com",
    "x-rapidapi-key": RAPID_API_KEY
}

# The user might not be subscribed to sportscore1. Let's see if it works.
url = "https://sportscore1.p.rapidapi.com/sports/1/events"
querystring = {"date": "2026-03-03"}

response = requests.get(url, headers=headers, params=querystring)
print("Sportscore:", response.status_code)
