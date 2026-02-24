import os
import json
import requests
import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()

# Initialize Gemini
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

# Use a standard stable model compatible with the free tier/broad availability
# We use gemini-3-flash-preview for stable Google Search Grounding support 
MODEL_NAME = "gemini-3-flash-preview" 
model = genai.GenerativeModel(MODEL_NAME)

from datetime import datetime, timezone

def predict_match(team_a: str, team_b: str, match_stats: dict, odds_data: list = None, h2h_data: dict = None, home_form: dict = None, away_form: dict = None, home_standings: dict = None, away_standings: dict = None):

    # Check for Stale Data (e.g. API stuck in IN_PLAY for > 4 hours)
    is_stale = False
    try:
        match_date = match_stats.get('utcDate')
        if match_date:
            # Parse ISO8601 string (e.g. 2026-02-19T00:30:00Z)
            match_dt = datetime.fromisoformat(match_date.replace("Z", "+00:00"))
            now_dt = datetime.now(timezone.utc)
            duration = (now_dt - match_dt).total_seconds() / 3600
            
            if match_stats.get('status') == 'IN_PLAY' and duration > 4:
                is_stale = True
    except Exception as e:
        print(f"Error checking stale date: {e}")

    # Construct Prompt
    stale_warning = ""
    if is_stale:
        stale_warning = """
    ### DATA WARNING: STALE API FEED
    - The match start time was over 4 hours ago, but the API still reports 'IN_PLAY' with a 0-0 score.
    - **THIS IS LIKELY AN API ERROR.** The match has almost certainly finished.
    - **IGNORE THE 0-0 SCORE.** It is likely incorrect/stale.
    - Treat this as a PREDICTION based on pre-match form and stats, NOT a live commentary.
    """

    prompt = f"""
    Act as an expert quantitative sports analyst for OmniBet AI.
    
    Match: {team_a} vs {team_b}
    {stale_warning}
    
    ### Match Stats / Data
    {json.dumps(match_stats, indent=2)}
    
    ### Head-to-Head & Form (Historical Context)
    {json.dumps(h2h_data, indent=2) if h2h_data else "No H2H data available."}
    
    ### The Fortress Effect: Isolated Venue Form (Last 5 Matches)
    Home Team ({team_a}) Form AT HOME: {json.dumps(home_form, indent=2) if home_form else "N/A"}
    Away Team ({team_b}) Form AWAY FROM HOME: {json.dumps(away_form, indent=2) if away_form else "N/A"}
    
    ### League Standings
    Home Team ({team_a}): {json.dumps(home_standings, indent=2) if home_standings else "N/A"}
    Away Team ({team_b}): {json.dumps(away_standings, indent=2) if away_standings else "N/A"}
    
    ### Market Odds (Implied Probability Context)
    {json.dumps(odds_data, indent=2) if odds_data else "No live odds available."}
    
    ### CRITICAL INSTRUCTIONS
    1. **CHECK THE MATCH STATUS**:
       - 'TIMED'/'SCHEDULED'/'UPCOMING' -> Match NOT started.
       - 'IN_PLAY'/'PAUSED' (with >0 score or recent start) -> Live Prediction.
       - **Ignore 0-0 score** if Stale Data Warning is present.
    
    2. **Analyze the following 12 Core Betting Markets**:
       - **Match Winner (1X2)**: Home, Draw, or Away?
       - **Match Total Goals**: Over/Under 2.5?
       - **BTTS**: Both Teams To Score (Yes/No)?
       - **Team Total Goals**: e.g. Home Over 1.5, Away Under 0.5.
       - **Double Chance**: 1X, X2, or 12.
       - **Draw No Bet (DNB)**: Home or Away (moneyback on draw).
       - **Asian Handicap**: e.g. Home -0.5, Away +1.5.
       - **First Half Goals**: Over/Under 0.5 or 1.5.
       - **Second Half Goals**: Over/Under 0.5 or 1.5.
       - **HT/FT**: Half Time/Full Time result (e.g. Home/Home, Draw/Away).
       - **Correct Score**: Exact final score prediction.
       - **Team Exact Goals**: Exact number of goals scored by Home or Away team.

    3. **Mathematical Synthesis**:
       - Weigh probabilities of ALL 12 markets against each other.
       - **Cross-Reference**:
         - *The Fortress Effect*: Strongly factor in the isolated home vs away form. A team might be great generally, but terrible on the road.
         - *Form vs Odds*: Find value where isolated form contradicts high odds.
         - *H2H vs Current Form*: Prioritize CURRENT FORM.
         - *News Impact*: Downgrade team significantly if key players missing.
    
    4. **Chain-of-Thought Process**: Before declaring any predictions, you MUST think step-by-step. 
       - FIRST: Use your built-in Google Search tool to look up current injuries, suspensions, and absent players for {team_a} and {team_b} right now (e.g., "injuries suspension {team_a} vs {team_b} today"). Base your confidence on who is actually starting or missing.
       - SECOND: Analyze the offensive stats vs defensive stats and The Fortress Effect.
       - THIRD: Evaluate the implied probability of the Vegas odds.
    
    5. **Select the SINGLE Safest Tip**:
       - Compare the calculated confidence of the best outcome from EACH of the 12 markets.
       - The `safe_bet_tip` must be the one with the HIGHEST statistical probability.
    
    ### Output Format
    Return ONLY valid JSON with this exact structure:
    {{
        "step_by_step_reasoning": "Write your 3-step internal thought process here before filling out the rest of the JSON.",
        "match": "{team_a} vs {team_b}",
        "full_analysis": {{
            "1X2": "Prediction: [Home/Draw/Away]. [Reasoning...]",
            "Match_Goals": "Prediction: [Over/Under]. [Reasoning...]",
            "BTTS": "Prediction: [Yes/No]. [Reasoning...]",
            "Team_Goals": "Prediction: [Team + O/U]. [Reasoning...]",
            "Double_Chance": "Prediction: [1X/X2/12]. [Reasoning...]",
            "DNB": "Prediction: [Home/Away]. [Reasoning...]",
            "Asian_Handicap": "Prediction: [Pick]. [Reasoning...]",
            "First_Half_Goals": "Prediction: [O/U]. [Reasoning...]",
            "Second_Half_Goals": "Prediction: [O/U]. [Reasoning...]",
            "HT_FT": "Prediction: [Pick]. [Reasoning...]",
            "Correct_Score": "Prediction: [Score]. [Reasoning...]",
            "Team_Exact_Goals": "Prediction: [Team + Exact Goals]. [Reasoning...]"
        }},
    }}
    """
    try:
        api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        if not api_key:
            raise ValueError("API Key is missing")
            
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL_NAME}:generateContent?key={api_key}"
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "tools": [{"google_search": {}}],
            "generationConfig": {
                "temperature": 0.0,
                "responseMimeType": "application/json"
            }
        }
        
        response = requests.post(url, headers={'Content-Type': 'application/json'}, json=payload)
        response.raise_for_status()
        
        # When using search grounding, the response might have multiple parts
        data = response.json()
        candidates = data.get('candidates', [])
        if not candidates:
            raise ValueError("No candidates returned")
            
        parts = candidates[0].get('content', {}).get('parts', [])
        
        text_content = ""
        for part in parts:
            if 'text' in part:
                text_content += part['text']
                
        return json.loads(text_content)
    except Exception as e:
        print(f"Gemini API Error in predict_match: {e}")
        try:
             print(f"Raw Response: {response.text}")
        except:
             pass
        return {
            "error": str(e),
            "match": f"{team_a} vs {team_b}",
            "safe_bet_tip": "Analysis Failed"
        }

