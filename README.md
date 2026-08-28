# PantryPal

A household-shared pantry and shopping list, mobile-first, with an AI meal planner that knows what you have at home.

**Status:** Phase 7K current — the Phase 6 mobile UX improvement plan is closed out, with every non-deferred audit item shipped and the remaining Tailwind build/dark-mode work intentionally deferred. PantryPal now has household sharing, pantry + shopping CRUD, duplicate-confirm/merge flows, undo toasts, AI meal planning with daily cost guardrails, meals history, onboarding gates, focused mobile polish across the main tabs, a DB-backed `/healthz` check for deploy readiness, in-flight disabling on Ask AI planner buttons, proactive Ask AI disablement when daily quota is exhausted, GitHub Actions running the pytest suite on push/PR, PWA manifest/icon metadata for home-screen installs, SQLite busy-timeout/WAL hardening, production cookie hardening, deploy smoke checks for cookie flags, a post-deploy smoke runbook, and a SQLite backup/restore runbook. Full regression is **602 pytest tests** green.

## The idea in one paragraph

One pantry per household. Multiple people contribute from their own phones with their own accounts. Everyone sees the same view from any device. When you're ready to cook, ask the AI "what about pasta carbonara tonight?" — it checks your pantry, tells you what you already have, and adds what you're missing to the shopping list with one tap.

## Stack

Python + Flask · SQLite (→ Postgres later) · Flask-Login · Tailwind CSS via CDN · htmx · OpenAI GPT-4o-mini · PWA manifest/icons for home-screen installs.

## Quick start

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then fill in FLASK_SECRET_KEY + OPENAI_API_KEY
python -c "import secrets; print(secrets.token_hex(32))"  # paste output into FLASK_SECRET_KEY
# OPENAI_API_KEY: reuse the same key from project-pawsitive-coach, or grab one
# at https://platform.openai.com/api-keys. Without it, the meal-planner UI still
# renders but POST /meal-plan returns a friendly 502 ("AI is taking a nap").
python app.py
```

Open <http://localhost:5001>. Health check at <http://localhost:5001/healthz>.
Run the full local suite with `python -m pytest -q`; CI runs the same command on pushes and pull requests.

Port 5001 is intentional — Pawsitive Coach uses 5000, so both can run side by side.

To run it on your phone while developing, find your laptop's LAN IP (`ipconfig getifaddr en0` on macOS) and open `http://<that-ip>:5001` on the phone (same Wi-Fi).

### Test accounts (seed script)

For quick dev work you don't have to re-signup every time. Run:

```bash
.venv/bin/python seed.py
```

This (re-)creates two test accounts with sample pantry + shopping data. Your real accounts are untouched.

| Email | Password | Household (Phase 2A) |
|---|---|---|
| `alice@example.com` | `testpass123` | "Alice's home" (solo for now) |
| `bob@example.com`   | `testpass123` | "Bob's home" (solo for now) |

