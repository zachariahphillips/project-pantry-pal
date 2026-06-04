# PantryPal — Build Plan

A household-shared pantry + shopping list, mobile-first, with an AI meal planner that knows what you already have at home.

**Status:** Phase 0 done (2026-05-27). Phase 1A done (2026-05-28). Phase 1B done (2026-05-29). Phase 1C done (2026-06-01). Phase 2A done (2026-06-03). **Phase 2B done (2026-06-04) — magic-link invite/join flow shipped: alice can invite bob via a shareable URL, bob can sign up OR log in (existing-user switch) into alice's household.** Phase 2C (Fly.io deploy) is next.

---

## Vision

One pantry per household. Multiple people contribute from their own phones with their own accounts. Everyone sees the same view from any device. When you're ready to cook, ask the AI "what about pasta carbonara tonight?" — it checks your pantry, tells you what you already have, and adds what you're missing to the shopping list with one tap.

## Locked decisions (2026-05-27)

| Decision | Choice | Why |
|---|---|---|
| **Name** | PantryPal | Friendly and descriptive |
| **Folder + repo** | `project-pantry-pal` | Matches the `project-*` convention from Pawsitive Coach |
| **Backend** | Python + Flask | Same stack as Pawsitive Coach — minimize new tools |
| **Database** | SQLite for v1, Postgres later | Single file, zero infra to start; swap to Postgres (Supabase/Neon free) when deployed for the household |
| **Auth** | Flask-Login + bcrypt (email + password) | Simplest path; no third-party OAuth setup |
| **UI** | Jinja templates + Tailwind CSS (CDN) + a sprinkle of htmx or vanilla JS | Mobile-first responsive, no React build pipeline |
| **AI** | OpenAI GPT-4o-mini, JSON response mode | Reuse the same OpenAI account + JSON-output pattern from Pawsitive Coach |
| **"Feels like an app"** | PWA manifest + service worker | Installs on iPhone home screen, no App Store needed |
| **Hosting (Phase 2)** | TBD: Render vs Fly.io | Both have hobby free tiers; pick when Phase 2 lands |

---

## Phased build — each phase ends at a useful state

### Phase 0 — Setup (≈1 sitting) — DONE 2026-05-27

- Create folder, `git init`, push to GitHub as `project-pantry-pal`
- `.gitignore`, `.env.example`, `requirements.txt`
- Hello-world Flask app with one page
- Confirms it runs on `localhost:5001` (5000 is taken by Pawsitive Coach)

**End state:** project exists, runs, is on GitHub.

### Phase 1A — Auth foundation (1 sitting) — DONE 2026-05-28

- Email/password signup + login + logout via Flask-Login (session auth)
- `User` model + SQLAlchemy ORM on SQLite (db file lives at `instance/pantrypal.sqlite3`)
- Flask-WTF forms with global CSRF protection
- Password hashing: pbkdf2:sha256 via Werkzeug (NOT scrypt — see "Gotchas" below)
- App-factory pattern (`create_app()`) so models can import `db` without circular imports
- `base.html` shared layout (mobile-first, Tailwind CDN, 16px+ inputs to suppress iOS focus-zoom)
- 13-check end-to-end smoke test (signup, login, logout, wrong-password, duplicate-email)

**End state:** can sign up, sign in, sign out, see your name on `/home`.

### Phase 1B — Pantry CRUD (1 sitting) — DONE 2026-05-29

