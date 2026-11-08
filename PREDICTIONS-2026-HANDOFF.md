# 2026 Predictions — 0-to-24D Slider (Front Page Only)

Branch: `migurski/expand-2026-predictions`

## Goal

Recast the "2026 Scenarios" slider from a symmetric ±12 margin swing (centered
on 2024 baseline) to a 0–24 D-only range. The actual 2026 election landed at
D+12, so D+12 on the current slider = reality. A 0–24 range spans from the
2024 baseline (0) through what actually happened (D+12) to a D+24 extreme.

This is a **front-page-only** change. Uploaded plans on planscore.org/plan.html
continue to see the existing ±12 scenario system — that's a PlanScore backend
feature, not part of this repo.

## Scope: What's Front-Page vs. Backend

**Front page (this repo):**
- `index.js6` / `index.src.html`: slider, scenario navigation, data rendering
- `bias_ushouse-elections.csv`: predict* rows consumed by index.js6
- Python pipeline scripts: generate predict* rows + clone plans via API
- State template pages: no prediction code at all (historical years only)

**PlanScore backend (NOT this repo):**
- `plan.html` pages for uploaded plans — served by PlanScore backend
- The ±12 scenario display on individual plan pages
- The `/clone` API itself

No changes to the PlanScore backend are needed. Uploaded plans keep ±12.

## What Exists Today

### CSV Data (25 cycles × 50 states = 1250 rows)

```
predict12R, predict11R, ..., predict1R, predict0, predict1D, ..., predict12D
```

Each row has: `cycle, stateabrev, newplan, EG, seats, dem_seats, url, districts`
- `url` = cloned PlanScore plan URL (e.g. `https://planscore.org/plan.html?2026...`)
- `districts` = empty for predict rows

### Slider (index.src.html lines 434-440)

```html
<form id="margin-swing">
    <span id="margin-range-caption">...</span>
    <br>
    D+12
    <input type="range" id="margin-swing-range" min="-12" max="12" step="1" value="0">
    R+12
</form>
```

CSS `direction: rtl` flips it visually: D+12 is on the left, R+12 on the right.
The slider's internal value -12 to +12 maps directly to cycle names.

### JS Functions (index.js6)

| Function | Lines | Purpose |
|----------|-------|---------|
| `getPredictionYearString(value)` | 353-357 | Slider int → cycle name: `0→predict0`, `5→predict5D`, `-3→predict3R` |
| `parseSwingSlug(slug)` | 313-328 | Cycle name → slider int (inverse of above) |
| `formatSwingValue(value)` | 330-333 | Slider int → display label: `0→"No-Swing"`, `5→"D+5"`, `-3→"R+3"` |
| `updatePredictionCaption(value)` | 218-236 | Updates vote share caption from CURRENT_VIEW data |
| `initPredictionSlider()` | 238-275 | Sets slider value, binds input handler |

These functions are **generic** — no hardcoded ±12 bounds in the JS logic.
The range is set only in the HTML `min`/`max` attributes and the flanking labels.

### Pipeline Scripts

**`update-ushouse-vote-swings.py`** generates scenarios:
- `SHIFT_HEADERS` (line 48): `['R+12', ..., 'No-Swing', ..., 'D+12']` — 25 entries
- `LINK_HASH_PARTS` (line 46): `['12R', ..., '0', ..., '12D']` — 25 entries
- `calculate_all_district_shifts()` (line 1016): loops `range(-12, 13)`
- Clones 50 states × 25 scenarios = 1250 plans via PlanScore API
- Writes "State Swings" and "District Swings" worksheets to Google Sheet

**`update-ushouse-data-files.py`** reads URLs from "State Swings" worksheet,
fetches each plan's S3 index.json, writes predict* rows to elections CSV.

## Implementation Plan

### Phase 1: Shift Pipeline from ±12 to 0–24

