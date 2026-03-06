import json
import os
import requests
from dotenv import load_dotenv

# Import our project helpers
from src.services.sports_api import resolve_sofascore_match_id, get_sofascore_match_grade_data

env_path = os.path.join(os.path.dirname(__file__), '..', '..', '.env')
load_dotenv(dotenv_path=env_path)

# Use the same model as the main pipeline
MODEL_NAME = "gemini-3-pro-preview"

def fetch_result_with_ai_fallback(team_a: str, team_b: str, match_date: str, safe_bet_tip: str) -> dict:
    """
    The original Google Search-based grader used as a fallback if RapidAPI completely fails
    or if the match ID cannot be resolved.
    """
    prompt = f"""
    Act as a strict sports betting adjudicator.
    
    ### Task
    Search the web for the final or live soccer score between {team_a} and {team_b} played on {match_date}.
    Then, evaluate if the prediction '{safe_bet_tip}' won or lost based on that score.
    
    ### Rules
    1. If the match has not started yet or was postponed, set `status` to "Scheduled" and `is_correct` to null.
    2. If the match is currently playing, set `status` to "Live" and evaluate `is_correct` IF the bet has already won or lost (e.g. "Over 2.5 goals" and the score is already 2-1). Otherwise, set `is_correct` to null.
    3. If the match is finished, set `status` to "Finished" and firmly evaluate `is_correct` as true or false.

    ### Output Format
    Return ONLY valid JSON matching this exact structure:
    {{
        "actual_score": "e.g., Chelsea 2 - 0 Burnley",
        "status": "e.g., Finished, Live, or Scheduled",
        "is_correct": true, false, or null
    }}
    """
    
    try:
        api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY or GOOGLE_API_KEY missing")
            
        from google import genai
        client = genai.Client(api_key=api_key)
        
        response = client.models.generate_content(
            model='gemini-2.0-flash',
            contents=prompt,
            config={"tools": [{"googleSearch": {}}]}
        )
        
        # Parse JSON block from pure text string
        raw_text = response.text.strip().replace("```json", "").replace("```", "")
        return json.loads(raw_text)
        
    except Exception as e:
        print(f"Error in fetch_result_with_ai_fallback: {e}")
        return {
            "actual_score": "Error Occurred",
            "status": "Unknown",
            "is_correct": None
        }

def fetch_result_with_ai(team_a: str, team_b: str, match_date: str, safe_bet_tip: str) -> dict:
    """
    Uses RapidAPI SofaScore direct retrieval combined with Gemini evaluating the payload.
    Gracefully falls back to pure Google Search if RapidAPI fails.
    """
    
    # 1. Resolve Match ID (using existing project helper)
    print(f"🔍 [Grader] Resolving SofaScore Match ID for {team_a} vs {team_b}...")
    match_id = resolve_sofascore_match_id(team_a, team_b, match_date)
    
    if not match_id:
        print(f"⚠️ Could not resolve Match ID for {team_a} vs {team_b}. Falling back to Search.")
        return fetch_result_with_ai_fallback(team_a, team_b, match_date, safe_bet_tip)
        
    # 2. Fetch Grade Data (Consolidated RapidAPI calls)
    print(f"📡 [Grader] Fetching RapidAPI data for match_id: {match_id}")
    grade_data = get_sofascore_match_grade_data(match_id)
    
    if not grade_data or grade_data.get("score_summary") == "Unknown":
        print(f"⚠️ Failed to fetch RapidAPI grade data for {match_id}. Falling back to Search.")
        return fetch_result_with_ai_fallback(team_a, team_b, match_date, safe_bet_tip)
        
    actual_score_str = grade_data["score_summary"]
    status_desc = grade_data["match_status"]
    
    # 3. AI Adjudication
    print(f"⚖️ [Grader] Evaluating {safe_bet_tip} against RapidAPI payload...")
    prompt = f"""
    Act as a strict sports betting adjudicator.
    
    I am providing you with the exact raw SofaScore data (JSON format) for the match between {team_a} and {team_b}.
    
    Based heavily on the 'score_summary', 'statistics', and 'incidents' lists provided below, evaluate if the predicted betting tip `{safe_bet_tip}` won or lost.

    SofaScore Payload Dump:
    {json.dumps(grade_data)[:25000]} 

    ### Rules
    1. If the match status is not finished, set `status` to "Live" or "Scheduled" and evaluate `is_correct` only if mathematically determined (e.g. Over 2.5 hits when score is 2-1).
    2. Review corners and cards in the 'statistics' or 'incidents' arrays carefully to grade micro-markets.
    3. The absolute score string should be your `actual_score` output.

    ### Output Format
    Return ONLY valid JSON matching this exact structure:
    {{
        "actual_score": "{actual_score_str}",
        "status": "e.g., Finished, Live, or Scheduled",
        "is_correct": true, false, or null
    }}
    """
    
    try:
        api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        from google import genai
        client = genai.Client(api_key=api_key)
        
        response = client.models.generate_content(
            model='gemini-2.0-flash',
            contents=prompt
        )
        raw_text = response.text.strip().replace("```json", "").replace("```", "")
        return json.loads(raw_text)
        
    except Exception as e:
        print(f"Error in RapidAPI Grader: {e}")
        return {
            "actual_score": actual_score_str,
            "status": status_desc,
            "is_correct": None
        }
