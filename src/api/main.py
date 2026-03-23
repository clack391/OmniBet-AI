from fastapi import FastAPI, HTTPException, Depends, WebSocket, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from typing import List, Dict, Any, Optional
from pydantic import BaseModel
import sqlite3
import json
import os
import uuid
import requests
import logging
import redis as redis_lib
from contextlib import asynccontextmanager
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
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
from src.rag.pipeline import predict_match, risk_manager_review, generate_best_picks, supreme_court_judge
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
from src.utils.delivery_router import deliver_prediction, deliver_accumulator
from src.bot.pref_manager import get_user_preference, set_user_preference
from src.services.grader import fetch_result_with_ai
from src.utils.auth import get_password_hash, verify_password, create_access_token, get_admin_user, get_current_user_from_token
from src.database.db import create_job, update_job_status, save_job_result, fail_job, get_job
from src.utils.time_utils import get_now_wat, get_today_wat_str, to_wat
from fastapi.responses import Response

logger = logging.getLogger("omnibet.scheduler")

# ─────────────────────────────────────────────────────────────────────────────
# Scheduled Cron Job — runs at 02:00 WAT (01:00 UTC) every day
# ─────────────────────────────────────────────────────────────────────────────
def scheduled_daily_cron():
    """Called by APScheduler every day at 02:00 WAT. Checks the DB toggle before running."""
    enabled = get_app_setting("cron_enabled", "true") == "true"
    if not enabled:
        logger.info("🛑 Daily cron skipped — AI Automation is DISABLED in settings.")
        return
    logger.info("⏰ APScheduler triggered: starting daily cron job...")
    try:
        from src.scripts.daily_cron import run_daily_cron
        run_daily_cron()
    except Exception as e:
        logger.error(f"❌ Daily cron job failed: {e}", exc_info=True)

# ─────────────────────────────────────────────────────────────────────────────
# FastAPI Lifespan — starts/stops the scheduler alongside the server
# ─────────────────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler = BackgroundScheduler(timezone="Africa/Lagos")
    # Fire at 02:00 WAT every day (WAT = UTC+1, so cron hour=2 in Africa/Lagos tz)
    scheduler.add_job(
        scheduled_daily_cron,
        CronTrigger(hour=2, minute=0, timezone="Africa/Lagos"),
        id="daily_cron",
        replace_existing=True,
        max_instances=1
    )
    scheduler.start()
    logger.info("✅ APScheduler started — daily cron scheduled at 02:00 WAT.")
    yield
    scheduler.shutdown(wait=False)
    logger.info("🛑 APScheduler shut down.")

app = FastAPI(lifespan=lifespan)

# Global registry for active prediction cancellations
CANCELLATION_FLAGS: Dict[int, bool] = {}

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

class CancelPredictionRequest(BaseModel):
    match_id: int

@app.post("/cancel-prediction")
def cancel_prediction(req: CancelPredictionRequest):
    """Flags an active AI analysis loop or LLM task for immediate abortion."""
    logger.info(f"🛑 Received manual kill signal for match {req.match_id}")
    CANCELLATION_FLAGS[req.match_id] = True
    return {"status": "cancelled", "match_id": req.match_id}

class MatchBatchRequest(BaseModel):
    match_ids: List[int]

class GradeRequest(BaseModel):
    match_id: int

class TelegramShareRequest(BaseModel):
    bets: List[Dict[str, Any]]

class GroupCreateRequest(BaseModel):
    name: str

class GroupMatchRequest(BaseModel):
    prediction_id: int

class ProviderSettingRequest(BaseModel):
    provider: str

class GeminiModelRequest(BaseModel):
    model: str

