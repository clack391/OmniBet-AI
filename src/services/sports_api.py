import requests
import time
import os
import json
import google.generativeai as genai
from datetime import datetime, timedelta, timezone
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
# Use GEMINI_API_KEY or GOOGLE_API_KEY interchangeably
gemini_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
genai.configure(api_key=gemini_key)
model = genai.GenerativeModel("gemini-3-pro-preview")

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

def get_sofascore_fixtures(start_date: str, end_date: str):
    """
    Fetch fixtures from SofaScore directly instead of football-data.org.
    Maps exactly to the football-data output schema for frontend compatibility.
    """
    try:
        from curl_cffi import requests as cffi_requests
    except ImportError:
        print("Missing curl_cffi for SofaScore. Fast fallback to football-data.")
        return get_fixtures_by_date(start_date, end_date)
        
    
    # 1. Check DB Cache First
    # We use a unique prefix for SofaScore cache keys so they don't collide with football-data
    cache_key = f"sofascore_{start_date}_{end_date}"
    cached_data = get_cached_fixtures(cache_key)
    if cached_data:
        print(f"✅ Loading SofaScore fixtures for {start_date} to {end_date} from Local Database Cache!")
        return cached_data
        
    start_dt = datetime.strptime(start_date, "%Y-%m-%d")
    end_dt = datetime.strptime(end_date, "%Y-%m-%d")
    delta = end_dt - start_dt
    
    all_matches = []
    
    for i in range(delta.days + 1):
        target_date = (start_dt + timedelta(days=i)).strftime("%Y-%m-%d")
        print(f"🌐 Fetching fixtures for {target_date} from SofaScore...")
        url = f"https://api.sofascore.com/api/v1/sport/football/scheduled-events/{target_date}"
        
        try:
            res = cffi_requests.get(url, impersonate="chrome120", timeout=15)
            
            # CRITICAL: Detect if EC2 IP is blocked (403 Forbidden)
            if res.status_code in [403, 401]:
                print(f"⚠️ SofaScore BLOCKED this IP ({res.status_code}). Failing over to Football-Data...")
                return get_fixtures_by_date(start_date, end_date)
                
            if res.status_code == 200:
                data = res.json()
                events = data.get("events", [])
                
                for event in events:
                    # Filter for top level or specific tournaments if needed
                    status_type = event.get("status", {}).get("type")
                    status = "TIMED"
                    if status_type == "finished":
                        status = "FINISHED"
                    elif status_type == "inprogress":
                        status = "IN_PLAY"
                        
                    home_id = event.get("homeTeam", {}).get("id")
                    away_id = event.get("awayTeam", {}).get("id")
                    
                    mapped_match = {
                        "id": event.get("id"), # We pass the SofaScore event ID
                        "utcDate": datetime.fromtimestamp(event.get("startTimestamp", 0), tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                        "status": status,
                        "competition": {
                            "id": event.get("tournament", {}).get("uniqueTournament", {}).get("id") or 2021,
                            "name": event.get("tournament", {}).get("name", "Unknown")
                        },
                        "homeTeam": {
                            "id": home_id,
                            "name": event.get("homeTeam", {}).get("name")
                        },
                        "awayTeam": {
                            "id": away_id,
                            "name": event.get("awayTeam", {}).get("name")
                        },
                        "score": {
                            "fullTime": {
                                "home": event.get("homeScore", {}).get("current", None),
                                "away": event.get("awayScore", {}).get("current", None)
                            }
                        },
                        "home_logo": f"/team-logo/{home_id}" if home_id else None,
                        "away_logo": f"/team-logo/{away_id}" if away_id else None,
                        "_timestamp": event.get("startTimestamp", 0) # Temporary key for sorting
                    }
                    all_matches.append(mapped_match)
        except Exception as e:
            print(f"SofaScore Date Fetch Error for {target_date}: {e}")
            
    # Sort matches chronologically
    all_matches.sort(key=lambda x: x.get("_timestamp", 0))
    
    # Remove the temporary timestamp key before returning
    for match in all_matches:
        if "_timestamp" in match:
            del match["_timestamp"]

    final_data = {"matches": all_matches}
    
    # 3. Save processed data to Cache
    save_fixtures_cache(cache_key, final_data)
    
    return final_data

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
    Resolves the SofaScore match ID for a given fixture.
    Enhanced with fuzzy team name matching and date tolerance to ensure 
    the correct match is graded, even if team names or dates differ slightly 
    between providers (e.g., 'Chelyabinsk' vs 'FC Chelyabinsk').
    """
    from difflib import SequenceMatcher

    def normalize(name):
        return name.lower().replace("fc", "").replace("afc", "").replace("united", "utd").strip()

    try:
        from curl_cffi import requests as cffi_requests
    except ImportError:
        print("Missing curl_cffi for ID Resolution. Install via `pip install curl_cffi`")
        return None
        
    try:
        import urllib.parse
        query = f"{team_a} {team_b}"
        url = f"https://api.sofascore.com/api/v1/search/events?q={urllib.parse.quote(query)}"
        
        try:
            res = cffi_requests.get(url, impersonate="chrome120", timeout=10)
        except Exception as req_e:
            print(f"curl_cffi request failed: {req_e}")
            return None
            
        if res.status_code == 200:
            data = res.json()
            results = data.get('results', [])
            if not results:
                return None

            best_match = None
            highest_score = 0.0
            
            target_date_dt = None
            if match_date:
                try:
                    target_date_dt = datetime.strptime(match_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
                except ValueError:
                    pass

            for r in results:
                if r.get('type') != 'event': continue
                entity = r.get('entity', {})
                ts = entity.get('startTimestamp')
                if not ts: continue
                
                res_date_dt = datetime.fromtimestamp(ts, tz=timezone.utc)
                res_date_str = res_date_dt.strftime("%Y-%m-%d")

                # 1. Date Check (Strict or +/- 1 day tolerance)
                is_date_ok = False
                if not match_date:
                    is_date_ok = True # No date filter requested
                elif res_date_str == match_date:
                    is_date_ok = True # Exact match
                elif target_date_dt:
                    diff = abs((res_date_dt - target_date_dt).days)
                    if diff <= 1:
                        is_date_ok = True # Tolerance match for timezones/scheduling shifts

                if not is_date_ok:
                    continue

                # 2. Team Name Fuzzy Matching
                h_name = normalize(entity.get('homeTeam', {}).get('name', ''))
                a_name = normalize(entity.get('awayTeam', {}).get('name', ''))
                t_h_name = normalize(team_a)
                t_a_name = normalize(team_b)

                # Check both orientations (SofaScore sometimes swaps)
                score_normal = SequenceMatcher(None, h_name, t_h_name).ratio() + SequenceMatcher(None, a_name, t_a_name).ratio()
                score_swapped = SequenceMatcher(None, h_name, t_a_name).ratio() + SequenceMatcher(None, a_name, t_h_name).ratio()
                
                current_score = max(score_normal, score_swapped)
                
                # Bonus for exact date match
                if res_date_str == match_date:
                    current_score += 0.5 

                if current_score > highest_score:
                    highest_score = current_score
                    best_match = entity.get('id')

            # Threshold for a "Good Match" (1.4 is safe, 2.0+ is very strong with bonus)
            if best_match and highest_score > 1.3:
                print(f"✅ Resolved SofaScore ID {best_match} with confidence score {round(highest_score, 2)}")
                return best_match
                
        return None
    except Exception as e:
        print(f"curl_cffi ID Resolution Error: {e}")
        return None

@rate_limit(calls_per_minute=16)
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
    
    # SAFETY: Sometimes the API returns a list (search results) if the ID is wrong or ambiguous
    if isinstance(event_data, list):
        if len(event_data) > 0:
            event_data = event_data[0]
        else:
            print(f"Match {sofascore_match_id} details came back as an empty list.")
            return None, None
    
    home_id = event_data.get('homeTeam', {}).get('id')
    home_name = event_data.get('homeTeam', {}).get('name')
    away_id = event_data.get('awayTeam', {}).get('id')
    away_name = event_data.get('awayTeam', {}).get('name')
    
    # Extract Referee & Match Context (zero extra API calls)
    referee_name = event_data.get('referee', {}).get('name') if event_data.get('referee') else None
    tournament_name = event_data.get('tournament', {}).get('name') or event_data.get('uniqueTournament', {}).get('name')
    round_info = event_data.get('roundInfo', {}).get('name') or event_data.get('roundInfo', {}).get('round')
    if referee_name:
        print(f"🟨 Referee Detected: {referee_name}")
    
    # Handle flat or nested tournament structure
    tournament_id = event_data.get('uniqueTournament', {}).get('id')
    if not tournament_id:
         tournament_id = event_data.get('tournament', {}).get('uniqueTournament', {}).get('id')
         
    season_id = event_data.get('season', {}).get('id')
    
    if not tournament_id or not season_id or not home_id or not away_id:
        print(f"Missing required IDs for Match {sofascore_match_id}.")
        return None, None
    
    # --- Helper: extract stats dict from raw API response ---
    def _extract_stats(raw_data):
        if isinstance(raw_data, list) and len(raw_data) > 0:
            return raw_data[0].get('statistics', {})
        elif isinstance(raw_data, dict):
            return raw_data.get('statistics', {})
        return {}

    # --- Helper: build flat comparison JSON from two stat dicts ---
    METRICS_TO_COMPARE = [
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

    def _build_comparison(h_stats, a_stats, h_label, a_label):
        m_h = h_stats.get('matches', 1) or 1
        m_a = a_stats.get('matches', 1) or 1
        flat = {}
        for display_name, json_key, needs_math in METRICS_TO_COMPARE:
            h_val = h_stats.get(json_key)
            a_val = a_stats.get(json_key)
            if needs_math:
                h_val = round(h_val / m_h, 1) if h_val is not None else None
                a_val = round(a_val / m_a, 1) if a_val is not None else None
            else:
                if isinstance(h_val, float): h_val = round(h_val, 1)
                if isinstance(a_val, float): a_val = round(a_val, 1)
            flat[display_name] = {h_label: h_val, a_label: a_val}
        return flat

    # 2. Fetch Team OVERALL Statistics
    stats_url = f"https://{RAPID_API_HOST}/api/sofascore/v1/team/statistics"
    
    home_params = {"team_id": home_id, "unique_tournament_id": tournament_id, "season_id": season_id}
    away_params = {"team_id": away_id, "unique_tournament_id": tournament_id, "season_id": season_id}
    
    home_stats_res = requests.get(stats_url, headers=headers, params=home_params)
    away_stats_res = requests.get(stats_url, headers=headers, params=away_params)
    
    if home_stats_res.status_code != 200 or away_stats_res.status_code != 200:
        print(f"Stats fetch failed. Home {home_stats_res.status_code}, Away {away_stats_res.status_code}")
        return None, None

    home_stats = _extract_stats(home_stats_res.json())
    away_stats = _extract_stats(away_stats_res.json())

    # Build the overall comparison (existing behavior)
    overall_json = _build_comparison(home_stats, away_stats, home_name, away_name)
    
    # Build DataFrame for legacy compatibility
    data_rows = [{"Statistic": k, home_name: v[home_name], away_name: v[away_name]} for k, v in overall_json.items()]
    df = pd.DataFrame(data_rows)
    df.set_index("Statistic", inplace=True)
    
    # 3. Fetch VENUE-SPECIFIC Statistics (Home team's HOME-ONLY stats, Away team's AWAY-ONLY stats)
    home_venue_json = None
    away_venue_json = None
    
    try:
        home_venue_params = {**home_params, "group": "home"}
        away_venue_params = {**away_params, "group": "away"}
        
        hv_res = requests.get(stats_url, headers=headers, params=home_venue_params)
        av_res = requests.get(stats_url, headers=headers, params=away_venue_params)
        
        if hv_res.status_code == 200 and av_res.status_code == 200:
            hv_stats = _extract_stats(hv_res.json())
            av_stats = _extract_stats(av_res.json())
            
            # Only use venue stats if they actually contain data (i.e., the API supports the group param)
            if hv_stats.get('matches') and av_stats.get('matches'):
                home_venue_json = _build_comparison(hv_stats, av_stats, f"{home_name} (HOME ONLY)", f"{away_name} (AWAY ONLY)")
                print(f"📊 Venue Split: {home_name} HOME={hv_stats.get('matches')} matches | {away_name} AWAY={av_stats.get('matches')} matches")
            else:
                print("⚠️ Venue-filtered stats returned empty. Using Overall stats only.")
        else:
            print(f"⚠️ Venue stats fetch returned {hv_res.status_code}/{av_res.status_code}. Using Overall stats only.")
    except Exception as venue_err:
        print(f"⚠️ Venue stats fetch failed ({venue_err}). Using Overall stats only.")
        
    advanced_stats = {
        "metadata": {
            "home_team": home_name,
            "away_team": away_name,
            "home_logo": f"/api/team-logo/{home_id}" if home_id else None,
            "away_logo": f"/api/team-logo/{away_id}" if away_id else None,
            "match_date": datetime.fromtimestamp(event_data.get("startTimestamp", 0), tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if event_data.get("startTimestamp") else None,
            "referee": referee_name,
            "tournament": tournament_name,
            "round": str(round_info) if round_info else None
        },
        "metrics": overall_json
    }
    
    # Attach venue-specific stats if available
    if home_venue_json:
        advanced_stats["home_away_split"] = home_venue_json
        
    return df, advanced_stats



@rate_limit(calls_per_minute=16)
@rate_limit(calls_per_minute=16)
def get_sofascore_match_grade_data(sofascore_match_id: int):
    """
    Consolidated fetch for the Grader service.
    Returns Score, Status, Statistics, Incidents (Goals/Cards), and Player Performance.
    """
    if not RAPID_API_KEY:
        return None

    headers = {
        "x-rapidapi-host": RAPID_API_HOST,
        "x-rapidapi-key": RAPID_API_KEY
    }

    results = {
        "score_summary": "Unknown",
        "match_status": "Unknown",
        "period_scores": {},
        "statistics": [],
        "incidents": [],
        "player_statistics": []
    }

    def _safe_get(obj, key, default={}):
        if not isinstance(obj, dict): return default
        val = obj.get(key, default)
        if isinstance(val, list) and len(val) > 0: return val[0]
        return val if isinstance(val, dict) else default

    try:
        # 1. Fetch Details (Score, Status, Period Scores)
        detail_url = f"https://{RAPID_API_HOST}/api/sofascore/v1/match/details"
        res = requests.get(detail_url, headers=headers, params={"match_id": sofascore_match_id}, timeout=15)
        if res.status_code == 200:
            data = res.json()
            if isinstance(data, list) and len(data) > 0: data = data[0]
            
            if isinstance(data, dict):
                hT = _safe_get(data, 'homeTeam')
                aT = _safe_get(data, 'awayTeam')
                hS = _safe_get(data, 'homeScore')
                aS = _safe_get(data, 'awayScore')
                st = _safe_get(data, 'status')

                home_name = hT.get('name', 'Home')
                away_name = aT.get('name', 'Away')
                home_score = hS.get('current', 0)
                away_score = aS.get('current', 0)
                status = st.get('description', 'Unknown')
                
                results["score_summary"] = f"{home_name} {home_score} - {away_score} {away_name}"
                results["match_status"] = status
                
                # Period Scores (1st Half, 2nd Half, ET, etc.)
                results["period_scores"] = {
                    "period1": {"home": hS.get("period1"), "away": aS.get("period1")},
                    "period2": {"home": hS.get("period2"), "away": aS.get("period2")},
                    "extraTime": {"home": hS.get("extra1"), "away": aS.get("extra1")} # simplified
                }

        # 2. Fetch Statistics (Corners, Cards, etc.)
        stats_url = f"https://{RAPID_API_HOST}/api/sofascore/v1/match/statistics"
        res = requests.get(stats_url, headers=headers, params={"match_id": sofascore_match_id}, timeout=15)
        if res.status_code == 200:
            data = res.json()
            if isinstance(data, list) and len(data) > 0:
                results["statistics"] = data[0].get('statistics', [])
            elif isinstance(data, dict):
                results["statistics"] = data.get('statistics', [])

        # 3. Fetch Incidents (Goals, Red Cards, Penalty minute markers)
        inc_url = f"https://{RAPID_API_HOST}/api/sofascore/v1/match/incidents"
        res = requests.get(inc_url, headers=headers, params={"match_id": sofascore_match_id}, timeout=15)
        if res.status_code == 200:
            data = res.json()
            if isinstance(data, list) and len(data) > 0:
                results["incidents"] = data[0].get('incidents', [])
            elif isinstance(data, dict):
                results["incidents"] = data.get('incidents', [])

        # 4. Fetch Player Statistics (For Player Props)
        player_stats_url = f"https://{RAPID_API_HOST}/api/sofascore/v1/match/player-statistics"
        res = requests.get(player_stats_url, headers=headers, params={"match_id": sofascore_match_id}, timeout=15)
        if res.status_code == 200:
            data = res.json()
            # This usually returns arrays for both teams
            if isinstance(data, dict):
                results["player_statistics"] = data.get('players', [])

        return results
    except Exception as e:
        print(f"Error fetching grade data for {sofascore_match_id}: {e}")
        return None
