# PantryPal

A household-shared pantry and shopping list, mobile-first, with an AI meal planner that knows what you have at home.

**Status:** Phase 1 complete — auth, pantry CRUD, shopping list (with check-off + clear-checked), one-tap "Add to shopping" from any pantry row, and a bottom tab bar. See [PLAN.md](./PLAN.md) for the phased build plan. Phase 2 (households + deploy) is up next.

## The idea in one paragraph

One pantry per household. Multiple people contribute from their own phones with their own accounts. Everyone sees the same view from any device. When you're ready to cook, ask the AI "what about pasta carbonara tonight?" — it checks your pantry, tells you what you already have, and adds what you're missing to the shopping list with one tap.

## Stack (planned)

Python + Flask · SQLite (→ Postgres later) · Flask-Login · Tailwind CSS via CDN · OpenAI GPT-4o-mini · PWA manifest for "install on home screen"

## Quick start

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then fill in FLASK_SECRET_KEY (OpenAI key not needed until Phase 3)
python -c "import secrets; print(secrets.token_hex(32))"  # paste output into FLASK_SECRET_KEY
python app.py
```

Open <http://localhost:5001>. Health check at <http://localhost:5001/healthz>.

Port 5001 is intentional — Pawsitive Coach uses 5000, so both can run side by side.

To run it on your phone while developing, find your laptop's LAN IP (`ipconfig getifaddr en0` on macOS) and open `http://<that-ip>:5001` on the phone (same Wi-Fi).

### Test accounts (seed script)

For quick dev work you don't have to re-signup every time. Run:

```bash
.venv/bin/python seed.py
```

This (re-)creates two test accounts with sample pantry + shopping data. Your real accounts are untouched.

| Email | Password |
|---|---|
| `alice@example.com` | `testpass123` |
| `bob@example.com`   | `testpass123` |

(`example.com` is the RFC 2606 reserved test domain. `*.local` doesn't work — `email_validator` rejects it as a reserved mDNS TLD.)

Re-running the script wipes those two accounts' items and rebuilds them — handy when you want a clean Phase 1C state without nuking the DB. (For a full reset, stop the server then `rm instance/pantrypal.sqlite3`.)

### iPhone autofill (Keychain) + "Stay signed in"

Two things make logging in on your phone painless:

1. **Keychain saves your password.** The forms use the standard autofill attributes (`autocomplete="new-password"` on signup, `autocomplete="current-password"` on login), so iOS will offer to save your password the first time you sign up, and to autofill it on every later sign-in. If Safari doesn't prompt, double-check that **Settings → Passwords → AutoFill Passwords** is on.
2. **"Keep me signed in" defaults to ON.** Flask-Login issues a 365-day remember-me cookie so closing the tab / rebooting your phone doesn't sign you out. Uncheck it on a shared device.

To make PantryPal feel like a native app on your phone, use Safari's **Share → Add to Home Screen** — the PWA manifest (coming in a later phase) plus standalone display mode hides the browser chrome.

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
- **Phase 2:** Households + multi-user invites + deploy — up next
- **Phase 3:** AI meal planning
- **Phase 4+:** Power-ups (barcode scan, receipt OCR, expiry tracking, etc.)

Full plan in [PLAN.md](./PLAN.md).

## Sibling project

[project-pawsitive-coach](../project-pawsitive-coach/) — sets the Flask + OpenAI patterns this project reuses.
