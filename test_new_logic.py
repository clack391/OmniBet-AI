import os
import json
import asyncio
from src.rag.pipeline import predict_match, risk_manager_review
from src.services.sports_api import get_match_stats, fetch_team_form, fetch_match_h2h, get_team_standings

async def test_leeds_sunderland():
    # 328: Leeds, 66: Sunderland (Using realistic IDs for testing, these might need adjustment)
    home_team = "Leeds United FC"
    away_team = "Sunderland AFC"
    
    # Mock stats to trigger the "Desperation" and "Missing Attackers" scenario
    stats = {"status": "TIMED", "homeTeam": {"id": 328, "name": home_team}, "awayTeam": {"id": 66, "name": away_team}}
    odds = [{"bookmaker": "DraftKings", "markets": [{"key": "1x2", "outcomes": [{"name": home_team, "price": 1.90}, {"name": "Draw", "price": 3.40}, {"name": away_team, "price": 4.00}]}]}]
    
    # Give Sunderland terrible form to trigger the Ineptitude Floor
    home_form = {"goals_scored_avg": 1.5, "goals_conceded_avg": 1.0, "form_string": "W-D-W-L-W"}
    away_form = {"goals_scored_avg": 0.4, "goals_conceded_avg": 1.8, "form_string": "L-L-D-L-L"}
    
    home_standings = {"position": 17, "points": 35} # Leeds desperate for relegation survival
    away_standings = {"position": 10, "points": 45} # Sunderland comfortable mid table
    
    # H2H and Advanced Stats
    h2h_data = {"matches": []}
    advanced_stats = {"Goals scored": {home_team: 1.5, away_team: 0.4}}

    print("--- Running Primary Agent ---")
    initial = predict_match(home_team, away_team, stats, odds, h2h_data, home_form, away_form, home_standings, away_standings, advanced_stats)
    
    print("\n--- Running Risk Manager ---")
    final = risk_manager_review(initial)
    
    print("\n--- FINAL OUTPUT ---")
    print(json.dumps(final, indent=2))

if __name__ == "__main__":
    asyncio.run(test_leeds_sunderland())
