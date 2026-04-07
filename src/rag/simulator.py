import numpy as np
import re
from scipy.stats import nbinom

# ==============================================================================
# ⚙️ UPGRADE 1: DIXON-COLES ADJUSTMENT RHO TABLE
# ==============================================================================
# Correlation factor that corrects the standard independent Poisson model.
# Boosts probability of true low-scoring scorelines (0-0, 1-0, 0-1, 1-1)
# that Standard Poisson chronically underestimates due to goal independence.
# Source: Dixon & Coles (1997) — "Modelling Association Football Scores..."
#
# RHO_TABLE[home_goals][away_goals] = adjustment multiplier
# Only applies to scorelines where max(h, a) <= 1 (the four "edge" cells).
RHO_STANDARD = -0.13  # Calibrated for evenly-matched football
RHO_MISMATCH = -0.10  # Reduced bias for mismatched games (reduces 0-0 over-weighting)
RHO_HIGH_SCORING = -0.05  # Minimal bias for high-scoring games (combined xG > 3.0)

def calculate_rho(home_xG: float, away_xG: float) -> float:
    """
    Dynamically adjusts rho based on:
    1. Combined xG (high-scoring game detection)
    2. xG imbalance (mismatch detection)

    For high-scoring games (combined xG > 3.0), Dixon-Coles should apply
    minimal 0-0 correction because the base probability of 0-0 is already
    very low. Standard Dixon-Coles was calibrated on low-scoring English
    football from the 1990s and over-corrects for modern high-xG matches.

    CRITICAL: This function is now protected by upstream recent form analysis.
    If a team is in a goal drought, the xG extraction layer will blend recent
    form (70%) with season averages (30%), preventing inflated xG values that
    would trigger High-Scoring mode inappropriately.
    """
    combined_xG = home_xG + away_xG
    xG_ratio = max(home_xG, away_xG) / max(min(home_xG, away_xG), 0.5)

    # Priority 1: High-scoring games need minimal 0-0 correction
    # (Now protected: drought teams will have combined_xG < 2.5, avoiding this branch)
    if combined_xG > 3.0:
        return RHO_HIGH_SCORING  # -0.05 for explosive matches

    # Priority 2: Mismatched games (one-sided)
    if xG_ratio > 1.5:
        return RHO_MISMATCH  # -0.10 for mismatches

    # Priority 3: Low-scoring drought scenarios (Dead Engine protection)
    # When combined_xG < 2.0, increase rho to better model 0-0 and 1-0 probability
    if combined_xG < 2.0:
        return -0.15  # Enhanced correction for very low-scoring matches

    # Default: Standard evenly-matched games
    return RHO_STANDARD  # -0.13 for normal matches

def dixon_coles_weight(h: int, a: int, mu_h: float, mu_a: float, rho: float) -> float:
    """
    Returns the Dixon-Coles correction multiplier for a (h, a) scoreline.
    Only meaningful for low-scoring outcomes (h <= 1 and a <= 1).
    For all other scorelines, returns 1.0 (no correction applied).
    """
    if h == 0 and a == 0:
        return 1.0 - mu_h * mu_a * rho
    elif h == 1 and a == 0:
        return 1.0 + mu_a * rho
    elif h == 0 and a == 1:
        return 1.0 + mu_h * rho
    elif h == 1 and a == 1:
        return 1.0 - rho
    return 1.0


# ==============================================================================
# ⚙️ UPGRADE 2: NEGATIVE BINOMIAL DISTRIBUTION — CHAOS MODE
# ==============================================================================
# Standard Poisson assumes Mean == Variance (perfectly "neat" randomness).
# For high-chaos matches (Rule 62: Nothing to Lose Shootout, or any fixture
# where variance_multiplier > 1.2), real football has FAT TAILS — meaning
# extreme scorelines like 4-2 or 3-3 are far more likely than Poisson suggests.
#
# Negative Binomial adds an "overdispersion" parameter (r) that separates Mean
# from Variance, creating those fat tails.
#
# CHAOS_THRESHOLD: variance_multiplier above this value triggers NegBinom mode.
CHAOS_THRESHOLD = 1.2

