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

def _extract_json(text: str) -> dict:
    """Helper to robustly extract JSON from AI text responses."""
    if not text:
        return {}
    
    import re
    # 1. Look for ```json ... ``` blocks
    json_match = re.search(r'```json\s*(\{.*?\})\s*```', text, re.DOTALL)
    if json_match:
        try:
            return json.loads(json_match.group(1))
        except:
            pass
            
    # 2. Look for any {...} block
    any_json = re.search(r'(\{.*\})', text, re.DOTALL)
    if any_json:
        try:
            return json.loads(any_json.group(1))
        except:
            pass

    # 3. Last ditch: strip common markdown
    cleaned = text.strip().replace("```json", "").replace("```", "").strip()
    try:
        return json.loads(cleaned)
    except:
        return {}


def fetch_result_with_ai_fallback(team_a: str, team_b: str, match_date: str, safe_bet_tip: str) -> dict:
    """
    The original Google Search-based grader used as a fallback if RapidAPI completely fails
    or if the match ID cannot be resolved.
    """
    prompt = f"""
    Act as a strict sports betting adjudicator with access to global football data sources.
    
    ### Task
    Search the web for the FINAL score of the soccer match between {team_a} and {team_b} played on {match_date}.
    Then evaluate if the prediction '{safe_bet_tip}' won or lost.
    
    ### MANDATORY SEARCH STRATEGY (Execute ALL of these searches):
    1. Search: "{team_a} {team_b} {match_date} score result"
    2. Search: "{team_a} vs {team_b} résultat" (French sources — many African/Algerian leagues are covered only in French)
    3. Search: "flashscore {team_a} {team_b}" OR "livescore {team_a} {team_b}"
    4. Search: "{team_a} {team_b} soccerway" OR "{team_a} {team_b} sofascore"
    5. If no English results: search the team names in their local language spellings
    
    ### Key Instruction
    You MUST exhaust all search attempts before declaring the result "Not available". 
    FlashScore and Soccerway cover virtually every professional league worldwide including 
    Algerian Ligue Professionnelle 1, Moroccan, Tunisian, and all African leagues.
    
    ### Rules
    1. If the match has not started yet or was postponed, set `status` to "Scheduled" and `is_correct` to null.
    2. If the match is currently playing, set `status` to "Live" and evaluate if the bet is already settled. Otherwise set `is_correct` to null.
    3. If the match is finished, set `status` to "Finished" and FIRMLY evaluate `is_correct` as true, false, or "refund".

    ### Output Format
    Return ONLY valid JSON:
    {{
        "actual_score": "e.g., {team_a} 2 - 1 {team_b}",
        "status": "Finished, Live, or Scheduled",
        "is_correct": true, false, "refund", or null
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
        
        # Robust text extraction — google search grounding sometimes wraps text differently
        raw_text = None
        try:
            raw_text = response.text
        except Exception:
            pass
        if not raw_text:
            try:
                raw_text = response.candidates[0].content.parts[0].text
            except Exception:
                pass
        
        # Parse JSON block from pure text string
        result = _extract_json(raw_text or "")
        if not result:
             raise ValueError(f"Empty or invalid JSON extracted from: {str(raw_text)[:100]}...")
        return result
        
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
    grade_data = get_sofascore_match_grade_data(match_id, match_date)
    
    if not grade_data or grade_data.get("score_summary") == "Unknown":
        print(f"⚠️ Failed to fetch RapidAPI grade data for {match_id}. Falling back to Search.")
        return fetch_result_with_ai_fallback(team_a, team_b, match_date, safe_bet_tip)

    actual_score_str = grade_data["score_summary"]
    status_desc = grade_data["match_status"]

    # 2b. Team Identity Sanity Check — prevent grading the wrong match
    # If neither team name appears anywhere in the resolved score summary, it's a false positive ID.
    def _team_in_score(team_name, score_str):
        # Check if any meaningful word (>3 chars) from team_name appears in score_str
        score_lower = score_str.lower()
        return any(w.lower() in score_lower for w in team_name.split() if len(w) > 3)

    if not _team_in_score(team_a, actual_score_str) and not _team_in_score(team_b, actual_score_str):
        print(f"🚨 [Grader] Team mismatch! Expected '{team_a} vs {team_b}' but got '{actual_score_str}'. Falling back to Search.")
        return fetch_result_with_ai_fallback(team_a, team_b, match_date, safe_bet_tip)
    
    # 3. AI Adjudication
    print(f"⚖️ [Grader] Evaluating {safe_bet_tip} against RapidAPI payload...")
    prompt = f"""
    Act as a strict, expert sports betting adjudicator. 
    
    ### Match Context
    Target Match: {team_a} vs {team_b} on {match_date}
    Predicted Tip: `{safe_bet_tip}`
    
    ### Data Source: SofaScore Forensic Payload
    {json.dumps(grade_data)[:25000]} 

    ### Your Adjudication Task
    Evaluate if `{safe_bet_tip}` won, lost, or is still pending. You have access to the full match statistics, period scores, incident timeline, and player-level data.

    #### Market Grading Guide:
    1. **1X2 / Double Chance**: Use `score_summary`. If win, return true. If lose, return false.
    2. **Draw No Bet (DNB)**: Use `score_summary`. If the pick wins, return true. If the pick loses, return false. If the match ends in a draw, return "refund".
    3. **Over/Under Goals / BTTS**: Use `score_summary`.
    3. **HT/FT & Highest Scoring Half**: Compare `period_scores['period1']` vs `score_summary`.
    4. **Player Props (e.g. Shots/Goals/Cards)**: Locate the player in `player_statistics`. Look for fields like 'shotsOnTarget', 'goals', 'yellowCards'.
    5. **10/15/30 Minute Markets**: Inspect `incidents`. If a goal occurs at minute X, and the market is "No goal before X", it is a LOSS. 
    6. **Corners/Cards**: Verify exact counts in the `statistics` array.

    ### Mandatory Identity Check
    Ensure the teams in the payload match "{team_a}" & "{team_b}". If they are different, set `is_correct` to null.

    ### Output Format
    Return ONLY valid JSON:
    {{
        "actual_score": "{actual_score_str}",
        "status": "Finished, Live, or Scheduled",
        "is_correct": true, false, "refund", or null,
        "reasoning": "... e.g., 'Goal at 7 min broke 10 min draw. Match ended in draw, giving a DNB refund.'"
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
        result = _extract_json(response.text)
        if not result:
             raise ValueError(f"Empty or invalid JSON extracted from: {response.text[:100]}...")
        
        # Log the decision for auditing
        print(f"✅ [Grader Content] Result: {result.get('is_correct')} | Score: {result.get('actual_score')} | Reason: {result.get('reasoning')}")
        
        return result
        
    except Exception as e:
        print(f"Error in RapidAPI Grader: {e}")
        return {
            "actual_score": actual_score_str,
            "status": status_desc,
            "is_correct": None
        }
