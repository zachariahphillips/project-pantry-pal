# PantryPal

A household-shared pantry and shopping list, mobile-first, with an AI meal planner that knows what you have at home.

**Status:** Phase 2B complete — multi-user households are real now. Invite a roommate via a magic link, they sign up (or log in) into your household, and you both see the same pantry + shopping list with "added by [name]" stamps. See [PLAN.md](./PLAN.md) for the phased build plan. Phase 2C (deploy to Fly.io so it actually runs on your household's phones) is up next.

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
- **Phase 2A:** Households data model + "added by" provenance + in-place SQLite migration — done
- **Phase 2B:** Magic-link invite/join flow (shareable URL, sign-up-with-invite + logged-in-switch) — done
- **Phase 2C:** Deploy to Fly.io (Dockerfile + persistent volume for SQLite) — up next
- **Phase 3:** AI meal planning
- **Phase 4+:** Power-ups (barcode scan, receipt OCR, expiry tracking, etc.)

Full plan in [PLAN.md](./PLAN.md).

## Sibling project

[project-pawsitive-coach](../project-pawsitive-coach/) — sets the Flask + OpenAI patterns this project reuses.
