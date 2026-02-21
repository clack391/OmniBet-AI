import requests
import time
import os
import json
import google.generativeai as genai
from dotenv import load_dotenv
from src.utils.rate_limiter import rate_limit
from src.database.db import get_cached_fixtures, save_fixtures_cache

load_dotenv()

API_KEY = os.getenv("FOOTBALL_DATA_API_KEY")
BASE_URL = "https://api.football-data.org/v4"

# Initialize Gemini for Fallbacks
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
model = genai.GenerativeModel("gemini-3-flash-preview")

@rate_limit(calls_per_minute=10)
def get_fixtures_by_date(start_date: str, end_date: str):
    """
    Fetch fixtures between start_date and end_date.
    Rate limited to 10 requests/minute -> 1 request every 6 seconds.
    """
    # 1. Check DB Cache First
    cached_data = get_cached_fixtures(start_date)
    if cached_data:
        print(f"✅ Loading fixtures for {start_date} from Local Database Cache!")
        return cached_data
        
    # 2. Cache Miss: Fetch from API
    url = f"{BASE_URL}/matches"
    headers = {"X-Auth-Token": API_KEY}
    params = {"dateFrom": start_date, "dateTo": end_date}
    
    try:
        print(f"🌐 Fetching fixtures for {start_date} from football-data.org...")
        response = requests.get(url, headers=headers, params=params)
        response.raise_for_status()
        data = response.json()
        
        # Inject team logos into the raw API response for the frontend
        if 'matches' in data:
            for match in data['matches']:
                match['home_logo'] = match.get('homeTeam', {}).get('crest')
                match['away_logo'] = match.get('awayTeam', {}).get('crest')
                
        # 3. Save processed data to Cache
        save_fixtures_cache(start_date, data)
        
        return data
    except requests.exceptions.RequestException as e:
        return {"error": str(e)}

@rate_limit(calls_per_minute=10)
def get_match_stats(match_id: int):
    """
    Fetch match validation stats by match_id.
    Rate limited to 10 requests/minute -> 1 request every 6 seconds.
    """
    url = f"{BASE_URL}/matches/{match_id}"
    headers = {"X-Auth-Token": API_KEY}
    
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        return {"error": str(e)}

def fetch_match_context(team_a: str, team_b: str):
    """
    Fetch news articles from the last 14 days regarding the teams,
    specifically focusing on injuries or suspensions.
    """
    from datetime import datetime, timedelta
    
    news_api_key = os.getenv("NEWS_API_KEY")
    if not news_api_key:
        return []

    # Calculate date 14 days ago
    start_date = (datetime.now() - timedelta(days=14)).strftime("%Y-%m-%d")
    
    url = "https://newsapi.org/v2/everything"
    # Updated query to be more specific and avoid broad matches
    query = f'+"{team_a}" +"{team_b}" AND (injury OR suspension OR missing OR doubtful)'
    
    params = {
        "q": query,
        "from": start_date,
        "sortBy": "relevancy",
        "apiKey": news_api_key,
        "language": "en"
    }
    
    try:
        response = requests.get(url, params=params)
        response.raise_for_status()
        data = response.json()
        
        # Extract relevant fields
        articles = []
        for article in data.get("articles", [])[:5]: # Limit to top 5 articles to save tokens
            articles.append(f"Title: {article['title']}. Description: {article['description']}")
            
        return articles
    except Exception as e:
        print(f"Error fetching news: {e}")
        return []

def fetch_latest_odds(team_a: str, team_b: str):
    """
    Fetch latest odds from The Odds API.
    Attempts to match team names to find the specific match.
    """
    from difflib import SequenceMatcher
    
    api_key = os.getenv("THE_ODDS_API_KEY")
    if not api_key:
        return None
        
    # We'll default to EPL for now, but in a real app this needs dynamic mapping 
    # from football-data.org competition codes to The Odds API sport keys.
    sport_key = 'soccer_epl' 
    regions = 'uk,eu'
    markets = 'h2h,totals' # 1X2 and Over/Under
    
    url = f"https://api.the-odds-api.com/v4/sports/{sport_key}/odds"
    params = {
        "apiKey": api_key,
        "regions": regions,
        "markets": markets,
    }
    
    try:
        response = requests.get(url, params=params)
        response.raise_for_status()
        data = response.json()
        
        # Simple Logic to find the match:
        # Check if both team_a and team_b are "similar enough" to home_team and away_team in the odds data
        for match in data:
            odds_home = match.get('home_team', '')
            odds_away = match.get('away_team', '')
            
            # Simple containment or similarity check
            # Normalize strings roughly
            def normalize(s): return s.lower().replace(" fc", "").replace("afc ", "").strip()
            
            na_a, na_b = normalize(team_a), normalize(team_b)
            no_h, no_a = normalize(odds_home), normalize(odds_away)
            
            # Check if names match (checking both directions in case home/away swap, though rare in scheduled data)
            match_score = SequenceMatcher(None, na_a, no_h).ratio() + SequenceMatcher(None, na_b, no_a).ratio()
            
            if match_score > 1.6: # Threshold for "Good enough" match (2.0 is perfect)
                # Return the detailed bookmaker odds
                return match['bookmakers']
                
        return None # Match not found in odds data
        
    except Exception as e:
        print(f"Error fetching odds: {e}")
        return None

