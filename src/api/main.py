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
    get_team_standings
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
    get_matches_by_group
)
from src.services.grader import fetch_result_with_ai
from src.utils.auth import get_password_hash, verify_password, create_access_token, get_admin_user

app = FastAPI()

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
    return get_fixtures_by_date(start_date, end_date)

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

@app.post("/generate-best-picks")
def create_best_picks(current_user: dict = Depends(get_admin_user)):
    # 1. Get all saved history
    saved_predictions = get_all_predictions()

    # 2. If nothing to analyze, return early
    if not saved_predictions:
        raise HTTPException(status_code=400, detail="No predictions in history to analyze.")

    # 3. Call the Gemini Chief Risk Officer Agent
    best_picks_json = generate_best_picks(saved_predictions)

    # 4. Save to DB
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

        # 1. Get Stats (Respects Rate Limit of 6s)
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
            match_date=match_date
        )

        # 11. Risk Manager Review (Agent 2)
        final_prediction = risk_manager_review(initial_prediction)

        # 11. Prepare Output logos
        final_prediction['home_logo'] = stats.get('homeTeam', {}).get('crest', '').replace("http://", "https://") if stats.get('homeTeam', {}).get('crest') else None
        final_prediction['away_logo'] = stats.get('awayTeam', {}).get('crest', '').replace("http://", "https://") if stats.get('awayTeam', {}).get('crest') else None

        # 13. Save to DB
        # Add match_id and match_date to prediction object if missing for DB consistency
        final_prediction['match_id'] = match_id
        final_prediction['match_date'] = match_date
        save_prediction(final_prediction)
        
        results.append(final_prediction)
        
    return results
