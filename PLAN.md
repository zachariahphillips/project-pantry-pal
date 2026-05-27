# PantryPal — Build Plan

A household-shared pantry + shopping list, mobile-first, with an AI meal planner that knows what you already have at home.

**Status:** Planning. No code yet. Phase 0 starts when Riah says "let's start Phase 0."

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

### Phase 0 — Setup (≈1 sitting)

- Create folder, `git init`, push to GitHub as `project-pantry-pal`
- `.gitignore`, `.env.example`, `requirements.txt`
- Hello-world Flask app with one page
- Confirm it runs on `localhost:5000`

**End state:** project exists, runs, is on GitHub.

### Phase 1 — Solo pantry + shopping list (2–3 sittings)

- Email/password signup + login (Flask-Login + bcrypt)
- Pantry: add / edit / delete / search items (name, quantity, unit, added date, notes)
- Shopping list: add / check off / clear checked
- Mobile-first single-column UI with big tap targets (44pt+ minimum)
- Run locally, open on your phone via your laptop's LAN IP

**End state:** a working personal pantry tracker, no AI yet, no households yet.

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
