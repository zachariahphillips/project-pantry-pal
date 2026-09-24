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

### Phase 10A — Inline Quick-Add for Pantry (Size: M, Priority: P1)
- **Goal:** Port the Phase 3H inline quick-add UI from the Shopping list over to the Pantry view.
- **Work:** Update `pantry.html` and `_pantry_list.html` to use a single `[Item name] [+]` bar with "More details" (qty, unit, notes) tucked behind a `<details>` expander. Keeps the top of the pantry view clean and saves vertical space. 
- **Tests:** Verify duplicate-confirm detour doesn't auto-reset the details block, mirroring Phase 6D shopping logic.

### Phase 10B — View Transitions (Size: S, Priority: P2)
- **Goal:** Smooth UI updates so checked shopping items slide down gracefully instead of snapping.
- **Work:** Implement standard CSS View Transitions or `htmx` swapping animations for the Shopping list checkout actions. 

### Phase 10C — Swipe Gestures (Size: M, Priority: P1)
- **Goal:** Add swipe-to-delete on Pantry rows and swipe-to-check on Shopping rows.
- **Work:** Use a lightweight mobile gesture library (or CSS scroll-snap trick) to enable native horizontal swipe actions on list items.

### Phase 10D — Empty State Illustrations (Size: XS, Priority: P2)
- **Goal:** Add a subtle, themed SVG illustration to empty states.
- **Work:** Update `_pantry_list.html` and `_shopping_list.html` empty states to feel more delightful with an SVG hero graphic.

---

## Phase 11: Smarter Inventory

Focus: Scaling up to larger pantries (50+ items) gracefully and taking action on thresholds.

### Phase 11A — Expiry Dates & "Eat Me First" (Size: L, Priority: P1)
- **Goal:** Track expiring items and use them to drive the AI planner.
- **Work:** 
  1. DB: Add `expiry_date` (nullable) to `pantry_items`.
  2. UI: Add date picker in Pantry Add/Edit forms.
  3. UI: Highlight items expiring in <3 days in amber/red.
  4. AI: Add a 1-tap chip: *"Plan a meal using expiring items."*

### Phase 11B — Low Stock Toggles (Size: M, Priority: P2)
- **Goal:** 1-tap restock for staples.
- **Work:**
  1. DB: Add `low_stock` boolean to `pantry_items`.
  2. UI: Add a quick-toggle button on pantry rows.
  3. Flow: When toggled ON, automatically prompt to push a copy to the Shopping list.

### Phase 11C — Smart Categorization & Aisle Sorting (Size: L, Priority: P1)
- **Goal:** Auto-group shopping lists by Aisle to make grocery trips faster.
- **Work:** 
  1. DB: Add `category` (string) to `shopping_items` (and maybe `pantry_items`).
  2. AI Hook: When an item is added, Ask AI to classify it (Produce, Dairy, Spices, Meat, etc.).
  3. UI: Group the Shopping view by category headers.

---

## Phase 12: AI Loop Completion

Focus: Closing the loop so cooking a meal updates the database, and saving great meal plans.

### Phase 12A — "I Cooked This" Auto-Deduct (Size: L, Priority: P1)
- **Goal:** Deduct ingredients from the pantry when a meal is cooked.
- **Work:**
  1. UI: Add a "Cooked it!" button on the AI Meal Plan result card.
  2. AI: Pass the meal plan + current pantry to OpenAI, asking it to return a JSON array of `[{id: 12, qty_to_deduct: 1.5}, ...]`.
  3. DB: Apply the deductions to the `pantry_items` table and flash a success toast ("Deducted 4 items").

### Phase 12B — Favorite / Pin Meals (Size: S, Priority: P2)
- **Goal:** Save home-run recipes.
- **Work:**
  1. DB: Add `is_favorite` to `meal_plans`.
  2. UI: Add a star icon to meal history cards. 
  3. UI: Add a "Favorites" filter tab in the Meals view.

### Phase 12C — Dietary & Scale Toggles (Size: M, Priority: P2)
- **Goal:** Quick-toggles instead of typing for common AI prompts.
- **Work:** Add UI toggles for Portions (- 2 +) and Household Diets (Vegetarian, GF). Inject these transparently into the system prompt.