def sample_goals(mu: float, variance_multiplier: float, size: int) -> np.ndarray:
    """
    Samples goal counts using the mathematically appropriate distribution:
      - Standard Poisson: Normal matches (variance_multiplier <= 1.2)
      - Negative Binomial: High-chaos matches (variance_multiplier > 1.2)

    The overdispersion parameter (r) is derived from the multiplier itself,
    so a multiplier of 2.0 produces much fatter tails than 1.3.
    """
    mu_adj = mu * variance_multiplier
    if variance_multiplier <= CHAOS_THRESHOLD:
        # Standard Poisson — clean, symmetric distribution
        return np.random.poisson(lam=mu_adj, size=size)
    else:
        # Negative Binomial — overdispersed for fat tails
        # Overdispersion grows with the variance multiplier
        overdispersion = (variance_multiplier - 1.0) * 2.0  # e.g., 1.5x → 1.0 extra variance
        variance = mu_adj + overdispersion * (mu_adj ** 2)
        r = (mu_adj ** 2) / max(variance - mu_adj, 1e-6)  # shape param
        p = r / (r + mu_adj)  # success probability
        r = max(r, 0.1)  # guard against degenerate values
        return nbinom.rvs(n=r, p=p, size=size)


# ==============================================================================
# MAIN SIMULATION FUNCTION
# ==============================================================================

