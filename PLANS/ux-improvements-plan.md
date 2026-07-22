# UX Improvements Plan — small + incremental

Working doc from a fresh visual audit on **2026-07-20** (Phase 6D just shipped).
Full survey ran at mobile viewport (414×896) against a seeded account so we saw
empty + populated + checked + duplicate-confirm states on every surface.

Rules for this plan:

- **Small.** Each item is one-chunk-shippable (matches how we've been shipping
  Themes 3/5/6 — one focused branch, one commit, one test file).
- **Slow.** The list is *ranked but not sequenced*. Pick one at a time. Ship it.
  Come back. Don't try to bundle.
- **Not a rewrite.** Nothing here suggests a redesign of the surface language
  (stone/amber/green + rounded-2xl + max-w-md). We keep the visual identity and
  polish the friction points.

## How to read the size column

- **XS** — one file, one commit, < 30 min. No new tests.
- **S** — 1–3 files, one commit, an hour or two. May add a small test.
- **M** — multiple templates + route changes + a new test file. Chunk-sized
  (comparable to 3F, 6A, 6D).

## How to read the priority column

- **P0** — real bug, ship first.
- **P1** — meaningful UX win the user will feel.
- **P2** — polish / nice-to-have.

---

## 0. Bug fix — P0 (ship first)

### 0.1 Checked-off shopping row leaks the red swipe-delete background — ✅ shipped 2026-07-20 (Phase 6E)

Where: `templates/_shopping_item.html`
Size: **XS** — one class swap on one line.

**What was wrong:** When a shopping item is checked off, `data-swipe-content`
gets `opacity-60`. But the parent `data-swipe-row` still has the red
`bg-red-600` "DELETE" affordance layer painted at full opacity underneath.
The reduced-opacity content lets the red bleed through — the checked row
renders as a **pink-red block with the word DELETE showing behind the
checkbox and item name**. Looked broken; blocked the row's readability.

See `/tmp/audit_07_shopping_checked.png` (before) — checked "Garlic" row
was rose-tinted with "Delete" text visible under it.
See `/tmp/6e_after_check.png` (after) — clean white card, no red leak.

**Diagnosis correction from the original plan:** the recommendation
("push affordance to `-z-10`, keep content `bg-white`") wouldn't fully
fix it. `opacity-60` on the content layer reduces the ENTIRE stacking
context's alpha, including the wrapper's own `bg-white`. Any `>0`
opacity on the wrapper means the red bleeds through regardless of
z-order. The real move is to keep the wrapper at 100% opacity and
push the dim onto the wrapper's children only.

**Final fix (chose option 1 in spirit, using a Tailwind arbitrary variant):**
`opacity-60` → `[&>*]:opacity-60` on the content wrapper's class list,
so only direct children (checkbox label, content column, actions column)
dim — the wrapper's `bg-white` stays 100% opaque and fully occludes the
red affordance layer at rest. One-class swap, no JS, no z-index churn.

**Test coverage:** `tests/test_phase_6e.py` (9 tests). Guards:
- unchecked wrapper has no opacity treatment
- checked wrapper uses `[&>*]:opacity-60` (child-scoped)
- checked wrapper does NOT carry a bare `opacity-60` (the exact regression)
- wrapper's `bg-white` unchanged in both states
- swipe scaffolding (`data-swipe-row`, `data-swipe-content`, `data-delete-url`,
  affordance `bg-red-600`) all preserved

---

## 1. Empty-state polish — P1

### 1.1 De-duplicate the empty-pantry copy — ✅ shipped 2026-07-22 (Phase 6F)

Where: `templates/pantry.html` (planner subcopy line)
Size: **XS** — copy-only, one branch of one `{% if %}`.

**What was wrong:** On the empty pantry, two adjacent blocks in the
`Plan a meal` section said the same thing:

- H2 subcopy: *"Add a few items first — the AI plans meals using what you have."*
- Dot progress panel: *"Add N more items to unlock the AI planner."*

