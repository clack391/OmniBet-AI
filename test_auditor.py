import requests
import json

# Fetch a match from the db to audit
import sqlite3
conn = sqlite3.connect("src/database/omnibet.db")
cursor = conn.cursor()
cursor.execute("SELECT id FROM matches LIMIT 1")
row = cursor.fetchone()
conn.close()

if row:
    match_id = row[0]
else:
    match_id = 450624 # Default fallback ID

print(f"Testing Auditor with Match ID: {match_id}")

payload = {
    "items": [
        {
            "match_id": match_id,
            "user_selected_bet": "Over 2.5 Goals"
        }
    ]
}

response = requests.post("http://localhost:8000/predict-audit", json=payload)
print(f"Status Code: {response.status_code}")
try:
    print(json.dumps(response.json(), indent=2))
except:
    print(response.text)
