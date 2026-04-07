# Validated Alternative Markets Implementation

## Overview

This document describes the implementation of the **Hybrid Approach: "Validated Alternative Markets"** system, which allows the Supreme Court to suggest 2-3 alternative markets, simulate ALL of them, and let the AI Accumulator Builder choose the safest option with accurate survival rates.

---

## Problem Statement

### Original Issue:
When the AI Accumulator Builder wanted to choose a different market than what the Supreme Court picked (e.g., "Over 0.5 Goals" instead of "Over 1.5 Goals"), it did NOT have an accurate survival percentage for that alternative market.

**Example:**
- Supreme Court picks: "Over 1.5 Goals" (85.4% survival)
- AI Accumulator sees Top 5 Scorelines: All have 2+ goals
- AI wants to choose: "Over 0.5 Goals" (safer - only loses on 0-0)
- **Problem**: No survival rate calculated for "Over 0.5"
- **Options were**:
  1. Stick with Supreme Court's exact pick only
  2. Re-run simulation (expensive)
  3. Estimate manually (unreliable)

---

## Solution: Validated Alternative Markets

### How It Works:

1. **Supreme Court suggests 2-3 alternative markets** from the SAME correlation bucket
2. **Simulation tests ALL picks** (Agent 2 + Supreme Court + 2-3 alternatives)
3. **AI Accumulator Builder sees all survival rates** and chooses the safest option

### Benefits:
- ✅ All survival rates are mathematically accurate (no estimation)
- ✅ AI can optimize safety (picks best from validated options)
- ✅ Not too expensive (only tests 3-5 picks total, not all 17 markets)
- ✅ Maintains "NO NARRATIVE" rule (pure math)
- ✅ Same correlation bucket ensures tactical coherence

---

## Implementation Details

### 1. Supreme Court Prompt Changes

**File**: `src/rag/pipeline.py` (lines 1660-1756)

**Added Field**: `validated_alternative_markets`

```json
{
  "Arbiter_Safe_Pick": {
    "market": "Match_Goals",
    "tip": "Over 1.5 Goals",
    "confidence": 88,
    "odds": 1.50
  },
  "validated_alternative_markets": [
    {
      "market": "Match_Goals",
      "tip": "Over 0.5 Goals",
      "confidence": 95,
      "odds": 1.15,
      "structural_reasoning": "Safer than Over 1.5 (only loses on 0-0)"
    },
    {
      "market": "Match_Goals",
      "tip": "BTTS Yes",
      "confidence": 82,
      "odds": 1.60,
      "structural_reasoning": "Similar safety to Over 1.5 (requires both teams to score)"
    },
    {
      "market": "Match_Goals",
      "tip": "Over 2.5 Goals",
      "confidence": 72,
      "odds": 2.10,
      "structural_reasoning": "Riskier but higher EV for Tier 2/3"
    }
  ]
}
```

**New Rule 3.5** (lines 1731-1756): "VALIDATED ALTERNATIVE MARKETS MANDATE"
- Supreme Court MUST provide 1-3 alternatives from the SAME BUCKET
- Arrange by safety gradient (safest → riskiest)
- Provide structural reasoning for each

---

### 2. Simulator Changes

**File**: `src/rag/simulator.py`

#### A. Function Signature Update (line 124)
```python
def run_crucible_simulation(
    home_xG: float,
    away_xG: float,
    variance_multiplier: float,
    agent_2_pick: str,
    supreme_court_pick: str,
    home_corners_avg: float = 5.0,
    away_corners_avg: float = 5.0,
    home_cards_avg: float = 2.0,
    away_cards_avg: float = 2.0,
    alternative_picks: list = None  # NEW: List of alternative markets to test
) -> dict:
```

#### B. Win Tracking for Alternatives (lines 475-479)
```python
# NEW: Track wins for alternative picks as well
alternative_wins = {}
if alternative_picks:
    for alt_pick in alternative_picks:
        alternative_wins[alt_pick] = 0
```

#### C. Evaluation Loop Update (lines 531-535)
```python
# NEW: Evaluate alternative picks
if alternative_picks:
    for alt_pick in alternative_picks:
        if evaluate_pick(h, a, h_corners, a_corners, h_cards, a_cards, h_1h, a_1h, h_2h, a_2h, h_10m, a_10m, alt_pick):
            alternative_wins[alt_pick] += 1
```

#### D. Calculate Alternative Win Rates (lines 554-559)
```python
# NEW: Calculate win rates for alternative picks
alternative_results = {}
if alternative_picks:
    for alt_pick in alternative_picks:
        alt_win_rate = (alternative_wins[alt_pick] / N) * 100
        alternative_results[alt_pick] = alt_win_rate
```

#### E. Enhanced Audit String (lines 589-594)
```python
# NEW: Append alternative picks to audit string
if alternative_results:
    alt_audit_parts = [f"{pick} Survival: {rate:.1f}%" for pick, rate in alternative_results.items()]
    audit_string = audit_base + " Alternative Markets: " + ", ".join(alt_audit_parts) + ".]"
else:
    audit_string = audit_base + "]"
```

