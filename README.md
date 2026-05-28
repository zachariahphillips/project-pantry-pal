# PantryPal

A household-shared pantry and shopping list, mobile-first, with an AI meal planner that knows what you have at home.

**Status:** Planning. See [PLAN.md](./PLAN.md) for the phased build plan.

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
python app.py
```

Open <http://localhost:5001>. Health check at <http://localhost:5001/healthz>.

Port 5001 is intentional — Pawsitive Coach uses 5000, so both can run side by side.

To run it on your phone while developing, find your laptop's LAN IP (`ipconfig getifaddr en0` on macOS) and open `http://<that-ip>:5001` on the phone (same Wi-Fi).

## Phases

- **Phase 0:** Project setup, hello-world Flask — done
- **Phase 1A:** Email/password auth foundation — done
- **Phase 1B:** Pantry CRUD — up next
- **Phase 1C:** Shopping list CRUD
- **Phase 2:** Households + multi-user invites + deploy
- **Phase 3:** AI meal planning
- **Phase 4+:** Power-ups (barcode scan, receipt OCR, expiry tracking, etc.)

Full plan in [PLAN.md](./PLAN.md).

## Sibling project

[project-pawsitive-coach](../project-pawsitive-coach/) — sets the Flask + OpenAI patterns this project reuses.