(`example.com` is the RFC 2606 reserved test domain. `*.local` doesn't work — `email_validator` rejects it as a reserved mDNS TLD.)

Re-running the script wipes only the items **each test user personally added** (NOT the rest of their household), so once Phase 2B's invite UI lands you can safely re-seed even when alice + bob are roommates. For a full reset: stop the server, `rm instance/pantrypal.sqlite3`, restart.

### Inviting a roommate (Phase 2B)

Scroll to the bottom of the pantry page — there's a "Household" card with your household name and member list. Tap **+ Invite** to mint a shareable link of the form `http://<host>/join/<token>`. Tap "Copy" and send it however you'd like.

When your roommate opens the link:

- **If they don't have a PantryPal account yet:** they see "[Your name] invited you to '[Your household]'" with a Create-account-and-join button. After signup they land directly in your household (no separate "household of one" is created for them).
- **If they already have an account:** they sign in via the same link and see a confirm step: "Switch from '[their current household]' to '[your household]'?" Their previous household + items stay in the DB (non-destructive) so they can switch back later if needed.

Invites default to **10 uses, 7-day expiration**. Both are tunable in `models.py` (`INVITE_DEFAULT_MAX_USES`, `INVITE_DEFAULT_TTL_DAYS`). You can revoke any active invite from the card.

### Tuning the AI meal planner (Phase 3C+)

Two optional env vars control the meal planner's cost + behavior. Both are read **lazily** (per-request, not per-boot), so `fly secrets set` takes effect on the next request — no restart needed.

| Env var | Default | What it does |
|---|---|---|
| `MEAL_PLAN_MODEL` | `gpt-4o-mini` | OpenAI model. Swap to `gpt-4o` for higher quality at ~6x the cost. Blank/whitespace is treated as "unset" and falls back to the default. |
| `MEAL_PLAN_DAILY_LIMIT` | `20` | Hard cap on `POST /meal-plan` calls per user per UTC day. The 21st call returns `429` with a friendly "limit resets at midnight UTC" message — without ever invoking OpenAI, so you don't pay tokens on the rejection. Garbage values (non-numeric / 0 / negative) silently fall back to the default rather than locking users out. |

```bash
# Tighten the cap to 5/user/day:
fly secrets set MEAL_PLAN_DAILY_LIMIT=5

# Upgrade to gpt-4o for the household:
fly secrets set MEAL_PLAN_MODEL=gpt-4o
```

#### Watching your spend

`GET /cost` (login required) returns JSON with today's call counts + estimated USD spend:

```bash
curl -b <auth-cookie> https://<your-app>.fly.dev/cost | jq
# {
#   "phase": "7K",
#   "model": "gpt-4o-mini",
#   "your_calls_today": 3,
#   "your_daily_limit": 20,
#   "your_calls_remaining": 17,
#   "household_calls_today": 7,
#   "estimated_spend_today_usd": 0.007,
#   "estimated_cost_per_call_usd": 0.001,
#   "reset_at": "00:00 UTC daily"
# }
```

The estimated spend is back-of-the-envelope ($0.001/call at gpt-4o-mini's typical token usage). Per-row token accounting is a Phase 4+ feature; for now this is enough to confirm "am I about to blow $50 today?" with a single curl.

#### When OpenAI is having a bad day

OpenAI errors now map to distinct user messages + HTTP status codes:

| Failure | User sees | HTTP |
|---|---|---|
| Rate-limited by OpenAI | "The AI is busy right now. Wait a minute and try again." | 503 |
| Network / DNS / TLS issue | "Couldn't reach the AI right now…" | 502 |
| Request timed out (>30s) | "The AI took too long to respond…" | 504 |
| API key invalid / unset | "PantryPal's AI is misconfigured. Please contact the app admin…" (logged at `ERROR` so you actually see it) | 500 |
| Malformed JSON response | "The AI got tongue-tied. Try again…" | 502 |
| Anything else | "The AI is taking a nap. Try again in a moment." | 502 |

### iPhone autofill (Keychain) + "Stay signed in"

Two things make logging in on your phone painless:

1. **Keychain saves your password.** The forms use the standard autofill attributes (`autocomplete="new-password"` on signup, `autocomplete="current-password"` on login), so iOS will offer to save your password the first time you sign up, and to autofill it on every later sign-in. If Safari doesn't prompt, double-check that **Settings → Passwords → AutoFill Passwords** is on.
2. **"Keep me signed in" defaults to ON.** Flask-Login issues a 365-day remember-me cookie so closing the tab / rebooting your phone doesn't sign you out. Uncheck it on a shared device.

To make PantryPal feel like a native app on your phone, use Safari's **Share → Add to Home Screen**. PantryPal ships a manifest and app icons so home-screen installs use the right name, color, and launcher artwork.

## Deploy to Fly.io (Phase 2C)

The app ships with everything you need to deploy: a `Dockerfile` (gunicorn-based, single worker so SQLite stays single-writer), a `.dockerignore` that keeps your local DB + venv out of the image, and a `fly.toml` with sensible Hobby-tier defaults (region `sea`, persistent volume at `/data`, auto-stop machines so cold starts are free).

### One-time setup

```bash
# 1) Install flyctl (Mac)
brew install flyctl

# 2) Sign up + log in (opens browser). Add a credit card during signup
#    even on the free tier; Fly won't charge you within the hobby limits
#    but they require one on file.
fly auth signup    # OR: fly auth login   if you already have an account

# 3) Pick a Fly app name. App names are GLOBAL across Fly, so `pantrypal`
#    is taken; the placeholder in fly.toml is `pantrypal-riah`. Edit that
#    line if you want something different.

# 4) Provision the app (uses the existing fly.toml — does NOT generate
#    a new one). Skip the optional Postgres/Redis prompts.
cd ~/personal-projects/project-pantry-pal
fly launch --no-deploy --copy-config --name pantrypal-riah --region sea

# 5) Create the persistent SQLite volume (1 GB is plenty — pantry data is
#    tiny). Region MUST match fly.toml's primary_region.
fly volumes create data --region sea --size 1

# 6) Set the Flask secret key as a Fly secret (NOT in fly.toml).
#    Generate a strong one with Python and pipe it straight in:
fly secrets set FLASK_SECRET_KEY="$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
```

### Deploy

```bash
fly deploy        # builds the Docker image remotely on Fly's builder
                  # (no local Docker required), runs the auto-migration
                  # on boot, and routes traffic to the new machine.
```

After a successful deploy, `fly status` shows the machine state and `fly logs` tails server logs. The app lives at `https://pantrypal-riah.fly.dev` (replace with your chosen name).

### Post-deploy smoke check

Run the smoke script after deploys that touch auth, cookies, database boot, invites, or core pantry/shopping flows. It signs up randomized throwaway users, adds a pantry item, mints an invite, joins a roommate into the household, verifies shared visibility, and checks hardened cookie flags when pointed at HTTPS.

```bash
# Local gunicorn smoke, useful before deploying. Cookie hardening checks are skipped
# because the local target is plain HTTP.
rm -f /tmp/pantrypal-prod-smoke.sqlite3
DATABASE_URL=sqlite:////tmp/pantrypal-prod-smoke.sqlite3 \
  FLASK_SECRET_KEY=secret \
  .venv/bin/gunicorn --bind 127.0.0.1:8080 \
  --workers 1 --threads 4 'app:app'

# In another terminal:
.venv/bin/python scripts/prod_smoke.py
```

```bash
# HTTPS deploy smoke, including Phase 7I cookie flag checks.
BASE=https://<your-app>.fly.dev EXPECT_SECURE_COOKIES=1 \
  .venv/bin/python scripts/prod_smoke.py
```

Expected coverage:

- `/healthz` returns `200` and the current phase.
- Signup sets a usable session and lands on `/pantry`.
- Pantry add works through the htmx route.
- Invite minting, anonymous invite preview, and invite signup all work.
- A roommate sees the shared pantry item with attribution.
- HTTPS deploy smoke verifies `session` and `remember_token` cookies include `Secure`, `HttpOnly`, and `SameSite=Lax`.

### Use it on your phone

1. Open `https://<your-app>.fly.dev` in Safari.
2. Sign up with your email + name (this creates your household-of-one).
3. Mint an invite from the Household card, AirDrop / iMessage the link to your roommate.
4. **Share → Add to Home Screen** to install it as a home-screen app with the PantryPal name, color, and icon.

### Redeploys

```bash
git pull           # or whatever you just changed
fly deploy         # ~60s build + ~30s machine swap; SQLite stays put
                   # because /data is volume-mounted, not in the image.
```

### SQLite backup and restore

Production SQLite lives at `/data/pantrypal.sqlite3` on the Fly volume. Do not copy the file with plain `cp` while the app is writing to it: Phase 7G enables WAL, so a live database can also have `pantrypal.sqlite3-wal` and `pantrypal.sqlite3-shm` sidecar files. For backups, use SQLite's online backup API from inside the machine.

```bash
# Create a consistent backup on the Fly volume.
fly ssh console -C "mkdir -p /data/backups && python - <<'PY'
import datetime as dt
import sqlite3
from pathlib import Path

source = Path('/data/pantrypal.sqlite3')
stamp = dt.datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')
dest = Path('/data/backups') / f'pantrypal-{stamp}.sqlite3'

with sqlite3.connect(f'file:{source}?mode=ro', uri=True) as src:
    with sqlite3.connect(dest) as dst:
        src.backup(dst)

print(dest)
PY"
```

Download the new backup and keep at least one copy off the Fly volume:

```bash
mkdir -p backups
fly ssh sftp
sftp> get /data/backups/pantrypal-YYYYMMDDTHHMMSSZ.sqlite3 backups/
sftp> exit
```

Before restoring production, do a local restore drill with the backup file:

```bash
cp backups/pantrypal-YYYYMMDDTHHMMSSZ.sqlite3 /tmp/pantrypal-restore-test.sqlite3
DATABASE_URL=sqlite:////tmp/pantrypal-restore-test.sqlite3 \
  FLASK_SECRET_KEY=secret \
  .venv/bin/gunicorn --bind 127.0.0.1:8080 \
  --workers 1 --threads 4 'app:app'

# In another terminal:
.venv/bin/python scripts/prod_smoke.py
```

For production restore, schedule a quiet window, take a fresh pre-restore backup first, upload the known-good backup with `fly ssh sftp`, then replace the DB and remove stale WAL sidecars before restarting the app:

```bash
fly ssh sftp
sftp> put backups/pantrypal-YYYYMMDDTHHMMSSZ.sqlite3 /data/restore.sqlite3
sftp> exit

fly ssh console -C "python - <<'PY'
import datetime as dt
import shutil
from pathlib import Path

data_dir = Path('/data')
live = data_dir / 'pantrypal.sqlite3'
restore = data_dir / 'restore.sqlite3'
stamp = dt.datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')

shutil.copy2(live, data_dir / f'pantrypal-pre-restore-{stamp}.sqlite3')
shutil.copy2(restore, live)
for sidecar in (data_dir / 'pantrypal.sqlite3-wal', data_dir / 'pantrypal.sqlite3-shm'):
    sidecar.unlink(missing_ok=True)
print(f'restored {restore} to {live}')
PY"

fly deploy
BASE=https://<your-app>.fly.dev EXPECT_SECURE_COOKIES=1 \
  .venv/bin/python scripts/prod_smoke.py
```

### Phase 2C deploy gotchas (learned the hard way)

- **SQLite URL needs 4 slashes for absolute paths.** `sqlite:////data/pantrypal.sqlite3` (four slashes) = absolute. Three slashes = relative-to-Flask-instance-folder, which on Fly would silently put your DB on the ephemeral container disk instead of the volume — and you'd lose data on every redeploy. There's a test (`tests/test_phase_2c.py`) that pins this behavior.
- **`--workers=1` in gunicorn is mandatory while SQLite is the DB.** Multiple writer processes → file locking → 500s under any concurrent load. The Dockerfile hard-codes this. If/when we move to Postgres, bump to `(2 * CPU) + 1` per the gunicorn docs.
- **Volumes are region-pinned.** If you change `primary_region` in fly.toml after creating the volume, the new region's machine can't see the volume and the deploy fails. Create a new volume in the new region (or stay put).
- **`auto_stop_machines = "stop"` means cold starts.** First request after ~5 min idle takes ~250 ms longer than normal. Worth it for $0 hobby-tier costs. Flip to `"off"` or set `min_machines_running = 1` if you want always-warm.
- **`FLASK_SECRET_KEY` MUST be a Fly secret, not an env var in fly.toml.** Secrets are encrypted at rest + only injected into the running machine; env vars in fly.toml are committed to git.

### On a fresh clone: pin git pushes to the personal GitHub account

Without this, `git push` will use whichever gh account is active, which fails when the active account is the work one.

```bash
git config --local --replace-all credential.https://github.com.helper ""
git config --local --add credential.https://github.com.helper \
  '!f() { test "$1" = "get" && printf "username=zachariahphillips\npassword=%s\n" "$(gh auth token --user zachariahphillips -h github.com)"; }; f'
```

## Phases

- **Phase 0:** Project setup, hello-world Flask — done
- **Phase 1A:** Email/password auth foundation — done
- **Phase 1B:** Pantry CRUD (add, edit, delete, search via htmx) — done
- **Phase 1C:** Shopping list CRUD + bottom tab bar + pantry→shopping cross-link — done
- **Phase 2A:** Households data model + "added by" provenance + in-place SQLite migration — done
- **Phase 2B:** Magic-link invite/join flow (shareable URL, sign-up-with-invite + logged-in-switch) — done
- **Phase 2C:** Deploy to Fly.io (Dockerfile + gunicorn + persistent volume for SQLite) — done
- **Phase 3A:** AI meal planning — plumbing + minimal UI (OpenAI JSON mode, `MealPlan` model, `+ Shop` on need items) — done
- **Phase 3B:** Past-meals view (`/meals` tab) + card polish + "Plan another" + bulk `+ Shop all` + loading skeleton — done
- **Phase 3C:** Per-user-per-day rate limits + differentiated error messages + prompt-injection mitigation + cost telemetry — done
- **Phases 4–5:** Pantry/shopping flow improvements, duplicate handling, undo/toast safety, onboarding gates, and signpost nudges — done
- **Phase 6:** Mobile UX audit improvements and closeout — done
- **Phase 7A:** Docs/status sync — done
- **Phase 7B:** DB-backed health check — done
- **Phase 7C:** Ask AI in-flight disable — done
- **Phase 7D:** Ask AI quota-zero disable — done
- **Phase 7E:** GitHub Actions pytest CI — done
- **Phase 7F:** PWA manifest + app icons — done
- **Phase 7G:** SQLite busy timeout + WAL — done
- **Phase 7H:** Production cookie hardening — done
- **Phase 7I:** Deploy smoke cookie checks — done
- **Phase 7J:** Deploy smoke runbook polish — done
- **Phase 7K:** SQLite backup/restore runbook — current
- **Next:** Small backlog items such as maintenance-mode restore safety

Full plan in [PLAN.md](./PLAN.md).

## Sibling project

[project-pawsitive-coach](../project-pawsitive-coach/) — sets the Flask + OpenAI patterns this project reuses.
