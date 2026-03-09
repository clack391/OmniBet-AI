import os
import sys
import time
import json
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv

load_dotenv()

# Add the root directory to sys.path so we can import src modules
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

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
from src.rag.pipeline import predict_match, risk_manager_review, supreme_court_judge
from src.database.db import get_cached_prediction, save_prediction, get_app_setting
from src.services.sports_api import get_sofascore_fixtures

def run_daily_cron():
    print("🚀 Starting OmniBet AI Daily Cron Job...")
    
    # 0. Check if automation is enabled in settings
    if get_app_setting("cron_enabled", "true") != "true":
        print("🛑 AI Automation is currently DISABLED in settings. Exiting.")
        return
    
    # 1. Get dates for the custom 2:00 AM to 1:59 AM window
    today_dt = datetime.now(timezone.utc)
    
    # Establish the exact 24-hour window starting at 2:00 AM
    start_time = today_dt.replace(hour=2, minute=0, second=0, microsecond=0)
    end_time = start_time + timedelta(hours=23, minutes=59, seconds=59)
    
    # We must fetch both today and tomorrow from the API to cover the gap
    start_date_str = start_time.strftime("%Y-%m-%d")
    end_date_str = end_time.strftime("%Y-%m-%d")
    
    print(f"📅 Fetching fixtures between {start_time.strftime('%Y-%m-%d %H:%M')} and {end_time.strftime('%Y-%m-%d %H:%M')} UTC...")
    
    provider = get_app_setting("primary_provider", "football-data")
    print(f"⚙️ Active Data Provider: {provider}")
    
    try:
        if provider == "sofascore":
            fixtures_data = get_sofascore_fixtures(start_date_str, end_date_str)
        else:
            fixtures_data = get_fixtures_by_date(start_date_str, end_date_str)
            
        all_matches = fixtures_data.get('matches', [])
    except Exception as e:
        print(f"❌ Failed to fetch fixtures: {e}")
        return

    # Filter to only the specific 2AM to 1:59AM window instead of whole calendar days
    target_matches = []
    for m in all_matches:
        utc_str = m.get('utcDate', '')
        if not utc_str:
            continue
        try:
            # Parse '2026-02-27T15:00:00Z' into datetime
            match_dt = datetime.fromisoformat(utc_str.replace('Z', '+00:00'))
            if start_time <= match_dt <= end_time:
                target_matches.append(m)
        except ValueError:
            pass
            
    today_matches = target_matches
    print(f"⚽ Found {len(today_matches)} matches scheduled in the 2:00 AM -> 1:59 AM window.")
    
    for i, match in enumerate(today_matches):
        match_id = match['id']
        home_team = match.get('homeTeam', {}).get('name', 'Unknown')
        away_team = match.get('awayTeam', {}).get('name', 'Unknown')
        
        print(f"\n--- Processing Match {i+1}/{len(today_matches)}: {home_team} vs {away_team} (ID: {match_id}) ---")
        
        # 1. Database Check
        cached = get_cached_prediction(match_id)
        if cached:
            print(f"✅ Prediction already exists in database. Skipping API calls.")
            continue
            
        print(f"⏳ No prediction found. Starting analysis...")
        
        try:
            if provider == "sofascore":
                print(f"✅ Route: SofaScore AI Pipeline for Match {match_id}")
                df, advanced_stats = get_sofascore_match_stats(match_id)
                if not advanced_stats:
                    print(f"⚠️ Failed to fetch SofaScore stats for match {match_id}")
                    continue
                    
                home_team = advanced_stats.get('metadata', {}).get('home_team', 'Unknown')
                away_team = advanced_stats.get('metadata', {}).get('away_team', 'Unknown')
                match_date = match.get('utcDate') # Best practice: pull exact date from the schedule payload
                
                odds = fetch_latest_odds(home_team, away_team)
                
                initial_prediction = predict_match(
                    home_team, away_team, 
                    match_stats={}, odds_data=odds, h2h_data={}, home_form=None, away_form=None, 
                    home_standings={}, away_standings={}, 
                    advanced_stats=advanced_stats, match_date=match_date
                )
                
                final_prediction = risk_manager_review(initial_prediction, match_date=match_date)
                
                # Agent 3: Supreme Court Final Adjudication
                supreme_verdict = supreme_court_judge(advanced_stats, initial_prediction, final_prediction)
                final_prediction['supreme_court'] = supreme_verdict
                final_prediction['home_logo'] = advanced_stats.get('metadata', {}).get('home_logo')
                final_prediction['away_logo'] = advanced_stats.get('metadata', {}).get('away_logo')
                
                final_prediction['match_id'] = match_id
                final_prediction['match_date'] = match_date
                save_prediction(final_prediction)
                
                print(f"🏆 Successfully saved prediction for {home_team} vs {away_team}")
                
                if i < len(today_matches) - 1:
                    print(f"💤 Sleeping for 30 seconds to respect API rate limits...")
                    time.sleep(30)
                continue

            # 2. Get Stats from pre-fetched calendar payload string to save API quota
            stats = match.copy()
            

            # 3. Get H2H
            h2h_data = fetch_match_h2h(match_id)
            if h2h_data and 'matches' in h2h_data:
                 h2h_data['matches'] = [m for m in h2h_data['matches'] if m['id'] != match_id]
                 
            # 4. Get Odds
            odds = fetch_latest_odds(home_team, away_team)
            
            # 5. Get Form
            home_id = match.get('homeTeam', {}).get('id')
            away_id = match.get('awayTeam', {}).get('id')
            home_form = fetch_team_form(home_id, team_name=home_team, venue="HOME") if home_id else None
            away_form = fetch_team_form(away_id, team_name=away_team, venue="AWAY") if away_id else None
            
            # 6. Get Standings
            competition_id = match.get('competition', {}).get('id', 2021)
            home_standings = get_team_standings(home_id, competition_id) if home_id else {}
            away_standings = get_team_standings(away_id, competition_id) if away_id else {}
            
            # 8. Scrubber
            if 'score' in stats:
                del stats['score']
            if 'match' in stats and 'score' in stats['match']:
                del stats['match']['score']
                
            match_date = stats.get('match', {}).get('utcDate') or stats.get('utcDate')
            
            # 8.5 RapidAPI Integration
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
            
            # 9. Agent 1
            initial_prediction = predict_match(
                home_team, away_team, stats, odds, h2h_data, home_form, away_form, home_standings, away_standings, advanced_stats=advanced_stats, match_date=match_date
            )
            
            # 9. Agent 2
            final_prediction = risk_manager_review(initial_prediction, match_date=match_date)
            
            # 9.5 Agent 3: Supreme Court Final Adjudication
            supreme_verdict = supreme_court_judge(advanced_stats or stats, initial_prediction, final_prediction)
            final_prediction['supreme_court'] = supreme_verdict
            
            # 10. Prepare and Save
            final_prediction['home_logo'] = match.get('homeTeam', {}).get('crest', '').replace("http://", "https://") if match.get('homeTeam', {}).get('crest') else None
            final_prediction['away_logo'] = match.get('awayTeam', {}).get('crest', '').replace("http://", "https://") if match.get('awayTeam', {}).get('crest') else None
            
            final_prediction['match_id'] = match_id
            final_prediction['match_date'] = match_date
            save_prediction(final_prediction)
            
            print(f"🏆 Successfully saved prediction for {home_team} vs {away_team}")
            
        except Exception as e:
            print(f"❌ Unhandled error processing match {match_id}: {e}")
            
        # VERY IMPORTANT: Rate Limit Sleep
        # Even if we hit an error, we sleep so the API doesn't ban us for looping too fast through failures
        if i < len(today_matches) - 1:
            print(f"💤 Sleeping for 30 seconds to respect API rate limits...")
            time.sleep(30)
            
    print("\n🎉 OmniBet AI Daily Cron Job Finished!")

if __name__ == "__main__":
    run_daily_cron()