The pipeline replaces the 12 R-side scenarios (R+1 through R+12) with 12 new
D-side scenarios (D+13 through D+24). Total stays at 25 scenarios per state.

**`update-ushouse-vote-swings.py` changes:**

1. Replace `LINK_HASH_PARTS` and `SHIFT_HEADERS` — shift from R+12…D+12 to
   No-Swing…D+24:
   ```python
   LINK_HASH_PARTS = ['0', '1D', '2D', ..., '12D', '13D', ..., '24D']
   SHIFT_HEADERS = [ZERO_HEADER, 'D+1', 'D+2', ..., 'D+12', 'D+13', ..., 'D+24']
   ```
   Still 25 entries, just shifted.

2. Change `calculate_all_district_shifts()` loop from `range(-12, 13)` to
   `range(0, 25)` — covers No-Swing through D+24 margin swings (vote swings
   0 to +12pp / 0.12 decimal).

3. Google Sheet worksheets stay the same size: "State Swings" has 25 scenario
   columns (old R-side columns replaced by new D+13–D+24 columns), "District
   Swings" same.

4. ~600 new API clone calls (50 states × 12 new D+13–D+24 scenarios). The
   650 existing plans (predict0 through predict12D) are reused via the
   freshness check (lines 680-701). The 600 old R-side plans are simply
   no longer referenced.

**`update-ushouse-data-files.py` changes:**

1. `get_state_swings_column_name()` already handles any `predictXD` format —
   `predict24D` → `"D+24 PlanScore URL"`. **No change needed.**

2. The elections CSV swaps 600 R-side rows (predict1R–predict12R × 50 states)
   for 600 new D-side rows (predict13D–predict24D × 50 states). Total stays
   at 1250 predict rows. The CSV needs the new cycle rows to pre-exist for
   `process_row()` to find and update them — either pre-seed them, or add
   logic to create rows for new cycles.

### Phase 2: Frontend Slider Changes

**`index.src.html`:**

Change slider range and labels. Two possible framings:

**Option A — Relabel as 0-to-24 (conceptually "points more D than 2024"):**
```html
D+24
<input type="range" id="margin-swing-range" min="0" max="24" step="1" value="12">
2024 Baseline
```
- Slider value 0 = predict0 (2024 baseline, "No-Swing")
- Slider value 12 = predict12D (≈ 2026 actual)
- Slider value 24 = predict24D (extreme D)
- Default value 12 = what actually happened

No changes needed to `getPredictionYearString()` or `parseSwingSlug()` — slider
value 5 still maps to `predict5D`, value 0 still maps to `predict0`. The
existing functions handle this natively because the slider range is now 0-24
(all non-negative), so `getPredictionYearString()` always takes the
`if (value > 0) return predict${value}D` path, or the `value === 0` path.

**Option B — Relabel as R+12 to D+12 with 2026 midpoint marker:**
Keep internal -12 to +12, but add a visual midpoint label showing "≈ 2026"
at the D+12 position and extending to D+24 requires the same pipeline work.
This is more confusing and doesn't save any work.

**Recommended: Option A.** The slider value 0-24 maps cleanly to existing cycle
names (predict0 through predict24D) with zero changes to the mapping functions.

**`index.js6` changes needed:**

1. `formatSwingValue()` (line 330): Currently shows "No-Swing" for value 0.
   For the 0-24 framing, value 0 should show "2024 Baseline" or "No-Swing
   (2024)", and value 12 should show "D+12 (≈ 2026)". Consider adding a
   midpoint annotation.

2. `updatePredictionCaption()` (line 218): Caption text says "at D+5 margin
   swing". May want to add context like "(2026 was D+12)".

3. `initPredictionSlider()` (line 238): Default landing position. Currently
   the URL hash determines the slider position. If someone navigates to
   `#!predict0-ushouse`, the slider goes to 0. If they click "2026 Scenarios"
   in the timeline, it uses the remembered position or defaults to predict0.
   **Should default to predict12D** (≈ 2026 actual) instead of predict0
   (2024 baseline). Change in small year picker click handler (line 151)
   and the default in line 168.

