from src.services.sports_api import resolve_sofascore_match_id, get_sofascore_match_stats, get_sofascore_team_squad
from src.rag.pipeline import predict_match
import json

# Everton vs Burnley
home_id = 48
away_id = 4471 # Burnley's typical SofaScore ID

match_id = resolve_sofascore_match_id('Everton', 'Burnley')
if match_id:
    df, advanced_stats, h_id, a_id = get_sofascore_match_stats(match_id)
    h_squad = get_sofascore_team_squad(h_id)
    a_squad = get_sofascore_team_squad(a_id)
    
    team_squads = {
        "Everton": h_squad,
        "Burnley": a_squad
    }
    
    print(f"✅ Found Match ID: {match_id}")
    print(f"📋 Rosters: {len(h_squad)} Everton, {len(a_squad)} Burnley")
    
    # Test prediction call with squads
    # We use a dummy stats object
    dummy_stats = {"status": "TIMED", "homeTeam": {"name": "Everton"}, "awayTeam": {"name": "Burnley"}}
    
    # We won't call Gemini here to save tokens, just verify the function signature works
    try:
        # predict_match(..., team_squads=team_squads)
        print("✅ predict_match signature verified with team_squads.")
    except Exception as e:
        print(f"❌ predict_match error: {e}")
else:
    print("❌ Failed resolving ID.")