#### F. Return Alternative Results (lines 608-612)
```python
# NEW: Include alternative results if present
if alternative_results:
    result["alternative_results"] = alternative_results

return result
```

---

### 3. Pipeline Changes

**File**: `src/rag/pipeline.py` (lines 2998-3025)

#### A. Extract Alternative Markets (lines 2998-3005)
```python
# NEW: Extract alternative markets from Supreme Court response
alternative_markets_list = []
validated_alternatives = parsed.get("validated_alternative_markets", [])
if validated_alternatives and isinstance(validated_alternatives, list):
    for alt_market in validated_alternatives:
        if isinstance(alt_market, dict) and "tip" in alt_market:
            alternative_markets_list.append(alt_market["tip"])
    print(f"🔍 [Alternative Markets] Testing {len(alternative_markets_list)} additional picks: {alternative_markets_list}")
```

#### B. Pass to Simulator (line 3017)
```python
sim_res = run_crucible_simulation(
    home_xG=h_xg,
    away_xG=a_xg,
    variance_multiplier=v_mult,
    agent_2_pick=a2_pick,
    supreme_court_pick=parsed.get("Arbiter_Safe_Pick", {}).get("tip", "N/A"),
    home_corners_avg=home_corners,
    away_corners_avg=away_corners,
    home_cards_avg=home_cards,
    away_cards_avg=away_cards,
    alternative_picks=alternative_markets_list if alternative_markets_list else None  # NEW
)
```

#### C. Store Alternative Results (lines 3023-3025)
```python
# NEW: Store alternative results if present
if "alternative_results" in sim_res:
    parsed["alternative_results"] = sim_res["alternative_results"]
```

---

### 4. AI Accumulator Builder Changes

**File**: `src/rag/pipeline.py` (lines 694-716)

**New Section**: "VALIDATED ALTERNATIVE MARKETS (MULTI-PICK OPTIMIZATION)"

**Mandate**:
1. Check each match for `alternative_results` field
2. Compare survival rates of all validated options
3. Choose the market with HIGHEST survival rate
4. Update `chosen_tip` if selecting an alternative
5. Place in appropriate tier based on final survival rate

**Example**:
```
Match data:
- Supreme Court Pick: "Over 1.5 Goals" (85.4%)
- Alternative Results: {"Over 0.5 Goals": 94.2%, "BTTS Yes": 81.3%, "Over 2.5 Goals": 73.1%}

AI Accumulator Builder's Action:
- Chooses: "Over 0.5 Goals" (94.2% - highest survival)
- Tier: TIER 1 (exceeds 85% threshold)
- Reasoning: "Over 0.5 Goals upgraded from Supreme Court's validated alternatives (94.2% vs 85.4%)"
```

---

## Example Workflow

### Scenario: İmişli FK vs Turan Tovuz

#### Step 1: Supreme Court Decides
```json
{
  "Arbiter_Safe_Pick": {
    "tip": "Under 3.5 Goals",
    "market": "Match_Goals"
  },
  "validated_alternative_markets": [
    {"tip": "Over 0.5 Goals", "structural_reasoning": "Wider floor - only loses on 0-0"},
    {"tip": "Under 4.5 Goals", "structural_reasoning": "Wider ceiling than Under 3.5"},
    {"tip": "First Half Under 0.5 Goals", "structural_reasoning": "Cagey start expected"}
  ]
}
```

#### Step 2: Simulation Runs (10,000 iterations)
```
Testing 5 picks:
1. Agent 2: "Under 2.5 Goals"
2. Supreme Court: "Under 3.5 Goals"
3. Alternative 1: "Over 0.5 Goals"
4. Alternative 2: "Under 4.5 Goals"
5. Alternative 3: "First Half Under 0.5 Goals"

Results:
- Agent 2 Pick (Under 2.5 Goals) Survival: 66.1%
- Supreme Court Pick (Under 3.5 Goals) Survival: 84.7%
- Over 0.5 Goals Survival: 91.3%
- Under 4.5 Goals Survival: 96.8%
- First Half Under 0.5 Goals Survival: 88.2%
```

#### Step 3: AI Accumulator Builder Chooses
```json
{
  "picks": [
    {
      "chosen_tip": "Under 4.5 Goals",
      "survival_rate": 96.8,
      "tier": "TIER 1: MASTER ACCUMULATOR",
      "mathematical_reason": "Under 4.5 Goals upgraded from Supreme Court's validated alternatives (96.8% vs 84.7%)",
      "market": "Match_Goals"
    }
  ]
}
```

**Result**: AI automatically selected the safest validated option (Under 4.5) instead of Supreme Court's pick (Under 3.5), increasing survival from 84.7% → 96.8%!

---

## Key Advantages

### 1. Accuracy
- ✅ All survival rates are from actual 10,000-iteration Monte Carlo simulations
- ✅ No manual estimation or guessing
- ✅ No circular logic or "cheating"

### 2. Optimization
- ✅ AI can find safer alternatives automatically
- ✅ Can move picks from Tier 2 → Tier 1 (e.g., 84.7% → 96.8%)
- ✅ Better accumulator survival rates

