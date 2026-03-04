import requests
import json
headers = {"User-Agent": "Mozilla/5.0"}
res = requests.get("https://api.sofascore.com/api/v1/search/events?q=Chelsea", headers=headers)
print("Status:", res.status_code)
if res.status_code == 200:
    print(res.text[:1000])