class TelegramModeRequest(BaseModel):
    mode: str

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
    
    # 3. PROACTIVE FALLBACK: If we have unmatched matches, fetch fixtures 
    # for the relevant dates to ensure our cache is populated.
    if enriched_results.get("unmatched"):
        from src.services.sports_api import get_fixtures_by_date, get_sofascore_fixtures
        from datetime import datetime, timedelta
        
        target_dates = set()
        for pm in result.get("matches", []):
            extracted_date = pm.get("match_date", "")
            if extracted_date and len(extracted_date) >= 10:
                 try:
                     d = extracted_date[:10]
                     datetime.strptime(d, "%Y-%m-%d")
                     target_dates.add(d)
                 except: pass
        
        if not target_dates:
            today = get_now_wat()
            for i in range(8):
                target_dates.add((today + timedelta(days=i)).strftime("%Y-%m-%d"))
        
        provider = get_app_setting("primary_provider", "football-data")
        print(f"⚠️ Unmatched matches detected. Proactive sync for {target_dates} using {provider}...")
        
        for d_str in target_dates:
            if provider == "sofascore":
                get_sofascore_fixtures(d_str, d_str)
            else:
                get_fixtures_by_date(d_str, d_str)
        
        # Re-run matching after cache update
        enriched_results = find_fixtures_cross_date(result.get("matches", []))

    # 4. DEEP SEARCH FALLBACK: For anything still unmatched, try a direct SofaScore search
    if enriched_results.get("unmatched") and get_app_setting("primary_provider", "") == "sofascore":
        from src.services.sports_api import resolve_sofascore_match_id
        from datetime import datetime, timezone
        try:
            from curl_cffi import requests as cffi_requests
        except ImportError:
            cffi_requests = None

        print(f"🔍 Deep searching for {len(enriched_results.get('unmatched'))} still unmatched fixtures...")
        
        for pm in result.get("matches", []):
            name_key = f"{pm.get('home_team')} vs {pm.get('away_team')}"
            # Check if this specific match is in the unmatched list
            if not any(name_key in u for u in enriched_results.get("unmatched", [])):
                continue

            home = pm.get('home_team')
            away = pm.get('away_team')
            match_date = pm.get('match_date', '')[:10]
            
            print(f"🔎 Direct Search: {home} vs {away} ({match_date})")
            ss_id = resolve_sofascore_match_id(home, away, match_date)
            
            if ss_id:
                try:
                    event = None
                    
                    # TIER 1: Use RapidAPI for event details (EC2-safe)
                    rapid_api_key = os.getenv("RAPID_API_KEY")
                    rapid_api_host = os.getenv("RAPID_API_HOST", "sofascore6.p.rapidapi.com")
                    if rapid_api_key:
                        import requests as std_requests
                        detail_url = f"https://{rapid_api_host}/api/sofascore/v1/match/details"
                        detail_res = std_requests.get(detail_url, 
                            headers={"x-rapidapi-host": rapid_api_host, "x-rapidapi-key": rapid_api_key},
                            params={"match_id": ss_id}, timeout=15)
                        if detail_res.status_code == 200:
                            event_data = detail_res.json()
                            # RapidAPI returns the event directly (not wrapped in 'event' key)
                            if isinstance(event_data, list) and len(event_data) > 0:
                                event = event_data[0]
                            elif isinstance(event_data, dict):
                                event = event_data
                    
                    # TIER 2: Fallback to SofaScore WWW (works locally)
                    if not event and cffi_requests:
                        url = f"https://api.sofascore.com/api/v1/event/{ss_id}"
                        res = cffi_requests.get(url, impersonate="chrome120", timeout=15)
                        if res.status_code == 200:
                            event = res.json().get('event', {})
                    
                    if event:
                        status_type = event.get("status", {}).get("type")
                        status = "TIMED" if status_type in ("notstarted", None) else "FINISHED" if status_type == "finished" else "IN_PLAY"
                        
                        # Handle timestamp: RapidAPI uses 'timestamp', WWW uses 'startTimestamp'
                        start_ts = event.get("startTimestamp") or event.get("timestamp") or 0
                        home_id = event.get('homeTeam', {}).get('id')
                        away_id = event.get('awayTeam', {}).get('id')
                        
                        mapped_match = {
                            "id": event.get("id"),
                            "utcDate": datetime.fromtimestamp(start_ts, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                            "status": status,
                            "competition": {"name": event.get("tournament", {}).get("name", "Unknown")},
                            "homeTeam": {"name": event.get("homeTeam", {}).get("name")},
                            "awayTeam": {"name": event.get("awayTeam", {}).get("name")},
                            "home_logo": f"/team-logo/{home_id}" if home_id else None,
                            "away_logo": f"/team-logo/{away_id}" if away_id else None
                        }
                        
                        if 'user_selected_bet' in pm:
                            mapped_match['_user_selected_bet'] = pm['user_selected_bet']
                        
                        enriched_results["matched"].append(mapped_match)
                        enriched_results["unmatched"] = [u for u in enriched_results["unmatched"] if name_key not in u]
                        print(f"✅ Deep Search Success: {home} vs {away} -> ID {ss_id}")
                except Exception as e:
                    print(f"Deep Search Detail Fetch Error for {ss_id}: {e}")

    return {
        "booking_code": request.booking_code,
        "booking_status": "success",
        "matches": enriched_results.get("matched", []),
        "enriched_matches": enriched_results.get("matched", []),
        "unmatched_names": enriched_results.get("unmatched", []),
        "raw_scraped_matches": result.get("matches", [])
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

@app.delete("/history/{prediction_id}")
def delete_single_history(prediction_id: int, current_user: dict = Depends(get_admin_user)):
    delete_prediction(prediction_id)
    return {"status": "deleted", "prediction_id": prediction_id}

@app.post("/history/{prediction_id}/restore")
def restore_prediction_to_history(prediction_id: int, current_user: dict = Depends(get_admin_user)):
    success = restore_to_history(prediction_id)
    if not success:
        raise HTTPException(status_code=400, detail="Failed to restore prediction to history.")
    return {"status": "restored", "prediction_id": prediction_id}

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
    try:
        delete_group(group_id)
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to delete group: {str(e)}")

@app.post("/groups/{group_id}/matches")
def api_add_match_to_group(group_id: int, req: GroupMatchRequest, current_user: dict = Depends(get_admin_user)):
    success = add_match_to_group(group_id, req.prediction_id)
    if not success:
        raise HTTPException(status_code=400, detail="Failed to add prediction to group.")
    return {"status": "success"}

@app.delete("/groups/{group_id}/matches/{prediction_id}")
def api_remove_match_from_group(group_id: int, prediction_id: int, current_user: dict = Depends(get_admin_user)):
    success = remove_match_from_group(group_id, prediction_id)
    if not success:
        raise HTTPException(status_code=400, detail="Failed to remove prediction from group.")
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

VALID_GEMINI_MODELS = [
    "gemini-3.1-pro-preview",
    "gemini-3-pro-preview",
    "gemini-3-flash-preview",
    "gemini-2.5-flash",
]

@app.get("/settings/gemini-model")
def api_get_gemini_model(current_user: dict = Depends(get_admin_user)):
    model = get_app_setting("gemini_model", "gemini-3-pro-preview")
    return {"model": model}

@app.put("/settings/gemini-model")
def api_set_gemini_model(req: GeminiModelRequest, current_user: dict = Depends(get_admin_user)):
    if req.model not in VALID_GEMINI_MODELS:
        raise HTTPException(status_code=400, detail="Invalid model specified")
    set_app_setting("gemini_model", req.model)
    return {"status": "success", "model": req.model}

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

@app.post("/settings/kill-active-cron")
def api_kill_active_cron(current_user: dict = Depends(get_admin_user)):
    """Sets a global flag to stop any currently running background cron analysis."""
    success = set_app_setting("cron_kill_signal", "true")
    if not success:
        raise HTTPException(status_code=500, detail="Failed to set kill signal")
    return {"status": "success", "message": "Global kill signal sent to background processes."}

@app.get("/settings/telegram-mode")
def api_get_telegram_mode(current_user: dict = Depends(get_admin_user)):
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not chat_id:
        return {"mode": "text"}
    mode = get_user_preference(chat_id)
    return {"mode": mode}

@app.put("/settings/telegram-mode")
def api_set_telegram_mode(req: TelegramModeRequest, current_user: dict = Depends(get_admin_user)):
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not chat_id:
        raise HTTPException(status_code=500, detail="TELEGRAM_CHAT_ID missing in .env")
    
    if req.mode not in ["text", "image"]:
        raise HTTPException(status_code=400, detail="Invalid mode. Must be 'text' or 'image'.")
    
    set_user_preference(chat_id, req.mode)
    return {"status": "success", "mode": req.mode}

@app.post("/share-betslip")
def share_betslip(request: TelegramShareRequest, current_user: dict = Depends(get_admin_user)):
    telegram_token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    if not telegram_token or not chat_id:
        raise HTTPException(status_code=500, detail="Telegram credentials missing in .env")

    from src.bot.pref_manager import get_user_preference
    mode = get_user_preference(chat_id)

    # 1. Calculate Summary Text and Total Odds (Used for Fallback/Summary)
    message = "🔥 *NEW AI ACCUMULATOR* 🔥\n\n"
    total_odds = 1.0
    from datetime import datetime
    
    for bet in request.bets:
        match_str = bet.get("match", "Unknown Match")
        selection = bet.get("selection", "Unknown Selection")
        market = bet.get("market", "")
        
        # Merge market into selection for clarity if not already there (e.g. "BTS" + "Yes" -> "BTS Yes")
        if market and market.upper() not in selection.upper():
            selection = f"{market} {selection}".strip()
            bet["selection"] = selection # Update in place for deliver_accumulator
            
        match_date_str = bet.get("match_date", None)
        odds = bet.get("odds")
        
        try:
            total_odds *= float(odds or 1.0)
        except: pass
        
        formatted_date = ""
        if match_date_str:
            try:
                dt = datetime.fromisoformat(match_date_str.replace('Z', '+00:00'))
                dt_wat = to_wat(dt)
                formatted_date = dt_wat.strftime("%Y-%m-%d %H:%M WAT")
            except: formatted_date = str(match_date_str)
        
        message += f"⚽ *{match_str}*\n"
        if formatted_date:
            message += f"📅 _{formatted_date}_\n"
        message += f"👉 Tip: _{selection}_\n"
        if odds:
            message += f"📈 Odds: *{odds}*\n\n"
        else:
            message += "\n"

    if total_odds > 1.0:
        message += f"💰 *Total Parlay Odds: {total_odds:.2f}x*\n\n"
    message += "⚡ _Generated by OmniBet AI JIT RAG Engine_"

    # 2. Process Delivery based on User Preference
    if len(request.bets) > 1:
        # Multi-bet Accumulator
        success = deliver_accumulator(chat_id, request.bets, total_odds)
        success_count = len(request.bets) if success else 0
    else:
        # Single Bet
        bet = request.bets[0]
        match_data = {
            "match": bet.get("match", "Unknown"),
            "match_date": bet.get("match_date"),
            "primary_pick": {
                "tip": bet.get("selection", "N/A"),
                "odds": bet.get("odds", "0.00"),
                "market": bet.get("market", "")
            }
        }
        success = deliver_prediction(chat_id, match_data)
        success_count = 1 if success else 0

    if success_count == 0:
        raise HTTPException(status_code=500, detail="Failed to deliver predictions to Telegram")

    return {"status": "success", "message": "Successfully delivered predictions."}

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
        result_data.get("status", "Unknown"),
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
        if CANCELLATION_FLAGS.get(match_id):
            print(f"🛑 Match {match_id} skipped because it was manually cancelled by user.")
            continue
            
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
            try:
                df, advanced_stats = get_sofascore_match_stats(match_id)
            except Exception as e:
                print(f"❌ SofaScore API failed after retries: {e}")
                df, advanced_stats = None, None
                
            if not advanced_stats:
                # RECOVERY: Try to get match name from cache if stats fetch failed
                recovered_match = "Unknown SofaScore Match"
                match_date = None
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
                                recovered_match = f"{m.get('homeTeam', {}).get('name', '???')} vs {m.get('awayTeam', {}).get('name', '???')}"
                                match_date = m.get('utcDate')
                                break
                        if recovered_match != "Unknown SofaScore Match": break
                except: pass
                finally: conn.close()

                if recovered_match != "Unknown SofaScore Match" and " vs " in recovered_match:
                    print(f"🔄 Resilient Fallback: Predicting {recovered_match} without advanced stats...")
                    hp, ap = recovered_match.split(" vs ")
                    
                    try:
                        odds = fetch_latest_odds(hp, ap)
                        initial_prediction = predict_match(
                            hp, ap, match_stats={}, odds_data=odds, 
                            match_date=match_date if match_date and "1970" not in match_date else None,
                            match_id=match_id
                        )
                        final_prediction = risk_manager_review(initial_prediction, match_date=match_date, match_id=match_id)
                        final_prediction['match_id'] = match_id
                        final_prediction['match_date'] = match_date
                        final_prediction['match'] = recovered_match
                        
                        save_prediction(final_prediction)
                        results.append(final_prediction)
                        continue
                    except Exception as pred_e:
                        if str(pred_e) == "Prediction manually cancelled by user":
                            print(f"🛑 Fallback prediction for {recovered_match} cleanly aborted by user.")
                            continue
                        print(f"Fallback Prediction Failed: {pred_e}")

                results.append({
                    "match_id": match_id, 
                    "match": recovered_match,
                    "error": "Advanced Stats Missing. The provider returned no data for this specific match ID."
                })
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

            try:
                odds = fetch_latest_odds(home_team, away_team)
                
                initial_prediction = predict_match(
                    home_team, away_team, 
                    match_stats={}, odds_data=odds, h2h_data={}, home_form=None, away_form=None, 
                    home_standings={}, away_standings={}, 
                    advanced_stats=advanced_stats, match_date=match_date, match_id=match_id
                )
                
                final_prediction = risk_manager_review(initial_prediction, match_date=match_date, match_id=match_id)
                
                # Agent 3: The Supreme Court Judge (Final Resolution Tier)
                supreme_verdict = supreme_court_judge(advanced_stats, initial_prediction, final_prediction, match_id=match_id)
                final_prediction['supreme_court'] = supreme_verdict
    
                final_prediction['home_logo'] = advanced_stats.get('metadata', {}).get('home_logo')
                final_prediction['away_logo'] = advanced_stats.get('metadata', {}).get('away_logo')
                final_prediction['match_id'] = match_id
                final_prediction['match_date'] = match_date
                
                save_prediction(final_prediction)
                results.append(final_prediction)
            except Exception as e:
                if str(e) == "Prediction manually cancelled by user":
                    print(f"🛑 Match {match_id} cleanly aborted by user.")
                    continue
                else:
                    print(f"Prediction Pipeline Failed Error: {e}")
                    
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

        # Agent 3: The Supreme Court Judge (Final Resolution Tier)
        # We pass advanced_stats (which might be None or populated)
        supreme_verdict = supreme_court_judge(advanced_stats or stats, initial_prediction, final_prediction)
        final_prediction['supreme_court'] = supreme_verdict

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
    items: List[AuditItem]
    booking_code: Optional[str] = None

@app.post("/predict-audit")
def predict_audit(request: AuditBatchRequest, current_user: dict = Depends(get_admin_user)):
    from src.rag.pipeline import audit_match
    results = []
    booking_code = request.booking_code

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
                advanced_stats=advanced_stats, match_date=match_date, match_id=match_id
            )
            
            # Agent 2: The Lead Risk Manager Auditor
            audit_verdict_json = audit_match(initial_prediction, user_selected_bet, match_date=match_date, match_id=match_id)
            
            # Agent 3: The Supreme Court Judge (Final Resolution Tier)
            from src.rag.pipeline import supreme_court_judge
            supreme_verdict = supreme_court_judge(advanced_stats, initial_prediction, audit_verdict_json, match_id=match_id)
            
            # Merge the output
            initial_prediction['audit_verdict'] = audit_verdict_json.get('audit_verdict')
            initial_prediction['internal_debate'] = audit_verdict_json.get('internal_debate')
            initial_prediction['verdict_reasoning'] = audit_verdict_json.get('verdict_reasoning')
            
            # Supreme Court Layer
            initial_prediction['supreme_court'] = supreme_verdict
            
            initial_prediction['home_team'] = home_team
            initial_prediction['away_team'] = away_team
            initial_prediction['home_logo'] = home_logo
            initial_prediction['away_logo'] = away_logo
            initial_prediction['match_id'] = match_id
            initial_prediction['match_date'] = match_date
            initial_prediction['booking_code'] = booking_code
            initial_prediction['user_selected_bet'] = user_selected_bet
            
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
            home_standings, away_standings, advanced_stats=advanced_stats, match_date=match_date, match_id=match_id
        )

        # Agent 2: The Lead Risk Manager Auditor
        audit_verdict_json = audit_match(initial_prediction, user_selected_bet, match_date=match_date, match_id=match_id)
        
        # Agent 3: The Supreme Court Judge (Final Resolution Tier)
        from src.rag.pipeline import supreme_court_judge
        supreme_verdict = supreme_court_judge(advanced_stats or stats, initial_prediction, audit_verdict_json, match_id=match_id)
        
        # Merge the output
        initial_prediction['audit_verdict'] = audit_verdict_json.get('audit_verdict')
        initial_prediction['internal_debate'] = audit_verdict_json.get('internal_debate')
        initial_prediction['verdict_reasoning'] = audit_verdict_json.get('verdict_reasoning')
        initial_prediction['supreme_court'] = supreme_verdict

        initial_prediction['home_team'] = home_team
        initial_prediction['away_team'] = away_team
        initial_prediction['home_logo'] = stats.get('homeTeam', {}).get('crest', '').replace("http://", "https://") if stats.get('homeTeam', {}).get('crest') else None
        initial_prediction['away_logo'] = stats.get('awayTeam', {}).get('crest', '').replace("http://", "https://") if stats.get('awayTeam', {}).get('crest') else None
        initial_prediction['match_id'] = match_id
        initial_prediction['match_date'] = match_date
        initial_prediction['booking_code'] = booking_code
        initial_prediction['user_selected_bet'] = user_selected_bet

        save_prediction(initial_prediction)
        results.append(initial_prediction)

    return results


