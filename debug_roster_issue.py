from src.services.sports_api import resolve_sofascore_match_id, get_sofascore_match_stats, get_sofascore_team_squad
import json
import os

# Everton vs Burnley
home_team = "Everton FC"
away_team = "Burnley FC"

match_id = resolve_sofascore_match_id(home_team, away_team)
if match_id:
    df, stats, h_id, a_id = get_sofascore_match_stats(match_id)
    h_squad = get_sofascore_team_squad(h_id)
    a_squad = get_sofascore_team_squad(a_id)
    
    print(f"DEBUG: Home ID {h_id} ({home_team}) -> {len(h_squad)} players")
    print(f"DEBUG: Away ID {a_id} ({away_team}) -> {len(a_squad)} players")
    
    if h_squad:
        print(f"Sample {home_team} Players: {h_squad[:5]}")
    if a_squad:
        print(f"Sample {away_team} Players: {a_squad[:5]}")
        
    # Check if Grealish is in either list
    if any("Grealish" in p for p in h_squad + a_squad):
        print("🚨 HALLUCINATION DETECTED IN DATA SOURCE (Impossible unless transferred)")
    else:
        print("✅ Data sources are clean. AI is hallucinating from internal knowledge.")
else:
    print("❌ Match ID not resolved.")
