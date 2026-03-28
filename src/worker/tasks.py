"""
Celery background task for asynchronous match analysis.

This task replicates the full pipeline logic from /predict-batch in main.py
but runs it in a separate worker process so the HTTP request returns instantly.
"""
import json
import sqlite3

from src.worker.celery_app import celery_app
from src.worker.log_streamer import stream_logs_to_redis
from src.database.db import (
    DB_NAME,
    get_app_setting,
    get_cached_prediction,
    save_prediction,
    update_job_status,
    save_job_result,
    fail_job,
)
from src.rag.pipeline import predict_match, risk_manager_review, supreme_court_judge, audit_match
from src.services.sports_api import (
    get_sofascore_match_stats,
    fetch_latest_odds,
    get_match_stats,
    fetch_match_h2h,
    fetch_team_form,
    get_team_standings,
    resolve_sofascore_match_id,
)


def _is_cancelled(job_id: str) -> bool:
    """Check Redis for a per-job cancellation flag AND the global analysis kill switch."""
    try:
        # 1. Global Kill Switch Check
        from src.database.db import get_app_setting
        global_kill = get_app_setting("analysis_kill_signal", "0")
        if global_kill == "1":
            print(f"🛑 [WORKER] Global Analysis Kill Switch is ACTIVE. Aborting Job {job_id}.")
            return True

        # 2. Per-Job Redis Check
        import redis as redis_lib
        r = redis_lib.Redis(host="localhost", port=6379, db=0, decode_responses=True)
        return r.exists(f"job:{job_id}:cancel") == 1
    except Exception as e:
        print(f"⚠️ [WORKER] Error checking cancellation for {job_id}: {e}")
        return False


