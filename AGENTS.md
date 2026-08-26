# AGENTS.md — onboarding for AI coding agents

This file is auto-loaded by Cursor for every chat opened against this
repo. If you're an AI agent working in `project-pantry-pal`, read this
first, then `README.md`.

## Boundary — this is a personal project

This repo is **not** Nike work. If you're carrying over rules or context
from `~/RiahFiles/` (Nike PM workspace), drop it. Different persona,
different conventions, different everything. No Nike terminology, no
Nike frameworks, no Nike-style stakeholder framing. Just a hobby Flask
app.

Git author: `Zachariah Phillips <zachariah.r.phillips@gmail.com>` →
GitHub `@zachariahphillips` (personal, contributions count on the
public graph). Do NOT commit anything that would push under a work
identity.

## What it is (1-liner)

Flask + htmx + SQLite mobile-first pantry & shopping-list PWA with an
OpenAI-powered meal planner. Full stack + deploy story in `README.md`.

## Local dev

```bash
source .venv/bin/activate         # Python 3.11+
python app.py                     # http://127.0.0.1:5001
pytest -q                         # full regression, 596 tests as of Phase 7H
.venv/bin/python seed.py          # (re)create alice@example.com + bob@example.com
```

GitHub Actions runs the same `python -m pytest -q` full regression on
every push and pull request.

Port 5001 is intentional — the sibling project (`project-pawsitive-coach`)
uses 5000, so both can run side-by-side.

## Repo layout (agent's cheat sheet)

| Path | What lives there |
|---|---|
| `app.py` | Every route + helper. Big file (~3K LOC) but shallow — grep by route name. |
| `models.py` | SQLAlchemy models. Watch: `PantryItem.added_by_user_id` maps to DB column `user_id`. |
| `forms.py` | Flask-WTF forms. |
| `extensions.py` | `db = SQLAlchemy()` init. |
| `templates/` | Jinja. `_partial.html` files are htmx swap targets. `_macros.html` holds shared macros (nudge banners, empty-states). |
| `tests/conftest.py` | `Client` wrapper (handles CSRF), per-test SQLite file, `sign_up` helper. |
| `tests/test_phase_XX.py` | One file per Phase. New phases add one; never mutate old ones unless the phase's behavior itself changed. |
| `PLAN.md` | Macro roadmap. Skim for phase history. |
| `PLANS/` | Narrower plans (e.g. `ux-improvements-plan.md`). Referenced from code comments. |
| `BUGS.md` | Known issues, priority-tagged. Add new ones here; don't silently fix them without an entry. |
| `Dockerfile`, `fly.toml` | Fly.io deploy artifacts. `--workers=1` is intentional (see gotchas). |
| `seed.py` | Reseeds `alice@example.com` + `bob@example.com` test accounts. |

## Development workflow

Work happens in **Phases** (`Phase 7A`, `Phase 7B`, `Phase 7C`, ...).
Each phase:

1. **Plan** — either extend `PLAN.md` or reference a section of a
   `PLANS/*.md` doc.
2. **Implement** — code + template changes.
3. **Test-per-phase** — add `tests/test_phase_XX.py` with regression
   coverage for exactly what changed. Docstrings explain what the test
   guards + why (future-you will need this).
4. **Tier discipline:**
   - **Tier 1**: `pytest tests/test_phase_XX.py -v` — new tests green
   - **Tier 3**: `pytest -q` — full regression before commit
5. **Visual verify (UI-touching phases only)** — spin up local server,
   drive the UI via Chrome DevTools MCP at mobile viewport (390×844 or
   414×896), take before/after screenshots. Store in `/tmp/` unless the
   plan says otherwise; don't commit screenshots.
6. **Commit** — subject line: `Phase XX: <short description>`. Body is
   optional, use it for gotchas or migration notes. Push to `main`
   (single-dev repo, no PR flow).

## Code conventions

- **Comments explain intent, not what the code does.** Cite the plan
  section: `{# Phase 6G (plan §1.2): hides search on empty pantry #}`.
- **Tests carry heavy docstrings.** Future-you needs to know what a
  test is guarding without reading the implementation.
- **Direct-DB test helpers exist** for state setup that shouldn't go
  through HTTP. When creating `PantryItem` this way, remember
  `added_by_user_id=user.id` (Python attribute) — NOT `user_id=...`.
- **No new dependencies without a reason.** Deps are pinned in
  `requirements.txt` with comments explaining each version pin.

## HTMX patterns you'll encounter

- `HX-Refresh: true` — server tells client to do a full page reload.
- `HX-Trigger: eventName` — fire client-side JS event on the swapped
  content.
- `HX-Detour` — custom header we use to signal "skip the default
  form-reset behavior" (used by dupe-confirm flows).
- `hx-swap-oob="true"` — out-of-band swap. Used for toast slots and
  pending-toast bridges.
- **Session-based undo pattern**: destructive actions store a snapshot
  in `session[..._UNDO_SESSION_KEY]`; the toast has a 7s Undo CTA.
  For `HX-Refresh` scenarios we store the pending toast in
  `session[..._PENDING_TOAST_SESSION_KEY]` and re-fire it via a
  one-shot script on the reloaded page.
- **OOB swap targets** live in `templates/base.html` (e.g.
  `#toast-slot`, `#pantry-dupe-confirm-slot`,
  `#shopping-dupe-confirm-slot`).

## Gotchas

- **CSRF is ON in tests.** `Client` in `conftest.py` scrapes tokens and
  re-attaches them. If a POST test returns 400, check that you're using
  the wrapper.
- **`PantryItem` model quirk** (see above): DB column `user_id`, Python
  attribute `added_by_user_id`. Migration was additive; don't "clean it
  up."
- **`--workers=1` in gunicorn is intentional.** SQLite is single-writer;
  more workers → file locking → 500s. Only bump when we move to Postgres.
- **SQLite URL needs 4 slashes for absolute paths** on Fly. See README's
  Phase 2C section — there's a test in `tests/test_phase_2c.py` pinning
  this.
- **B-002 is a known low-priority bug** (see `BUGS.md`): anonymous POST
  to `/shopping/undo` returns 400 instead of 302/401 because CSRF
  middleware fires before `@login_required`. Don't accidentally "fix" it
  without reading the entry.
- **Empty-state gating changes what renders.** Phase 6G hides the pantry
  search input + household-share card until the pantry has any item
  (or a roommate / pending invite exists). If you're testing rendering
  behavior, seed at least one item.

## Fresh-clone git-identity pin

Without this, `git push` uses whichever `gh` account is active, which
fails when the work account is active:

```bash
git config --local --replace-all credential.https://github.com.helper ""
git config --local --add credential.https://github.com.helper \
  '!f() { test "$1" = "get" && printf "username=zachariahphillips\npassword=%s\n" "$(gh auth token --user zachariahphillips -h github.com)"; }; f'
```

## Where to look first for a new task

1. Read the top-of-file docstrings + section headers in `app.py` —
   routes are grouped by feature (auth, pantry, shopping, meal-planning,
   households).
2. Grep the most recent 3–5 `Phase XX` commits — style + patterns stay
   consistent.
3. Find the newest `tests/test_phase_XX.py` — it's the template for what
   a new test file should look like.
4. Check `BUGS.md` before implementing anything adjacent to known bugs.
5. If the task references a UX plan item (`§1.2`, `§0.1`, etc.), open
   `PLANS/ux-improvements-plan.md` for the source-of-truth diagnosis and
   recommendation.
