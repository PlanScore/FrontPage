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

**Test scaffolding (committed, remove after validation):**

3. `--states` argument: comma-separated state abbreviations. Non-filtered
   states still appear in all output with blank URL cells (not skipped).
4. `--states` triggers "TEST " prefix on worksheet names.

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

### Step 3: Modify `update-ushouse-data-files.py`

**Changes needed:**

1. Add `--states` argument, same pattern as above. When set, only process
   predict* rows for matching states. Also filter which cycle values to
   process — skip predict1R through predict12R, process predict0 through
   predict24D.

2. The script reads the most recent "State Swings" worksheet, but for the
   test it needs to read the "TEST State Swings 2026-11-07" worksheet. Add
   a `--test` flag or `--sheet-prefix` argument that makes
   `load_google_state_swings()` look for "TEST State Swings" worksheets
   instead of "State Swings" worksheets.

3. The CSV needs predict13D–predict24D rows to exist before `process_row()`
   can update them. Two options:
   - **Pre-seed**: Before running, add placeholder rows to the CSV for the
     new cycles (copy predict12D rows, change cycle to predict13D–predict24D,
     blank out the computed fields)
   - **Create on the fly**: Modify the script to insert new rows when it
     encounters a cycle in the State Swings sheet that doesn't exist in the
     CSV yet

   Pre-seeding is simpler and avoids modifying production logic.

4. Run against a **copy** of the elections CSV to avoid touching production data:
   ```bash
   cp WEBSITE_OUTPUT/data/bias_ushouse-elections.csv /tmp/test-elections.csv
   # Pre-seed predict13D–predict24D rows for NE states in the copy
   .venv/bin/python update-ushouse-data-files.py \
       credentials.json \
       /tmp/test-elections.csv \
       --states CT,ME,MA,NH,RI,VT \
       --sheet-prefix "TEST"
   ```

**What to verify:**
- predict0 through predict12D rows for NE states have URLs matching the
  "TEST State Swings" worksheet (reused plans)
- predict13D through predict24D rows have new URLs from the cloned plans
- EG, dem_seats values are populated and reasonable
- No predict1R through predict12R rows remain for NE states

### Step 4: Test Frontend with New England Data

After Step 3, the test CSV has 0–24 data for NE states but still has ±12
data for all other states. To test the slider:

1. Copy the test CSV into WEBSITE_OUTPUT/data/ (backing up the original)
2. Make the `index.src.html` slider changes: `min="0" max="24" value="12"`
3. Make the `index.js6` `formatSwingValue()` label changes
4. Load the site in a browser, navigate to 2026 Scenarios
5. Drag slider to 0 (predict0) — should show data for all states
6. Drag slider to 12 (predict12D) — should show data for all states
7. Drag slider to 24 (predict24D) — NE states should show data; other
   states will show nothing (no predict24D rows yet)
8. Click a NE state tooltip — should link to the cloned plan on PlanScore
9. Click the plan link — PlanScore plan page should load and show the plan
   with D+24 vote swings applied

### Step 5: Clean Up and Full Run

After validation:
1. Remove `--states` and `--sheet-prefix` / test prefix scaffolding
2. Delete "TEST State Swings" and "TEST District Swings" worksheets
3. Run the full pipeline for all 50 states
4. Commit the permanent changes

## Open Questions

1. **Slider labels**: "2024 Baseline" at 0 and "D+24" at 24? Or something else?
2. **Default position**: Land on D+12 (≈ 2026) or D+0 (2024 baseline)?
3. **Midpoint marker**: Show "≈ 2026 Actual" label at the D+12 position?
4. **D+24 feasibility**: Will the logit shift solver handle 0.12 target_diff
   for all 50 states? Need to test with New England first.
5. **"2026 Scenarios" label**: Keep as-is, or rename to reflect the new range?