Two "Add … items" instructions stacked one on top of the other, pushing
the hero card further down the fold. The H1 subheading ("What you've
got at home — and what to cook with it.") + hero card
("Let's stock your pantry.") remain untouched — they do different jobs
than the section-level subcopy, so they don't fold into this dedup.

**Fix:** shortened the planner subcopy on the empty state to
*"Locked until your pantry has a few items."* — a state descriptor,
letting the dot panel below own the action verb. The un-locked branch's
copy is unchanged.

**Test coverage:** `tests/test_phase_6f.py` (7 tests). Guards:
- new locked-state subcopy is present on empty pantry
- old redundant string is retired
- dot-panel instruction is preserved (redundancy was the bug — absence
  would be a bigger bug)
- un-locked branch still swaps to the AI-prompt subcopy
- both boundary states around the onboarding threshold render correctly

**Compare:** `/tmp/audit_02_pantry_empty.png` (before) →
`/tmp/6f_empty_pantry.png` (after).

### 1.2 Hide search + household-share cards until the pantry has any item

Where: `templates/pantry.html` (search input + `_household_share.html` include)
Size: **XS**

**What's wrong:** On a completely empty pantry we still render the
`Search pantry` box (nothing to search) and the `Alice's home` household
share card. Roommate-invite before you've added a single item is unusual —
the card feels like a distraction from the hero's job.

**Recommendation:** Wrap both in `{% if not is_empty_pantry %}` (search) and
`{% if pantry_item_count > 0 or has_roommate %}` (household card). Show
household share only when there's shared-pantry substance, OR the household
already has a co-op relationship.

### 1.3 Shopping empty-state hero (mirror the pantry pattern)

Where: `templates/_shopping_list.html` (empty-state block)
Size: **S**

**What's wrong:** Empty shopping is a bare `Nothing on your shopping list
yet · Add items above, or tap + Shop on any pantry item.` block. Not
terrible, but noticeably plainer than the pantry's icon-hero + seed-button
treatment. Especially awkward when the user lands on `/shopping` first
(via the tab bar) on a fresh account.

**Recommendation:** Same hero pattern the empty pantry uses — bag icon +
short heading + subcopy. No seed-button equivalent (there's no meaningful
"starter shopping list"). Focus copy on the two entry points that DO exist:
adding here directly, or the `+ Shop` path from pantry.

### 1.4 Empty meals page needs the seed of first-plan action

Where: `templates/meals.html` empty state
Size: **XS**

**What's wrong:** The current copy — "Ask the AI what to cook from the
pantry page" — is *correct* but the CTA button just says "Plan a meal"
and links to `/pantry`. On the empty pantry, that means the user is
bounced onto a screen where the planner might still be locked (they
haven't added the 3 items yet). Fine link, misleading label.

**Recommendation:** If `pantry_item_count < onboarding_threshold`, change
the CTA to "Stock your pantry first →" and skip the misleading "Plan a
meal" copy. If the threshold is cleared, keep the current CTA.

---

## 2. Visual polish — P1 / P2

### 2.1 Item-row action buttons — cramped on longer names

Where: `templates/_pantry_item.html` + `templates/_shopping_item.html`
Size: **S**

**What's wrong:** Pantry rows render `+ Shop · Edit · Delete` as three
text-labeled buttons that eat ~150px on the right. Item names > ~15 chars
get truncated even on a 414px viewport. Shopping rows are lighter (only
`Edit · Delete`) but hit the same issue.

**Recommendation options:**
- Icon-only actions with `aria-label`. Small pencil for Edit, small
  trash for Delete, small basket-plus for `+ Shop`. Standard mobile row
  pattern.
- **Or:** keep text, hide behind an overflow menu (⋮) that opens the three
  actions in a small popover. More work, more surface area, but keeps the
  row very clean.

**Recommendation:** icon-only. It's the smaller step and it aligns with the
existing icon-only pattern already used on the shopping quick-add "+" and
the tab bar. **P2 (nice-to-have), not urgent** — but a genuine mobile win.

### 2.2 Delete button visual weight is too high for a rare action

Where: `templates/_pantry_item.html` + `templates/_shopping_item.html`
Size: **XS**

**What's wrong:** The Delete text-button uses `text-red-700` — high
contrast against a white row. Every row on the pantry list screams "look at
Delete" — a rare, destructive action getting equal visual weight with
`+ Shop` and `Edit` (both frequent actions).

**Recommendation:** Drop delete to a neutral tone (`text-stone-500`, becomes
`text-red-700` on hover/focus). Keep the destructive color at the moment of
intent, not at rest.

**Interaction with 2.1:** If we go icon-only in 2.1, this is even simpler —
the trash icon can be neutral gray by default.

### 2.3 Cost pill is too easy to miss

Where: `templates/pantry.html` (the `#meal-plan-cost-pill` span)
Size: **XS**

**What's wrong:** The "20 of 20 left today" pill next to the "Plan a meal"
heading uses `text-[11px]` — deliberately unobtrusive. For a rate-limited
AI feature the user is paying for (indirectly, via daily quota), being
unobtrusive is the wrong choice. When we hit `≤3`, we amber; at 0, we red.
But at that point the user has already blown through their quota — they
should have seen the counter dropping.

**Recommendation:** Bump to `text-xs` (12px) and add a subtle border/bg
treatment (e.g., stone-50 pill with border-stone-200) so it reads as a
budget indicator rather than a whisper. Preserve the amber/red color
transitions.

### 2.4 Nudge banner's "loading spinner" glyph reads ambiguously

Where: `templates/_macros.html` (the `nudge_banner` macro)
Size: **XS**

**What's wrong:** The nudge banner leads with a spinning green swirl that
gets read as a loading indicator by users familiar with web loading
patterns. It's decorative here — meant to draw the eye, not indicate
in-flight work. In `/tmp/audit_05_pantry_stocked.png` and
`/tmp/audit_08_pantry_compact.png` it's especially confusing because there
IS a real loading state elsewhere on the page (the `#meal-plan-spinner`
skeleton).

**Recommendation:** Replace the spinner with a static icon that reads as
"tip / signpost" — a lightbulb, an arrow, or a small green check. Or drop
the icon entirely and let the amber background carry the "notice this"
signal.

### 2.5 "VIEW: Compact" toggle label is opaque

Where: `templates/_pantry_list.html` (the density toggle)
Size: **XS**

**What's wrong:** The `VIEW  [Compact]` micro-label is either confusing
("Compact… what?") or invisible until you find it and puzzle it out. It's
a good feature (real space savings) hidden behind bad labeling.

**Recommendation:** Change label to `DENSITY` or use an icon pair (rows-3
vs rows-1) with tooltip. Or: just call the button "Compact / Roomy" as a
segmented control instead of a single toggle, so both states are visible
and the switch is discoverable.

### 2.6 Header logo is small + unstyled

Where: `templates/base.html` (the `P PantryPal` mark)
Size: **XS**

**What's wrong:** The header is fine but generic — a green rounded square
with a "P" and the word PantryPal. Cute enough, no personality. On the
signup/login screens especially, where the header is the only branded
surface, it feels understated.

**Recommendation:** Zero code change urgency — but if you ever want the
app to feel less like a form and more like a product, this is where it
starts. Could commission a small mark. Deferred.

---

## 3. Interaction / feedback — P1

### 3.1 Add haptic-style press feedback to primary buttons

Where: Primary green buttons across `pantry.html`, `shopping.html`,
`meals.html`
Size: **XS**

**What's wrong:** Buttons have `hover:bg-green-700` and `focus:ring-2` but
no `active:` state. On mobile there's no hover — so a tap on `Add to
pantry` or `Ask AI` gives zero feedback until the response lands (which is
1–5s for AI). Users tap twice.

**Recommendation:** Add `active:bg-green-800 active:scale-[0.98]
transition` to primary buttons. Cheap, universal, feels alive.

### 3.2 `htmx-request` state on the "+" quick-add button

Where: `templates/shopping.html` (the round green "+" submit)
Size: **XS**

**What's wrong:** When you rapid-fire tap "+" on the quick-add bar, the
button gives no in-flight indication. The row lands and the input resets,
but the ~150ms round-trip is silent. Users may tap again mid-flight,
triggering a 2nd add (or in Phase 6D, a duplicate-confirm card that catches
it).

**Recommendation:** Add `hx-disabled-elt="this"` + a small pulse or spinner
inside the button via `.htmx-request` targeting. htmx already toggles the
class for us.

### 3.3 Toast timing feels short for the Undo grace window

Where: `templates/base.html` (`showToast` function)
Size: **XS**

**What's wrong:** Action toasts (with Undo) stay 5s. On desktop that's
fine. On mobile — the user just tapped Delete, put the phone down to
grab a coffee, comes back to see nothing. The safety net evaporated
before they could realize they wanted it.

**Recommendation:** Bump action-bearing toasts from 5000ms to 7000ms.
Text-only toasts stay at 1800ms. Tiny change, meaningfully broader
safety window.

### 3.4 Auto-dismiss the "Welcome to PantryPal, Alice!" flash

Where: `templates/base.html` (the flash-messages block)
Size: **XS**

**What's wrong:** Flask flashes render as full-width green banners that
persist until the next `get_flashed_messages()` call. On a fresh signup the
"Welcome" banner sits above the fold on every reload of `/pantry` until
you navigate away. Doesn't stack (Flask consumes on read) but the first
visit is oddly long-lived.

**Recommendation:** Auto-dismiss non-error flashes after 4s with a CSS
transition + JS timer. Or add a close X. Errors should still be manually
dismissed (they can carry actionable info).

---

## 4. Copy — P2

### 4.1 "+2 head" reads awkwardly in the shopping duplicate-confirm

Where: `templates/_shopping_dupe_confirm.html`
Size: **XS**

**What's wrong:** The button label "Update existing (+2 head)" is
grammatically fine only if you already know "head" is a produce unit.
Alone it reads as broken English.

**Recommendation options:**
- Wrap the unit in parentheses: "Update existing (+2 · head)"
- Or: show "+2" as the delta and put the full unit description in a
  subline underneath, or as a tooltip on the button
- Or: only include the unit when it's an unambiguous SI unit (`gal`,
  `oz`, `ml`). For domain-specific units like "head" / "bag" / "jar",
  just say "+2"

**Recommendation:** third option. Cleanest.

### 4.2 "Tap the checkbox as you shop..." strip is redundant

Where: `templates/_shopping_list.html` (helper strip when items exist)
Size: **XS**

**What's wrong:** The heading subcopy already says "Tap the checkbox when
it's in the cart." The helper strip below then says "Tap the checkbox as
you shop. When you're home, tap I'm home →..." — reinforces the same idea
plus the I'm-home teach. On a first-visit that's helpful. On the 50th
visit that's clutter.

**Recommendation:** Only render the helper strip on the FIRST time a user
has any shopping items (mirrors the Phase 5D "one-shot signpost" pattern
you built for the pantry). Store a `has_seen_shopping_helper` flag in the
session; retire the strip after that.

### 4.3 Meals page — "Meal history" heading feels like archive

Where: `templates/meals.html`
Size: **XS**

**What's wrong:** "Meal history" reads as retrospective / "look back at
your past meals." The page's actual value is "here are ideas you could cook
again." The framing sells the feature short.

**Recommendation:** "Your meals" or "Cooked & planned" or just "Meals".
The subcopy already carries the "the AI has planned for your household"
context.

---

## 5. Density / hierarchy — P2

### 5.1 Above-the-fold planner is bigger than the actual pantry list

Where: `templates/pantry.html` — the whole `<section aria-labelledby="meal-plan-heading">` block
Size: **M**

**What's wrong:** On the stocked pantry (audit_05), the "Plan a meal"
section — heading + subcopy + 5 chips + nudge banner + input + submit +
spinner slot + last-meal teaser — takes ~40% of the initial viewport before
you see a single pantry item. It's a great feature but it's not what the
user came here for on visit N > 1. First visit yes; return visit no.

**Recommendation options:**
- Collapse the planner into a compact bar (`Plan a meal · [prompt input] · Ask AI`)
  when the household has at least 1 meal plan. The teaser card stays.
- Move the planner to a floating action button (FAB) at bottom-right,
  above the tab bar. Modal opens on tap.
- Keep it inline but move it BELOW the pantry list. Return visits will see
  the pantry first.

**Recommendation:** first option (compact bar with expand-on-tap). Preserves
the AI-first framing without letting the planner monopolize the fold.
Bigger chunk than the XS items above — leave for a later phase.

### 5.2 Chip strip on pantry has no visual anchor

Where: `templates/pantry.html` (the 5 prompt chips)
Size: **XS**

**What's wrong:** The chip row (Tonight's dinner / Quick / Vegetarian /
Comfort food / Use what we have) floats free of the input below. Feels
unconnected on scroll.

**Recommendation:** Group chips + input + submit into a single bordered
card the way the shopping quick-add bar is. Reads as one composed control.

---

## 6. Cross-cutting infrastructure — P2, deferred

### 6.1 Tailwind CDN causes ~300–600ms of white-flash on load

Where: `templates/base.html` (`<script src="https://cdn.tailwindcss.com">`)
Size: **M**

**What's wrong:** Loading Tailwind via CDN means the browser runs a JIT
compiler before painting. The `body { visibility: hidden }` + `load` event
show-hide dance minimizes flash but doesn't eliminate the delay. Real
mobile users on a train wi-fi experience this as "app takes a beat to
appear."

**Recommendation:** Switch to a real build. Two paths:
- Tailwind CLI in a tiny `npm run build` step — outputs a static
  `static/tailwind.css`. Adds a package.json + one build step.
- Just accept the flash — it's a personal side project, deploy overhead
  matters more than a 300ms flash.

**Recommendation:** Defer. Only take on when you have another reason to
add a build step.

### 6.2 No dark mode

Where: everywhere
Size: **M**

**What's wrong:** iOS + Android + browsers all offer dark mode. Tailwind
supports it out of the box (`dark:` variants). Right now the app is
light-only.

**Recommendation:** Real work — every color would need a `dark:` twin.
Defer until you feel it personally. Not a v1 priority.

---

## Ranked shortlist (my picks for the next 3 shipments)

If you asked "what next, in order?" — this is what I'd pull off the shelf:

1. ~~**§0.1** — Fix the checked-off shopping row's red-leak bleed. Bug. XS.~~ ✅ shipped 2026-07-20
2. ~~**§1.1** — Empty-pantry planner subcopy dedup.~~ ✅ shipped 2026-07-22
   / **§1.2** still open — hide search + household cards on empty pantry.
3. **§3.1 + §3.3** — Button `active:` state + longer Undo toast (7s).
   Both XS, both universally felt, one commit.

After those three the "next natural chunk" I'd reach for is one of:
- **§2.1** — Icon-only row actions (biggest visual density win, some risk
  of accessibility regression so wants care)
- **§1.3** — Shopping empty-state hero (mirrors an existing pattern; low
  risk)
- **§4.2** — First-visit shopping helper (leverages the Phase 5D nudge
  infra you already built)

---

## Anti-recommendations (things I explicitly do NOT recommend right now)

- **A full visual redesign.** The palette + rounded-2xl + max-w-md center-
  aligned column is coherent, mobile-first, and doesn't fight the content.
  Redesigning wholesale would be effort out of proportion to gain.
- **Adding a settings screen.** The density toggle + sort/filter pills all
  work as inline controls. Don't invent a page just for chrome.
- **Introducing a component library.** The Tailwind + template-macro
  approach fits this codebase's scale. A React/Vue/etc. refactor would be
  the wrong shape of investment.
- **Frame-perfect animations.** The htmx-added fade + toast slide are
  enough. Don't chase Framer Motion — a personal project doesn't need to
  feel like an art piece.

---

## Reference screenshots

Captured 2026-07-20 during the audit:

- `/tmp/audit_01_signup.png` — signup
- `/tmp/audit_02_pantry_empty.png` — empty pantry (hero + seed)
- `/tmp/audit_03_shopping_empty.png` — empty shopping (plain text)
- `/tmp/audit_04_meals_empty.png` — empty meals (dashed hero)
- `/tmp/audit_05_pantry_stocked.png` — pantry with 6 items, planner unlocked
- `/tmp/audit_06_shopping_populated.png` — shopping with 1 item
- `/tmp/audit_07_shopping_checked.png` — checked-off shopping (**bug visible**)
- `/tmp/audit_08_pantry_compact.png` — pantry compact-density variant
- `/tmp/audit_09_dupe_confirm.png` — shopping dupe-confirm card
- `/tmp/audit_10_login.png` — login