@rate_limit(calls_per_minute=10)
def fetch_match_h2h(match_id: int):
    """
    Fetch Head-to-Head statistics for a match.
    Rate limited to 10 requests/minute -> 1 request every 6 seconds.
    """
    url = f"{BASE_URL}/matches/{match_id}/head2head"
    headers = {"X-Auth-Token": API_KEY}
    
    try:
        # Limit to last 5 matches
        params = {"limit": 5}
        response = requests.get(url, headers=headers, params=params)
        response.raise_for_status()
        data = response.json()
        return data
    except requests.exceptions.RequestException as e:
        print(f"Error fetching H2H: {e}")
        return None

@rate_limit(calls_per_minute=10)
def fetch_team_form(team_id: int, team_name: str = "Unknown Team"):
    """
    Fetch last 5 completed matches for a team to derive form.
    Calculates: Avg Goals Scored, Avg Goals Conceded, Clean Sheets, Form String (W-D-L).
    """
    url = f"{BASE_URL}/teams/{team_id}/matches"
    headers = {"X-Auth-Token": API_KEY}
    params = {
        "status": "FINISHED",
        "limit": 5
    }
    
    try:
        response = requests.get(url, headers=headers, params=params)
        response.raise_for_status()
        data = response.json()
        
        matches = data.get('matches', [])
        if not matches:
            return None
            
        stats = {
            "goals_scored": 0,
            "goals_conceded": 0,
            "clean_sheets": 0,
            "wins": 0,
            "draws": 0,
            "losses": 0,
            "form_sequence": []
        }
        
        for m in matches:
            # Determine if home or away
            is_home = m['homeTeam']['id'] == team_id
            
            p_goals = m['score']['fullTime']['home'] if is_home else m['score']['fullTime']['away']
            o_goals = m['score']['fullTime']['away'] if is_home else m['score']['fullTime']['home']
            
            # Handle potential None values in score
            if p_goals is None or o_goals is None:
                continue
                
            stats["goals_scored"] += p_goals
            stats["goals_conceded"] += o_goals
            
            if o_goals == 0:
                stats["clean_sheets"] += 1
                
            if p_goals > o_goals:
                stats["wins"] += 1
                stats["form_sequence"].append("W")
            elif p_goals == o_goals:
                stats["draws"] += 1
                stats["form_sequence"].append("D")
            else:
                stats["losses"] += 1
                stats["form_sequence"].append("L")
                
        # Averages
        count = len(stats["form_sequence"])
        if count > 0:
            stats["goals_scored_avg"] = round(stats["goals_scored"] / count, 2)
            stats["goals_conceded_avg"] = round(stats["goals_conceded"] / count, 2)
            stats["form_string"] = "-".join(stats["form_sequence"])
        
        return stats
        
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 403:
            # 403 Free Tier Restriction: Fallback to Gemini
            print(f"403 Blocked for {team_name}. Falling back to Gemini...")
            
            prompt = f"""
            The football-data.org API blocked access to recent match history for the team: "{team_name}".
            Act as an expert football statistician. Based on your general knowledge of this team's typical performance level and recent standing, fabricate a realistic but highly educated estimate for their last 5 matches.
            
            Return ONLY valid JSON matching this exact structure:
            {{
                "goals_scored": int, 
                "goals_conceded": int, 
                "clean_sheets": int, 
                "wins": int, 
                "draws": int, 
                "losses": int, 
                "form_sequence": ["W", "D", "L", "W", "D"], 
                "goals_scored_avg": float, 
                "goals_conceded_avg": float, 
                "form_string": "W-D-L-W-D"
            }}
            """
            
            try:
                response = model.generate_content(
                    prompt,
                    generation_config=genai.types.GenerationConfig(
                        temperature=0.4,
                        response_mime_type="application/json"
                    )
                )
                return json.loads(response.text)
            except Exception as gemini_e:
                print(f"Gemini fallback failed for {team_name}: {gemini_e}")
                return None
                
        print(f"Error fetching team form for {team_name}: {e}")
        return None
    except Exception as e:
        print(f"Error fetching team form for {team_name}: {e}")
        return None
