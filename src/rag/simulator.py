import numpy as np
import re

def run_crucible_simulation(home_xG: float, away_xG: float, variance_multiplier: float, agent_2_pick: str, supreme_court_pick: str) -> dict:
    """
    Runs a 10,000 iteration Monte Carlo simulation using Poisson distributions to test the survival rate of the AI picks.
    """
    # 1. Adjust xG by the variance multiplier configured by the Supreme Court
    home_xG_adj = home_xG * variance_multiplier
    away_xG_adj = away_xG * variance_multiplier

    # 2. Generate distributions n=10000
    home_goals = np.random.poisson(lam=home_xG_adj, size=10000)
    away_goals = np.random.poisson(lam=away_xG_adj, size=10000)

    agent_2_wins = 0
    sc_wins = 0

    def evaluate_pick(home_score, away_score, pick):
        pick = str(pick).lower().strip()
        if not pick: return False
        
        # Match Winner & Double Chance
        if "1x" in pick or "1 x" in pick or "home/draw" in pick or "home or draw" in pick:
            return home_score >= away_score
        elif "x2" in pick or "x 2" in pick or "draw/away" in pick or "draw or away" in pick:
            return away_score >= home_score
        elif "12" in pick or "home/away" in pick or "home or away" in pick:
            return home_score != away_score
        elif "home win" in pick or pick == "1" or pick == "home":
            return home_score > away_score
        elif "away win" in pick or pick == "2" or pick == "away":
            return away_score > home_score
        elif "draw" in pick or pick == "x":
            return home_score == away_score
        
        # Match Goals
        elif "over 0.5" in pick: return (home_score + away_score) > 0.5
        elif "over 1.5" in pick: return (home_score + away_score) > 1.5
        elif "over 2.5" in pick: return (home_score + away_score) > 2.5
        elif "over 3.5" in pick: return (home_score + away_score) > 3.5
        elif "over 4.5" in pick: return (home_score + away_score) > 4.5
        elif "under 0.5" in pick: return (home_score + away_score) < 0.5
        elif "under 1.5" in pick: return (home_score + away_score) < 1.5
        elif "under 2.5" in pick: return (home_score + away_score) < 2.5
        elif "under 3.5" in pick: return (home_score + away_score) < 3.5
        elif "under 4.5" in pick: return (home_score + away_score) < 4.5
        
        # BTTS
        elif "btts: yes" in pick or "both teams to score: yes" in pick or pick == "btts" or "yes" in pick and "btts" in pick:
            return home_score > 0 and away_score > 0
        elif "btts: no" in pick or "both teams to score: no" in pick or "no" in pick and "btts" in pick:
            return home_score == 0 or away_score == 0
            
        # Team Goals
        elif "home over 0.5" in pick or "home team over 0.5" in pick or "home to score" in pick: return home_score > 0.5
        elif "home over 1.5" in pick or "home team over 1.5" in pick: return home_score > 1.5
        elif "away over 0.5" in pick or "away team over 0.5" in pick or "away to score" in pick: return away_score > 0.5
        elif "away over 1.5" in pick or "away team over 1.5" in pick: return away_score > 1.5
            
        # Draw No Bet
        elif "draw no bet: home" in pick or "dnb: home" in pick or "dnb 1" in pick:
            return home_score >= away_score # Refund is mathematically a parlay survival, not a loss
        elif "draw no bet: away" in pick or "dnb: away" in pick or "dnb 2" in pick:
            return away_score >= home_score 
        # Asian Handicap
        if "asian handicap" in pick or "ah " in pick or "+" in pick or "-" in pick:
            match = re.search(r'([+-]\d+\.\d+)', pick)
            if match:
                handicap = float(match.group(1))
                if "home" in pick or " 1 " in pick or pick.endswith("1"):
                    return (home_score + handicap) >= away_score # Re-fund tie survives parlay
                elif "away" in pick or " 2 " in pick or pick.endswith("2"):
                    return (away_score + handicap) >= home_score

        # Default fallback for corners/cards markets we cannot simulate with xG
        return True

    # 3. Test the logic
    for i in range(10000):
        if evaluate_pick(home_goals[i], away_goals[i], agent_2_pick):
            agent_2_wins += 1
        if evaluate_pick(home_goals[i], away_goals[i], supreme_court_pick):
            sc_wins += 1

    a2_win_rate = (agent_2_wins / 10000) * 100
    sc_win_rate = (sc_wins / 10000) * 100

    audit_string = f"[SIMULATION AUDIT: 10,000 Monte Carlo iterations completed. Agent 2 Pick ({agent_2_pick}) Survival: {a2_win_rate:.1f}%. Supreme Court Pick ({supreme_court_pick}) Survival: {sc_win_rate:.1f}%.]"

    # 4. Generate the Heatmap Distributions
    distribution = {"0": 0, "1": 0, "2": 0, "3": 0, "4": 0, "5+": 0}
    for i in range(10000):
        total = home_goals[i] + away_goals[i]
        if total == 0: distribution["0"] += 1
        elif total == 1: distribution["1"] += 1
        elif total == 2: distribution["2"] += 1
        elif total == 3: distribution["3"] += 1
        elif total == 4: distribution["4"] += 1
        else: distribution["5+"] += 1

    return {
        "audit_string": audit_string,
        "agent_2_win_rate": a2_win_rate,
        "supreme_court_win_rate": sc_win_rate,
        "distribution": distribution
    }