4. No changes to `getPredictionYearString()` or `parseSwingSlug()` — they
   already handle 0-24 correctly.

**`index.src.html` SVG timeline:**
- "2026 Scenarios" label (line 528) may need updating to reflect the new framing

### Phase 3: Linking to Extended Plans

Each predict* row's `url` field already contains a full PlanScore plan URL.
When a user clicks a state tooltip on the front page at a prediction scenario,
the link goes to `stateInfo.url` (the PlanScore plan page for that cloned
plan). This works for D+13 through D+24 plans just like it works for existing
ones — the cloned plans exist on PlanScore and are viewable at their URLs.

The PlanScore plan page for a D+24 clone will show the plan with its vote
swings applied. The plan page's own ±12 scenario slider (if it has one) is
a PlanScore backend feature and is independent.

## File-by-File Change Summary

| File | Change | Effort |
|------|--------|--------|
| `update-ushouse-vote-swings.py` | Shift SHIFT_HEADERS/LINK_HASH_PARTS from ±12 to 0–24, shift loop range | Small |
| `update-ushouse-data-files.py` | May need to handle new predict cycles not yet in CSV | Small |
| `bias_ushouse-elections.csv` | Remove 600 R-side rows, add 600 D+13–D+24 rows (net zero) | Generated |
| `index.src.html` | Slider min/max/value, flanking labels | Small |
| `index.js6` | formatSwingValue labels, default landing position | Small |
| Google Sheet | State Swings: replace 12 R-side columns with 12 D+13–D+24 columns | Generated |
| PlanScore API | ~600 new clone calls (D+13–D+24 only; existing plans reused) | Pipeline run |

## Key Observations

1. **The JS mapping functions don't need changes.** `getPredictionYearString()`
   and `parseSwingSlug()` are generic — they work with any non-negative integer
   mapping to `predictXD` cycle names. The only hardcoded range is in the HTML
   slider attributes.

2. **Existing D-side URLs are preserved.** The 650 existing plans (predict0
   through predict12D) stay valid and are reused. The 600 R-side plans become
   unreferenced but still exist on S3. Only 600 new clones are needed
   (D+13 through D+24). Net data volume is unchanged (25 cycles × 50 states).

3. **The ±12 on uploaded plans is untouched.** Plan pages are served by the
   PlanScore backend. The front page slider range is independent.

4. **D+24 = +12pp vote swing = 0.12 decimal.** This is a large swing (the
   logit shift math may produce extreme results for safe districts). The
   `calculate_district_shifts()` function uses `bracket=[-1, 1]` for the
   root finder — verify that +0.12 target_diff stays within bracket bounds
   for all states. For context, D+12 is already +0.06 and works fine; D+24
   doubles that to +0.12 which may push some states' logit solver to the
   bracket edge.

5. **The "2026 Outcomes" branch is separate.** cycle=2026 rows in the CSV
   are actual outcomes data, not affected by prediction changes. The timeline
   fork ("2026 Outcomes" vs "2026 Scenarios") continues to work.

## New England Validation Plan

Test the full pipeline end-to-end on 6 states (CT, ME, MA, NH, RI, VT — 21
districts total) before running against all 50.

### Step 1: Modify `update-ushouse-vote-swings.py` — DONE

**Permanent changes (committed):**

1. `LINK_HASH_PARTS` and `SHIFT_HEADERS` shifted from ±12 to 0–24D
2. `calculate_all_district_shifts()` loop changed from `range(-12, 13)` to
   `range(0, 25)`

*(Test scaffolding `--states` and `--sheet-prefix` were added for
validation, then removed after Step 5.)*

### Step 2: Run the Vote Swings Pipeline (New England Only) — DONE

