import json
import os
import requests
from dotenv import load_dotenv

# Force dotenv to look in the project root instead of the current /src/services/ directory
env_path = os.path.join(os.path.dirname(__file__), '..', '..', '.env')
load_dotenv(dotenv_path=env_path)

# The user specified gemini-3-pro-preview for best search grounding results.
# We interact via pure REST to avoid SDK protobuf validation errors with bleeding-edge models.
MODEL_NAME = "gemini-3-pro-preview"

def fetch_result_with_ai(team_a: str, team_b: str, match_date: str, safe_bet_tip: str) -> dict:
    """
    Uses Gemini with Google Search Grounding to scrape the live internet for a match result
    and grade the AI's previous prediction.
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
            raise ValueError("GEMINI_API_KEY or GOOGLE_API_KEY is missing from environment variables.")
            
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL_NAME}:generateContent?key={api_key}"
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "tools": [{"googleSearch": {}}],  # Native REST syntax for Google Search Grounding
            "generationConfig": {
                "temperature": 0.0,
                "responseMimeType": "application/json"
            }
        }
        
        response = requests.post(url, headers={'Content-Type': 'application/json'}, json=payload)
        response.raise_for_status()
        
        # Parse the JSON response
        response_json = response.json()
        
        # Extract the text content from the Gemini response structure
        raw_text = response_json['candidates'][0]['content']['parts'][0]['text']
        
        # It's already forced to be JSON by responseMimeType
        return json.loads(raw_text)
        
    except Exception as e:
        print(f"Error in fetch_result_with_ai: {e}")
        return {
            "actual_score": "Error Occurred",
            "status": "Unknown",
            "is_correct": None
        }