def risk_manager_review(initial_prediction_json: dict) -> dict:
    """
    Second agent in the Multi-Agent Loop. Acts as a strict Risk Manager to verify 
    the safety of the initial prediction.
    """
    prompt = f"""
    Act as a strict, mathematically-driven Sports Betting Risk Manager.
    Your job is to review the following initial AI prediction and evaluate if the `safe_bet_tip` is truly safe.
    
    ### Initial Prediction
    {json.dumps(initial_prediction_json, indent=2)}
    
    ### RISK MANAGEMENT RULES
    1. **Scrutinize the `safe_bet_tip`**: Is it too aggressive? 
       - If it predicts a pure Match Winner (e.g., "Home Win"), but the `step_by_step_reasoning` or `confidence` suggests it's a tight game, DOWNGRADE it.
       - If it predicts "BTTS - Yes", ensure both teams actually have strong scoring records. If not, downgrade it.
       - If the tip is already very safe (e.g., "Over 1.5 Goals" or "Double Chance"), you may approve it.
       - **CRITICAL**: If you downgrade the tip, you MUST choose the safest option from the OTHER 11 MARKETS already analyzed in the `full_analysis` section (e.g., 1X2, Match_Goals, BTTS, Team_Goals, Double_Chance, DNB, Asian_Handicap, First_Half_Goals, Second_Half_Goals, HT_FT, Correct_Score, Team_Exact_Goals).
       
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
        "match": "{initial_prediction_json.get('match')}",
        "full_analysis": {json.dumps(initial_prediction_json.get('full_analysis', {}))},
        "safe_bet_tip": "The Final, Approved Safe Bet",
        "confidence": 90,
        "is_downgraded": true,
        "reasoning": ["Risk Manager point 1", "Risk Manager point 2"]
    }}
    """
    
    try:
        response = model.generate_content(
            prompt,
            generation_config=genai.types.GenerationConfig(
                temperature=0.0,
                response_mime_type="application/json"
            )
        )
        return json.loads(response.text)
    except Exception as e:
        print(f"Risk Manager Error: {e}")
        # Fallback to the initial prediction if the second agent fails
        return initial_prediction_json

