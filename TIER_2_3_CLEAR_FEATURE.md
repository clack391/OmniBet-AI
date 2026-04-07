# Tier 2 & 3 Clear Feature

## Problem

After the AI Accumulator generates picks, users had no way to clear entire Tier 2 (Value Trebles & Doubles) or Tier 3 (Singles & EV Snipes) sections independently.

The only option was to delete the entire AI Accumulator using the main clear button, which would remove ALL tiers including Tier 1 (Master Accumulator).

## Solution

Added individual "Clear Tier" buttons (X icon) to Tier 2 and Tier 3 section headers, matching the same UI pattern as Tier 1's clear button.

### Implementation Details

#### 1. New Handler Function ([HistoryTab.jsx:190-204](frontend/src/components/HistoryTab.jsx#L190-L204))

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

**Key Features**:
- Removes the entire tier array (all picks at once)
- Uses React immutable state update pattern
- Does not affect other tiers
- Automatically hides the tier section when cleared

#### 2. Tier 2 Clear Button ([HistoryTab.jsx:486-493](frontend/src/components/HistoryTab.jsx#L486-L493))

Added an X button next to the "Add to slip" button in Tier 2 header:

```javascript
<div className="flex gap-2 relative z-20">
    <button onClick={() => handleAddAllToSlip(bestPicks.tier_2_picks)} className="...">
        <PlusCircle className="w-4 h-4" /> Add to slip
    </button>
    <button onClick={() => handleClearTier('tier2')} className="p-2 text-blue-500/50 hover:text-blue-400 hover:bg-blue-500/10 rounded-lg transition-colors" title="Clear Tier 2">
        <XCircle className="w-5 h-5" />
    </button>
</div>
```

#### 3. Tier 3 Clear Button ([HistoryTab.jsx:524-531](frontend/src/components/HistoryTab.jsx#L524-L531))

Added an X button next to the "Add to slip" button in Tier 3 header:

```javascript
<div className="flex gap-2 relative z-20">
    <button onClick={() => handleAddAllToSlip(bestPicks.tier_3_picks)} className="...">
        <PlusCircle className="w-4 h-4" /> Add to slip
    </button>
    <button onClick={() => handleClearTier('tier3')} className="p-2 text-rose-500/50 hover:text-rose-400 hover:bg-rose-500/10 rounded-lg transition-colors" title="Clear Tier 3">
        <XCircle className="w-5 h-5" />
    </button>
</div>
```

### Design Choices

1. **Consistent UI Pattern**: Matches Tier 1's clear button (X icon) for visual consistency
2. **Positioned Next to "Add to Slip"**: Keeps all action buttons grouped together in the header
3. **Color-Coded Hover States**:
   - Tier 2: Blue accent (matches tier theme)
   - Tier 3: Rose accent (matches tier theme)
4. **No Confirmation Dialog**: Instant deletion (user can always regenerate accumulator)
5. **Whole Tier Deletion**: Removes all picks at once, not individual picks

## User Experience

### Before:
```
❌ No way to clear just Tier 2 or Tier 3
❌ Had to delete entire accumulator (including Tier 1)
❌ Had to regenerate everything
```

### After:
```
✅ Click X button on Tier 2 → Clears only Tier 2 picks
✅ Click X button on Tier 3 → Clears only Tier 3 picks
✅ Tier 1 (Master Accumulator) remains untouched
✅ Can regenerate just one tier if needed
```

## Visual Layout

```
┌─────────────────────────────────────────────────────────────┐
│ TIER 1 — AI Master Accumulator (≥85% SURVIVAL)              │
│ [Add all to slip] [X]  ← Clears entire accumulator          │
│                                                              │
│ Pick 1, Pick 2, Pick 3...                                    │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│ TIER 2 — Value Trebles & Doubles (75-84.9% SURVIVAL)        │
│ [Add to slip] [X]  ← NEW: Clears only Tier 2                │
│                                                              │
│ Pick 1, Pick 2, Pick 3...                                    │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│ TIER 3 — Singles & EV Snipes (<75% SURVIVAL)                │
│ [Add to slip] [X]  ← NEW: Clears only Tier 3                │
│                                                              │
│ Pick 1, Pick 2...                                            │
└─────────────────────────────────────────────────────────────┘
```

## Use Cases

### 1. User wants to discard risky Tier 3 picks
- Click X on Tier 3 header
- Tier 3 section disappears
- Tier 1 and Tier 2 remain visible

### 2. User wants only Tier 1 (safest picks)
- Click X on Tier 2 header → Tier 2 disappears
- Click X on Tier 3 header → Tier 3 disappears
- Only Tier 1 remains

### 3. User wants to regenerate with different target odds
- Click X on main Tier 1 button → Clears entire accumulator
- Enter new target odds
- Click "Build Accumulator" again
- All 3 tiers regenerate with new configuration

## Technical Notes

- **State Management**: Uses React's `useState` with functional updates (`prevState => newState`)
- **Immutability**: Creates new object with spread operator, then deletes specific tier property
- **Conditional Rendering**: Tier sections automatically hide when their array is deleted from state
- **No API Calls**: Changes are only in frontend state (not persisted to backend)
- **Event Bubbling**: No need for `stopPropagation()` since buttons are in header (not inside cards)

## Files Modified

- [frontend/src/components/HistoryTab.jsx:190-204](frontend/src/components/HistoryTab.jsx#L190-L204) - `handleClearTier()` handler
- [frontend/src/components/HistoryTab.jsx:486-493](frontend/src/components/HistoryTab.jsx#L486-L493) - Tier 2 clear button
- [frontend/src/components/HistoryTab.jsx:524-531](frontend/src/components/HistoryTab.jsx#L524-L531) - Tier 3 clear button

## Testing

To test this feature:

1. Generate an AI Accumulator with picks in all 3 tiers
2. Click X button on Tier 2 header
   - ✅ Tier 2 section should disappear immediately
   - ✅ Tier 1 and Tier 3 should remain visible
3. Refresh page → Tier 2 reappears (changes not persisted - expected behavior)
4. Generate accumulator again
5. Click X button on Tier 3 header
   - ✅ Tier 3 section should disappear immediately
   - ✅ Tier 1 and Tier 2 should remain visible
6. Click X button on Tier 1 header (main clear button)
   - ✅ Entire accumulator should disappear (all tiers)
7. Verify hover states show correct colors (blue for Tier 2, rose for Tier 3)

## Implementation Status

✅ **COMPLETED** - Users can now clear entire Tier 2 or Tier 3 sections independently using X buttons in section headers.