# =============================================================================
# ASYNC TASK QUEUE — Never-Timeout endpoints
# =============================================================================

@app.post("/predict-async", status_code=202)
def predict_async(request: MatchBatchRequest, current_user: dict = Depends(get_admin_user)):
    """
    Submit one or more match IDs for async background analysis.
    Returns immediately with a job_id per match.
    The frontend polls GET /jobs/{job_id} to retrieve results.
    """
    from src.worker.tasks import analyze_match

    results = []
    for match_id in request.match_ids:
        job_id = str(uuid.uuid4())
        create_job(job_id, match_id)
        analyze_match.delay(match_id, job_id)
        results.append({"job_id": job_id, "match_id": match_id, "status": "PENDING"})
    return results


@app.post("/audit-async", status_code=202)
def audit_async(request: AuditBatchRequest, current_user: dict = Depends(get_admin_user)):
    """Submit betslip audit jobs to Celery. Returns a job_id per item immediately."""
    from src.worker.tasks import analyze_audit

    results = []
    booking_code = request.booking_code
    for item in request.items:
        job_id = str(uuid.uuid4())
        create_job(job_id, item.match_id)
        analyze_audit.delay(item.match_id, job_id, item.user_selected_bet, booking_code)
        results.append({"job_id": job_id, "match_id": item.match_id, "status": "PENDING"})
    return results


