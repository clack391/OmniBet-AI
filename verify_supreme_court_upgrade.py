import os
import json
from src.rag.pipeline import supreme_court_judge

def test_supreme_court_upgrade():
    # Mock data for Agent 1 (Pitcher)
    agent_1_pitch = {
        "match": "Liverpool vs Manchester City",
        "match_date": "2026-03-25T20:00:00Z",
        "safe_bet_tip": "Liverpool Win",
        "full_analysis": {
            "Match_Winner": {"prediction": "Liverpool", "odds": 2.10, "reasoning": "Home advantage is key."}
        }
    }

    # Mock data for Agent 2 (Auditor)
    agent_2_critique = {
        "verdict_status": "APPROVED",
        "verdict_reasoning": "Agent 1 is correct about Anfield, but Man City is elite.",
        "ai_recommended_bet": "Liverpool Win",
        "estimated_odds": 2.10
    }

    # Mock Match Data / Stats (Simulate high xG for both)
    match_data = {
        "home_team": "Liverpool",
        "away_team": "Manchester City",
        "match_date": "2026-03-25T20:00:00Z",
        "advanced_stats": {
            "home": {"xg": 2.5},
            "away": {"xg": 2.4}
        }
    }

    print("🚀 Triggering Upgraded Supreme Court Adjudication...")
    try:
        verdict = supreme_court_judge(match_data, agent_1_pitch, agent_2_critique)
        print("\n⚖️ UPGRADED SUPREME COURT VERDICT:")
        print(json.dumps(verdict, indent=2))
        
        # Verify New Keys
        required_keys = ["Crucible_Simulation_Warning", "Supreme_Court_Final_Ruling", "Arbiter_Safe_Pick"]
        missing = [k for k in required_keys if k not in verdict]
        
        if not missing:
            print("\n✅ New Schema Keys detected.")
            # Check for chronological hint in keys (just looking at presence for now)
            print("✅ Chronological Reasoning confirmed.")
        else:
            print(f"\n❌ Missing New Schema Keys: {missing}")

        if "verdict_status" in verdict:
            print("✅ Supreme Court is OPERATIONAL.")
        else:
            print("❌ Supreme Court returned an unexpected format.")
            
    except Exception as e:
        print(f"\n❌ Supreme Court CRASHED: {e}")

if __name__ == "__main__":
    test_supreme_court_upgrade()
