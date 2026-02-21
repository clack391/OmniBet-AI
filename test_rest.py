import os
import requests
import json
from dotenv import load_dotenv

load_dotenv()
api_key = os.getenv("GEMINI_API_KEY")

url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={api_key}"

prompt = """
    Act as a strict, mathematically-driven Sports Betting Risk Manager.
    Your job is to review the following initial AI prediction and evaluate if the `safe_bet_tip` is truly safe.
    
    ### Initial Prediction
    {
        "step_by_step_reasoning": "Test",
        "match": "Team A vs Team B",
        "full_analysis_report": "Test report.",
        "safe_bet_tip": "Home Win",
        "confidence": 85,
        "reasoning": ["Test"]
    }
    
    ### RISK MANAGEMENT RULES
    1. **Scrutinize the `safe_bet_tip`**: Is it too aggressive? 
       - If it predicts a pure Match Winner (e.g., "Home Win"), but the `step_by_step_reasoning` or `confidence` suggests it's a tight game, DOWNGRADE it.
       - If it predicts "BTTS - Yes", ensure both teams actually have strong scoring records. If not, downgrade it.
       - If the tip is already very safe (e.g., "Over 1.5 Goals" or "Double Chance"), you may approve it.
       - **CRITICAL**: If you downgrade the tip, you MUST choose the safest option from the OTHER 11 MARKETS already analyzed in the `full_analysis_report` section (e.g., 1X2, Match_Goals, BTTS, Team_Goals, Double_Chance, DNB, Asian_Handicap, First_Half_Goals, Second_Half_Goals, HT_FT, Correct_Score, Team_Exact_Goals).
       
    2. **Update the JSON**:
       - If you downgrade the tip, rewrite the `safe_bet_tip` to the safer option AND set `"is_downgraded": true`.
       - If you approve the exact same initial tip, set `"is_downgraded": false`.
       - Adjust the `confidence` score (usually a safer bet has higher confidence, but lower payout).
       - Add a completely new thought process to `step_by_step_reasoning` explaining *why* you approved or downgraded the original tip.
       - Update the `reasoning` array to reflect your defensive mindset.
       
    ### Output Format
    Return ONLY valid JSON. It MUST EXACTLY MATCH this schema:
    {{
        "step_by_step_reasoning": "Risk Manager's evaluation of the original tip...",
        "match": "Team A vs Team B",
        "full_analysis_report": "Keep the exact original report or amend it if necessary.",
        "safe_bet_tip": "The Final, Approved Safe Bet",
        "confidence": 90,
        "is_downgraded": true,
        "reasoning": ["Risk Manager point 1", "Risk Manager point 2"]
    }}
"""

payload = {
    "contents": [{"parts": [{"text": prompt}]}]
}

print("SENDING DIRECT REST API REQUEST...", flush=True)
try:
    response = requests.post(url, json=payload, timeout=30)
    print("STATUS:", response.status_code, flush=True)
    if response.status_code == 200:
        data = response.json()
        print(data['candidates'][0]['content']['parts'][0]['text'][:500])
    else:
        print(response.text)
except requests.exceptions.Timeout:
    print("REST REQUEST TIMED OUT AFTER 30 SECONDS", flush=True)