@app.get("/jobs/{job_id}")
def get_job_status(job_id: str, current_user: dict = Depends(get_admin_user)):
    """Poll a background job for its current status and result."""
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@app.post("/jobs/{job_id}/cancel")
def cancel_job_endpoint(job_id: str, current_user: dict = Depends(get_admin_user)):
    """Cancel a running background job via Redis flag."""
    try:
        r = redis_lib.Redis(host="localhost", port=6379, db=0)
        r.setex(f"job:{job_id}:cancel", 3600, "1")
    except Exception as e:
        logger.warning(f"Redis unavailable for job cancellation: {e}")

    # Also set the in-memory flag so pipeline.py's check_cancelled() stops LLM work mid-run
    job = get_job(job_id)
    if job and job.get("match_id"):
        CANCELLATION_FLAGS[job["match_id"]] = True

    update_job_status(job_id, "CANCELLED")
    return {"status": "cancelled", "job_id": job_id}


# =============================================================================
# ADMIN LIVE TERMINAL — WebSocket log stream
# =============================================================================

@app.websocket("/ws/terminal/{job_id}")
async def terminal_websocket(websocket: WebSocket, job_id: str, token: str = Query(...)):
    """
    Streams real-time backend logs for a running job to admin clients.
    Authentication: JWT token passed as ?token= query parameter.
    Non-admin connections are rejected immediately with code 4003.
    """
    import redis.asyncio as aioredis

    # --- Auth gate ---
    try:
        user = get_current_user_from_token(token)
        if user.get("role") != "admin":
            await websocket.close(code=4003)
            return
    except Exception:
        await websocket.close(code=4001)
        return

    await websocket.accept()

    # Check if job already completed before subscribing
    job = get_job(job_id)
    if job and job.get("status") in ("COMPLETED", "FAILED", "CANCELLED"):
        await websocket.send_text(json.dumps({
            "type": "done",
            "job_id": job_id,
            "status": job.get("status"),
        }))
        await websocket.close()
        return

    r = None
    pubsub = None
    try:
        r = aioredis.Redis(host="localhost", port=6379, db=0)
        pubsub = r.pubsub()
        await pubsub.subscribe(f"job:{job_id}:logs")

        async for message in pubsub.listen():
            if message["type"] == "message":
                raw = message["data"]
                text = raw.decode() if isinstance(raw, bytes) else raw
                await websocket.send_text(text)
                # Stop streaming once the task signals completion
                try:
                    payload = json.loads(text)
                    if payload.get("type") == "done":
                        break
                except Exception:
                    pass
    except Exception as e:
        logger.debug(f"WebSocket terminal closed for job {job_id}: {e}")
    finally:
        if pubsub:
            try:
                await pubsub.unsubscribe()
            except Exception:
                pass
        if r:
            try:
                await r.aclose()
            except Exception:
                pass
        try:
            await websocket.close()
        except Exception:
            pass
