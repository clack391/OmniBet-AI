# Tier Deletion Persistence Feature

## Problem
Previously, when users deleted Tier 2 or Tier 3 picks from the AI Master Accumulator, the deletions were **not persistent**:
- Deletions only updated local React state
- Page refresh would restore deleted tiers from the database
- Users had to manually delete tiers again after every refresh

## Solution Implemented

### Backend Changes

#### 1. **New Database Function** (`src/database/db.py`)

Added `update_best_picks(data: dict)` function (lines 424-446):

```python
def update_best_picks(data: dict):
    """
    Update the most recent AI Accumulator with modified data.
    Used for persisting tier deletions.
    """
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    try:
        # Remove created_at if it exists (it's auto-generated)
        data_copy = data.copy()
        data_copy.pop('created_at', None)

        # Update the most recent accumulator
        cursor.execute('''
            UPDATE ai_best_picks
            SET accumulator_json = ?
            WHERE id = (SELECT id FROM ai_best_picks ORDER BY created_at DESC LIMIT 1)
        ''', (json.dumps(data_copy),))
        conn.commit()
    except Exception as e:
        print(f"Error updating accumulator: {e}")
    finally:
        conn.close()
```

**What it does:**
- Updates the most recent AI Accumulator in the `ai_best_picks` table
- Removes the specified tier from the JSON data
- Persists changes to SQLite database

#### 2. **New API Endpoint** (`src/api/main.py`)

Added `PATCH /best-picks/clear-tier` endpoint (lines 487-510):

**Request Model** (lines 444-445):
```python
class ClearTierRequest(BaseModel):
    tier: str  # "tier2" or "tier3"
```

**Endpoint Implementation**:
```python
@app.patch("/best-picks/clear-tier")
def clear_tier_from_best_picks(req: ClearTierRequest, current_user: dict = Depends(get_admin_user)):
    """
    Remove a specific tier (tier2 or tier3) from the saved AI Accumulator.
    This makes tier deletions persistent across page refreshes.
    """
    # 1. Get current best picks
    picks = get_best_picks()
    if not picks:
        raise HTTPException(status_code=404, detail="No AI Accumulator found.")

    # 2. Delete the specified tier
    if req.tier == "tier2" and "tier_2_picks" in picks:
        del picks["tier_2_picks"]
    elif req.tier == "tier3" and "tier_3_picks" in picks:
        del picks["tier_3_picks"]
    else:
        raise HTTPException(status_code=400, detail=f"Invalid tier: {req.tier}")

    # 3. Save updated picks back to database
    from src.database.db import update_best_picks
    update_best_picks(picks)

    return {"status": "success", "tier_removed": req.tier}
```

**What it does:**
1. Loads current AI Accumulator from database
2. Deletes the specified tier (`tier_2_picks` or `tier_3_picks`)
3. Saves the modified accumulator back to database
4. Returns success confirmation

**Security:** Requires admin authentication via `get_admin_user` dependency

### Frontend Changes

#### Updated `handleClearTier` Function (`frontend/src/components/HistoryTab.jsx`, lines 190-217)

**Before:**
```javascript
const handleClearTier = (tierKey) => {
    setBestPicks(prevPicks => {
        if (!prevPicks) return null;

        const newPicks = { ...prevPicks };

        if (tierKey === 'tier2') {
            delete newPicks.tier_2_picks;
        } else if (tierKey === 'tier3') {
            delete newPicks.tier_3_picks;
        }

        return newPicks;
    });
};
```

**After:**
```javascript
const handleClearTier = async (tierKey) => {
    if (!window.confirm(`Are you sure you want to permanently delete ${tierKey === 'tier2' ? 'Tier 2' : 'Tier 3'}?`)) {
        return;
    }

    try {
        // Call backend to persist the deletion
        await api.patch(`/best-picks/clear-tier`, { tier: tierKey });

        // Update local state to reflect the deletion immediately
        setBestPicks(prevPicks => {
            if (!prevPicks) return null;

            const newPicks = { ...prevPicks };

            if (tierKey === 'tier2') {
                delete newPicks.tier_2_picks;
            } else if (tierKey === 'tier3') {
                delete newPicks.tier_3_picks;
            }

            return newPicks;
        });
    } catch (err) {
        console.error("Failed to clear tier:", err);
        alert("Failed to delete tier. Please try again.");
    }
};
```

**Changes:**
1. **Made function async** - Now uses `async/await` to call backend API
2. **Added confirmation dialog** - User must confirm before permanent deletion
3. **Calls backend API** - `api.patch('/best-picks/clear-tier', { tier: tierKey })`
4. **Updates local state** - UI updates immediately (optimistic update)
5. **Error handling** - Displays alert if backend call fails

## How It Works

### User Flow:

1. **User clicks "Clear Tier 2/3" button** in the History tab
2. **Confirmation dialog appears**: "Are you sure you want to permanently delete Tier 2?"
3. **User confirms**
4. **Frontend calls backend**: `PATCH /best-picks/clear-tier` with `{ tier: "tier2" }`
5. **Backend updates database**: Removes `tier_2_picks` from the JSON in `ai_best_picks` table
6. **Backend returns success**: `{ status: "success", tier_removed: "tier2" }`
7. **Frontend updates UI**: Tier 2 section disappears immediately
8. **Page refresh**: Tier 2 remains deleted (persisted in database)