- `PantryItem` model (id, user_id, name, quantity, unit, notes, added_at) with cascade-delete on user
- `/pantry` list view: search, empty state (with separate "no matches" copy when filtering)
- Add via htmx (returns list partial; empty state vanishes correctly)
- Edit toggles a single row in/out of edit mode (htmx targets `closest li`-style — actually `#pantry-item-N` divs)
- Delete via real HTTP DELETE verb with `hx-confirm` and returns the refreshed list
- htmx loaded via CDN with subresource integrity; CSRF token forwarded on every request via `htmx:configRequest` listener in `base.html`
- Validation errors on add come back as a 422 fragment with `HX-Retarget`/`HX-Reswap` headers so in-progress input survives
- Quantity field is `FloatField` with `Optional()` — empty stays empty, no implicit zero
- Unit field has a `<datalist>` of common units (ea, g, kg, oz, lb, ml, l, cup, tbsp, tsp, cans, boxes, bags, bunches)
- 20-check end-to-end smoke test including user isolation (alice's items 404 for bob)
- `home.html` retired — auth flows now redirect to `/pantry`

**End state:** working personal pantry tracker, htmx-driven, accessed via phone over LAN.

### Phase 1C — Shopping list CRUD (1 sitting) — DONE 2026-06-01

- `ShoppingItem` model (id, user_id, name, quantity, unit, notes, checked, added_at) with cascade-delete on user; sorted unchecked-first then newest-first
- `ShoppingItemForm(PantryItemForm)` — same fields today, separate class so pantry-only (expiry, location) or shopping-only (priority, store) fields can land in Phase 4 without coupling
- `/shopping` — list, add, edit, delete (mirrors the Phase 1B pantry routes; same htmx + 422-with-retarget pattern for validation errors)
- `POST /shopping/<id>/toggle` — single checkbox tap flips `checked`; response re-renders the whole list so checked items slide to the bottom
- `POST /shopping/clear-checked` — bulk-delete all checked items behind an `hx-confirm` (guards against an accidental swipe wiping the list)
- `POST /pantry/<id>/add-to-shopping` — copies a pantry row (name/qty/unit, but **not** notes — notes are pantry-context) into the shopping list and returns `200`/empty with `HX-Trigger: shopping:added`; pantry row is left alone
- Bottom tab bar (Pantry / Shopping) in `base.html`, only rendered when authenticated; honors `env(safe-area-inset-bottom)` for iPhone notches; active tab uses green text + `aria-current="page"`; main content gets `pb-28` to clear the bar
- Global toast slot (`#toast`) listens for the `shopping:added` event and shows "Added to shopping list" for ~1.8s. Belt-and-suspenders: the `+ Shop` button itself also flips its label to "Added" for 1.5s via `hx-on::after-request` so feedback works even if the toast listener has a hiccup.
- 38-check end-to-end smoke test (one-off, live server) covering: shopping CRUD, check-off + auto-reorder + strikethrough, toggle-back-off, clear-checked, the `+ Shop` cross-link (including the deliberate "two taps = two rows" no-dedupe behavior), pantry-row notes NOT carrying over, tab bar active states, tab bar hidden when logged out, full user isolation across BOTH lists, and search-with-no-matches empty state
- **Regression suite committed:** `tests/test_phase_1c.py` — 30 pytest cases (~12s wall time) built on Flask's test client, no live server needed. Per-test SQLite file via `tmp_path`, real CSRF tokens scraped from the rendered `<meta name="csrf-token">`. Grouped into 6 test classes so a failure points at the exact behavior that regressed. Run: `.venv/bin/pytest tests/ -v`. Phase 1A/1B retroactive coverage can land in Phase 2 prep.

**End state:** Phase 1 complete — solo pantry + shopping list + one-tap cross-link on your phone, with a clean two-tab bottom nav AND a pytest regression suite guarding the behavior.

### Phase 2A — Households data model (1 sitting) — DONE 2026-06-03

- New `Household` model (id, name, created_at) + `User.household_id` FK
- Items are now owned by the **household** (new `pantry_items.household_id` + `shopping_items.household_id` columns)
- The pre-Phase-2A "ownership" column `user_id` on items is semantically retired to **provenance** ("who added this") — Python attribute renamed to `added_by_user_id` via `db.Column("user_id", …)` so the DB column name stays `user_id` and the migration is purely **additive** (no destructive ALTERs, no renames)
- New `Household.pantry_items` / `Household.shopping_items` relationships replace `User.pantry_items` / `User.shopping_items` in the routes; `User.added_pantry_items` / `User.added_shopping_items` keep the "what did I add?" view for the seed script and future "your contributions" UIs
- `_get_pantry_item_or_404` / `_get_shopping_item_or_404` ownership check changed from `item.user_id == current_user.id` to `item.household_id == current_user.household_id` — a roommate who didn't add the item can still edit + delete it
- **Auto-migration on startup** (`_run_phase_2a_migration` in `app.py`, called from `create_app()`): idempotent backfill that
  1. Calls `_ensure_phase_2a_columns` which uses SQLAlchemy's `Inspector` + raw `ALTER TABLE … ADD COLUMN` to add the `household_id` FK columns on `users` / `pantry_items` / `shopping_items` when they're missing (because `db.create_all()` only creates missing **tables**, never adds columns)
  2. Gives every user with `household_id IS NULL` a "household of one" named `"<First name>'s home"`
  3. Sets each orphan item's `household_id` to its `added_by` user's household
- Signup route auto-creates a household (same shape as the migration's "household of one"); Phase 2B will branch here on an optional `?invite=<token>` to join an existing household instead
- `+ Shop` cross-link records the **tapper** as `added_by_user_id`, not the original pantry adder — so "alice put olive oil in pantry, bob tapped +Shop on his shopping run" attributes correctly
- "added by [name]" stamp on pantry + shopping rows, **hidden when added_by == current_user** (avoids "added by you" noise in solo households)
- `seed.py` updated: each test user gets a household-of-one explicitly (doesn't depend on migration ordering); re-running wipes only items the test user **added**, never other household members' items
- **Regression suite expanded:** `tests/test_phase_2a.py` — 13 pytest cases (~9s) in 5 classes covering signup→household auto-create, item provenance fields, shared-household visibility/edit/delete/toggle (stitched via direct DB write since the invite UI is Phase 2B), `+ Shop` provenance correctness, "added by" stamp visibility rules, and a full Phase-1C-to-2A schema-evolution migration test (builds a 1C-shaped SQLite by hand, boots create_app, asserts ALTER + backfill + idempotence). All 30 Phase 1C tests still green — the data model swap is transparent at the route level.
- **End-to-end smoke against the real dev DB:** killed the stale Flask servers (they had auto-reloaded against partial Phase 2A code and created a half-migrated state), restored from the pre-2A backup, booted fresh, logged in as alice from yesterday's password, all 5 pantry + 3 shopping items survived with their `checked` state, "added by" stamp correctly hidden, new item add still works.

**End state:** items are now properly household-owned with provenance. No invite UI yet, so every household is still a household-of-one in production. Phase 2B closes that gap.

### Phase 2B — Invite / join flow (1 sitting) — DONE 2026-06-04

- `Invite` model: `token` (22-char URL-safe via `secrets.token_urlsafe(16)`), `household_id`, `created_by_user_id`, `created_at`, `expires_at` (default 7 days), `max_uses` (default 10), `used_count`. Tunable defaults live as module-level constants in `models.py` so a future "single-use link" feature is one keyword away. `is_active()` checks both expiration AND uses-remaining; `reason_inactive()` returns the specific failure copy so the landing page can be specific rather than just "invalid"
- `POST /household/invite` mints; `DELETE /household/invite/<id>` revokes. Both return the refreshed `_household_share.html` partial via htmx so the share card updates in place
- New "Household" card at the bottom of `pantry.html` (`_household_share.html` partial): household name, member list (or "Just you for now — invite a roommate"), an "Invite" button, and an inline list of active invites with a read-only URL input (tap to select), Copy button (uses `navigator.clipboard.writeText`), and Revoke button. Each invite shows uses-left + expiry date
- `GET /join/<token>` — single template handling **three states**:
  - **Anonymous:** "[Creator] invited you to '[Household]'. [Create account & join] / [Sign in to join]" — both CTAs forward `?invite=<token>` so the token survives the auth round-trip without needing session state
  - **Already-member:** "You're already in '[Household]'" + an "Open pantry" CTA
  - **Switch-confirm (logged into a different household):** "Join '[Target]'? You're currently in '[Current]'. Switching is non-destructive — your previous items stay saved." Two buttons: confirm + cancel
  - Bad/expired/used-up token: error template with the specific reason; HTTP `404` for unknown tokens, `410 Gone` for expired/exhausted (gives bots / link-checkers a precise signal)
- `POST /join/<token>` — logged-in confirmation step. Swaps `user.household_id`, calls `invite.consume()` (increments `used_count`), commits, flashes "Joined '[Target]'. Your previous household '[Old]' and its items are still saved." The flash banner replaces the toast hook for this case — page navigates fully, toast hook only fires on in-page htmx responses
- `/signup` now accepts `?invite=<token>`: browsers POST forms back to the current URL by default (no `action=` attribute on the form), so the token query-string survives GET→POST without a hidden field — that's a feature, not an accident. On success: if the invite is valid → set `user.household_id` to the invited household + `consume()` the invite + skip the household-of-one mint. If the token is stale by the time signup happens → fall back to household-of-one + flash a non-blocking warning (don't block account creation just because someone took 8 days to click the link)
- `/login` accepts `?invite=<token>`: after successful login, redirects to `/join/<token>` (the switch-confirm landing) rather than directly mutating the household. Same fallback: if invite is dead by the time they log in, the redirect still lands them on the join page which shows the specific failure reason. Already-authenticated users hitting `/login?invite=<token>` short-circuit straight to `/join/<token>`
- Cross-household isolation preserved: bob can't `DELETE /household/invite/<id>` on alice's invite — returns **404** (not 403) so we don't leak existence of other households' invites
- **No destructive merge:** when a user switches households, their old household + items remain intact in the DB. They lose visibility, but if they ever switch back the data is still there. We can layer a "delete my old empty household" affordance later — for v1 the safer default is keep everything
- **Regression suite expanded:** `tests/test_phase_2b.py` — 16 pytest cases in 6 classes, covering: render share card / mint via htmx / revoke / cross-household revoke 404, anonymous landing / unknown 404 / expired 410 / used-up 410, already-member landing / switch-confirm landing, full switch commit (bob → alice's household, with alice's existing items now visible to bob AND bob's old household preserved in DB), expired-on-POST flash, signup-with-invite (joining the invited household, no Bob's-home minted), stale-token-on-signup falls back to household-of-one, login-with-invite redirect to `/join/<token>`, login template forwards token to signup link. All 30 Phase 1C + 13 Phase 2A tests still green. Total: **59 tests, 30s wall time**

**End state:** real shared households over a shareable URL. The app is finally useful for more than one person — alice can put olive oil in the pantry from her phone, bob can see it from his phone and tap "+Shop" if they're out. Still localhost-only; Phase 2C deploys it.

### Phase 2C — Deploy to Fly.io (1 sitting)

- Dockerfile + Gunicorn + Fly volumes for SQLite persistence (Fly's free tier + a small persistent volume keeps Phase 2 hosting at $0/mo)
- `fly secrets set FLASK_SECRET_KEY=…`
- Test against Riah's phone over the public URL
- PWA manifest + service worker (so "Add to Home Screen" feels native) is the natural Phase 2C polish

**End state:** you and your household share a real, hosted pantry app at a `*.fly.dev` URL.

### Phase 3 — AI meal planning (2–3 sittings)

- "I want to make ___" prompt input on the home screen
- Backend sends GPT-4o-mini: the user's prompt + a structured snapshot of the household's pantry
- AI returns JSON: `meal_name`, `have` (items in pantry that work), `need` (items to buy), `steps`
- One tap on any `need` item adds it to the shopping list
- Reuse the JSON-output pattern from `../project-pawsitive-coach/app.py` (look for `response_format={"type": "json_object"}`)

**End state:** the app described in the original idea.

### Phase 4+ — Power-ups (build what excites you, no required order)

- **Barcode scanning** — phone camera + Open Food Facts API → instant pantry add
- **Receipt OCR** — photograph receipt, AI parses → bulk pantry add
- **Expiry tracking** — mark items with expiry, see "use it soon" list
- **AI suggests recipes** based on what's expiring (no prompt needed)
- **Push notifications** via PWA push API
- **Cost-split tracking** — who bought what
- **Voice input** — "add 2 cans of black beans" while loading groceries

---

## Data model (first cut — locked for Phase 1, evolves in Phase 2)

```text
users
  id              integer  primary key
  email           text     unique not null
  password_hash   text     not null
  name            text
  household_id    integer  foreign key (added in Phase 2)
  created_at      datetime

households                                       -- Phase 2
  id              integer  primary key
  name            text
  invite_code     text     unique
  created_at      datetime

pantry_items
  id              integer  primary key
  household_id    integer  -- Phase 1: user_id; Phase 2: rename to household_id
  name            text     not null
  quantity        real
  unit            text     -- "ea", "g", "ml", "cans", "lbs", etc.
  notes           text
  added_by_user_id integer
  added_at        datetime

shopping_items
  id              integer  primary key
  household_id    integer  -- Phase 1: user_id; Phase 2: rename to household_id
  name            text     not null
  quantity        real
  unit            text
  checked         boolean  default false
  added_by_user_id integer
  added_at        datetime

meal_plans                                       -- Phase 3
  id              integer  primary key
  household_id    integer
  user_id         integer
  prompt          text
  response_json   text     -- raw JSON the AI returned
  created_at      datetime
```

**Migration note:** in Phase 1 we'll attach pantry + shopping items to `user_id`. In Phase 2 we'll add `households`, set every existing user as their own household of one, then rename the foreign key. SQLite makes this a one-script migration.

---

## Why this build order (defend the choices)

- **Phase 1 before AI** — forces us to nail data + auth without the distraction of the LLM. Boring but load-bearing.
- **Phase 2 before AI** — multi-user shared state is the *real* technical risk of this app. Doing it before AI means the AI feature lands in an app that already works for the household.
- **Phase 3 is mostly a port** of the Pawsitive Coach JSON-response pattern, so by the time we get there it should feel fast.
- **Phase 4 is à la carte** — once the core works, each power-up is independent and skippable.

---

## Open questions (deferred — answer at the phase they affect)

1. **Hosting** — Render vs Fly.io. Decide at Phase 2 deploy.
2. **SQLite on Fly volumes vs. moving to Postgres** at Phase 2. Default: stay on SQLite until it actually hurts.
3. **Real-time sync** — polling is fine for v1. If usage shows it's annoying, look at server-sent events or a tiny websocket layer in Phase 4.
4. **AI cost guardrails** — add a per-user-per-day meal-plan call limit in Phase 3 if usage spikes.
5. **Native app** — only revisit if PWA limitations actually bite. Expo / React Native is a full rewrite of the frontend.

---

## Reference repo

The Pawsitive Coach sibling project is at `../project-pawsitive-coach`. Pattern reuse opportunities:

- **Flask app skeleton + env loading** — `app.py` lines 1–29
- **OpenAI JSON-mode call + error handling** — `app.py` lines 142–179
- **Session-based state** (we'll replace this with Flask-Login + a real DB, but the request handling shape carries over)
- **Mobile-friendly chat UI** — `templates/index.html` (worth scanning for layout patterns)

---

## Gotchas (learned the hard way, don't relearn)

- **`hashlib.scrypt` missing on macOS system Python.** Python 3.9 shipped with macOS links against LibreSSL, which doesn't include `hashlib.scrypt`. Werkzeug 3.x defaults to scrypt for password hashing, which crashes with `AttributeError`. Fix: pass `method="pbkdf2:sha256"` to `generate_password_hash`. See `models.py::set_password`.
- **`csrf_token()` in templates needs `CSRFProtect`.** Flask-WTF's `form.hidden_tag()` only embeds a token in *its own* form. For ad-hoc forms (like the logout button in `base.html`), you need to call `csrf_token()` directly, which only exists if `CSRFProtect` is initialized on the app. We do this in `extensions.py` and `create_app()`.
- **SQLite db lives at `instance/pantrypal.sqlite3`, not the project root.** Flask-SQLAlchemy resolves relative `sqlite:///` URIs against `<app>/instance/`. Already gitignored. To reset the db: `rm instance/pantrypal.sqlite3` AND restart the server (connection pool keeps the deleted file's inode alive otherwise).
- **Port 5001, not 5000.** Pawsitive Coach owns 5000 so you can run both side by side.
- **gh active account flips between work and personal.** `gh auth git-credential` always returns the *active* account's token, so a `git push` to a personal repo fails with "denied to zphil1_nike" whenever the active account is the work one. Fix: this repo's local git config pins the credential helper to `gh auth token --user zachariahphillips`, which always returns the personal token regardless of which account is active. See README "Quick start" for the one-liner to apply on a fresh clone.
- **Flask-WTF CSRF needs the X-CSRFToken header for body-less verbs (DELETE).** htmx fires `htmx:configRequest` on every request and the listener in `base.html` adds the header automatically — but any smoke test or external client also needs to send it, otherwise DELETE returns `400 The CSRF token is missing.` Our test script (re-)pulls the per-session token from the `<meta name="csrf-token">` tag.
- **Never `rm instance/pantrypal.sqlite3` while the dev server is running.** SQLAlchemy's pool keeps the deleted-inode file open and subsequent writes fail with `attempt to write a readonly database` (the directory inode for the recreated file ends up unwritable). Always stop the server *first*, then wipe.
- **Smoke-test assertions: prefer presence of the action button over substring matches on shared phrases.** First Phase 1C run failed on `"checked off" not in body` because the row's `aria-label="Toggle 'X' checked off"` matched as a false positive. The clean assertion is `"Clear checked" not in body` (looking for the button that only renders when there's something to clear) rather than the count-summary text.
- **Counting rows in rendered HTML: don't rely on `>{{ item.name }}<`.** Jinja preserves whitespace inside `<p>` tags, so the rendered text is `<p>\n  Olive oil\n</p>` — there's no literal `>Olive oil<` to match. Count `id="shopping-item-N"` (or the analogous prefix) instead.
- **`+ Shop` is intentionally NOT idempotent.** Two taps create two shopping rows. The smoke test asserts this so a future refactor that adds dedupe doesn't sneak through. If a real user complains, the right fix is a confirmation/merge UX, not silent dedupe.
- **Cascade ordering on `User.shopping_items`** uses `ShoppingItem.checked.asc(), ShoppingItem.added_at.desc()`. SQL `FALSE` sorts before `TRUE`, so unchecked items appear first; within each group, newest-first. SQLAlchemy passes this string directly to the SQL ORDER BY, so don't try to reach for Python booleans here.
- **Toast event listener is on `document`, fires on `shopping:added`.** Anywhere you want to flash a toast from an htmx response, return an `HX-Trigger: <event-name>` header. The existing listener can be reused for other events (Phase 2: `household:joined`, Phase 3: `meal:planned`) by adding sibling handlers in `base.html`.
- **`db.create_all()` is NOT a migration tool — it only creates missing TABLES, never adds COLUMNS.** Hit during Phase 2A: I added `household_id` FK columns to existing `User` / `PantryItem` / `ShoppingItem` models and assumed startup would pick them up. It didn't — the new `households` table got created, but `users.household_id` / `pantry_items.household_id` / `shopping_items.household_id` were silently absent and every query against `current_user.household_id` returned `None`. Fix: explicit `ALTER TABLE … ADD COLUMN` via `db.inspect(db.engine).get_columns(...)` to detect missing columns + `conn.exec_driver_sql(...)`. See `_ensure_phase_2a_columns` in `app.py`. When schema evolves again (Phase 2B `Invite` table, Phase 3 `meal_plans` table — those are pure new-tables and create_all DOES handle them), still no need for Alembic. But the moment we add a column to an existing table, we need an explicit ALTER again.
- **Flask debug-mode auto-reload runs `create_app()` on every file save**, which means any migration logic in `create_app()` runs against the real dev DB the moment a model file is touched — even mid-edit. Hit during Phase 2A: a Flask dev server I'd left running yesterday auto-reloaded into a half-finished Phase 2A model (households table existed, household_id columns didn't) and persisted that state in the live DB. Fix going forward: when starting destructive-ish schema work, **stop the dev server first** (the same rule as wiping the SQLite file). Also: `lsof -t -i :5001 | xargs -r kill` finds zombie servers on the dev port.
- **DON'T rename the `user_id` DB column when its meaning changes — just rename the Python attribute.** Phase 2A re-purposed the items' `user_id` column from "ownership" to "provenance" (who added it). SQLite supports column renames since 3.25, but `ALTER TABLE … RENAME COLUMN` is irreversible if any code still queries the old name. Cleaner: `db.Column("user_id", db.Integer, …)` lets the Python attribute (`added_by_user_id`) be one thing while the DB column stays `user_id`. Zero DB risk, the migration becomes purely additive (new `household_id` column on each table + new `households` table). Same trick applies whenever a column's meaning evolves: keep the DB name, rename the Python attribute via `db.Column("legacy_name", …)`.
- **Re-seeding a SHARED household should never `delete()` items by household.** `seed.py` originally wiped `user.pantry_items` (the dynamic relationship) — in Phase 2A that semantic shifted to "the household's items." If alice and bob end up in the same household (Phase 2B), wiping alice's spec'd items would also wipe bob's contributions. Fix: seed wipes only `user.added_pantry_items` / `user.added_shopping_items` (items the user PERSONALLY added). Safe in solo + shared households. Same principle for any "reset my data" UI we build later.
- **Provenance backref needs `foreign_keys=` because the model has TWO FKs to `users`.** Wait — actually it only has ONE FK to users (`added_by_user_id`) and one FK to households. SQLAlchemy CAN auto-detect this, but I declared `foreign_keys="PantryItem.added_by_user_id"` on `User.added_pantry_items` anyway as future-proofing: if Phase 2B+ adds a `last_edited_by_user_id` column, the relationship still resolves correctly without breaking.
- **"added by [name]" stamp is hidden when added_by == current_user.** Conditional in `_pantry_item.html` and `_shopping_item.html`: `{% if item.added_by and item.added_by.id != current_user.id %}`. The `item.added_by and` short-circuit is paranoia for an orphan row (no `added_by_user_id` somehow), shouldn't ever fire in practice — but means a malformed row renders blank instead of crashing the whole list.
- **Jinja autoescape turns `'` into `&#39;` in the rendered HTML.** First Phase 2B test run had 6 failures all of the form `assert "Alice's home" in body` — the body actually contained `Alice&#39;s home`. Don't disable autoescape (XSS risk). Don't rename test households to avoid apostrophes (the production household names will have them too). Fix: small test helper `_body(resp) = html.unescape(resp.get_data(as_text=True))` that decodes entities for assertion purposes only. The HTTP response keeps the entities — that's the secure default. See `tests/test_phase_2b.py`.
- **Browsers POST forms back to the current URL (including the query string) when the `<form>` has no `action=`.** Used this deliberately in Phase 2B: `/signup?invite=<token>` POSTs to `/signup?invite=<token>`, so the token survives the auth round-trip without a hidden field, without a session-stashed value, without anything. The route reads `request.args.get("invite")` on both GET and POST. The "Already have an account? Sign in" link in the template explicitly forwards the token (since `<a>` doesn't auto-inherit the query string). Same trick works for any one-shot context token that needs to survive a single form submit.
- **HTTP 410 Gone is the right status for expired/used-up invites; 404 is the right status for unknown tokens.** `404` says "this URL doesn't address anything"; `410` says "this URL DID address something but it's been retired." Link checkers (e.g. Slack's URL unfurler) treat them differently — 410 is a hint to never re-check, 404 might be a transient miss. Tiny detail but free correctness.
- **Don't auto-delete a user's old household when they accept an invite.** v1 keeps the orphan household + its items intact in the DB so the user can switch back without data loss. The trade-off is some clutter in the DB; cleanup is a Phase 2C+ concern. The flash message on join explicitly says "your previous household '[X]' and its items are still saved" so the user knows nothing was destroyed.
- **CSRF token via `csrf_token()` (not `form.hidden_tag()`) on the join-confirm form.** The `/join/<token>` page isn't a Flask-WTF form — it's a single confirm button — so I render the token directly with `<input type="hidden" name="csrf_token" value="{{ csrf_token() }}" />`. This works because `CSRFProtect.init_app(app)` exposes `csrf_token()` as a template global (same as the existing logout button in `base.html`). Don't reach for a fake WTForm just to get `hidden_tag()` — direct call is cleaner.
- **Invite uniqueness via `db.Column(unique=True)`, not application-level checks.** `secrets.token_urlsafe(16)` has ~10^38 keyspace, so collisions are vanishingly unlikely, but the DB-level uniqueness constraint catches the impossible case AND it's free. Phase 2C deploy gets a periodic cleanup job that deletes invites where `expires_at < now() - 30 days`; for now they just accumulate (negligible space).
- **`invite.consume()` increments `used_count` but doesn't commit — caller commits.** Pattern from the signup + join routes: `invite.consume(); db.session.commit()` (the latter commits other changes alongside). Decouples "what does consume mean" from "when do we commit," which made the stale-invite-fallback in signup much cleaner to write. If we ever go multi-worker we'll wrap the read + write in a transaction with `SELECT … FOR UPDATE`; for SQLite + single-process gunicorn (Phase 2C plan), it's fine.