def _run_pipeline(match_id: int, job_id: str) -> dict:
    """
    Core prediction pipeline — mirrors predict_batch in main.py lines 687-942.
    Returns the final_prediction dict on success.
    Raises on unrecoverable error.
    """
    if _is_cancelled(job_id):
        raise Exception("Job cancelled by user")

    # 0. Cache check
    cached = get_cached_prediction(match_id)
    if cached:
        print(f"✅ Fast-tracking cached prediction for Match {match_id}")
        return cached

    provider = get_app_setting("primary_provider", "football-data")

    # ------------------------------------------------------------------ #
    # SofaScore route
    # ------------------------------------------------------------------ #
    if provider == "sofascore":
        print(f"✅ Route: SofaScore AI Pipeline for Match {match_id}")

        try:
            df, advanced_stats = get_sofascore_match_stats(match_id)
        except Exception as e:
            print(f"❌ SofaScore API failed after retries: {e}")
            df, advanced_stats = None, None

        if not advanced_stats:
            # Recovery: try to get match name from fixture cache
            recovered_match = "Unknown SofaScore Match"
            match_date = None
            try:
                conn = sqlite3.connect(DB_NAME)
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT fixtures_json FROM daily_fixtures WHERE date LIKE 'sofascore_%'"
                )
                for row in cursor.fetchall():
                    cached_matches = json.loads(row[0]).get("matches", [])
                    for m in cached_matches:
                        if str(m.get("id")) == str(match_id):
                            recovered_match = (
                                f"{m.get('homeTeam', {}).get('name', '???')} vs "
                                f"{m.get('awayTeam', {}).get('name', '???')}"
                            )
                            match_date = m.get("utcDate")
                            break
                    if recovered_match != "Unknown SofaScore Match":
                        break
            except Exception:
                pass
            finally:
                conn.close()

            if recovered_match != "Unknown SofaScore Match" and " vs " in recovered_match:
                print(f"🔄 Resilient Fallback: Predicting {recovered_match} without advanced stats...")
                hp, ap = recovered_match.split(" vs ")
                if _is_cancelled(job_id):
                    raise Exception("Job cancelled by user")
                odds = fetch_latest_odds(hp, ap)
                initial_prediction = predict_match(
                    hp, ap,
                    match_stats={},
                    odds_data=odds,
                    match_date=match_date if match_date and "1970" not in match_date else None,
                    match_id=match_id,
                    job_id=job_id,
                )
                final_prediction = risk_manager_review(
                    initial_prediction, match_date=match_date, match_id=match_id, job_id=job_id
                )
                final_prediction["match_id"] = match_id
                final_prediction["match_date"] = match_date
                final_prediction["match"] = recovered_match
                save_prediction(final_prediction)
                return final_prediction

            return {
                "match_id": match_id,
                "match": recovered_match,
                "error": "Advanced Stats Missing. The provider returned no data for this specific match ID.",
            }

        home_team = advanced_stats.get("metadata", {}).get("home_team", "Unknown")
        away_team = advanced_stats.get("metadata", {}).get("away_team", "Unknown")
        match_date = advanced_stats.get("metadata", {}).get("match_date")
        home_logo = advanced_stats.get("metadata", {}).get("home_logo")
        away_logo = advanced_stats.get("metadata", {}).get("away_logo")

        if not match_date or "1970" in match_date:
            try:
                conn = sqlite3.connect(DB_NAME)
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT fixtures_json FROM daily_fixtures WHERE date LIKE 'sofascore_%'"
                )
                for row in cursor.fetchall():
                    cached_matches = json.loads(row[0]).get("matches", [])
                    for m in cached_matches:
                        if str(m.get("id")) == str(match_id):
                            match_date = m.get("utcDate")
                            home_logo = home_logo or m.get("home_logo")
                            away_logo = away_logo or m.get("away_logo")
                            break
                    if match_date and "1970" not in match_date:
                        break
            except Exception as e:
                print("Date Fallback Error:", e)
            finally:
                conn.close()

        if _is_cancelled(job_id):
            raise Exception("Job cancelled by user")

        odds = fetch_latest_odds(home_team, away_team)
        if _is_cancelled(job_id): raise Exception("Job cancelled by user")
        initial_prediction = predict_match(
            home_team, away_team,
            match_stats={}, odds_data=odds, h2h_data={},
            home_form=None, away_form=None,
            home_standings={}, away_standings={},
            advanced_stats=advanced_stats,
            match_date=match_date,
            match_id=match_id,
            job_id=job_id,
        )
        if _is_cancelled(job_id): raise Exception("Job cancelled by user")
        final_prediction = risk_manager_review(
            initial_prediction, match_date=match_date, match_id=match_id, job_id=job_id
        )
        if _is_cancelled(job_id): raise Exception("Job cancelled by user")
        supreme_verdict = supreme_court_judge(
            advanced_stats, initial_prediction, final_prediction, match_id=match_id, job_id=job_id
        )
        final_prediction["supreme_court"] = supreme_verdict
        final_prediction["home_logo"] = home_logo
        final_prediction["away_logo"] = away_logo
        final_prediction["match_id"] = match_id
        final_prediction["match_date"] = match_date
        save_prediction(final_prediction)
        return final_prediction

    # ------------------------------------------------------------------ #
    # Football-Data route
    # ------------------------------------------------------------------ #
    stats = get_match_stats(match_id)
    if "error" in stats:
        return {"match_id": match_id, "error": stats["error"]}

    try:
        home_team = stats.get("homeTeam", {}).get("name")
        away_team = stats.get("awayTeam", {}).get("name")
        if not home_team or not away_team:
            if "match" in stats:
                home_team = stats["match"].get("homeTeam", {}).get("name")
                away_team = stats["match"].get("awayTeam", {}).get("name")
        if not home_team or not away_team:
            return {"match_id": match_id, "error": "Could not parse team names"}
    except Exception as e:
        return {"match_id": match_id, "error": f"Parsing error: {str(e)}"}

    h2h_data = fetch_match_h2h(match_id)
    if h2h_data and "matches" in h2h_data:
        h2h_data["matches"] = [m for m in h2h_data["matches"] if m["id"] != match_id]

    if _is_cancelled(job_id):
        raise Exception("Job cancelled by user")

    odds = fetch_latest_odds(home_team, away_team)

    home_id = stats.get("homeTeam", {}).get("id")
    away_id = stats.get("awayTeam", {}).get("id")
    home_form = fetch_team_form(home_id, team_name=home_team, venue="HOME") if home_id else None
    away_form = fetch_team_form(away_id, team_name=away_team, venue="AWAY") if away_id else None

    competition_id = stats.get("competition", {}).get("id", 2021)
    home_standings = get_team_standings(home_id, competition_id) if home_id else {}
    away_standings = get_team_standings(away_id, competition_id) if away_id else {}

    # Anti-data-leakage scrubber
    if "score" in stats:
        del stats["score"]
    if "match" in stats and "score" in stats["match"]:
        del stats["match"]["score"]

    match_date = stats.get("match", {}).get("utcDate") or stats.get("utcDate")

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

    if _is_cancelled(job_id):
        raise Exception("Job cancelled by user")

    if _is_cancelled(job_id): raise Exception("Job cancelled by user")
    initial_prediction = predict_match(
        home_team, away_team, stats, odds, h2h_data,
        home_form, away_form, home_standings, away_standings,
        advanced_stats=advanced_stats, match_date=match_date,
        match_id=match_id, job_id=job_id,
    )
    if _is_cancelled(job_id): raise Exception("Job cancelled by user")
    final_prediction = risk_manager_review(initial_prediction, match_date=match_date, match_id=match_id, job_id=job_id)
    if _is_cancelled(job_id): raise Exception("Job cancelled by user")
    supreme_verdict = supreme_court_judge(
        advanced_stats or stats, initial_prediction, final_prediction, match_id=match_id, job_id=job_id
    )
    final_prediction["supreme_court"] = supreme_verdict
    final_prediction["home_logo"] = (
        stats.get("homeTeam", {}).get("crest", "").replace("http://", "https://")
        if stats.get("homeTeam", {}).get("crest") else None
    )
    final_prediction["away_logo"] = (
        stats.get("awayTeam", {}).get("crest", "").replace("http://", "https://")
        if stats.get("awayTeam", {}).get("crest") else None
    )
    final_prediction["match_id"] = match_id
    final_prediction["match_date"] = match_date
    save_prediction(final_prediction)
    return final_prediction


