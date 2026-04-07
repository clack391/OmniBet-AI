# Rule 40 Simplification - Complete Fix

## Problem

Rule 40 had **two conflicting thresholds**:
- **Code enforcement**: N < 5 matches → Force NO BET
- **Supreme Court prompt**: N < 8 matches → Soft quarantine, restrict markets

This caused the LLM to incorrectly apply Rule 40 to matches with 5-7 games played (like Rajasthan with 6 matches), treating them as "early season" when they weren't.

## Solution

**Simplified to single threshold: N < 5 matches**

Rule 40 now ONLY triggers when a team has played fewer than 5 matches. This aligns the code enforcement with the LLM guidance.

## Changes Made

### 1. Rule Hierarchy (Line 1465-1467)
```python
# BEFORE:
- Rule 40: Early-Season Quarantine (N < 8 matches)

# AFTER:
- Rule 40: Early-Season Quarantine (N < 5 matches)
  → NOTE: The enforcement threshold is N < 5 (not 8). Matches with 5+ games have sufficient sample size.
```

### 2. Override Hierarchy (Line 2239)
```python
# BEFORE:
Rule 40 STRICTLY OVERRIDES... when the sample size for either team is fewer than 8 matches.
...they MUST NOT be triggered by a 3-7 match average...

# AFTER:
Rule 40 STRICTLY OVERRIDES... when the sample size for either team is fewer than 5 matches.
...they MUST NOT be triggered by a 1-4 match average...
```

### 3. Rule 40 Main Definition (Line 2193)
```python
# BEFORE:
If EITHER team has played fewer than 8 league matches...

# AFTER:
If EITHER team has played fewer than 5 league matches...
```

### 4. Forbidden Action Description (Line 2211-2214)
```python
# BEFORE:
When EITHER team has played fewer than 8 league matches, the Supreme Court is STRICTLY FORBIDDEN...
- FORBIDDEN: 'Over 2.5', 'Over 3.5' — require reliable mid-season bilateral offensive data that a <8-match sample cannot provide.

# AFTER:
When EITHER team has played fewer than 5 league matches, the Supreme Court is STRICTLY FORBIDDEN...
- FORBIDDEN: 'Over 2.5', 'Over 3.5' — require reliable mid-season bilateral offensive data that a <5-match sample cannot provide.
```

### 5. Supporting Rules Updated

**Rule 16 (Line 169):**
- Changed: "fewer than 8 rounds (Matchdays 1-7)" → "fewer than 5 rounds (Matchdays 1-4)"

**Rule 18 (Line 173):**
- Changed: "fewer than 8 matches" → "fewer than 5 matches"

**Rule 23 (Line 1753):**
- Changed: "fewer than 8 matches" → "fewer than 5 matches"

**Risk Manager Rule (Line 894):**
- Changed: "fewer than 8 matches" → "fewer than 5 matches"

## Impact on Current Predictions

### Before Fix:
| Match | Matches Played | Rule 40 Status | Behavior |
|-------|----------------|----------------|----------|
| Melbourne City | ~15+ | ❌ Not triggered | ✅ Normal analysis |
| Vizela U23 | Unknown | ⚠️ Claimed active | ⚠️ NO BET (correct but wrong rule cited) |
| Rajasthan | 6 matches | ❌ **INCORRECTLY** triggered | ❌ Forced downgrade |

### After Fix:
| Match | Matches Played | Rule 40 Status | Behavior |
|-------|----------------|----------------|----------|
| Melbourne City | ~15+ | ❌ Not triggered | ✅ Normal analysis |
| Vizela U23 | Check needed | ✅ Depends on actual count | ✅ Consistent logic |
| Rajasthan | 6 matches | ✅ **NOT triggered** (6 ≥ 5) | ✅ Normal analysis allowed |

## Expected Results After Fix

**Rajasthan vs Gokulam Kerala** (6 matches each):
- Rule 40 should **NOT** be triggered
- All goal markets should be allowed
- Pick should be based on actual tactical analysis, not forced structural floors
- "Rajasthan United Over 0.5 Goals" should be a valid pick if tactically sound

## Files Modified

- [src/rag/pipeline.py](src/rag/pipeline.py) - Multiple sections updated:
  - Lines 169: Rule 16
  - Lines 173: Rule 18
  - Lines 894: Risk Manager guidance
  - Lines 1465-1467: Rule hierarchy
  - Lines 1737: Rule 16 main definition
  - Lines 1753: Rule 23
  - Lines 2193: Rule 40 trigger
  - Lines 2207-2214: Rule 40 forbidden actions
  - Lines 2224: Rule 40 core logic
  - Lines 2239: Override hierarchy

## Testing Recommendation

Re-analyze **Rajasthan vs Gokulam Kerala** to verify:
1. ✅ Rule 40 warning should disappear
2. ✅ All goal markets should be available
3. ✅ Pick should be based on xG and tactical data, not forced floors

## Summary

**Old behavior**: Matches with 5-7 games played were treated as "early season" with restricted markets

**New behavior**: Only matches with < 5 games trigger Rule 40, all others get normal analysis

This simplification eliminates the confusion between code enforcement (N < 5) and LLM guidance (N < 8), making Rule 40 consistent and predictable.
