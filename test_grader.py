import asyncio
from src.services.grader import fetch_result_with_ai

if __name__ == "__main__":
    print("Testing OmniBet AI Auto-Grader Integration...")
    
    # We will test Hamburg vs Leipzig with the "Both Teams to Score - Yes" tip.
    team_a = "Hamburger SV"
    team_b = "RB Leipzig"
    match_date = "today" # Relative is fine for Google Search resolving
    safe_bet_tip = "Both Teams to Score - Yes"
    
    print("\n--------------------------")
    print(f"Match: {team_a} vs {team_b}")
    print(f"Prediction Evaluated: {safe_bet_tip}")
    print("--------------------------\n")
    
    result = fetch_result_with_ai(team_a, team_b, match_date, safe_bet_tip)
    
    print("\n--------------------------")
    print("FINAL GRADER JSON OUTPUT:")
    print(result)
    print("--------------------------\n")
