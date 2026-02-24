from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Dict, Any
from pydantic import BaseModel
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
    save_prediction,
    get_accuracy_stats,
    get_cached_prediction,
    get_all_predictions,
    clear_predictions,
    update_prediction_result,
    delete_prediction,
    save_best_picks,
    get_best_picks,
    clear_best_picks
)
from src.services.grader import fetch_result_with_ai

app = FastAPI()

class MatchBatchRequest(BaseModel):
    match_ids: List[int]

class GradeRequest(BaseModel):
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
def clear_history():
    clear_predictions()
    return {"message": "Prediction history cleared."}

@app.delete("/history/{match_id}")
def delete_single_history(match_id: int):
    delete_prediction(match_id)
    return {"status": "deleted", "match_id": match_id}

@app.post("/generate-best-picks")
def create_best_picks():
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
def delete_best_picks():
    clear_best_picks()
    return {"status": "cleared"}

@app.post("/grade-history")
def grade_history(request: GradeRequest):
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
def predict_batch(request: MatchBatchRequest):
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

        # 9. Predict (Agent 1)
        initial_prediction = predict_match(
            home_team,
            away_team,
            stats,
            odds,
            h2h_data,
            home_form,
            away_form,
            home_standings,
            away_standings
        )

        # 10. Risk Manager Review (Agent 2)
        final_prediction = risk_manager_review(initial_prediction)

        # 11. Prepare Output logos
        final_prediction['home_logo'] = stats.get('homeTeam', {}).get('crest', '').replace("http://", "https://") if stats.get('homeTeam', {}).get('crest') else None
        final_prediction['away_logo'] = stats.get('awayTeam', {}).get('crest', '').replace("http://", "https://") if stats.get('awayTeam', {}).get('crest') else None

        # 9. Save to DB
        # Add match_id and match_date to prediction object if missing for DB consistency
        final_prediction['match_id'] = match_id
        final_prediction['match_date'] = stats.get('match', {}).get('utcDate') or stats.get('utcDate')
        save_prediction(final_prediction)
        
        results.append(final_prediction)
        
    return results
