import json
import os
import requests
from dotenv import load_dotenv

env_path = os.path.join(os.path.dirname(__file__), '..', '..', '.env')
load_dotenv(dotenv_path=env_path)

MODEL_NAME = "gemini-3-pro-preview"

def resolve_sofascore_url(team_a: str, team_b: str, match_date: str) -> str:
    """
    Uses Apify's official Google Search scraper to find the exact SofaScore URL.
    This safely bypasses Cloudflare and Google IP blocks while preventing LLM hallucination of URL hashes.
    """
    try:
        from apify_client import ApifyClient
    except ImportError:
        print("apify-client not installed.")
        return "NOT_FOUND"
        
    apify_token = os.getenv("APIFY_API_TOKEN")
    if not apify_token:
        print("Missing APIFY_API_TOKEN in .env for URL Resolution.")
        return "NOT_FOUND"
        
    try:
        client = ApifyClient(apify_token)
        query = f"site:sofascore.com/football/match {team_a} {team_b}"
        
        run_input = {
            "queries": query,
            "resultsPerPage": 3,
            "maxPagesPerQuery": 1,
            "languageCode": "en"
        }
        
        # Apify's lightweight Google Search Actor
        run = client.actor("apify/google-search-scraper").call(run_input=run_input)
        
        for item in client.dataset(run["defaultDatasetId"]).iterate_items():
            organic = item.get("organicResults", [])
            for res in organic:
                url = res.get("url", "")
                if "sofascore.com/football/match" in url:
                    return url
                    
        return "NOT_FOUND"
    except Exception as e:
        print(f"Apify URL Resolution Error: {e}")
        return "NOT_FOUND"

def scrape_sofascore_data(url: str) -> dict:
    """
    Uses the Apify client to scrape raw match data from the provided SofaScore URL.
    """
    try:
        from apify_client import ApifyClient
    except ImportError:
        return None
        
    apify_token = os.getenv("APIFY_API_TOKEN")
    if not apify_token:
        return None
        
    try:
        client = ApifyClient(apify_token)
        run_input = {"startUrls": [url]}
        
        run = client.actor("azzouzana/sofascore-scraper-pro").call(run_input=run_input)
        
        for item in client.dataset(run["defaultDatasetId"]).iterate_items():
            return item.get("data", {})
            
        return None
    except Exception as e:
        print(f"Apify Scraper Error: {e}")
        return None

def fetch_result_with_ai_fallback(team_a: str, team_b: str, match_date: str, safe_bet_tip: str) -> dict:
    """
    The original Google Search-based grader used as a fallback if Apify completely fails.
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
    Uses Apify SofaScore scraping combined with Gemini evaluating the payload.
    Gracefully falls back to pure Google Search if Apify fails or lacks a token.
    """
    apify_token = os.getenv("APIFY_API_TOKEN")
    
    if not apify_token:
        print("No Apify token found. Using Pure Google Search Fallback Grader.")
        return fetch_result_with_ai_fallback(team_a, team_b, match_date, safe_bet_tip)
        
    print(f"Resolving SofaScore URL for {team_a} vs {team_b} via Apify...")
    url = resolve_sofascore_url(team_a, team_b, match_date)
    
    if url == "NOT_FOUND":
        print("Could not resolve SofaScore URL. Using Pure Google Search Fallback Grader.")
        return fetch_result_with_ai_fallback(team_a, team_b, match_date, safe_bet_tip)
        
    print(f"Scraping SofaScore using Apify at URL: {url}")
    sofa_data = scrape_sofascore_data(url)
    
    if not sofa_data:
        print("Failed to scrape SofaScore data. Using Pure Google Search Fallback Grader.")
        return fetch_result_with_ai_fallback(team_a, team_b, match_date, safe_bet_tip)
        
    event_data = sofa_data.get("event", {})
    home_score = event_data.get("homeScore", {}).get("current", 0)
    away_score = event_data.get("awayScore", {}).get("current", 0)
    status_desc = event_data.get("status", {}).get("description", "Unknown")
    
    actual_score_str = f"{team_a} {home_score} - {away_score} {team_b}"
    
    trimmed_data = {
        "score_summary": actual_score_str,
        "match_status": status_desc,
        "statistics": sofa_data.get("statistics", []),
        "incidents": sofa_data.get("incidents", []) 
    }
    
    print("Grading match against parsed SofaScore payload using Gemini SDK...")
    prompt = f"""
    Act as a strict sports betting adjudicator.
    
    I am providing you with the exact raw SofaScore data (JSON format) for the match between {team_a} and {team_b}.
    
    Based heavily on the 'score_summary', 'statistics', and 'incidents' lists provided below, evaluate if the predicted betting tip `{safe_bet_tip}` won or lost.

    SofaScore Payload Dump:
    {json.dumps(trimmed_data)[:25000]} 

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
        print(f"Error in Hybrid Apify-Gemini Grader: {e}")
        return {
            "actual_score": actual_score_str,
            "status": status_desc,
            "is_correct": None
        }
