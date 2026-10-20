# UX & Roadmap Plan (Phases 10–12)

Working document born from the UX Audit on **2026-09-23**.
PantryPal is currently at Phase 9A. This plan covers three major themes to take the app to the next level: Mobile Polish, Smarter Inventory, and AI Loop Completion.

Rules for this plan:
- **Small.** Each sub-phase is designed to be shipped in a single session (like our prior chunked phases).
- **Incremental.** They build on each other but don't strictly block each other.
- **Maintainable.** We stick to the existing htmx + Tailwind + SQLite stack.

---

## Phase 10: Mobile Polish & Interactions

Focus: Make the app feel indistinguishable from a native mobile application.

### Phase 10A — Inline Quick-Add for Pantry (Size: M, Priority: P1) — DONE 2026-09-24
- **Goal:** Port the Phase 3H inline quick-add UI from the Shopping list over to the Pantry view.
- **Work:** Update `pantry.html` and `_pantry_list.html` to use a single `[Item name] [+]` bar with "More details" (qty, unit, notes) tucked behind a `<details>` expander. Keeps the top of the pantry view clean and saves vertical space. 
- **Tests:** Verify duplicate-confirm detour doesn't auto-reset the details block, mirroring Phase 6D shopping logic.

### Phase 10B — View Transitions (Size: S, Priority: P2) — DONE 2026-09-25
- **Goal:** Smooth UI updates so checked shopping items slide down gracefully instead of snapping.
- **Work:** Implement standard CSS View Transitions or `htmx` swapping animations for the Shopping list checkout actions. 

### Phase 10C — Pantry Swipe-to-Delete (Size: M, Priority: P1) — DONE 2026-09-28
- **Goal:** Add a left-swipe delete shortcut to Pantry rows.
- **Work:** Reused the existing lightweight touch-event pattern from Shopping. The gesture calls Pantry's established DELETE route, preserving the Undo toast and onboarding-boundary reload behavior; visible row actions remain intact. Shopping's existing left-swipe delete gesture remains its single swipe action, avoiding a conflicting swipe-to-check interaction.

### Phase 10D — Empty State Illustrations (Size: XS, Priority: P2) — DONE 2026-09-30
- **Goal:** Add subtle, themed SVG illustrations to true empty states.
- **Work:** Replaced the single-glyph pantry and shopping empty-state icons with richer inline pantry-shelf and grocery-basket illustrations. Both remain decorative (`aria-hidden`), while the existing headings and actionable copy stay as the semantic message.

---

## Phase 11: Smarter Inventory

Focus: Scaling up to larger pantries (50+ items) gracefully and taking action on thresholds.

### Phase 11A — Expiry Dates & "Eat Me First" (Size: L, Priority: P1)
- **Goal:** Track expiring items and use them to drive the AI planner.

#### Phase 11A.1 — Expiry-date foundation (Size: M) — DONE 2026-10-01
- DB: Add nullable `expiry_date` to `pantry_items` through an idempotent SQLite migration.
- UI: Add an optional date picker to Pantry Add/Edit and display the date on pantry rows.
- Data safety: preserve expiry dates through duplicate merge (earliest date wins) and delete/Undo.

#### Phase 11A.2 — Expiry urgency styling (Size: S) — DONE 2026-10-02
- Highlight expired items and dates within three days using clear amber/red treatment.
- Keep expiry dates informational: PantryPal labels the calendar status but does not prevent a user from keeping or using the item.

#### Phase 11A.3 — "Eat Me First" AI prompt (Size: S) — DONE 2026-10-02
- Added an "Eat me first" one-tap planner prompt when the household has
  non-expired items within the three-day urgency window.
- Include expiry dates in the structured AI pantry snapshot so the planner
  can prioritize soon-to-expire ingredients while excluding expired food.

### Phase 11B — Low Stock Toggles (Size: M, Priority: P2)
- **Goal:** 1-tap restock for staples.

#### Phase 11B.1 — Manual low-stock foundation (Size: S) — DONE 2026-10-07
- DB: Add `low_stock` boolean to `pantry_items` through an idempotent SQLite
  migration. Existing items default to not manually flagged.

#### Phase 11B.2 — Pantry-row restock toggle (Size: S) — DONE 2026-10-08
- UI: Added an accessible one-tap restock toggle on pantry rows. The
  persistent amber “Restock” state is deliberately distinct from the
  existing quantity-derived red “Low” cue.

#### Phase 11B.3 — Shopping-list handoff (Size: S) — DONE 2026-10-09
- Flow: When toggled ON, offer an immediate explicit prompt to copy the item
  to the Shopping list. The handoff is ephemeral so manually flagged rows
  remain compact on later visits.

### Phase 11C — Smart Categorization & Aisle Sorting (Size: L, Priority: P1)
- **Goal:** Auto-group shopping lists by Aisle to make grocery trips faster.

#### Phase 11C.1 — Shopping category foundation (Size: S) — DONE 2026-10-12
- DB: Add nullable `category` (string) to `shopping_items` through an
  idempotent SQLite migration. Existing entries remain uncategorized.

#### Phase 11C.2 — Aisle grouping UI (Size: M) — DONE 2026-10-13
- UI: Group categorized unchecked items by alphabetical aisle headers, with
  an “Other” section for uncategorized items. Checked-off items retain their
  established global section at the bottom.

#### Phase 11C.3 — Category defaults (Size: M) — DONE 2026-10-14
- Classification: added exact-match local defaults for common groceries across
  every shopping-item creation path. Unknown names remain in “Other”; no
  synchronous AI/network call is made when adding an item.

---

## Phase 12: AI Loop Completion

Focus: Closing the loop so cooking a meal updates the database, and saving great meal plans.

### Phase 12A — "I Cooked This" Auto-Deduct (Size: L, Priority: P1)
- **Goal:** Deduct ingredients from the pantry when a meal is cooked.

#### Phase 12A.1 — Cooked-meal preview (Size: S) — DONE 2026-10-15
- UI: Added “Cooked it” to meal-plan cards. It shows a current pantry-match
  preview without calling AI or mutating quantities.

#### Phase 12A.2 — Reviewed deduction proposal (Size: M) — DONE 2026-10-16
- AI: A strict JSON proposal is restricted to current, measured pantry-item
  IDs and quantities, server-validated, and shown as editable suggested
  amounts. It remains non-mutating until confirmation in 12A.3.

#### Phase 12A.3 — Confirmed deduction and Undo (Size: M) — DONE 2026-10-18
- DB: User-confirmed amounts are revalidated and applied in one transaction.
  A one-time Undo restores unchanged quantities (including items removed at
  zero) without overwriting a newer household update.

### Phase 12B — Favorite / Pin Meals (Size: S, Priority: P2)
- **Goal:** Save home-run recipes.

#### Phase 12B.1 — Favorite foundation (Size: S) — DONE 2026-10-19
- DB: Added a household-shared `is_favorite` flag to meal plans with a safe
  false default and an idempotent SQLite migration for installed databases.

#### Phase 12B.2 — Pin/unpin cards (Size: S) — DONE 2026-10-20
- UI: Added an in-place, household-shared star control to each meal card.
  It swaps only the control, preserves card state, and enforces household
  authorization server-side.

#### Phase 12B.3 — Favorites filter (Size: S)
- UI: Add a Favorites filter to Meals, including an empty state.

### Phase 12C — Dietary & Scale Toggles (Size: M, Priority: P2)
- **Goal:** Quick-toggles instead of typing for common AI prompts.
- **Work:** Add UI toggles for Portions (- 2 +) and Household Diets (Vegetarian, GF). Inject these transparently into the system prompt.