```bash
.venv/bin/python update-ushouse-vote-swings.py \
    P9GEnZU9 planscore-317316-d79165b0b57a.json \
    --states CT,ME,MA,NH,RI,VT
```

**Results:**
- All 25 shift calculations completed cleanly (D+0 through D+24)
- No logit solver errors at D+24 (0.120 target_diff) — bracket bounds OK
- Existing plan URLs loaded from "State Swings 2026-09-10" for reuse
- Non-NE states left blank in output (not skipped)
- Google Sheet: "TEST State Swings 2026-11-07" — 50 state rows, URLs
  populated only for CT/ME/MA/NH/RI/VT
- Google Sheet: "TEST District Swings 2026-11-07" — all 435 districts,
  all shift columns filled (pure math, no API dependency)
- Exit code 0

### Step 3: Modify `update-ushouse-data-files.py` — DONE

**Changes (committed):**

1. `--sheet-prefix` argument: makes `load_google_state_swings()` search for
   worksheets with the given prefix (e.g. `--sheet-prefix "TEST "` reads
   "TEST State Swings" sheets).
2. `--states` argument: limits which predict rows get API-fetched; others
   pass through unchanged.
3. CSV row swap logic in `main()`: removes predict*R rows, adds
   predict13D–predict24D placeholder rows (templated from predict0), then
   processes all rows through `process_row()`.

**Test run:**
```bash
cp WEBSITE_OUTPUT/data/bias_ushouse-elections.csv /tmp/test-elections.csv
.venv/bin/python update-ushouse-data-files.py \
    planscore-317316-d79165b0b57a.json \
    /tmp/test-elections.csv \
    --sheet-prefix "TEST " --states CT,ME,MA,NH,RI,VT
```

**Results:**
- Read 25 URLs for each of 6 NE states from "TEST State Swings 2026-11-07"
- Removed 600 R-side predict rows, added 600 D-side predict rows
- NE states: EG, dem_seats, URLs populated for all 25 cycles
- Non-NE states: predict0–predict12D kept from original, predict13D–24D blank
- No predict*R rows remain

### Step 4: Test Frontend with New England Data — DONE

**Changes (committed):**

`index.src.html` slider: `min="0" max="24" step="1" value="12"`, labels
"D+24" (left) and "2024 Baseline" (right).

**Results:**
- Slider range 0–24 works, URL hash navigation works (predict24D no longer
  snaps back to predict12D — was caused by browser clamping slider value to
  old max="12")
- NE states show data at all 25 cycles
- Non-NE states show NaN at D+13–D+24 (expected: blank computed fields)
- All states show data at D+0–D+12 (original data preserved)

### Step 5: Full 50-State Run — DONE

```bash
.venv/bin/python update-ushouse-vote-swings.py \
    P9GEnZU9 planscore-317316-d79165b0b57a.json
.venv/bin/python update-ushouse-data-files.py \
    planscore-317316-d79165b0b57a.json \
    WEBSITE_OUTPUT/data/bias_ushouse-elections.csv
```

**Results:**
- 650 existing plans reused (D+0–D+12 × 50 states, from September sheet)
- 600 new plans cloned (D+13–D+24 × 50 states)
- All 50 states × 25 scenarios = 1250 predict rows fully populated
- No logit solver errors at any swing level
- Google Sheet: "State Swings 2026-11-07" and "District Swings 2026-11-07"
- TEST worksheets deleted
- `--states` and `--sheet-prefix` scaffolding removed from both scripts
- Default slider position changed from predict0 to predict12D
- Elections CSV and all code changes committed

## Resolved Questions

1. **Slider labels**: "D+24" at left and "2024 Baseline" at right — accepted.
2. **Midpoint marker**: Not needed for now.
3. **"2026 Scenarios" label**: Kept as-is.
4. **`formatSwingValue()` labels**: Kept as-is ("No-Swing" at 0, "D+N" for
   others). No special annotation at D+12.
5. **Default slider position**: Changed to D+12 (predict12D).