def generate_best_picks(saved_predictions: list) -> dict:
    prompt = f"""
    You are a Chief Risk Officer building the ultimate, safest sports accumulator.
    
    ### Task
    Review the following JSON list of analyzed matches. Your goal is to filter out the risky ones and return ONLY the absolute safest, highest-confidence matches (aim for the top 30-50% safest picks).
    
    ### Matches to Analyze:
    {json.dumps(saved_predictions)}
    
    ### Output Format
    Return ONLY valid JSON matching this exact structure:
    {{
        "master_reasoning": "Explain the overarching theme of why these specific matches were chosen and why the others were rejected. Be analytical and professional.",
        "picks": [
            {{
                "match_id": 12345,
                "teams": "Home vs Away",
                "match_date": "YYYY-MM-DDTHH:MM:SSZ",
                "safe_bet_tip": "The approved safe tip",
                "confidence": 95,
                "home_logo": "url_if_exists",
                "away_logo": "url_if_exists",
                "reasoning": ["Brief reason 1", "Brief reason 2"]
            }}
        ]
    }}
    """
    
    try:
        api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        if not api_key:
            raise ValueError("API Key is missing")
            
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3-flash-preview:generateContent?key={api_key}"
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.2, # Slight creativity for master_reasoning, but mostly deterministic 
                "responseMimeType": "application/json"
            }
        }
        
        response = requests.post(url, headers={'Content-Type': 'application/json'}, json=payload)
        response.raise_for_status()
        
        response_json = response.json()
        raw_text = response_json['candidates'][0]['content']['parts'][0]['text']
        
        return json.loads(raw_text)
        
    except Exception as e:
        print(f"Error generating best picks: {e}")
        return {
            "master_reasoning": "Failed to generate AI accumulator due to an error.",
            "picks": []
        }
