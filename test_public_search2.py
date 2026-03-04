import requests
import json
import urllib.parse
from datetime import datetime

def search_sofascore_public(team_a, team_b, match_date=None):
    # Try the open API search. Sofascore often allows simple search endpoints 
    # if the Origin/Referer headers look legitimate.
    query = f"{team_a} {team_b}"
    url = f"https://api.sofascore.com/api/v1/search/events?q={urllib.parse.quote(query)}"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Origin": "https://www.sofascore.com",
        "Referer": "https://www.sofascore.com/",
        "Cache-Control": "max-age=0"
    }

    try:
        res = requests.get(url, headers=headers)
        print("Status:", res.status_code)
        if res.status_code == 200:
            data = res.json()
            if 'results' in data and len(data['results']) > 0:
                print("Found match:", json.dumps(data['results'][0], indent=2)[:500])
                return data['results'][0].get('id')
    except Exception as e:
        print("Error:", e)
    return None

print("ID:", search_sofascore_public("Everton", "Burnley"))
