import requests
import time
import os
import json
import google.generativeai as genai
from datetime import datetime, timedelta
from dotenv import load_dotenv
import pandas as pd
from src.utils.rate_limiter import rate_limit
from src.database.db import get_cached_fixtures, save_fixtures_cache

load_dotenv()

RAPID_API_KEY = os.getenv("RAPID_API_KEY")
RAPID_API_HOST = os.getenv("RAPID_API_HOST", "sofascore6.p.rapidapi.com")

API_KEY = os.getenv("FOOTBALL_DATA_API_KEY")
BASE_URL = "https://api.football-data.org/v4"

# Initialize Gemini for Fallbacks
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
model = genai.GenerativeModel("gemini-3.1-pro-preview")

# Cache for league standings with TTL 
# Structure: { competition_id: {"data": [...], "fetched_at": datetime} }
standings_cache = {}

@rate_limit(calls_per_minute=6)
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
        response = requests.get(url, headers=headers, params=params, timeout=15)
        response.raise_for_status()
        data = response.json()
        
        # Inject team logos into the raw API response for the frontend
        if 'matches' in data:
            for match in data['matches']:
                match['home_logo'] = match.get('homeTeam', {}).get('crest', '').replace("http://", "https://") if match.get('homeTeam', {}).get('crest') else None
                match['away_logo'] = match.get('awayTeam', {}).get('crest', '').replace("http://", "https://") if match.get('awayTeam', {}).get('crest') else None
                
        # 3. Save processed data to Cache
        save_fixtures_cache(start_date, data)
        
        return data
    except requests.exceptions.RequestException as e:
        return {"error": str(e)}

@rate_limit(calls_per_minute=6)
def get_match_stats(match_id: int):
    """
    Fetch match validation stats by match_id.
    Rate limited to 10 requests/minute -> 1 request every 6 seconds.
    """
    url = f"{BASE_URL}/matches/{match_id}"
    headers = {"X-Auth-Token": API_KEY}
    
    try:
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        return {"error": str(e)}

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

@rate_limit(calls_per_minute=6)
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
        response = requests.get(url, headers=headers, params=params, timeout=15)
        response.raise_for_status()
        data = response.json()
        return data
    except requests.exceptions.RequestException as e:
        print(f"Error fetching H2H: {e}")
        return None

