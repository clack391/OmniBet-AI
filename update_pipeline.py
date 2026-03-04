import os

content = r'''import os
import json
import re
import requests
import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()

# Initialize Gemini
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

# Use a standard stable model compatible with the free tier/broad availability
# We use gemini-3.1-pro-preview for deeper analytical reasoning and Google Search Grounding support 
MODEL_NAME = "gemini-3-flash-preview" 
model = genai.GenerativeModel(MODEL_NAME)

from datetime import datetime, timezone

def predict_match(team_a: str, team_b: str, match_stats: dict, odds_data: list = None, h2h_data: dict = None, home_form: dict = None, away_form: dict = None, home_standings: dict = None, away_standings: dict = None, advanced_stats: dict = None, match_date: str = None, team_squads: dict = None):

    # Check for Stale Data (e.g. API stuck in IN_PLAY for > 4 hours)
    is_stale = False
    is_historical = False
    try:
        if match_date:
            # Parse ISO8601 string (e.g. 2026-02-19T00:30:00Z)
            match_dt = datetime.fromisoformat(match_date.replace("Z", "+00:00"))
            now_dt = datetime.now(timezone.utc)
            duration = (now_dt - match_dt).total_seconds() / 3600
            
            # Strict Backtesting Mode: If match started in the past, disable Live Search to prevent cheating
            if duration > 0:
                is_historical = True
                
            if match_stats.get('status') == 'IN_PLAY' and duration > 4:
                is_stale = True
    except Exception as e:
        print(f"Error parse match_date: {e}")

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

    current_date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    prompt = f"""
    Act as an expert quantitative sports analyst for OmniBet AI.
    Current Date: {current_date_str}
    
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
    
    ### Advanced Tactical Metrics (RapidAPI SofaScore)
    {json.dumps(advanced_stats, indent=2) if advanced_stats else "No advanced tactical metrics available."}
    
    ### Team Squads (Official 25/26 Roster)
    {json.dumps(team_squads, indent=2) if team_squads else "No official squad data available."}
    
    ### CRITICAL INSTRUCTIONS
    1. **CHECK THE MATCH STATUS**:
       - 'TIMED'/'SCHEDULED'/'UPCOMING' -> Match NOT started.
       - 'IN_PLAY'/'PAUSED' (with >0 score or recent start) -> Live Prediction.
       - **Ignore 0-0 score** if Stale Data Warning is present.
       
    2. **DYNAMIC WEIGHTING & DATA SEARCH FALLBACK**:
       - **Advanced Tactical Analysis**: Use the `Advanced Tactical Metrics` block to mathematically determine the match script. Do not just look at "Goals Scored." Compare "Shots on target", "Big chances missed", "Interceptions per game", and "Ball possession". For example, if a team has 65% possession but the opponent averages 18 interceptions and 20 tackles, expect a frustrating low-block scenario.
       - If any critical data block above says "No data available." or "N/A" (especially Odds or Standings), you MUST use Google Search to fetch recent team news, historical results, or odds.
       - **Rule 1 - Contextualize Motivation**: You must explicitly state how each team's current league table position dictates their motivation and likely tactical setup (e.g., desperate for points near relegation vs. comfortable mid-table).
       - **Rule 2 - Evaluate True Fatigue**: Do not just state a team is "fatigued." Analyze their `recent_scorelines` history. Describe if the fatigue is physical (heavy minutes/grueling match like a 2-2 draw) or mental (tough loss/draw).
       - **Rule 3 - Net Impact of Absences**: Cross-reference Team A's missing attackers against Team B's missing defenders using your Google Search. Explicitly name the available bench/impact players who will be relied upon to fill the gaps.
       - **Rule 4 - Edge Case Safeguard**: If specific bench personnel or interval data is unavailable after searching, acknowledge the missing data and weigh the primary prediction heavily toward recent form and overall head-to-head stats.
       - **Competition Isolation & The First Leg Anchor**: Explicitly separate domestic league form from cup/continental form. IF THIS IS A CUP OR CONTINENTAL MATCH, YOU MUST USE GOOGLE SEARCH TO FIND OUT IF THIS IS A 2ND-LEG TIE. If a team is leading on aggregate, they do not need to win; they will play highly conservative, suffocating football. Do not blindly predict the favorite to win if a draw advances them. 
       - **ANTI-HALLUCINATION & TEMPORAL INTEGRITY**: You are STRICTLY FORBIDDEN from inventing historical narratives. Google Search snippets often pull up old articles. If an article mentions a player injury or a match result from years ago (e.g., Sebastien Haller at Utrecht), you MUST ignore it.
       - **STRICT ROSTER VERIFICATION (ZERO TOLERANCE)**:
           - You are STRICTLY FORBIDDEN from mentioning players who are NOT in the `Team Squads` lists provided above.
           - **POISONED DATA ALERT**: The `Team Squads` JSON provided above is a raw industrial feed for the year 2026 and may contain "Simulated Transfers" (e.g., Grealish at Everton, Alcaraz at Everton, Marcus Edwards at Burnley).
           - **VERIFICATION PROTOCOL**: You MUST use your Google Search tool to verify: "Current official squad for {team_a} and {team_b} 25/26 season". 
           - If your Google Search confirms a player actually plays for a different world-famous club (e.g., Grealish at Man City), you MUST ignore their presence in the `Team Squads` JSON. They are DATA NOISE.
           - Any player name in your output (Player Props, Strategy, Simulation) MUST be verified against BOTH the provided list AND your search results. If they aren't verified at the club, DELETE THEM IMMEDIATELY.
           - **Example**: If Man City is not playing, you MUST NOT mention Jack Grealish, Haaland, or Alcaraz, even if the API data incorrectly lists them.
       - **Rule 5 - Regression to the Mean**: If a team is on an extreme streak (e.g., 5+ games without scoring, or a 10-match winless/winning streak), you MUST apply Regression to the Mean logic. The probability of a breakout or reversion increases with each game. 
       - **Rule 6 - High-Variance Desperation States**: If a team is facing relegation or knockout desperation, you MUST classify the match as a "High-Variance Game State". Desperate teams do not play conservative, low-scoring football; they abandon defensive structures to chase points, making games open, chaotic, and goal-heavy. Desperation = Goals.
       - **Rule 7 - The "Post-European Hangover"**: For top-tier teams coming off a massive midweek continental fixture (e.g., Champions League), you MUST drastically penalize their domestic away rating. 
       - **Rule 8 - The Derby Chaos Directive**: If your Google Search confirms this match is a historic or fierce local derby/rivalry, you MUST throw out conservative, structure-based logic. 

    3. **GAME STATE SIMULATION**:
       Do not just give a flat prediction. You MUST simulate conditional timelines based on who controls the game script.
       - **Scenario A (The Expected Script)**: If the pre-match favorite (or Home team) scores first within 30 minutes, how does the opponent historically respond? 
       - **Scenario B (The Underdog Disruption)**: If the underdog (or Away team) scores first against the run of play, what happens? 
    
    4. **Analyze the following 17 Core Betting Markets**:
       Match Winner (1X2), Match Total Goals, BTTS, Team Total Goals, Double Chance, Draw No Bet, Asian Handicap, First Half Goals, Second Half Goals, HT/FT, Correct Score, Team Exact Goals, Total Match Corners, Total Match Cards, Highest Scoring Half, 10 Minute Draw, Player Props.
    
    5. **Mathematical Synthesis**:
       - Weigh probabilities of ALL 17 markets against each other.
       - **Cross-Reference**:
          - *The Fortress Effect*: Factor in the isolated home vs away form. 
          - *CRITICAL NEWS IMPACT*: If Google Search reveals a Top Goalscorer is missing, you MUST drastically reduce the confidence of goal-heavy markets.
    
    6. **Chain-of-Thought Process**: Before declaring any predictions, you MUST think step-by-step. 
       - FIRST: Explicitly search for: "confirmed injuries and official starting lineups for {team_a} vs {team_b} today". 
       - SECOND: Search for the assigned referee and their card average.
       - THIRD: Analyze offensive stats vs defensive stats, xG, and Fatigue.

    7. **Select the Dual Expert Tips (DETERMINISTIC SELECTION)**:
       - **Primary Pick**: Must be the absolute SAFEST mathematical bet. To ensure consistency across runs, if multiple markets are identically safe, default to the BASE MARKETS in this strict priority order: 1) Double Chance, 2) Over/Under 1.5 Goals, 3) Draw No Bet. Treat this as the banker.
       - **Alternative Pick**: Must be a VALUE bet. Slightly riskier but offers significantly better odds. Default to Match Winner if tied.
       - **ODDS EXTRACTION**: You MUST provide the realistic Decimal Odds for both picks. If you have the Odds API payload, use those exact numbers. If the payload is empty, use your Google Search to find the real market odds. If you cannot find them, estimate the exact decimal odds based on implied probability.
    
    ### Output Format
    CRITICAL: Ensure your JSON structure is perfectly valid and contains ZERO trailing commas at the end of objects or lists.
    Return ONLY valid JSON with this exact structure:
    {{
        "step_by_step_reasoning": "Sentence 1 MUST state exactly who is injured/missing/transferred from the starting lineups based on your search. Sentence 2 MUST state how this changes your confidence. Then write your normal thought process.",
        "scenario_analysis": {{
            "scenario_a_expected_script": "Detailed projection of what happens if the favorite/home team scores first and controls possession.",
            "scenario_b_underdog_disruption": "Detailed projection of what happens if the underdog/away team scores first and forces the favorite to chase the game."
        }},
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
            "Team_Exact_Goals": "Prediction: [Team + Exact Goals]. [Reasoning...]",
            "Total_Corners": "Prediction: [O/U]. [Reasoning...]",
            "Total_Cards": "Prediction: [O/U Booking Points]. [Reasoning...]",
            "Highest_Scoring_Half": "Prediction: [1st Half / 2nd Half / Tie]. [Reasoning...]",
            "10_Minute_Draw": "Prediction: [Yes/No]. [Reasoning...]",
            "Player_Props": "Prediction: [Player Bet]. [Reasoning...]"
        }},
        "primary_pick": {{
            "tip": "The Safest Banker Prediction",
            "confidence": 85,
            "odds": 1.45
        }},
        "alternative_pick": {{
            "tip": "The Higher ROI Value Prediction",
            "confidence": 65,
            "odds": 2.10
        }},
        "reasoning": ["point 1", "point 2", "point 3"]
    }}
    """
    try:
        api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        if not api_key:
            raise ValueError("API Key is missing")
            
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL_NAME}:generateContent?key={api_key}"
        
        # Build payload dynamically to support Strict Backtesting Mode
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.0,
                "responseMimeType": "application/json"
            }
        }
        
        if is_historical:
            print(f"🛡️ Strict Backtesting Mode: Disabling Google Search for past match {team_a} vs {team_b}")
        else:
            payload["tools"] = [{"google_search": {}}]
        
        print(f"🧠 [Agent 1] Generating analysis for {team_a} vs {team_b} (Searching web if future match)...")
        request_start = datetime.now()
        response = requests.post(url, headers={'Content-Type': 'application/json'}, json=payload)
        response.raise_for_status()
        request_end = datetime.now()
        print(f"✅ [Agent 1] Analysis finished in {(request_end - request_start).total_seconds():.2f}s")
        
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
                
        # Proactively clean trailing commas introduced by LLM hallucinations before parsing
        text_content = re.sub(r',\s*}', '}', text_content)
        text_content = re.sub(r',\s*\]', ']', text_content)
                
        return json.loads(text_content)
    except Exception as e:
        safe_error = re.sub(r'key=[^&\s]+', 'key=[REDACTED]', str(e))
        print(f"Gemini API Error in predict_match: {safe_error}")
        try:
             print(f"Raw Response: {response.text}")
        except:
             pass
        return {
            "error": safe_error,
            "match": f"{team_a} vs {team_b}",
            "primary_pick": {"tip": "Analysis Failed", "confidence": 0},
            "alternative_pick": {"tip": "Analysis Failed", "confidence": 0}
        }

def risk_manager_review(initial_prediction_json: dict) -> dict:
    """
    Second agent in the Multi-Agent Loop. Acts as a strict Risk Manager to verify 
    the safety of the initial prediction.
    """
    if "error" in initial_prediction_json:
        print("⚠️ [Agent 2] Skipping Risk Review: Primary Agent failed with an API error.")
        return initial_prediction_json

    prompt = f"""
    Act as a strict, mathematically-driven Sports Betting Risk Manager.
    Your job is to review the following initial AI prediction's two picks (`primary_pick` and `alternative_pick`) to evaluate if they are truly safe and viable.
    
    ### Initial Prediction & Primary Agent's Notes
    {json.dumps(initial_prediction_json, indent=2)}
    
    ### RISK MANAGEMENT RULES
    1. **Catching the "Human Bias"**: Identify any widespread public narratives about this match. Cross-reference this bias with the underlying defensive/offensive data.
    2. **Catching the "Gambler's Fallacy" & "Desperation"**: Do not assume extreme streaks will continue indefinitely; enforce Regression to the Mean.
    3. **The "Post-European Hangover"**: If the favorite is returning from a grueling midweek match, respect the "Underdog Disruption".
    4. **The "Derby Chaos Directive"**: Rivalries are mathematically unpredictable. Throw out conservative structure-based logic.
    5. **Scrutinize the `primary_pick` (The Banker)**: Is it too aggressive? If it completely fails in "Scenario B", downgrade it.
    6. **ROSTER ACCURACY SCRUBBER (STRICT ENFORCEMENT)**:
       - You MUST cross-check every player name mentioned in the primary prediction.
       - If the primary agent mentioned a player who does NOT belong to {initial_prediction_json.get('match')} (e.g., mentioning Grealish for Everton), you MUST delete that player from the final output and flag it as a data hallucination in your reasoning.
       - **ZERO TOLERANCE**: If the primary agent failed to scrub transfer noise from the 2026 data feed, YOU are the final line of defense.
       - **Example**: Grealish plays for Man City. If he is mentioned in a prediction for Everton, DELETE HIM and flag the error.
       
    7. **Update the JSON**:
       - Rewrite the `primary_pick` and `alternative_pick` objects with your final approved tips.
       - Set `"is_downgraded": true` if you had to change the `primary_pick`, otherwise `false`.
       - Add a completely new thought process to `step_by_step_reasoning` explaining *why* you approved or downgraded.
       - Rewrite the 17-market `full_analysis` grid to harmonize with your final tips.
       - Return ONLY valid JSON.
    """
    try:
        api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL_NAME}:generateContent?key={api_key}"
        
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.0,
                "responseMimeType": "application/json"
            }
        }
        
        print(f"🛡️ [Agent 2] Risk Manager reviewing analysis for {initial_prediction_json.get('match')}...")
        response = requests.post(url, headers={'Content-Type': 'application/json'}, json=payload)
        response.raise_for_status()
        
        data = response.json()
        candidates = data.get('candidates', [])
        if not candidates:
            return initial_prediction_json
            
        text_content = candidates[0].get('content', {}).get('parts', [{}])[0].get('text', "")
        text_content = re.sub(r',\s*}', '}', text_content)
        text_content = re.sub(r',\s*\]', ']', text_content)
        
        return json.loads(text_content)
    except Exception as e:
        print(f"Risk Manager Error: {e}")
        return initial_prediction_json
'''

# We need to preserve the imports and other functions at the bottom of pipeline.py
# Let's read the whole file, replace the functions, and write it back.

with open('/home/jay/OmniBet AI/src/rag/pipeline.py', 'r') as f:
    orig = f.read()

# We identify the boundaries of predict_match and risk_manager_review
# This is tricky without regex, but we can just use the content string.

# Or, simpler: we write a placeholder script that just overwrites the whole file if we have the full content.
# Let's get the full content of pipeline.py first.
