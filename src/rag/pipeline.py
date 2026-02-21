import os
import json
import chromadb
import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()

# Initialize ChromaDB (Ephemeral for JIT)
chroma_client = chromadb.Client()

# Initialize Gemini
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

# Use a standard stable model compatible with the free tier/broad availability
# User requested "Gemini 3 flash preview"
MODEL_NAME = "gemini-3-flash-preview" 
model = genai.GenerativeModel(MODEL_NAME)

from datetime import datetime, timezone

def predict_match(team_a: str, team_b: str, match_stats: dict, news_context: list, odds_data: list = None, h2h_data: dict = None, home_form: dict = None, away_form: dict = None):

    # JIT Vectorization
    # Sanitize collection name: Only allow alphanumeric, underscores, and hyphens. Max 63 chars for safety.
    import re
    safe_team_a = re.sub(r'[^a-zA-Z0-9]', '', team_a.lower())
    safe_team_b = re.sub(r'[^a-zA-Z0-9]', '', team_b.lower())
    collection_name = f"match_{safe_team_a}_{safe_team_b}"[:63]
    try:
        chroma_client.delete_collection(collection_name)
    except:
        pass
        
    collection = chroma_client.create_collection(name=collection_name)
    
    if news_context:
        collection.add(
            documents=news_context,
            ids=[str(i) for i in range(len(news_context))]
        )
        # Updated query to use team names more broadly if needed
        results = collection.query(
            query_texts=[f"injury suspension {team_a} {team_b}"],
            n_results=min(len(news_context), 3)
        )
        if results['documents']:
             context_text = "\n".join(results['documents'][0])
        else:
             context_text = "No relevant news found in context."
    else:
        context_text = "No recent injury or suspension news found."

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
    
    ### Recent Team Form (Last 5 Matches Derived Stats)
    Home Team ({team_a}): {json.dumps(home_form, indent=2) if home_form else "N/A"}
    Away Team ({team_b}): {json.dumps(away_form, indent=2) if away_form else "N/A"}
    
    ### Recent News (Injury/Suspension Context)
    {context_text}
    
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
         - *Form vs Odds*: Find value where form contradicts high odds.
         - *H2H vs Current Form*: Prioritize CURRENT FORM.
         - *News Impact*: Downgrade team significantly if key players missing.
    
    4. **Chain-of-Thought Process**: Before declaring any predictions, you MUST think step-by-step. First, analyze the offensive stats vs defensive stats. Second, factor in the NewsAPI injury reports. Third, evaluate the implied probability of the Vegas odds.
    
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
        "safe_bet_tip": "The Single Best Prediction",
        "confidence": 85,
        "reasoning": ["point 1", "point 2", "point 3"]
    }}
    """
    
    try:
        response = model.generate_content(
            prompt,
            generation_config=genai.types.GenerationConfig(
                temperature=0.0, # Keep deterministic
                response_mime_type="application/json"
            )
        )
        return json.loads(response.text)
    except Exception as e:
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
