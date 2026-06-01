# PantryPal — Build Plan

A household-shared pantry + shopping list, mobile-first, with an AI meal planner that knows what you already have at home.

**Status:** Phase 0 done (2026-05-27). Phase 1A done (2026-05-28). Phase 1B done (2026-05-29). **Phase 1C done (2026-06-01) — Phase 1 is complete.** Phase 2 (households + deploy) starts when Riah says "let's start Phase 2."

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
- 38-check end-to-end smoke test covering: shopping CRUD, check-off + auto-reorder + strikethrough, toggle-back-off, clear-checked, the `+ Shop` cross-link (including the deliberate "two taps = two rows" no-dedupe behavior), pantry-row notes NOT carrying over, tab bar active states, tab bar hidden when logged out, full user isolation across BOTH lists, and search-with-no-matches empty state

**End state:** Phase 1 complete — solo pantry + shopping list + one-tap cross-link on your phone, with a clean two-tab bottom nav.

### Phase 2 — Households (the real multi-user piece) (2–3 sittings)

- New `households` table — a user belongs to one household
- Pantry + shopping list now belong to the **household**, not the user
- Invite flow: a household generates a short invite code; another user signs up and enters it to join
- "Last edited by [name]" stamps on items
- Simple sync: refresh on app focus + optional poll every 10s (good enough for v1; websockets can come later)
- Deploy to Render or Fly.io so household members can actually use it on their own phones

**End state:** you and your household share a real, hosted pantry app.

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