### 3. Performance
- ✅ Only tests 3-5 picks per match (not all 17 markets)
- ✅ Single simulation call (no re-runs needed)
- ✅ Fast enough for real-time use

### 4. Tactical Coherence
- ✅ All alternatives from SAME correlation bucket
- ✅ Maintains Supreme Court's tactical vision
- ✅ No random market hopping

---

## Expected Impact

### Before This Feature:
- Supreme Court picks: "Over 1.5 Goals" (85.4%)
- AI Accumulator: Stuck with 85.4% (Tier 1, barely qualified)
- User gets: Medium-safety accumulator

### After This Feature:
- Supreme Court picks: "Over 1.5 Goals" (85.4%)
- Alternatives tested: "Over 0.5" (94.2%), "BTTS Yes" (81.3%), "Over 2.5" (73.1%)
- AI Accumulator: Chooses "Over 0.5 Goals" (94.2%)
- User gets: High-safety accumulator (+8.8pp improvement)

### Estimated Improvement:
- **+5-10% better Tier 1 accumulator survival rates**
- **+10-15% more picks qualify for Tier 1** (alternatives can push picks over 85% threshold)
- **+3-5% better overall portfolio performance** (smarter market selection)

---

## Testing Checklist

### Manual Testing Steps:

1. **Run a prediction with Supreme Court**
   - Check that `validated_alternative_markets` field is populated
   - Should have 1-3 alternatives with structural reasoning

2. **Check simulation output**
   - Verify audit string includes alternative markets
   - Confirm `alternative_results` field in response
   - Example: `{"Over 0.5 Goals": 94.2, "BTTS Yes": 81.3}`

3. **Generate AI Accumulator**
   - Verify AI Accumulator Builder sees alternative results
   - Check if it selects a different market than Supreme Court
   - Confirm survival rate matches the chosen alternative

4. **Test edge cases**
   - Match with NO alternatives (should work normally)
   - Match where Supreme Court's pick is already the safest
   - Match where alternative moves pick from Tier 2 → Tier 1

### Expected Console Output:
```
📊 [Phase 1] Corners: Home=5.0, Away=5.0. Cards: Home=2.0, Away=1.7
🔍 [Alternative Markets] Testing 3 additional picks: ['Over 0.5 Goals', 'Under 4.5 Goals', 'First Half Under 0.5 Goals']
```

### Expected Simulation Audit:
```
[SIMULATION AUDIT: 10,000 Monte Carlo iterations. Parameters: Home xG=0.75, Away xG=1.28, Variance=1.00, Home Corners=5.0, Away Corners=5.0, Home Cards=2.0, Away Cards=1.7. Engine: Poisson(Standard) + Dixon-Coles Mismatch (ρ=-0.10). Agent 2 Pick (Under 2.5 Goals) Survival: 66.1%. Supreme Court Pick (Under 3.5 Goals) Survival: 84.7%. Alternative Markets: Over 0.5 Goals Survival: 91.3%, Under 4.5 Goals Survival: 96.8%, First Half Under 0.5 Goals Survival: 88.2%.]
```

---

## Files Modified

| File | Lines Changed | Description |
|------|---------------|-------------|
| `src/rag/pipeline.py` | 1660-1756 | Added `validated_alternative_markets` to Supreme Court JSON output + Rule 3.5 |
| `src/rag/pipeline.py` | 2998-3025 | Extract alternative markets and pass to simulator |
| `src/rag/pipeline.py` | 694-716 | Updated AI Accumulator Builder to use alternative results |
| `src/rag/simulator.py` | 124 | Added `alternative_picks` parameter to function signature |
| `src/rag/simulator.py` | 475-479 | Initialize win tracking for alternative picks |
| `src/rag/simulator.py` | 531-535 | Evaluate alternative picks in simulation loop |
| `src/rag/simulator.py` | 554-559 | Calculate win rates for alternatives |
| `src/rag/simulator.py` | 589-594 | Add alternatives to audit string |
| `src/rag/simulator.py` | 608-612 | Return alternative results in response |

---

## Backward Compatibility

✅ **Fully backward compatible**:
- If Supreme Court doesn't provide `validated_alternative_markets`, system works normally
- `alternative_picks` parameter defaults to `None`
- Old predictions without alternatives will still process correctly
- AI Accumulator Builder gracefully handles missing `alternative_results` field

---

## Next Steps

1. ✅ Implementation complete
2. ⏳ Test with real predictions
3. ⏳ Monitor AI Accumulator Builder's alternative selection rate
4. ⏳ Analyze improvement in Tier 1 accumulator survival rates
5. ⏳ Tune Supreme Court's alternative market selection logic based on results

---

## Implementation Status

**✅ COMPLETED** - All 4 components implemented:
1. ✅ Supreme Court generates alternative markets
2. ✅ Simulator tests all alternatives
3. ✅ Pipeline passes alternatives to simulator
4. ✅ AI Accumulator Builder optimizes pick selection

**Ready for testing with real predictions.**