def run_crucible_simulation(home_xG: float, away_xG: float, variance_multiplier: float, agent_2_pick: str, supreme_court_pick: str) -> dict:
    """
    Runs a 10,000 iteration Monte Carlo simulation to test the survival rate of the AI picks.

    MATHEMATICAL ENGINE:
    - Upgrade 1 (Dixon-Coles): Corrects standard Poisson to accurately model the
      probability of low-scoring results (0-0, 1-0, 0-1, 1-1) via a correlation factor.
    - Upgrade 2 (Negative Binomial): Switches from Poisson to Negative Binomial when
      variance_multiplier > 1.2, enabling fat-tail modelling for chaotic high-scoring matches.
    """
    N = 10_000

    # Calculate dynamic rho based on xG imbalance
    rho = calculate_rho(home_xG, away_xG)

    # 1. Sample goal distributions (Upgrade 2: Poisson vs NegBinom based on chaos level)
    home_goals_raw = sample_goals(home_xG, variance_multiplier, N)
    away_goals_raw = sample_goals(away_xG, variance_multiplier, N)

    # Adjusted xG means (for Dixon-Coles weight calculation)
    mu_h = home_xG * variance_multiplier
    mu_a = away_xG * variance_multiplier

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
        elif "btts: yes" in pick or "both teams to score: yes" in pick or pick == "btts" or ("yes" in pick and "btts" in pick):
            return home_score > 0 and away_score > 0
        elif "btts: no" in pick or "both teams to score: no" in pick or ("no" in pick and "btts" in pick):
            return home_score == 0 or away_score == 0

        # Team Goals
        elif "home over 0.5" in pick or "home team over 0.5" in pick or "home to score" in pick: return home_score > 0.5
        elif "home over 1.5" in pick or "home team over 1.5" in pick: return home_score > 1.5
        elif "away over 0.5" in pick or "away team over 0.5" in pick or "away to score" in pick: return away_score > 0.5
        elif "away over 1.5" in pick or "away team over 1.5" in pick: return away_score > 1.5
        elif "home under 0.5" in pick or "home team under 0.5" in pick: return home_score < 0.5
        elif "home under 1.5" in pick or "home team under 1.5" in pick: return home_score < 1.5
        elif "away under 0.5" in pick or "away team under 0.5" in pick: return away_score < 0.5
        elif "away under 1.5" in pick or "away team under 1.5" in pick: return away_score < 1.5

        # Draw No Bet
        elif "draw no bet: home" in pick or "dnb: home" in pick or "dnb 1" in pick:
            return home_score >= away_score
        elif "draw no bet: away" in pick or "dnb: away" in pick or "dnb 2" in pick:
            return away_score >= home_score

        # Asian Handicap
        elif "asian handicap" in pick or "ah " in pick or "handicap" in pick or "+" in pick or "-" in pick:
            match = re.search(r'([+-]\d+(?:\.\d+)?)', pick)
            if match:
                handicap = float(match.group(1))
                # Check if "home" or "away" is explicitly mentioned
                if "home" in pick or " 1 " in pick or pick.endswith(" 1"):
                    return (home_score + handicap) >= away_score
                elif "away" in pick or " 2 " in pick or pick.endswith(" 2"):
                    return (away_score + handicap) >= home_score
                # If neither home/away mentioned, infer from handicap sign convention:
                # Negative handicap typically means favorite (if at start of string, assume home)
                # Positive handicap typically means underdog
                elif handicap > 0:
                    # Positive handicap usually for underdog (commonly away, but context-dependent)
                    # Default to away getting the handicap
                    return (away_score + handicap) >= home_score
                elif handicap < 0:
                    # Negative handicap for favorite (commonly home, but context-dependent)
                    # Default to home giving the handicap (home score adjusted)
                    return (home_score + handicap) >= away_score

        # Default fallback for corners/cards markets we cannot simulate with xG
        return True

    # 3. High-Speed Execution Loop — with Dixon-Coles reweighting (Upgrade 1)
    agent_2_wins = 0
    sc_wins = 0
    distribution = {"0": 0, "1": 0, "2": 0, "3": 0, "4": 0, "5+": 0}
    scoreline_counts = {}

    for i in range(N):
        h = int(home_goals_raw[i])
        a = int(away_goals_raw[i])

        # === Dixon-Coles Acceptance-Rejection Sampling ===
        # CRITICAL: Only apply Dixon-Coles for STANDARD POISSON (variance <= 1.2).
        # Negative Binomial already accounts for goal correlation through its
        # overdispersion parameter. Applying Dixon-Coles on top of NegBinom
        # creates double-counting and artificially inflates 0-0 probability.
        if variance_multiplier <= CHAOS_THRESHOLD:
            # For low-scoring scorelines (h<=1, a<=1), apply the correlation adjustment.
            # dc_weight < 1.0: Poisson overestimates this scoreline → reject with probability (1 - dc_weight)
            # dc_weight > 1.0: Poisson underestimates this scoreline → accept always (no rejection)
            dc_weight = dixon_coles_weight(h, a, mu_h, mu_a, rho)

            # Only apply rejection if Poisson overweighted (dc_weight < 1.0)
            if dc_weight < 1.0:
                # Reject this sample with probability (1 - dc_weight)
                if np.random.random() > dc_weight:
                    # Rejected - resample once
                    h = int(sample_goals(home_xG, variance_multiplier, 1)[0])
                    a = int(sample_goals(away_xG, variance_multiplier, 1)[0])
            # If dc_weight >= 1.0, accept the sample as-is (Poisson underweighted or neutral)
        # If using NegBinom (variance > 1.2), skip Dixon-Coles entirely and accept raw sample

        # Evaluate Picks
        if evaluate_pick(h, a, agent_2_pick):
            agent_2_wins += 1
        if evaluate_pick(h, a, supreme_court_pick):
            sc_wins += 1

        # Build Goal Distribution
        total = h + a
        if total == 0: distribution["0"] += 1
        elif total == 1: distribution["1"] += 1
        elif total == 2: distribution["2"] += 1
        elif total == 3: distribution["3"] += 1
        elif total == 4: distribution["4"] += 1
        else: distribution["5+"] += 1

        # Tally Exact Scorelines
        score_str = f"{h}-{a}"
        scoreline_counts[score_str] = scoreline_counts.get(score_str, 0) + 1

    # 4. Final Math Calculations
    a2_win_rate = (agent_2_wins / N) * 100
    sc_win_rate = (sc_wins / N) * 100

    # Describe the engine used for transparency
    engine_mode = "NegBinom(Chaos)" if variance_multiplier > CHAOS_THRESHOLD else "Poisson(Standard)"

    # Dixon-Coles is only applied to Poisson, not NegBinom
    if variance_multiplier <= CHAOS_THRESHOLD:
        # Determine rho label based on value
        if rho == RHO_HIGH_SCORING:
            rho_label = "High-Scoring"
        elif rho == RHO_MISMATCH:
            rho_label = "Mismatch"
        else:
            rho_label = "Standard"
        dc_description = f" + Dixon-Coles {rho_label} (ρ={rho:.2f})"
    else:
        # NegBinom mode - Dixon-Coles not applied
        dc_description = ""

    audit_string = (
        f"[SIMULATION AUDIT: 10,000 Monte Carlo iterations. "
        f"Parameters: Home xG={home_xG:.2f}, Away xG={away_xG:.2f}, Variance={variance_multiplier:.2f}. "
        f"Engine: {engine_mode}{dc_description}. "
        f"Agent 2 Pick ({agent_2_pick}) Survival: {a2_win_rate:.1f}%. "
        f"Supreme Court Pick ({supreme_court_pick}) Survival: {sc_win_rate:.1f}%.]"
    )

    # Extract top 5 scorelines
    sorted_scores = sorted(scoreline_counts.items(), key=lambda item: item[1], reverse=True)[:5]
    top_scorelines = [{"score": score, "probability": (count / N) * 100} for score, count in sorted_scores]

    return {
        "audit_string": audit_string,
        "agent_2_win_rate": a2_win_rate,
        "supreme_court_win_rate": sc_win_rate,
        "distribution": distribution,
        "top_scorelines": top_scorelines
    }