@celery_app.task(bind=True, name="analyze_match", max_retries=0)
def analyze_match(self, match_id: int, job_id: str):
    """
    Background Celery task that runs the full 3-agent prediction pipeline
    for a single match and persists the result to the jobs table.
    """
    update_job_status(job_id, "PROCESSING")
    try:
        with stream_logs_to_redis(job_id):
            result = _run_pipeline(match_id, job_id)
        save_job_result(job_id, result)
        return {"job_id": job_id, "status": "COMPLETED"}
    except Exception as e:
        error_msg = str(e)
        fail_job(job_id, error_msg)
        print(f"❌ Job {job_id} failed: {error_msg}")
        raise


# ---------------------------------------------------------------------------
# Betslip Audit Pipeline
# ---------------------------------------------------------------------------

def _run_audit_pipeline(match_id: int, job_id: str,
                         user_selected_bet: str, booking_code) -> dict:
    """
    Core audit pipeline — mirrors predict_audit in main.py lines 961–1107.
    Calls audit_match() as Agent 2 instead of risk_manager_review().
    Returns the final prediction dict (with audit_verdict, etc.) on success.
    """
    if _is_cancelled(job_id):
        raise Exception("Job cancelled by user")

    provider = get_app_setting("primary_provider", "football-data")

    # ------------------------------------------------------------------ #
    # SofaScore route
    # ------------------------------------------------------------------ #
    if provider == "sofascore":
        print(f"✅ Route: SofaScore Auditor Pipeline for Match {match_id}")

        try:
            df, advanced_stats = get_sofascore_match_stats(match_id)
        except Exception as e:
            print(f"❌ SofaScore API failed: {e}")
            advanced_stats = None

        if not advanced_stats:
            return {"match_id": match_id, "error": "Failed to fetch SofaScore stats."}

        home_team = advanced_stats.get("metadata", {}).get("home_team", "Unknown")
        away_team = advanced_stats.get("metadata", {}).get("away_team", "Unknown")
        match_date = advanced_stats.get("metadata", {}).get("match_date")
        home_logo = advanced_stats.get("metadata", {}).get("home_logo")
        away_logo = advanced_stats.get("metadata", {}).get("away_logo")

        if not match_date or "1970" in match_date:
            try:
                conn = sqlite3.connect(DB_NAME)
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT fixtures_json FROM daily_fixtures WHERE date LIKE 'sofascore_%'"
                )
                for row in cursor.fetchall():
                    import json as _json
                    cached_matches = _json.loads(row[0]).get("matches", [])
                    for m in cached_matches:
                        if str(m.get("id")) == str(match_id):
                            match_date = m.get("utcDate")
                            home_logo = home_logo or m.get("home_logo")
                            away_logo = away_logo or m.get("away_logo")
                            break
                    if match_date and "1970" not in match_date:
                        break
            except Exception as e:
                print("Date Fallback Error:", e)
            finally:
                conn.close()

        if _is_cancelled(job_id):
            raise Exception("Job cancelled by user")

        odds = fetch_latest_odds(home_team, away_team)

        if _is_cancelled(job_id): raise Exception("Job cancelled by user")
        initial_prediction = predict_match(
            home_team, away_team,
            match_stats={}, odds_data=odds, h2h_data={},
            home_form=None, away_form=None,
            home_standings={}, away_standings={},
            advanced_stats=advanced_stats,
            match_date=match_date,
            match_id=match_id,
            job_id=job_id,
        )
        if _is_cancelled(job_id): raise Exception("Job cancelled by user")
        audit_verdict_json = audit_match(
            initial_prediction, user_selected_bet,
            match_date=match_date, match_id=match_id, job_id=job_id,
        )
        if _is_cancelled(job_id): raise Exception("Job cancelled by user")
        supreme_verdict = supreme_court_judge(
            advanced_stats, initial_prediction, audit_verdict_json, match_id=match_id, job_id=job_id
        )

        initial_prediction["audit_verdict"]     = audit_verdict_json.get("audit_verdict")
        initial_prediction["internal_debate"]   = audit_verdict_json.get("internal_debate")
        initial_prediction["verdict_reasoning"] = audit_verdict_json.get("verdict_reasoning")
        initial_prediction["supreme_court"]     = supreme_verdict
        initial_prediction["home_team"]         = home_team
        initial_prediction["away_team"]         = away_team
        initial_prediction["home_logo"]         = home_logo
        initial_prediction["away_logo"]         = away_logo
        initial_prediction["match_id"]          = match_id
        initial_prediction["match_date"]        = match_date
        initial_prediction["booking_code"]      = booking_code
        initial_prediction["user_selected_bet"] = user_selected_bet
        save_prediction(initial_prediction)
        return initial_prediction

    # ------------------------------------------------------------------ #
    # Football-Data route
    # ------------------------------------------------------------------ #
    stats = get_match_stats(match_id)
    if "error" in stats:
        return {"match_id": match_id, "error": stats["error"]}

    home_team = stats.get("homeTeam", {}).get("name", "Unknown")
    away_team = stats.get("awayTeam", {}).get("name", "Unknown")

    h2h_data = fetch_match_h2h(match_id)
    if h2h_data and "matches" in h2h_data:
        h2h_data["matches"] = [m for m in h2h_data["matches"] if m["id"] != match_id]

    if _is_cancelled(job_id):
        raise Exception("Job cancelled by user")

    odds = fetch_latest_odds(home_team, away_team)

    home_id = stats.get("homeTeam", {}).get("id")
    away_id = stats.get("awayTeam", {}).get("id")
    home_form = fetch_team_form(home_id, team_name=home_team, venue="HOME") if home_id else None
    away_form = fetch_team_form(away_id, team_name=away_team, venue="AWAY") if away_id else None

    competition_id = stats.get("competition", {}).get("id", 2021)
    home_standings = get_team_standings(home_id, competition_id) if home_id else {}
    away_standings = get_team_standings(away_id, competition_id) if away_id else {}

    if "score" in stats:
        del stats["score"]
    if "match" in stats and "score" in stats["match"]:
        del stats["match"]["score"]

    match_date = stats.get("match", {}).get("utcDate") or stats.get("utcDate")

    advanced_stats = None
    sofascore_id = resolve_sofascore_match_id(home_team, away_team, match_date)
    if sofascore_id:
        df, advanced_stats = get_sofascore_match_stats(sofascore_id)

    if _is_cancelled(job_id):
        raise Exception("Job cancelled by user")

    if _is_cancelled(job_id): raise Exception("Job cancelled by user")
    initial_prediction = predict_match(
        home_team, away_team, stats, odds, h2h_data,
        home_form, away_form, home_standings, away_standings,
        advanced_stats=advanced_stats, match_date=match_date, match_id=match_id, job_id=job_id,
    )
    if _is_cancelled(job_id): raise Exception("Job cancelled by user")
    audit_verdict_json = audit_match(
        initial_prediction, user_selected_bet,
        match_date=match_date, match_id=match_id, job_id=job_id,
    )
    if _is_cancelled(job_id): raise Exception("Job cancelled by user")
    supreme_verdict = supreme_court_judge(
        advanced_stats or stats, initial_prediction, audit_verdict_json, match_id=match_id, job_id=job_id
    )

    initial_prediction["audit_verdict"]     = audit_verdict_json.get("audit_verdict")
    initial_prediction["internal_debate"]   = audit_verdict_json.get("internal_debate")
    initial_prediction["verdict_reasoning"] = audit_verdict_json.get("verdict_reasoning")
    initial_prediction["supreme_court"]     = supreme_verdict
    initial_prediction["home_team"]         = home_team
    initial_prediction["away_team"]         = away_team
    initial_prediction["home_logo"] = (
        stats.get("homeTeam", {}).get("crest", "").replace("http://", "https://")
        if stats.get("homeTeam", {}).get("crest") else None
    )
    initial_prediction["away_logo"] = (
        stats.get("awayTeam", {}).get("crest", "").replace("http://", "https://")
        if stats.get("awayTeam", {}).get("crest") else None
    )
    initial_prediction["match_id"]          = match_id
    initial_prediction["match_date"]        = match_date
    initial_prediction["booking_code"]      = booking_code
    initial_prediction["user_selected_bet"] = user_selected_bet
    save_prediction(initial_prediction)
    return initial_prediction


@celery_app.task(bind=True, name="analyze_audit", max_retries=0)
def analyze_audit(self, match_id: int, job_id: str,
                  user_selected_bet: str, booking_code):
    """
    Background Celery task that runs the full 3-agent betslip audit pipeline
    for a single match and persists the result to the jobs table.
    """
    update_job_status(job_id, "PROCESSING")
    try:
        with stream_logs_to_redis(job_id):
            result = _run_audit_pipeline(match_id, job_id, user_selected_bet, booking_code)
        save_job_result(job_id, result)
        return {"job_id": job_id, "status": "COMPLETED"}
    except Exception as e:
        error_msg = str(e)
        fail_job(job_id, error_msg)
        print(f"❌ Audit job {job_id} failed: {error_msg}")
        raise
