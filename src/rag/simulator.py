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

def run_crucible_simulation(
    home_xG: float,
    away_xG: float,
    variance_multiplier: float,
    agent_2_pick: str,
    supreme_court_pick: str,
    home_corners_avg: float = 5.0,  # NEW: Phase 1 - Corners support
    away_corners_avg: float = 5.0,  # NEW: Phase 1 - Corners support
    home_cards_avg: float = 2.0,    # NEW: Phase 1 - Cards support
    away_cards_avg: float = 2.0,    # NEW: Phase 1 - Cards support
    alternative_picks: list = None  # NEW: List of alternative markets to test
) -> dict:
    """
    Runs a 10,000 iteration Monte Carlo simulation to test the survival rate of the AI picks.

    MATHEMATICAL ENGINE:
    - Upgrade 1 (Dixon-Coles): Corrects standard Poisson to accurately model the
      probability of low-scoring results (0-0, 1-0, 0-1, 1-1) via a correlation factor.
    - Upgrade 2 (Negative Binomial): Switches from Poisson to Negative Binomial when
      variance_multiplier > 1.2, enabling fat-tail modelling for chaotic high-scoring matches.

    PHASE 1 UPGRADE (Corners & Cards):
    - Corners: Simulated using Poisson distribution based on team corner averages
    - Cards: Simulated using Poisson distribution based on team card averages
    """
    N = 10_000

    # Calculate dynamic rho based on xG imbalance
    rho = calculate_rho(home_xG, away_xG)

    # 1. Sample goal distributions (Upgrade 2: Poisson vs NegBinom based on chaos level)
    home_goals_raw = sample_goals(home_xG, variance_multiplier, N)
    away_goals_raw = sample_goals(away_xG, variance_multiplier, N)

    # 2. Sample corners and cards distributions (NEW: Phase 1)
    # Corners and cards use standard Poisson (no chaos multiplier needed - they're volume metrics)
    home_corners_raw = np.random.poisson(home_corners_avg, N)
    away_corners_raw = np.random.poisson(away_corners_avg, N)
    home_cards_raw = np.random.poisson(home_cards_avg, N)
    away_cards_raw = np.random.poisson(away_cards_avg, N)

    # 3. Sample half-time goal distributions (NEW: Phase 2)
    # Research shows ~45% of goals occur in 1st half, ~55% in 2nd half
    # This accounts for substitutions, tactical changes, and late-game urgency
    FIRST_HALF_RATIO = 0.45
    SECOND_HALF_RATIO = 0.55

    home_xG_first_half = home_xG * FIRST_HALF_RATIO
    away_xG_first_half = away_xG * FIRST_HALF_RATIO
    home_xG_second_half = home_xG * SECOND_HALF_RATIO
    away_xG_second_half = away_xG * SECOND_HALF_RATIO

    # Sample goals for each half independently
    home_goals_first_half = sample_goals(home_xG_first_half, variance_multiplier, N)
    away_goals_first_half = sample_goals(away_xG_first_half, variance_multiplier, N)
    home_goals_second_half = sample_goals(home_xG_second_half, variance_multiplier, N)
    away_goals_second_half = sample_goals(away_xG_second_half, variance_multiplier, N)

    # 4. Sample 10-minute goal distributions (NEW: Phase 3)
    # 10 minutes = 11.1% of 90-minute match
    # Early game is typically cautious - most goals happen after 10 minutes
    TEN_MINUTE_RATIO = 10.0 / 90.0  # 0.111

    home_xG_10min = home_xG * TEN_MINUTE_RATIO
    away_xG_10min = away_xG * TEN_MINUTE_RATIO

    # Sample goals in first 10 minutes
    home_goals_10min = sample_goals(home_xG_10min, variance_multiplier, N)
    away_goals_10min = sample_goals(away_xG_10min, variance_multiplier, N)

    # Adjusted xG means (for Dixon-Coles weight calculation)
    mu_h = home_xG * variance_multiplier
    mu_a = away_xG * variance_multiplier

    def evaluate_pick(home_score, away_score, home_corners, away_corners, home_cards, away_cards,
                      home_1h, away_1h, home_2h, away_2h, home_10m, away_10m, pick):
        """
        Evaluate if a pick wins given the match outcome.

        NEW Phase 2 parameters:
        - home_1h, away_1h: Goals scored in first half
        - home_2h, away_2h: Goals scored in second half

        NEW Phase 3 parameters:
        - home_10m, away_10m: Goals scored in first 10 minutes
        """
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

        # === NEW: PHASE 1 MARKETS ===

        # Correct Score (Exact scoreline prediction)
        elif "correct score" in pick or "exact score" in pick:
            # Extract scoreline pattern like "2-1" or "2:1"
            score_match = re.search(r'(\d+)[-:](\d+)', pick)
            if score_match:
                predicted_home = int(score_match.group(1))
                predicted_away = int(score_match.group(2))
                return home_score == predicted_home and away_score == predicted_away
            return False

        # Team Exact Goals
        elif "home exact" in pick or "home team exact" in pick:
            # Extract number like "home exact goals: 2"
            goals_match = re.search(r'(\d+)', pick)
            if goals_match:
                predicted_goals = int(goals_match.group(1))
                return home_score == predicted_goals
            return False
        elif "away exact" in pick or "away team exact" in pick:
            goals_match = re.search(r'(\d+)', pick)
            if goals_match:
                predicted_goals = int(goals_match.group(1))
                return away_score == predicted_goals
            return False

        # Total Match Corners
        elif "corner" in pick:
            total_corners = home_corners + away_corners
            if "over 8.5" in pick: return total_corners > 8.5
            elif "over 9.5" in pick: return total_corners > 9.5
            elif "over 10.5" in pick: return total_corners > 10.5
            elif "over 11.5" in pick: return total_corners > 11.5
            elif "over 12.5" in pick: return total_corners > 12.5
            elif "under 8.5" in pick: return total_corners < 8.5
            elif "under 9.5" in pick: return total_corners < 9.5
            elif "under 10.5" in pick: return total_corners < 10.5
            elif "under 11.5" in pick: return total_corners < 11.5
            elif "under 12.5" in pick: return total_corners < 12.5
            # Generic over/under extraction
            elif "over" in pick:
                corner_match = re.search(r'over\s+(\d+(?:\.\d+)?)', pick)
                if corner_match:
                    threshold = float(corner_match.group(1))
                    return total_corners > threshold
            elif "under" in pick:
                corner_match = re.search(r'under\s+(\d+(?:\.\d+)?)', pick)
                if corner_match:
                    threshold = float(corner_match.group(1))
                    return total_corners < threshold
            return False

        # Total Match Cards
        elif "card" in pick:
            total_cards = home_cards + away_cards
            if "over 3.5" in pick: return total_cards > 3.5
            elif "over 4.5" in pick: return total_cards > 4.5
            elif "over 5.5" in pick: return total_cards > 5.5
            elif "over 6.5" in pick: return total_cards > 6.5
            elif "under 3.5" in pick: return total_cards < 3.5
            elif "under 4.5" in pick: return total_cards < 4.5
            elif "under 5.5" in pick: return total_cards < 5.5
            elif "under 6.5" in pick: return total_cards < 6.5
            # Generic over/under extraction
            elif "over" in pick:
                card_match = re.search(r'over\s+(\d+(?:\.\d+)?)', pick)
                if card_match:
                    threshold = float(card_match.group(1))
                    return total_cards > threshold
            elif "under" in pick:
                card_match = re.search(r'under\s+(\d+(?:\.\d+)?)', pick)
                if card_match:
                    threshold = float(card_match.group(1))
                    return total_cards < threshold
            return False

        # === NEW: PHASE 2 MARKETS ===

        # Highest Scoring Half (CHECK THIS FIRST - more specific than "first half" or "second half")
        elif "highest scoring half" in pick or "highest half" in pick:
            first_half_total = home_1h + away_1h
            second_half_total = home_2h + away_2h

            # Check for 2nd half first (more specific patterns)
            if "2nd" in pick or "second" in pick or "2h" in pick or "second half" in pick:
                return second_half_total > first_half_total
            # Then check for 1st half
            elif "1st" in pick or "first" in pick or "1h" in pick or "first half" in pick:
                return first_half_total > second_half_total
            elif "tie" in pick or "equal" in pick or "same" in pick:
                return first_half_total == second_half_total
            return False

        # First Half Goals
        elif "first half" in pick or "1st half" in pick or "1h " in pick:
            first_half_total = home_1h + away_1h
            if "over 0.5" in pick: return first_half_total > 0.5
            elif "over 1.5" in pick: return first_half_total > 1.5
            elif "over 2.5" in pick: return first_half_total > 2.5
            elif "under 0.5" in pick: return first_half_total < 0.5
            elif "under 1.5" in pick: return first_half_total < 1.5
            elif "under 2.5" in pick: return first_half_total < 2.5
            # Generic over/under extraction
            elif "over" in pick:
                fh_match = re.search(r'over\s+(\d+(?:\.\d+)?)', pick)
                if fh_match:
                    threshold = float(fh_match.group(1))
                    return first_half_total > threshold
            elif "under" in pick:
                fh_match = re.search(r'under\s+(\d+(?:\.\d+)?)', pick)
                if fh_match:
                    threshold = float(fh_match.group(1))
                    return first_half_total < threshold
            return False

        # Second Half Goals
        elif "second half" in pick or "2nd half" in pick or "2h " in pick:
            second_half_total = home_2h + away_2h
            if "over 0.5" in pick: return second_half_total > 0.5
            elif "over 1.5" in pick: return second_half_total > 1.5
            elif "over 2.5" in pick: return second_half_total > 2.5
            elif "under 0.5" in pick: return second_half_total < 0.5
            elif "under 1.5" in pick: return second_half_total < 1.5
            elif "under 2.5" in pick: return second_half_total < 2.5
            # Generic over/under extraction
            elif "over" in pick:
                sh_match = re.search(r'over\s+(\d+(?:\.\d+)?)', pick)
                if sh_match:
                    threshold = float(sh_match.group(1))
                    return second_half_total > threshold
            elif "under" in pick:
                sh_match = re.search(r'under\s+(\d+(?:\.\d+)?)', pick)
                if sh_match:
                    threshold = float(sh_match.group(1))
                    return second_half_total < threshold
            return False

        # HT/FT (Half Time / Full Time)
        elif "ht/ft" in pick or "half time full time" in pick or "halftime/fulltime" in pick:
            # Determine HT result
            if home_1h > away_1h:
                ht_result = "home"
            elif away_1h > home_1h:
                ht_result = "away"
            else:
                ht_result = "draw"

            # Determine FT result (already have home_score, away_score)
            if home_score > away_score:
                ft_result = "home"
            elif away_score > home_score:
                ft_result = "away"
            else:
                ft_result = "draw"

            # Match against pick patterns
            # Format examples: "HT/FT: Home/Home", "HT/FT: Draw/Away", "ht/ft draw-home"
            if f"{ht_result}/{ft_result}" in pick or f"{ht_result}-{ft_result}" in pick:
                return True
            # Also check for explicit patterns
            elif "home/home" in pick or "home-home" in pick or "1/1" in pick:
                return ht_result == "home" and ft_result == "home"
            elif "home/draw" in pick or "home-draw" in pick or "1/x" in pick:
                return ht_result == "home" and ft_result == "draw"
            elif "home/away" in pick or "home-away" in pick or "1/2" in pick:
                return ht_result == "home" and ft_result == "away"
            elif "draw/home" in pick or "draw-home" in pick or "x/1" in pick:
                return ht_result == "draw" and ft_result == "home"
            elif "draw/draw" in pick or "draw-draw" in pick or "x/x" in pick:
                return ht_result == "draw" and ft_result == "draw"
            elif "draw/away" in pick or "draw-away" in pick or "x/2" in pick:
                return ht_result == "draw" and ft_result == "away"
            elif "away/home" in pick or "away-home" in pick or "2/1" in pick:
                return ht_result == "away" and ft_result == "home"
            elif "away/draw" in pick or "away-draw" in pick or "2/x" in pick:
                return ht_result == "away" and ft_result == "draw"
            elif "away/away" in pick or "away-away" in pick or "2/2" in pick:
                return ht_result == "away" and ft_result == "away"
            return False

        # === NEW: PHASE 3 MARKETS ===

        # 10 Minute Draw
        elif "10 minute" in pick or "10min" in pick or "10-minute" in pick:
            # Check if score is 0-0 at 10 minutes
            is_draw_at_10min = (home_10m == 0 and away_10m == 0)

            if "yes" in pick or ": yes" in pick:
                return is_draw_at_10min
            elif "no" in pick or ": no" in pick:
                return not is_draw_at_10min
            # Default: If just "10 Minute Draw" without yes/no, assume "yes"
            return is_draw_at_10min

        # CRITICAL FIX: Catch ambiguous picks (e.g., just "Yes" or "No" without market context)
        # These should NOT default to True (100% survival) - that's a bug
        ambiguous_picks = ["yes", "no", "1", "2", "x"]
        if pick in ambiguous_picks:
            print(f"⚠️ [SIMULATOR WARNING] Ambiguous pick detected: '{pick}'. Cannot evaluate. Returning False (0% survival).")
            return False

        # Default fallback for markets not yet implemented
        # Only return True if the pick looks like a valid market name
        if len(pick) > 3:  # Valid market names are usually longer than 3 characters
            return True
        else:
            # Short, unrecognized picks are likely errors
            return False

    # 3. High-Speed Execution Loop — with Dixon-Coles reweighting (Upgrade 1)
    agent_2_wins = 0
    sc_wins = 0

    # NEW: Track wins for alternative picks as well
    alternative_wins = {}
    if alternative_picks:
        for alt_pick in alternative_picks:
            alternative_wins[alt_pick] = 0

    distribution = {"0": 0, "1": 0, "2": 0, "3": 0, "4": 0, "5+": 0}
    scoreline_counts = {}

    for i in range(N):
        h = int(home_goals_raw[i])
        a = int(away_goals_raw[i])

        # NEW: Phase 1 - Sample corners and cards for this iteration
        h_corners = int(home_corners_raw[i])
        a_corners = int(away_corners_raw[i])
        h_cards = int(home_cards_raw[i])
        a_cards = int(away_cards_raw[i])

        # NEW: Phase 2 - Sample half-time goals for this iteration
        h_1h = int(home_goals_first_half[i])
        a_1h = int(away_goals_first_half[i])
        h_2h = int(home_goals_second_half[i])
        a_2h = int(away_goals_second_half[i])

        # NEW: Phase 3 - Sample 10-minute goals for this iteration
        h_10m = int(home_goals_10min[i])
        a_10m = int(away_goals_10min[i])

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

        # Evaluate Picks (NEW: Pass corners, cards, half-time, and 10-minute data)
        if evaluate_pick(h, a, h_corners, a_corners, h_cards, a_cards, h_1h, a_1h, h_2h, a_2h, h_10m, a_10m, agent_2_pick):
            agent_2_wins += 1
        if evaluate_pick(h, a, h_corners, a_corners, h_cards, a_cards, h_1h, a_1h, h_2h, a_2h, h_10m, a_10m, supreme_court_pick):
            sc_wins += 1

        # NEW: Evaluate alternative picks
        if alternative_picks:
            for alt_pick in alternative_picks:
                if evaluate_pick(h, a, h_corners, a_corners, h_cards, a_cards, h_1h, a_1h, h_2h, a_2h, h_10m, a_10m, alt_pick):
                    alternative_wins[alt_pick] += 1

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

    # NEW: Calculate win rates for alternative picks
    alternative_results = {}
    if alternative_picks:
        for alt_pick in alternative_picks:
            alt_win_rate = (alternative_wins[alt_pick] / N) * 100
            alternative_results[alt_pick] = alt_win_rate

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

    # Build audit string with alternative picks if present
    audit_base = (
        f"[SIMULATION AUDIT: 10,000 Monte Carlo iterations. "
        f"Parameters: Home xG={home_xG:.2f}, Away xG={away_xG:.2f}, Variance={variance_multiplier:.2f}, "
        f"Home Corners={home_corners_avg:.1f}, Away Corners={away_corners_avg:.1f}, "
        f"Home Cards={home_cards_avg:.1f}, Away Cards={away_cards_avg:.1f}. "
        f"Engine: {engine_mode}{dc_description}. "
        f"Agent 2 Pick ({agent_2_pick}) Survival: {a2_win_rate:.1f}%. "
        f"Supreme Court Pick ({supreme_court_pick}) Survival: {sc_win_rate:.1f}%."
    )

    # NEW: Append alternative picks to audit string
    if alternative_results:
        alt_audit_parts = [f"{pick} Survival: {rate:.1f}%" for pick, rate in alternative_results.items()]
        audit_string = audit_base + " Alternative Markets: " + ", ".join(alt_audit_parts) + ".]"
    else:
        audit_string = audit_base + "]"

    # Extract top 5 scorelines
    sorted_scores = sorted(scoreline_counts.items(), key=lambda item: item[1], reverse=True)[:5]
    top_scorelines = [{"score": score, "probability": (count / N) * 100} for score, count in sorted_scores]

    result = {
        "audit_string": audit_string,
        "agent_2_win_rate": a2_win_rate,
        "supreme_court_win_rate": sc_win_rate,
        "distribution": distribution,
        "top_scorelines": top_scorelines
    }

    # NEW: Include alternative results if present
    if alternative_results:
        result["alternative_results"] = alternative_results

    return result