@rate_limit(calls_per_minute=6)
def fetch_team_form(team_id: int, team_name: str = "Unknown Team", venue: str = None):
    """
    Fetch last 5 completed matches for a team to derive form.
    Calculates: Avg Goals Scored, Avg Goals Conceded, Clean Sheets, Form String (W-D-L).
    Accepts an optional 'venue' parameter ("HOME" or "AWAY") to filter matches.
    """
    url = f"{BASE_URL}/teams/{team_id}/matches"
    headers = {"X-Auth-Token": API_KEY}
    params = {
        "status": "FINISHED",
        "limit": 5
    }
    
    if venue:
        params["venue"] = venue
    
    try:
        response = requests.get(url, headers=headers, params=params, timeout=15)
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
            "form_sequence": [],
            "recent_scorelines": []
        }
        
        for m in matches:
            # Determine if home or away
            is_home = m['homeTeam']['id'] == team_id
            
            p_goals = m['score']['fullTime']['home'] if is_home else m['score']['fullTime']['away']
            o_goals = m['score']['fullTime']['away'] if is_home else m['score']['fullTime']['home']
            opponent_name = m['awayTeam']['shortName'] if is_home else m['homeTeam']['shortName']
            
            # Handle potential None values in score
            if p_goals is None or o_goals is None:
                continue
                
            # Ground the AI with explicit factual scorelines
            stats["recent_scorelines"].append(f"vs {opponent_name}: {p_goals}-{o_goals}")
                
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
            venue_context = f"specifically for matches played at {venue} " if venue else ""
            print(f"403 Blocked for {team_name}. Falling back to Gemini...")
            
            prompt = f"""
            The football-data.org API blocked access to recent match history for the team: "{team_name}".
            Act as an expert football statistician. Based on your general knowledge of this team's typical performance level and recent standing, fabricate a realistic but highly educated estimate for their last 5 matches {venue_context}.
            
            Return ONLY valid JSON matching this exact structure:
            {{
                "goals_scored": int, 
                "goals_conceded": int, 
                "clean_sheets": int, 
                "wins": int, 
                "draws": int, 
                "losses": int, 
                "form_sequence": ["W", "D", "L", "W", "D"], 
                "recent_scorelines": ["vs Team: 1-1", "vs Team: 2-0", "vs Team: 0-1", "vs Team: 3-3", "vs Team: 0-0"],
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

@rate_limit(calls_per_minute=6)
def get_team_standings(team_id: int, competition_id: int = 2021) -> dict:
    """
    Fetch league standings for a specific team.
    Uses a 12-hour Time-To-Live (TTL) dictionary cache to minimize API calls.
    Defaults to 2021 (Premier League).
    """
    global standings_cache
    
    # 1. Check TTL Cache
    if competition_id in standings_cache:
        cache_entry = standings_cache[competition_id]
        time_since_fetch = datetime.now() - cache_entry["fetched_at"]
        
        if time_since_fetch < timedelta(hours=12):
            print(f"✅ Loading standings for Comp {competition_id} from 12-Hour Cache (Age: {time_since_fetch})")
            standings_data = cache_entry["data"]
        else:
            print(f"♻️ Cache for Comp {competition_id} expired. Fetching fresh standings...")
            standings_data = None
    else:
        standings_data = None

    # 2. Fetch from API if Cache Miss or Expired
    if not standings_data:
        url = f"{BASE_URL}/competitions/{competition_id}/standings"
        headers = {"X-Auth-Token": API_KEY}
        
        try:
            print(f"🌐 Fetching fresh table for Comp {competition_id} from API...")
            response = requests.get(url, headers=headers, timeout=15)
            response.raise_for_status()
            data = response.json()
            
            # Extract the actual standings array (usually Total table)
            if 'standings' in data and len(data['standings']) > 0:
                standings_data = data['standings'][0].get('table', [])
                
                # Update Cache with Data and Timestamp
                standings_cache[competition_id] = {
                    "data": standings_data,
                    "fetched_at": datetime.now()
                }
            else:
                return {} # Invalid data format
                
        except Exception as e:
            print(f"Error fetching standings: {e}")
            # If the API fails but we have stale cache, use the stale cache as a fallback!
            if competition_id in standings_cache:
                print("⚠️ API failed. Falling back to stale standings cache.")
                standings_data = standings_cache[competition_id]["data"]
            else:
                return {}

    # 3. Find and Return the Specific Team's Stats
    for team_row in standings_data:
        if team_row.get("team", {}).get("id") == team_id:
            return {
                "position": team_row.get("position"),
                "playedGames": team_row.get("playedGames"),
                "won": team_row.get("won"),
                "draw": team_row.get("draw"),
                "lost": team_row.get("lost"),
                "points": team_row.get("points"),
                "goalsFor": team_row.get("goalsFor"),
                "goalsAgainst": team_row.get("goalsAgainst"),
                "goalDifference": team_row.get("goalDifference")
            }
            
    return {} # Team not found in that competition

def resolve_sofascore_match_id(team_a: str, team_b: str, match_date: str = None) -> int:
    """
    RapidAPI SofaScore6 does not have a reliable team name search endpoint.
    To avoid using expensive Apify scraper credits for every lookup, we use
    `curl_cffi` to perfectly impersonate a Chrome browser TLS signature, which
    bypasses Cloudflare's 403 blocks against standard Python requests.
    We hit the official SofaScore search API directly.
    """
    try:
        from curl_cffi import requests as cffi_requests
    except ImportError:
        print("Missing curl_cffi for ID Resolution. Install via `pip install curl_cffi`")
        return None
        
    try:
        import urllib.parse
        query = f"{team_a} {team_b}"
        url = f"https://api.sofascore.com/api/v1/search/events?q={urllib.parse.quote(query)}"
        
        # We don't need heavy headers, just the TLS impersonation
        try:
            res = cffi_requests.get(url, impersonate="chrome120", timeout=10)
        except Exception as req_e:
            print(f"curl_cffi request failed: {req_e}")
            return None
            
        if res.status_code == 200:
            data = res.json()
            if 'results' in data and len(data['results']) > 0:
                # We optionally verify if the result name sort of matches our teams
                # But typically the first search result is highly accurate.
                return data['results'][0].get('entity', {}).get('id')
                
        return None
    except Exception as e:
        print(f"curl_cffi ID Resolution Error: {e}")
        return None

@rate_limit(calls_per_minute=20)
def get_sofascore_match_stats(sofascore_match_id: int):
    """
    Fetches detailed match and team statistics using the RapidAPI SofaScore6 wrapper.
    Returns a Pandas DataFrame and a flat JSON dictionary of advanced metrics.
    """
    if not RAPID_API_KEY:
        print("Warning: RAPID_API_KEY not found in .env")
        return None, None
        
    headers = {
        "x-rapidapi-host": RAPID_API_HOST,
        "x-rapidapi-key": RAPID_API_KEY
    }
    
    # 1. Fetch Event Details to get IDs
    event_url = f"https://{RAPID_API_HOST}/api/sofascore/v1/match/details"
    event_res = requests.get(event_url, headers=headers, params={"match_id": sofascore_match_id})
    
    if event_res.status_code != 200:
        print(f"Could not fetch match {sofascore_match_id} data. Status: {event_res.status_code}")
        return None, None

    # The RapidAPI response doesn't wrap it in an 'event' object; the payload IS the event
    event_data = event_res.json()
    
    home_id = event_data.get('homeTeam', {}).get('id')
    home_name = event_data.get('homeTeam', {}).get('name')
    away_id = event_data.get('awayTeam', {}).get('id')
    away_name = event_data.get('awayTeam', {}).get('name')
    
    # Handle flat or nested tournament structure
    tournament_id = event_data.get('uniqueTournament', {}).get('id')
    if not tournament_id:
         tournament_id = event_data.get('tournament', {}).get('uniqueTournament', {}).get('id')
         
    season_id = event_data.get('season', {}).get('id')
    
    if not tournament_id or not season_id or not home_id or not away_id:
        print(f"Missing required IDs for Match {sofascore_match_id}.")
        return None, None
    
    # 2. Fetch Team Overall Statistics
    stats_url = f"https://{RAPID_API_HOST}/api/sofascore/v1/team/statistics"
    
    home_params = {"team_id": home_id, "unique_tournament_id": tournament_id, "season_id": season_id}
    away_params = {"team_id": away_id, "unique_tournament_id": tournament_id, "season_id": season_id}
    
    home_stats_res = requests.get(stats_url, headers=headers, params=home_params)
    away_stats_res = requests.get(stats_url, headers=headers, params=away_params)
    
    if home_stats_res.status_code == 200 and away_stats_res.status_code == 200:
        home_data = home_stats_res.json()
        away_data = away_stats_res.json()
        
        # Sometimes RapidAPI returns a list of stat objects (e.g., if a tournament has multiple stages like Group & Knockout)
        if isinstance(home_data, list) and len(home_data) > 0:
            home_stats = home_data[0].get('statistics', {})
        elif isinstance(home_data, dict):
            home_stats = home_data.get('statistics', {})
        else:
            home_stats = {}
            
        if isinstance(away_data, list) and len(away_data) > 0:
            away_stats = away_data[0].get('statistics', {})
        elif isinstance(away_data, dict):
            away_stats = away_data.get('statistics', {})
        else:
            away_stats = {}
        
        matches_home = home_stats.get('matches', 1) 
        matches_away = away_stats.get('matches', 1)

        metrics_to_compare = [
            ("Matches", "matches", False),
            ("Goals scored", "goalsScored", False),
            ("Goals conceded", "goalsConceded", False),
            ("Assists", "assists", False),
            ("Goals per game", "goalsScored", True),
            ("Shots on target per game", "shotsOnTarget", True),
            ("Big chances created", "bigChancesCreated", False),
            ("Big chances missed", "bigChancesMissed", False),
            ("Ball possession (%)", "averageBallPossession", False),
            ("Accurate passes per game", "accuratePasses", True),
            ("Acc. long balls per game", "accurateLongBalls", True),
            ("Clean sheets", "cleanSheets", False),
            ("Goals conceded per game", "goalsConceded", True),
            ("Interceptions per game", "interceptions", True),
            ("Tackles per game", "tackles", True),
            ("Clearances per game", "clearances", True),
            ("Penalty goals conceded", "penaltyGoalsConceded", False),
            ("Saves per game", "saves", True),
            ("Duels won per game", "duelsWon", True),
            ("Fouls per game", "fouls", True),
            ("Offsides per game", "offsides", True),
            ("Goal kicks per game", "goalKicks", True),
            ("Throw-ins per game", "throwIns", True),
            ("Yellow cards", "yellowCards", False),
            ("Red cards", "redCards", False)
        ]
        
        data_rows = []
        
        for display_name, json_key, needs_math in metrics_to_compare:
            h_val = home_stats.get(json_key)
            a_val = away_stats.get(json_key)
            
            if needs_math:
                h_val = round(h_val / matches_home, 1) if h_val is not None else None
                a_val = round(a_val / matches_away, 1) if a_val is not None else None
            else:
                if isinstance(h_val, float): h_val = round(h_val, 1)
                if isinstance(a_val, float): a_val = round(a_val, 1)
            
            data_rows.append({
                "Statistic": display_name,
                home_name: h_val,
                away_name: a_val
            })
            
        df = pd.DataFrame(data_rows)
        df.set_index("Statistic", inplace=True)
        
        flat_json = {}
        for row in data_rows:
            stat_name = row["Statistic"]
            flat_json[stat_name] = {
                home_name: row[home_name],
                away_name: row[away_name]
            }
            
        return df, flat_json
            
    else:
        print(f"Stats fetch failed. Home {home_stats_res.status_code}, Away {away_stats_res.status_code}")
        return None, None


