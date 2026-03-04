import os
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
MODEL_NAME = "gemini-3.1-pro-preview" 
model = genai.GenerativeModel(MODEL_NAME)

from datetime import datetime, timezone

def predict_match(team_a: str, team_b: str, match_stats: dict, odds_data: list = None, h2h_data: dict = None, home_form: dict = None, away_form: dict = None, home_standings: dict = None, away_standings: dict = None, advanced_stats: dict = None, match_date: str = None):

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
    
    ### CRITICAL INSTRUCTIONS
    1. **CHECK THE MATCH STATUS**:
       - 'TIMED'/'SCHEDULED'/'UPCOMING' -> Match NOT started.
       - 'IN_PLAY'/'PAUSED' (with >0 score or recent start) -> Live Prediction.
       - **Ignore 0-0 score** if Stale Data Warning is present.
       
    2. **DYNAMIC WEIGHTING & DATA SEARCH FALLBACK**:
       - **Advanced Tactical Analysis**: Use the `Advanced Tactical Metrics` block to mathematically determine the match script. Do not just look at "Goals Scored." Compare "Shots on target", "Big chances missed", "Interceptions per game", and "Ball possession". For example, if a team has 65% possession but the opponent averages 18 interceptions and 20 tackles, expect a frustrating low-block scenario.
       - If any critical data block above says "No data available." or "N/A" (especially Odds or Standings), you MUST use Google Search to fetch recent team news, historical results, or odds.
       - **Rule 1 - Contextualize Motivation**: You must explicitly state how each team's current league table position dictates their motivation and likely tactical setup (e.g., desperate for points near relegation vs. comfortable mid-table).
       - **Rule 2 - Evaluate True Fatigue**: Do not just state a team is "fatigued." Analyze their `recent_scorelines` history. Decide if the fatigue will lead to a collapse in defensive concentration, or a complete lack of offensive energy resulting in a low-scoring game.
       - **Rule 3 - Net Impact of Absences**: Cross-reference Team A's missing attackers against Team B's missing defenders using your Google Search. Explicitly name the available bench/impact players who will be relied upon.
       - **Rule 4 - The Ineptitude Floor**: If a team has a statistically abysmal scoring record (e.g., averaging < 0.8 goals per game or failing to score in multiple recent matches), you MUST NOT predict them to score purely based on narrative concepts like "desperation" or "derby rivalry." Data supersedes narrative. A team missing key attackers cannot magically produce goals.
       - **Competition Isolation & The First Leg Anchor**: Explicitly separate domestic league form from cup/continental form. IF THIS IS A CUP OR CONTINENTAL MATCH, YOU MUST USE GOOGLE SEARCH TO FIND OUT IF THIS IS A 2ND-LEG TIE. If a team is leading on aggregate, they do not need to win; they will play highly conservative, suffocating football. Do not blindly predict the favorite to win if a draw advances them. 
       - **ANTI-HALLUCINATION & TEMPORAL INTEGRITY**: You are STRICTLY FORBIDDEN from inventing historical narratives. Google Search snippets often pull up old articles. If an article mentions a player injury or a match result from years ago, you MUST ignore it.
        - **STRICT ROSTER VERIFICATION (ZERO TOLERANCE)**: You are STRICTLY FORBIDDEN from mentioning players who are NOT in the `Team Squads` lists provided above. For example, if Man City is not playing, you MUST NOT mention Jack Grealish, Haaland, or Alcaraz. If you mention a player for a "Player Prop" or in your "Strategy," verify their name exists in the squad list for that specific team. If they aren't there, THEY ARE HALLUCINATIONS—DELETE THEM IMMEDIATELY.
        - **Player Prop Validation**: In the `Player Props` section, you MUST predict a specific player from the active squad lists (e.g., "Phil Foden over 0.5 Shots on Target"). Do NOT output generic text like "Market Suggestion". If the main strikers are injured, predict the next most likely attacking midfielder or winger who will step up. If NO attacking players are reliable, you MUST pivot to a defensive prop for a specific player, such as "[Defender Name] To Be Booked" or "[Midfielder Name] Over 1.5 Tackles". Never suggest a player who plays for a team NOT involved in this match.
       - **Rule 5 - Regression to the Mean**: If a team is on an extreme streak (e.g., 5+ games without scoring, or a 10-match winless/winning streak), you MUST apply Regression to the Mean logic. The probability of a breakout or reversion increases with each game. Do NOT anchor your prediction to the assumption that an extreme streak will continue indefinitely into this specific match.
       - **Rule 6 - High-Variance Desperation States**: If a team is facing relegation or knockout desperation, they may attempt to abandon defensive structures to chase points. HOWEVER, desperation often leads to frustration and forced errors, not high-quality goals. If they lack the offensive metrics to score, they will simply concede more goals without replying. Do NOT automatically predict BTTS or Over 2.5 just because a team is desperate.
       - **Rule 7 - The "Post-European Hangover"**: For top-tier teams coming off a massive midweek continental fixture (e.g., Champions League), you MUST drastically penalize their domestic away rating. Physical and emotional hangovers highly expose them to energetic underdog disruptions. If Scenario B maps out a frustrated favorite losing to lower-table counters, prioritize low-scoring outcomes like Under 2.5 or Underdog Double Chance (1X/X2).
       - **Rule 8 - The Derby Chaos Directive**: If your Google Search confirms this match is a historic or fierce local derby/rivalry, recognize that Derbies are emotionally charged. While this can sometimes mean goals, it very often means cagey, foul-heavy, and violently defensive 0-0 or 1-0 matches. You MUST analyze the underlying offensive stats: if both teams are missing playmakers, the derby will likely be a low-scoring battle of attrition. Do not force an Over 2.5 prediction purely because it is a derby.

    3. **GAME STATE SIMULATION**:
       Do not just give a flat prediction. You MUST simulate conditional timelines based on who controls the game script.
       - **Scenario A (The Expected Script)**: If the pre-match favorite (or Home team) scores first within 30 minutes, how does the opponent historically respond? Do they have the tactical discipline to avoid a blowout, or do they collapse?
       - **Scenario B (The Underdog Disruption)**: If the underdog (or Away team) scores first against the run of play, what happens? Does the favorite have the attacking metrics to break down a low block, or do they leave themselves vulnerable to devastating counter-attacks?

    4. **Analyze the following 17 Core Betting Markets**:
       - **Match Winner (1X2)**: Home, Draw, or Away?
       - **Match Total Goals**: Over/Under 2.5?
       - **BTTS**: Both Teams To Score (Yes/No)?
       - **Team Total Goals**: e.g. Home Over 1.5, Away Under 0.5.
       - **Double Chance**: 1X, X2, or 12.
       - **Draw No Bet (DNB)**: Home or Away (moneyback on draw).
       - **Asian Handicap**: e.g. Home -0.5, Away +1.5.
       - **First Half Goals**: Over/Under 0.5 or 1.5.
       - **Second Half Goals**: Over/Under 0.5 or 1.5.
       - **HT/FT**: Half Time/Full Time result.
       - **Correct Score**: Exact final score prediction.
       - **Team Exact Goals**: Exact number of goals scored by Home or Away team.
       - **Total Match Corners**: Over/Under based on tactical matchups & possession.
       - **Total Match Cards**: Over/Under based on motivation, fouls, and derby intensity.
       - **Highest Scoring Half**: 1st Half, 2nd Half, or Tie.
       - **10 Minute Draw**: Prediction on whether the match will realistically be a draw at the 10:00 minute mark (Yes/No).
       - **Player Props**: e.g. Anytime Goalscorer, Shots on Target for specific players.

    5. **Mathematical Synthesis**:
       - Weigh probabilities of ALL 17 markets against each other.
       - **Cross-Reference**:
         - *The Fortress Effect*: Strongly factor in the isolated home vs away form. 
         - *CRITICAL NEWS IMPACT*: If Google Search reveals a Top Goalscorer, Star Player, or Captain is missing/injured or recently left the club in a transfer, you MUST drastically reduce the confidence of goal-heavy markets.
    
    6. **Chain-of-Thought Process**: Before declaring any predictions, you MUST think step-by-step. 
       - FIRST: If you have Google Search access, explicitly search for: "confirmed injuries, suspended players, and official starting lineups for {team_a} vs {team_b} today". Do NOT search for transfer rumors.
       - SECOND: If estimating the 'Total Match Cards' market, explicitly use your Google Search tool to find the assigned referee for this match and their historical average cards per game to calibrate your prediction.
       - THIRD: Analyze the offensive stats vs defensive stats, xG, and Fatigue.

    7. **Select the Dual Expert Tips (DETERMINISTIC SELECTION)**:
       - **Primary Pick (The Banker)**: Must be the absolute SAFEST mathematical bet. You are no longer restricted to a specific priority list. You MUST evaluate all 17 markets and select the single market that has the highest mathematical probability of winning based on the data you collected. If the data screams 'Over 1.5 Goals' or 'BTTS: Yes' as the safest possible outcome over 'Double Chance', you must choose that. Act as a pure quantitative expert finding the most undeniable edge.
       - **Alternative Pick**: Must be a VALUE bet. Find a market that offers a significantly higher ROI (higher odds) but is still heavily supported by the statistics and scenario analysis.
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
        
        max_retries = 3
        for attempt in range(max_retries):
            try:
                # Add timeout and retry logic to gracefully handle RemoteDisconnected drops
                response = requests.post(url, headers={'Content-Type': 'application/json'}, json=payload, timeout=120)
                response.raise_for_status()
                break
            except requests.exceptions.RequestException as e:
                if attempt < max_retries - 1:
                    import time
                    print(f"⚠️ Network Error during API call. Retrying {attempt + 1}/{max_retries} in 5 seconds ...")
                    time.sleep(5)
                else:
                    raise
                    
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
    1. **Catching the "Human Bias"**: Identify any widespread public narratives about this match (e.g., "The Home Team is unbeatable at home" or "They drew 0-0 last match so it will be low scoring again"). Cross-reference this bias with the underlying defensive/offensive data. If the public expectation contradicts the deep data, aggressive bet sizing against the public is warranted.

    2. **Catching the "Gambler's Fallacy"**: Do not assume extreme streaks (e.g., 5 games without scoring) will continue indefinitely; enforce Regression to the Mean when probabilistically appropriate.

    3. **The "Ineptitude Floor" & Desperation check**: If the primary agent justified an aggressive 'Over 2.5' or 'BTTS: Yes' pick by claiming one team is "desperate" for points (e.g., relegation battle), you MUST verify their actual offensive output. Desperation does NOT equal goals if a team is statistically inept at scoring or missing key attackers. If a team averages < 0.8 goals a game or their top scorer is missing, Overrule BTTS/Over picks to safer Under markets (e.g., Under 3.5, Under 2.5, or Team Under).

    4. **The "Derby Caution Directive"**: If the primary agent upgraded a goal market purely because it is a "Derby", exercise extreme caution. Derbies are notoriously tight, card-heavy, defensive struggles. If the baseline data points to a low-scoring match, OVERRULE the agent's derby narrative and reinstate the mathematically sound Under/Conservative pick.

    5. **Scrutinize the `primary_pick` (The Banker)**: Is it truly the safest mathematical edge among all 17 markets? 
       - **SCENARIO CHECK**: Read the `scenario_analysis` block provided by the primary agent. The primary pick might be 'Match Winner', 'Over 1.5', 'BTTS', etc. Whatever it is, if it completely fails in "Scenario B (The Underdog Disruption)", it is NOT a safe banker. Downgrade it to a safer, more resilient market.
       - **HONOR INJURY NEWS**: If the primary agent chose a goal-dependent market (Over 2.5, BTTS) but discovered injuries to top strikers, you MUST downgrade the pick. Do not ignore structural problems just because of a narrative.
       - **CRITICAL INSTRUCTION - CONFLICT RESOLUTION**: Before finalizing your analysis, cross-reference all statistics you are about to output. Your final narrative must be logically consistent. If you downgrade the tip to an "Under" market, ensure the text explicitly cites the data (e.g., missing players or low expected goals).
       - **CRITICAL**: If you downgrade the tip, you MUST choose the absolute safest option from the OTHER 11 MARKETS already analyzed in the `full_analysis` section that better survives both Scenarios.
       
    5. **Scrutinize the `alternative_pick` (The Value Bet)**: Is it completely reckless?
       - A value bet can be risky, but it must be backed by the data timeline. If it predicts an Away win, ensure "Scenario A" doesn't completely wipe them out in the first 15 minutes.

    6. **Update the JSON**:
       - Rewrite the `primary_pick` and `alternative_pick` objects with your final approved tips.
       - **STRICT HARMONIZATION**: The exact text inside `primary_pick["tip"]` and `alternative_pick["tip"]` MUST perfectly match one of the predictions inside your `full_analysis` grid. For example, you are FORBIDDEN from choosing 'Under 2.5' as your fallback value bet if your `Match_Goals` grid says 'Under 3.5'. They must be 100% identical.
       - **GRID OVERWRITE**: If you downgraded a tip to be more defensive, you MUST completely overwrite the `full_analysis` grid to perfectly harmonize with your new defensive logic (e.g., updating Asian Handicap to tighter spreads, Correct Score to a low sum, BTTS to No). DO NOT leave contradictory high-scoring alternative markets if you predicted a defensive stalemate.
       - Preserve the `scenario_analysis` object exactly as the primary agent wrote it, so the user can read those scenarios.
       - Add a completely new thought process to `step_by_step_reasoning` explaining *why* you approved or downgraded the original tips based on the Ineptitude Floor and Scenarios.
       - Set `"is_downgraded": true` if you had to change the `primary_pick`, otherwise `false`.
       - Update the `reasoning` array to reflect your defensive mindset.
       
    ### Output Format
    CRITICAL: Ensure your JSON structure is perfectly valid and contains ZERO trailing commas at the end of objects or lists.
    Return ONLY valid JSON. It MUST EXACTLY MATCH this schema:
    {{
        "step_by_step_reasoning": "Risk Manager's evaluation of the original tips...",
        "scenario_analysis": {json.dumps(initial_prediction_json.get('scenario_analysis', {}))},
        "match": "{initial_prediction_json.get('match')}",
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
            "tip": "The Final, Approved Safe Bet",
            "confidence": 90,
            "odds": 1.45
        }},
        "alternative_pick": {{
            "tip": "The Final, Approved Value Bet",
            "confidence": 65,
            "odds": 2.10
        }},
        "is_downgraded": true,
        "reasoning": ["Risk Manager point 1", "Risk Manager point 2"]
    }}
    """
    
    import time
    
    try:
        print(f"⏳ [Agent 2] Pausing 5 seconds to clear Gemini API Rate Limits...")
        time.sleep(5)
        print(f"🔎 [Agent 2] Risk Manager is now reviewing {initial_prediction_json.get('match')}...")
        rm_start = datetime.now()
        response = model.generate_content(
            prompt,
            generation_config=genai.types.GenerationConfig(
                temperature=0.0,
                response_mime_type="application/json"
            )
        )
        rm_end = datetime.now()
        print(f"✅ [Agent 2] Risk review completed in {(rm_end - rm_start).total_seconds():.2f}s")
        return json.loads(response.text)
    except Exception as e:
        print(f"Risk Manager Error: {e}")
        # Fallback to the initial prediction if the second agent fails
        return initial_prediction_json

def generate_best_picks(saved_predictions: list, target_odds: float = None) -> dict:
    target_instruction = ""
    if target_odds:
        target_instruction = f"""
    - **TARGET ODDS REQUIREMENT**: The user explicitly requested this accumulator to reach approximately **{target_odds}x total odds**.
      You MUST select enough highly-safe picks to mathematically multiply out to around {target_odds}x. 
      Do NOT select reckless bets just to hit the target. If hitting {target_odds}x requires picking unviable/dangerous matches, stop before ruining the accumulator and explain why you fell short.
      If {target_odds}x is easily achievable, select the absolute safest combinations of 'primary_pick' or 'alternative_pick' across the matches to hit it.
        """

    prompt = f"""
    You are a Chief Risk Officer building the ultimate, safest sports accumulator.
    
    ### Task
    Review the following JSON list of analyzed matches. Each match now contains a `primary_pick` (the safest bet), an `alternative_pick`, and a deep `scenario_analysis`.
    Your goal is to filter out the risky matches entirely, and for the matches you KEEP, select EXACTLY ONE tip (either the primary or alternative) that balances supreme safety with reasonable accumulator odds.
    - **SCENARIO SURVIVAL CHECK**: Before adding any tip to the master parlay, you MUST actively read the `scenario_analysis` block for that match. If the chosen tip does not safely survive BOTH Scenario A (Expected Script) AND Scenario B (Underdog Disruption), you must throw the match out.
    {target_instruction}
    Return ONLY the absolute safest, highest-confidence matches for the master parlay.
    
    ### Matches to Analyze:
    {json.dumps(saved_predictions)}
    
    ### Output Format
    CRITICAL: Ensure your JSON structure is perfectly valid and contains ZERO trailing commas at the end of objects or lists.
    Return ONLY valid JSON matching this exact structure:
    {{
        "master_reasoning": "Explain the overarching theme of why these specific matches and specific tips were chosen.",
        "total_accumulator_odds": 5.45,
        "picks": [
            {{
                "match_id": 12345,
                "teams": "Home vs Away",
                "match_date": "YYYY-MM-DDTHH:MM:SSZ",
                "chosen_tip": "The singular tip you selected from either the primary or alternative options",
                "odds": 1.45,
                "confidence": 95,
                "home_logo": "url_if_exists",
                "away_logo": "url_if_exists",
                "reasoning": ["Brief reason 1", "Brief reason 2"]
            }}
        ]
    }}
    """
    
    try:
        print(f"🏆 [Risk Officer] Building the safest master accumulator. Please wait...")
        master_start = datetime.now()
        api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        if not api_key:
            raise ValueError("API Key is missing")
            
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.1-pro-preview:generateContent?key={api_key}"
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.0, # Strict determinism for master parlay selection
                "responseMimeType": "application/json"
            }
        }
        
        max_retries = 3
        for attempt in range(max_retries):
            try:
                response = requests.post(url, headers={'Content-Type': 'application/json'}, json=payload, timeout=120)
                response.raise_for_status()
                break
            except requests.exceptions.RequestException as e:
                if attempt < max_retries - 1:
                    import time
                    print(f"⚠️ Network error (Risk Officer). Retrying {attempt + 1}/{max_retries} in 5s...")
                    time.sleep(5)
                else:
                    raise
        master_end = datetime.now()
        print(f"✅ [Risk Officer] Master parlay crafted in {(master_end - master_start).total_seconds():.2f}s")
        
        response_json = response.json()
        raw_text = response_json['candidates'][0]['content']['parts'][0]['text']
        
        return json.loads(raw_text)
        
    except Exception as e:
        print(f"Error generating best picks: {e}")
        return {
            "master_reasoning": "Failed to generate AI accumulator due to an error.",
            "picks": []
        }