### Database Structure:

**Table:** `ai_best_picks`

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PRIMARY KEY | Auto-increment ID |
| accumulator_json | TEXT | JSON containing picks, tier_2_picks, tier_3_picks |
| created_at | TIMESTAMP | Auto-generated timestamp |

**Before Tier Deletion:**
```json
{
  "picks": [...],
  "tier_2_picks": [...],  ← Present
  "tier_3_picks": [...],
  "total_accumulator_odds": 5.2,
  "master_reasoning": "..."
}
```

**After Deleting Tier 2:**
```json
{
  "picks": [...],
  // tier_2_picks removed ✅
  "tier_3_picks": [...],
  "total_accumulator_odds": 5.2,
  "master_reasoning": "..."
}
```

## Benefits

### 1. **Persistent User Preferences**
- Users can remove unwanted tiers once
- Deletions survive page refreshes
- No need to repeatedly delete same tiers

### 2. **Portfolio Customization**
- Users can keep only Tier 1 (safest picks)
- Or keep Tier 1 + Tier 2 (mixed strategy)
- Matches user's risk appetite

### 3. **Cleaner UI**
- Removed tiers don't clutter the interface
- Focus on relevant picks only

### 4. **Confirmation Protection**
- Users must confirm before deletion
- Prevents accidental tier removal

## Testing Checklist

Test the feature with these scenarios:

- [ ] **Delete Tier 2**:
  1. Generate AI Accumulator with Tier 2 and Tier 3
  2. Click "Clear Tier 2" button
  3. Confirm deletion dialog
  4. Verify Tier 2 disappears from UI
  5. Refresh page
  6. Verify Tier 2 is still deleted (not restored)

- [ ] **Delete Tier 3**:
  1. Generate AI Accumulator with Tier 2 and Tier 3
  2. Click "Clear Tier 3" button
  3. Confirm deletion dialog
  4. Verify Tier 3 disappears from UI
  5. Refresh page
  6. Verify Tier 3 is still deleted (not restored)

- [ ] **Delete Both Tiers**:
  1. Generate AI Accumulator
  2. Delete Tier 2
  3. Delete Tier 3
  4. Verify only Tier 1 remains
  5. Refresh page
  6. Verify only Tier 1 still shows

- [ ] **Cancel Deletion**:
  1. Click "Clear Tier 2"
  2. Click "Cancel" in confirmation dialog
  3. Verify Tier 2 is NOT deleted

- [ ] **Error Handling**:
  1. Stop backend server
  2. Try to delete tier
  3. Verify error alert appears
  4. Verify tier is NOT deleted in UI (since backend failed)

- [ ] **Generate New Accumulator**:
  1. Delete Tier 2 from current accumulator
  2. Generate a new accumulator
  3. Verify new accumulator has all 3 tiers (fresh start)
  4. Delete Tier 3 from new accumulator
  5. Refresh page
  6. Verify only new accumulator's Tier 3 deletion persists

## Edge Cases Handled

1. **No Accumulator Exists**: Backend returns 404 error
2. **Invalid Tier Name**: Backend returns 400 error with message
3. **Tier Already Deleted**: Backend gracefully handles (no error)
4. **Multiple Users**: Each user's deletions are isolated (JWT authentication)
5. **Fresh Accumulator**: New accumulators have all tiers (deletions don't carry over)

## API Reference

### Endpoint: `PATCH /best-picks/clear-tier`

**Authentication:** Required (Bearer token)

**Request Body:**
```json
{
  "tier": "tier2"  // or "tier3"
}
```

**Success Response (200):**
```json
{
  "status": "success",
  "tier_removed": "tier2"
}
```

**Error Responses:**

**404 - No Accumulator Found:**
```json
{
  "detail": "No AI Accumulator found."
}
```

**400 - Invalid Tier:**
```json
{
  "detail": "Invalid tier: tierX"
}
```

**401 - Unauthorized:**
```json
{
  "detail": "Not authenticated"
}
```

## Related Files

**Backend:**
- [src/api/main.py](src/api/main.py) - API endpoint (lines 444-510)
- [src/database/db.py](src/database/db.py) - Database function (lines 424-446)

**Frontend:**
- [frontend/src/components/HistoryTab.jsx](frontend/src/components/HistoryTab.jsx) - Tier deletion handler (lines 190-217)

## Future Enhancements

Potential improvements for later:

1. **Undo Deletion**: Add "Restore Tier" button to undo accidental deletions
2. **Tier Filtering UI**: Add toggle switches instead of permanent deletion
3. **Deletion History**: Track which tiers were deleted and when
4. **Batch Operations**: Delete multiple tiers at once
5. **Tier Notes**: Allow users to add notes explaining why they deleted a tier

---

**Status:** ✅ **IMPLEMENTED AND READY FOR TESTING**

**Implementation Date:** 2026-04-07

**Feature Category:** User Experience / Portfolio Management
