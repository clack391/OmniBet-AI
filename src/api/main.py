from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from typing import List, Dict, Any
from pydantic import BaseModel
import sqlite3
import json
import os
import requests
from src.services.sports_api import (
    get_fixtures_by_date,
    get_match_stats,
    fetch_latest_odds,
    fetch_match_h2h,
    fetch_team_form,
    get_team_standings,
    resolve_sofascore_match_id,
    get_sofascore_match_stats
)
from src.rag.pipeline import predict_match, risk_manager_review, generate_best_picks
from src.database.db import (
    DB_NAME,
    save_prediction,
    get_accuracy_stats,
    get_cached_prediction,
    get_all_predictions,
    clear_predictions,
    update_prediction_result,
    delete_prediction,
    restore_to_history,
    save_best_picks,
    get_best_picks,
    clear_best_picks,
    create_group,
    get_groups,
    delete_group,
    add_match_to_group,
    remove_match_from_group,
    get_matches_by_group,
    get_app_setting,
    set_app_setting
)
from src.services.grader import fetch_result_with_ai
from src.utils.auth import get_password_hash, verify_password, create_access_token, get_admin_user
from fastapi.responses import Response

app = FastAPI()

# --- Team Logo Proxy (bypasses SofaScore Cloudflare 403) ---
@app.get("/api/team-logo/{team_id}")
@app.get("/team-logo/{team_id}")
async def team_logo_proxy(team_id: int):
    """Proxies SofaScore team images through the backend to bypass Cloudflare and caches them locally."""
    cache_path = f"data/logos/{team_id}.png"
    
    # 1. Check Local Cache (FAST)
    if os.path.exists(cache_path):
        try:
            with open(cache_path, "rb") as f:
                return Response(content=f.read(), media_type="image/png")
        except Exception:
            pass # Fallback to fetch if read fails
            
    # 2. Fetch from SofaScore CDN (LESS PROTECTED)
    try:
        from curl_cffi import requests as cffi_requests
        # Use img domain which is usually less restricted than the main api domain
        url = f"https://img.sofascore.com/api/v1/team/{team_id}/image"
        headers = {
            "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
            "Sec-Ch-Ua": '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
            "Sec-Ch-Ua-Mobile": "?0",
            "Sec-Ch-Ua-Platform": '"Windows"',
            "Sec-Fetch-Dest": "image",
            "Sec-Fetch-Mode": "no-cors",
            "Sec-Fetch-Site": "cross-site",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": "https://www.sofascore.com/",
        }
        res = cffi_requests.get(url, impersonate="chrome120", headers=headers, timeout=15)
        
        if res.status_code == 200:
            # Save to Cache for next time
            os.makedirs("data/logos", exist_ok=True)
            with open(cache_path, "wb") as f:
                f.write(res.content)
            print(f"✅ Logo cached and served for team {team_id}")
            return Response(content=res.content, media_type="image/png")
        else:
            print(f"⚠️ Logo fetch failed (Status {res.status_code}) for team {team_id} at {url}")
            
    except Exception as e:
        print(f"❌ Logo proxy error for team {team_id}: {str(e)}")
        
    # Fallback: return a 1x1 transparent PNG
    return Response(content=b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n\xb4\x00\x00\x00\x00IEND\xaeB`\x82', media_type="image/png")


oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login")

class UserRegister(BaseModel):
    username: str
    password: str

class Token(BaseModel):
    access_token: str
    token_type: str
    role: str

class MatchBatchRequest(BaseModel):
    match_ids: List[int]

class GradeRequest(BaseModel):
    match_id: int

class TelegramShareRequest(BaseModel):
    bets: List[Dict[str, Any]]

class GroupCreateRequest(BaseModel):
    name: str

class GroupMatchRequest(BaseModel):
    match_id: int

class ProviderSettingRequest(BaseModel):
    provider: str

class AutomationSettingRequest(BaseModel):
    enabled: bool

class BookingCodeRequest(BaseModel):
    booking_code: str

origins = [
    "http://localhost:3000",
    "http://localhost:5173",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.post("/register", response_model=Token)
def register_user(user: UserRegister):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    try:
        # Check if username exists
        cursor.execute("SELECT id FROM users WHERE username = ?", (user.username,))
        if cursor.fetchone():
            raise HTTPException(status_code=400, detail="Username already registered")
            
        hashed_password = get_password_hash(user.password)
        role = "user"
        
        cursor.execute(
            "INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)",
            (user.username, hashed_password, role)
        )
        conn.commit()
        
        access_token = create_access_token(data={"sub": user.username, "role": role})
        return {"access_token": access_token, "token_type": "bearer", "role": role}
    finally:
        conn.close()

@app.post("/login", response_model=Token)
def login_for_access_token(form_data: OAuth2PasswordRequestForm = Depends()):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT password_hash, role FROM users WHERE username = ?", (form_data.username,))
        row = cursor.fetchone()
        
        if not row or not verify_password(form_data.password, row[0]):
            raise HTTPException(
                status_code=401,
                detail="Incorrect username or password",
                headers={"WWW-Authenticate": "Bearer"},
            )
            
        role = row[1]
        access_token = create_access_token(data={"sub": form_data.username, "role": role})
        return {"access_token": access_token, "token_type": "bearer", "role": role}
    finally:
        conn.close()

@app.get("/fixtures")
def fixtures(start_date: str, end_date: str):
    # Determine the active provider
    provider = get_app_setting("primary_provider", "football-data")
    if provider == "sofascore":
        # We will build this next in sports_api.py
        from src.services.sports_api import get_sofascore_fixtures
        return get_sofascore_fixtures(start_date, end_date)
    else:
        return get_fixtures_by_date(start_date, end_date)

@app.post("/api/sportybet/parse")
@app.post("/sportybet/parse")
def parse_sportybet_code(request: BookingCodeRequest):
    from src.services.sportybet_scraper import scrape_sportybet_code
    from src.database.db import find_fixtures_cross_date
    
    # 1. Scrape and Parse via Playwright & Gemini
    result = scrape_sportybet_code(request.booking_code)
    
    if result.get("booking_status") == "failed":
        raise HTTPException(status_code=400, detail=result.get("error", "Failed to extract matches from booking code."))
        
    # 2. Enrich the parsed string names with actual our API match IDs and Dates
    enriched_results = find_fixtures_cross_date(result.get("matches", []))
    
    # Maintain backwards compatibility with the raw output for the frontend
    return {
        "booking_status": "success",
        "total_matches_found": result.get("total_matches_found", 0),
        "matches": result.get("matches", []),         # The raw strings exactly as scraped
        "enriched_matches": enriched_results.get("matched", []), # Fully hydrated Fixture objects
        "unmatched_names": enriched_results.get("unmatched", []) # Strings that failed cross-date checks
    }

@app.get("/stats/{match_id}")
def match_stats(match_id: int):
    return get_match_stats(match_id)

@app.get("/accuracy")
def accuracy():
    return get_accuracy_stats()

@app.get("/history")
def history():
    return get_all_predictions()

@app.delete("/history")
def clear_history(current_user: dict = Depends(get_admin_user)):
    clear_predictions()
    return {"message": "Prediction history cleared."}

@app.delete("/history/{match_id}")
def delete_single_history(match_id: int, current_user: dict = Depends(get_admin_user)):
    delete_prediction(match_id)
    return {"status": "deleted", "match_id": match_id}

@app.post("/history/{match_id}/restore")
def restore_prediction_to_history(match_id: int, current_user: dict = Depends(get_admin_user)):
    success = restore_to_history(match_id)
    if not success:
        raise HTTPException(status_code=400, detail="Failed to restore prediction to history.")
    return {"status": "restored", "match_id": match_id}

class BestPicksRequest(BaseModel):
    target_odds: float | None = None

@app.post("/generate-best-picks")
def create_best_picks(req: BestPicksRequest = None, current_user: dict = Depends(get_admin_user)):
    # 1. Get all saved history
    saved_predictions = get_all_predictions()

    # 2. If nothing to analyze, return early
    if not saved_predictions:
        raise HTTPException(status_code=400, detail="No predictions in history to analyze.")

    # 3. Get optional target odds
    target_odds = req.target_odds if req else None

    # 4. Call the Gemini Chief Risk Officer Agent
    best_picks_json = generate_best_picks(saved_predictions, target_odds=target_odds)

    # 5. Save to DB
    save_best_picks(best_picks_json)

    return best_picks_json

@app.get("/best-picks")
def read_best_picks():
    picks = get_best_picks()
    return picks or {}

@app.delete("/best-picks")
def delete_best_picks(current_user: dict = Depends(get_admin_user)):
    clear_best_picks()
    return {"status": "cleared"}

# --- Groups API ---

@app.post("/groups")
def api_create_group(req: GroupCreateRequest, current_user: dict = Depends(get_admin_user)):
    res = create_group(req.name)
    if "error" in res:
        raise HTTPException(status_code=400, detail=res["error"])
    return res

@app.get("/groups")
def api_get_groups():
    return get_groups()

@app.delete("/groups/{group_id}")
def api_delete_group(group_id: int, current_user: dict = Depends(get_admin_user)):
    delete_group(group_id)
    return {"status": "success"}

@app.post("/groups/{group_id}/matches")
def api_add_match_to_group(group_id: int, req: GroupMatchRequest, current_user: dict = Depends(get_admin_user)):
    success = add_match_to_group(group_id, req.match_id)
    if not success:
        raise HTTPException(status_code=400, detail="Failed to add match to group.")
    return {"status": "success"}

@app.delete("/groups/{group_id}/matches/{match_id}")
def api_remove_match_from_group(group_id: int, match_id: int, current_user: dict = Depends(get_admin_user)):
    success = remove_match_from_group(group_id, match_id)
    if not success:
        raise HTTPException(status_code=400, detail="Failed to remove match from group.")
    return {"status": "success"}

@app.get("/groups/{group_id}/matches")
def api_get_group_matches(group_id: int):
    return get_matches_by_group(group_id)

@app.get("/settings/provider")
def api_get_provider(current_user: dict = Depends(get_admin_user)):
    provider = get_app_setting("primary_provider", "football-data")
    return {"provider": provider}

@app.put("/settings/provider")
def api_set_provider(req: ProviderSettingRequest, current_user: dict = Depends(get_admin_user)):
    if req.provider not in ["football-data", "sofascore"]:
        raise HTTPException(status_code=400, detail="Invalid provider specified")
    
    success = set_app_setting("primary_provider", req.provider)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to update provider setting")
    
    return {"status": "success", "provider": req.provider}

@app.get("/settings/automation")
def api_get_automation(current_user: dict = Depends(get_admin_user)):
    enabled = get_app_setting("cron_enabled", "true") == "true"
    return {"enabled": enabled}

@app.put("/settings/automation")
def api_set_automation(req: AutomationSettingRequest, current_user: dict = Depends(get_admin_user)):
    success = set_app_setting("cron_enabled", "true" if req.enabled else "false")
    if not success:
        raise HTTPException(status_code=500, detail="Failed to update automation setting")
    return {"status": "success", "enabled": req.enabled}

@app.post("/share-betslip")
def share_betslip(request: TelegramShareRequest, current_user: dict = Depends(get_admin_user)):
    telegram_token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    if not telegram_token or not chat_id:
        raise HTTPException(status_code=500, detail="Telegram credentials missing in .env")

    # Format the message
    message = "🔥 *NEW AI ACCUMULATOR* 🔥\n\n"
    
    from datetime import datetime
    for bet in request.bets:
        match_str = bet.get("match", "Unknown Match")
        selection = bet.get("selection", "Unknown Selection")
        match_date_str = bet.get("match_date", None)
        
        formatted_date = ""
        if match_date_str:
            try:
                # Try to parse the ISO format string 
                # API usually gives something like '2024-03-22T20:00:00Z'
                dt = datetime.fromisoformat(match_date_str.replace('Z', '+00:00'))
                
                from zoneinfo import ZoneInfo
                dt_wat = dt.astimezone(ZoneInfo("Africa/Lagos"))
                
                formatted_date = dt_wat.strftime("%Y-%m-%d %H:%M WAT")
            except Exception:
                formatted_date = str(match_date_str)
        
        message += f"⚽ *{match_str}*\n"
        if formatted_date:
            message += f"📅 _{formatted_date}_\n"
        message += f"👉 Tip: _{selection}_\n"
        
        odds = bet.get("odds")
        if odds:
            message += f"📈 Odds: *{odds}*\n\n"
        else:
            message += "\n"
            
    total_odds = 1.0
    for bet in request.bets:
        try:
            total_odds *= float(bet.get("odds", 1.0))
        except Exception:
            pass

    if total_odds > 1.0:
        message += f"💰 *Total Parlay Odds: {total_odds:.2f}x*\n\n"

    message += "⚡ _Generated by OmniBet AI JIT RAG Engine_"

    # Send to Telegram
    url = f"https://api.telegram.org/bot{telegram_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "Markdown"
    }

    response = requests.post(url, json=payload)
    
    if response.status_code != 200:
        raise HTTPException(status_code=500, detail=f"Failed to send to Telegram: {response.text}")

    return {"status": "success", "message": "Betslip shared to Telegram!"}

@app.post("/grade-history")
def grade_history(request: GradeRequest, current_user: dict = Depends(get_admin_user)):
    prediction = get_cached_prediction(request.match_id)
    if not prediction:
        raise HTTPException(status_code=404, detail="Prediction not found in history.")

    # We need the team names and date. Let's extract from the DB JSON string if not returned directly.
    # We'll re-fetch the raw row if needed, but get_all_predictions is easier for the frontend to pass data.
    # To keep it simple, we'll require the frontend to just pass the match_id, and we'll infer it from the DB.
    conn = __import__('sqlite3').connect("omnibet.db")
    cursor = conn.cursor()
    cursor.execute('SELECT teams, match_date, safe_bet_tip FROM predictions WHERE match_id = ?', (request.match_id,))
    row = cursor.fetchone()
    conn.close()

    if not row:
        raise HTTPException(status_code=404, detail="Match data not found.")

    teams_str = row[0] # e.g. "Chelsea vs Burnley"
    match_date = row[1]
    safe_bet_tip = row[2]

    parts = teams_str.split(" vs ")
    team_a = parts[0] if len(parts) > 1 else teams_str
    team_b = parts[1] if len(parts) > 1 else "Unknown Opponent"

    # Run the AI Grader (Takes a few seconds due to Google Search Grounding)
    result_data = fetch_result_with_ai(team_a, team_b, match_date, safe_bet_tip)

    # Save to Database
    update_prediction_result(
        request.match_id,
        result_data.get("actual_score", "Unknown"),
        result_data.get("is_correct")
    )

    return {
        "match_id": request.match_id,
        "graded_result": result_data
    }

@app.post("/predict-batch")
def predict_batch(request: MatchBatchRequest, current_user: dict = Depends(get_admin_user)):
    results = []

    for match_id in request.match_ids:
        # 0. Check Prediction Cache First
        cached_prediction = get_cached_prediction(match_id)
        if cached_prediction:
            print(f"✅ Fast-tracking cached prediction for Match {match_id}")
            results.append(cached_prediction)
            continue

        # 1. Check Global Provider
        provider = get_app_setting("primary_provider", "football-data")
        
        if provider == "sofascore":
            print(f"✅ Route: SofaScore AI Pipeline for Match {match_id}")
            df, advanced_stats = get_sofascore_match_stats(match_id)
            if not advanced_stats:
                results.append({"match_id": match_id, "error": "Failed to fetch SofaScore stats. Check your RapidAPI configuration."})
                continue
                
            home_team = advanced_stats.get('metadata', {}).get('home_team', 'Unknown')
            away_team = advanced_stats.get('metadata', {}).get('away_team', 'Unknown')
            match_date = advanced_stats.get('metadata', {}).get('match_date')
            home_logo = advanced_stats.get('metadata', {}).get('home_logo')
            away_logo = advanced_stats.get('metadata', {}).get('away_logo')
            
            if not match_date or "1970" in match_date:
                # Fallback: Extract the exact match date from the existing calendar cache
                import sqlite3, json
                from src.database.db import DB_NAME
                try:
                    conn = sqlite3.connect(DB_NAME)
                    cursor = conn.cursor()
                    cursor.execute("SELECT fixtures_json FROM daily_fixtures WHERE date LIKE 'sofascore_%'")
                    for row in cursor.fetchall():
                        cached_matches = json.loads(row[0]).get('matches', [])
                        for m in cached_matches:
                            if str(m.get('id')) == str(match_id):
                                match_date = m.get('utcDate')
                                home_logo = home_logo or m.get('home_logo')
                                away_logo = away_logo or m.get('away_logo')
                                break
                        if match_date and "1970" not in match_date:
                            break
                except Exception as e:
                    print("Date Fallback Error:", e)
                finally:
                    conn.close()

            
            odds = fetch_latest_odds(home_team, away_team)
            
            initial_prediction = predict_match(
                home_team, away_team, 
                match_stats={}, odds_data=odds, h2h_data={}, home_form=None, away_form=None, 
                home_standings={}, away_standings={}, 
                advanced_stats=advanced_stats, match_date=match_date
            )
            
            final_prediction = risk_manager_review(initial_prediction, match_date=match_date)
            final_prediction['home_logo'] = advanced_stats.get('metadata', {}).get('home_logo')
            final_prediction['away_logo'] = advanced_stats.get('metadata', {}).get('away_logo')
            final_prediction['match_id'] = match_id
            final_prediction['match_date'] = match_date
            
            save_prediction(final_prediction)
            results.append(final_prediction)
            continue

        # 1. Get Stats (Respects Rate Limit of 6s) - Football Data Route
        stats = get_match_stats(match_id)

        if "error" in stats:
            results.append({"match_id": match_id, "error": stats["error"]})
            continue

        # 2. Extract Team Names
        # football-data.org structure for /matches/{id}
        try:
            home_team = stats.get("homeTeam", {}).get("name")
            away_team = stats.get("awayTeam", {}).get("name")

            if not home_team or not away_team:
                # Try alternative structure if API changes
                if "match" in stats:
                    home_team = stats["match"].get("homeTeam", {}).get("name")
                    away_team = stats["match"].get("awayTeam", {}).get("name")

            if not home_team or not away_team:
                results.append({"match_id": match_id, "error": "Could not parse team names"})
                continue

        except Exception as e:
            results.append({"match_id": match_id, "error": f"Parsing error: {str(e)}"})
            continue

        # 4. Get Head-to-Head Data (New)
        # Adds ~6s latency but crucial for "AI" analysis
        h2h_data = fetch_match_h2h(match_id)

        # FILTER: Remove the current match from H2H if present to avoid "seeing the future"
        # or seeing conflicting "Finished" status for a match we think is "In Play"
        if h2h_data and 'matches' in h2h_data:
             h2h_data['matches'] = [m for m in h2h_data['matches'] if m['id'] != match_id]

        # 5. Get Latest Odds
        odds = fetch_latest_odds(home_team, away_team)

        # 6. Get Recent Team Form (New Phase 7)
        # Adds ~12s total (6s per team)
        home_id = stats.get("homeTeam", {}).get("id")
        away_id = stats.get("awayTeam", {}).get("id")

        home_form = fetch_team_form(home_id, team_name=home_team, venue="HOME") if home_id else None
        away_form = fetch_team_form(away_id, team_name=away_team, venue="AWAY") if away_id else None

        # 7. Get League Standings
        competition_id = stats.get("competition", {}).get("id", 2021) # Default to EPL if missing

        home_standings = get_team_standings(home_id, competition_id) if home_id else {}
        away_standings = get_team_standings(away_id, competition_id) if away_id else {}

        # 8. ANTI-DATA LEAKAGE SCRUBBER
        # Actively delete the 'score' objects from the current match stats
        # so the AI cannot "cheat" by looking at the live score of an IN_PLAY match.
        if 'score' in stats:
            del stats['score']
        if 'match' in stats and 'score' in stats['match']:
            del stats['match']['score']

        # 9. Extract Match Date for Anti-Cheating Backtest Mode
        match_date = stats.get('match', {}).get('utcDate') or stats.get('utcDate')

        # 9.5 RapidAPI SofaScore Deep Statistics Integration
        print(f"🔍 Resolving SofaScore Match ID for {home_team} vs {away_team}...")
        advanced_stats = None
        sofascore_id = resolve_sofascore_match_id(home_team, away_team, match_date)
        
        if sofascore_id:
            print(f"✅ Found SofaScore ID: {sofascore_id}. Fetching deep stats from RapidAPI...")
            df, advanced_stats = get_sofascore_match_stats(sofascore_id)
            if advanced_stats:
                print(f"🔬 Successfully extracted deep tactical metrics for {home_team} vs {away_team}!")
            else:
                print(f"⚠️ Could not build DataFrame for Match {sofascore_id}.")
        else:
            print(f"⚠️ Could not resolve SofaScore Match ID for {home_team} vs {away_team}.")

        # 10. Predict (Agent 1)
        initial_prediction = predict_match(
            home_team,
            away_team,
            stats,
            odds,
            h2h_data,
            home_form,
            away_form,
            home_standings,
            away_standings,
            advanced_stats=advanced_stats,
            match_date=match_date
        )

        # 11. Risk Manager Review (Agent 2)
        final_prediction = risk_manager_review(initial_prediction, match_date=match_date)

        # 11. Prepare Output logos
        if provider == "sofascore":
            final_prediction['home_logo'] = home_logo
            final_prediction['away_logo'] = away_logo
        else:
            final_prediction['home_logo'] = stats.get('homeTeam', {}).get('crest', '').replace("http://", "https://") if stats.get('homeTeam', {}).get('crest') else None
            final_prediction['away_logo'] = stats.get('awayTeam', {}).get('crest', '').replace("http://", "https://") if stats.get('awayTeam', {}).get('crest') else None

        # 13. Save to DB
        # Add match_id and match_date to prediction object if missing for DB consistency
        final_prediction['match_id'] = match_id
        final_prediction['match_date'] = match_date
        save_prediction(final_prediction)
        
        results.append(final_prediction)
        
    return results

class AuditItem(BaseModel):
    match_id: int
    user_selected_bet: str

class AuditBatchRequest(BaseModel):
    items: list[AuditItem]

@app.post("/predict-audit")
def predict_audit(request: AuditBatchRequest, current_user: dict = Depends(get_admin_user)):
    from src.rag.pipeline import audit_match
    results = []

    for item in request.items:
        match_id = item.match_id
        user_selected_bet = item.user_selected_bet

        # 1. Check Global Provider
        provider = get_app_setting("primary_provider", "football-data")
        
        if provider == "sofascore":
            print(f"✅ Route: SofaScore Auditor Pipeline for Match {match_id}")
            df, advanced_stats = get_sofascore_match_stats(match_id)
            if not advanced_stats:
                results.append({"match_id": match_id, "error": "Failed to fetch SofaScore stats."})
                continue
                
            home_team = advanced_stats.get('metadata', {}).get('home_team', 'Unknown')
            away_team = advanced_stats.get('metadata', {}).get('away_team', 'Unknown')
            match_date = advanced_stats.get('metadata', {}).get('match_date')
            home_logo = advanced_stats.get('metadata', {}).get('home_logo')
            away_logo = advanced_stats.get('metadata', {}).get('away_logo')
            
            if not match_date or "1970" in match_date:
                # Fallback: Extract the exact match date from the existing calendar cache
                import sqlite3, json
                from src.database.db import DB_NAME
                try:
                    conn = sqlite3.connect(DB_NAME)
                    cursor = conn.cursor()
                    cursor.execute("SELECT fixtures_json FROM daily_fixtures WHERE date LIKE 'sofascore_%'")
                    for row in cursor.fetchall():
                        cached_matches = json.loads(row[0]).get('matches', [])
                        for m in cached_matches:
                            if str(m.get('id')) == str(match_id):
                                match_date = m.get('utcDate')
                                home_logo = home_logo or m.get('home_logo')
                                away_logo = away_logo or m.get('away_logo')
                                break
                        if match_date and "1970" not in match_date:
                            break
                except Exception as e:
                    print("Date Fallback Error:", e)
                finally:
                    conn.close()
            
            odds = fetch_latest_odds(home_team, away_team)
            
            # Agent 1: The Deep Tactical Analyzer
            from src.rag.pipeline import predict_match, audit_match
            initial_prediction = predict_match(
                home_team, away_team, 
                match_stats={}, odds_data=odds, h2h_data={}, 
                home_form=None, away_form=None, home_standings={}, away_standings={}, 
                advanced_stats=advanced_stats, match_date=match_date
            )
            
            # Agent 2: The Lead Risk Manager Auditor
            audit_verdict_json = audit_match(initial_prediction, user_selected_bet, match_date=match_date)
            
            # Merge the output
            initial_prediction['audit_verdict'] = audit_verdict_json.get('audit_verdict')
            initial_prediction['internal_debate'] = audit_verdict_json.get('internal_debate')
            initial_prediction['verdict_reasoning'] = audit_verdict_json.get('verdict_reasoning')
            
            initial_prediction['home_team'] = home_team
            initial_prediction['away_team'] = away_team
            initial_prediction['home_logo'] = home_logo
            initial_prediction['away_logo'] = away_logo
            initial_prediction['match_id'] = match_id
            initial_prediction['match_date'] = match_date
            
            save_prediction(initial_prediction)
            results.append(initial_prediction)
            continue

        # FOOTBALL-DATA ROUTE
        stats = get_match_stats(match_id)
        if "error" in stats:
            results.append({"match_id": match_id, "error": stats["error"]})
            continue

        home_team = stats.get("homeTeam", {}).get("name", "Unknown")
        away_team = stats.get("awayTeam", {}).get("name", "Unknown")
        
        h2h_data = fetch_match_h2h(match_id)
        if h2h_data and 'matches' in h2h_data:
             h2h_data['matches'] = [m for m in h2h_data['matches'] if m['id'] != match_id]
             
        odds = fetch_latest_odds(home_team, away_team)
        
        home_id = stats.get("homeTeam", {}).get("id")
        away_id = stats.get("awayTeam", {}).get("id")
        home_form = fetch_team_form(home_id, team_name=home_team, venue="HOME") if home_id else None
        away_form = fetch_team_form(away_id, team_name=away_team, venue="AWAY") if away_id else None
        competition_id = stats.get("competition", {}).get("id", 2021)
        home_standings = get_team_standings(home_id, competition_id) if home_id else {}
        away_standings = get_team_standings(away_id, competition_id) if away_id else {}

        if 'score' in stats: del stats['score']
        if 'match' in stats and 'score' in stats['match']: del stats['match']['score']
        match_date = stats.get('match', {}).get('utcDate') or stats.get('utcDate')

        advanced_stats = None
        sofascore_id = resolve_sofascore_match_id(home_team, away_team, match_date)
        if sofascore_id:
            df, advanced_stats = get_sofascore_match_stats(sofascore_id)
            
        # Agent 1: The Deep Tactical Analyzer
        from src.rag.pipeline import predict_match, audit_match
        initial_prediction = predict_match(
            home_team, away_team, 
            stats, odds, h2h_data, home_form, away_form, 
            home_standings, away_standings, advanced_stats=advanced_stats, match_date=match_date
        )

        # Agent 2: The Lead Risk Manager Auditor
        audit_verdict_json = audit_match(initial_prediction, user_selected_bet, match_date=match_date)
        
        # Merge the output
        initial_prediction['audit_verdict'] = audit_verdict_json.get('audit_verdict')
        initial_prediction['internal_debate'] = audit_verdict_json.get('internal_debate')
        initial_prediction['verdict_reasoning'] = audit_verdict_json.get('verdict_reasoning')

        initial_prediction['home_team'] = home_team
        initial_prediction['away_team'] = away_team
        initial_prediction['home_logo'] = stats.get('homeTeam', {}).get('crest', '').replace("http://", "https://") if stats.get('homeTeam', {}).get('crest') else None
        initial_prediction['away_logo'] = stats.get('awayTeam', {}).get('crest', '').replace("http://", "https://") if stats.get('awayTeam', {}).get('crest') else None
        initial_prediction['match_id'] = match_id
        initial_prediction['match_date'] = match_date
        
        save_prediction(initial_prediction)
        results.append(initial_prediction)
        
    return results
