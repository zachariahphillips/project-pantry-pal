# BUGS.md — Known issues & deferred fixes

Living tracker for regressions, edge-case bugs, and UX papercuts we've
consciously chosen not to fix in the current chunk. The point isn't to
have zero bugs — it's to make sure we know which ones we're carrying
and can decide when each earns a fix.

---

## Ship rule

A chunk can ship with open bugs, provided:

- Each open bug is logged below with a severity + repro
- **No open bug is marked `Blocker`**
- The chunk's own new tests all pass
- The failure isn't a genuine regression in the chunk's own scope
  (see "How to triage a Tier 3 failure" below)

## Severity

| Level | Meaning | Reaction |
|---|---|---|
| **Blocker** | Data loss, security, broken auth, or breaks a currently-shipping phase's core contract | Fix before commit. Do not defer. |
| **High** | Regression in previously-shipped user-visible behavior with no clean workaround | Fix in the next chunk unless we've explicitly decided otherwise |
| **Medium** | UX papercut with a clear workaround, or a non-obvious edge case | Fix opportunistically when nearby code is touched |
| **Low** | Cosmetic, test-only, or edge case unlikely to hit real users | Fix if trivial, otherwise carry indefinitely |

---

## Test tiers (to minimize full-regression time)

Full runs take ~3-4 minutes on this repo. We don't need to eat that on
every save. Convention:

| Tier | When | Command | Wall time |
|---|---|---|---|
| **1 — Chunk** | Dev loop, after each code change | `pytest tests/test_phase_XX.py -q` (just the chunk you're working on) | ~5-10s |
| **2 — Focused** | Before commit, once the chunk feels done | Chunk file + any phase file whose contract you touched | ~20-40s |
| **3 — Full** | Before pushing to `main`, or once per work session | `pytest tests/ -q` | ~3-4 min |

**Only Tier 3 failures ever get logged here.** Tier 1 and 2 failures
must be resolved before proceeding to the next tier — those are your
own chunk's tests failing, which is a different failure mode than
"pre-existing bug surfaced by a full run."

### How to triage a Tier 3 failure

1. **Is the failure traceable to the current chunk's diff?** (i.e.
   would `git stash` and re-run make it pass?)
   - Yes → **fix it** or log as **High** with a clear justification
     for deferring. Never silently ship a regression in previously-
     shipped behavior.
2. **Was the failure present before this chunk?** (Common: dormant
   pre-existing bug that our new test setup surfaces.)
   - Yes → log at the appropriate severity below and ship.
3. **Is the failing test itself wrong now that behavior legitimately
   changed?**
   - Yes → update the test in the same chunk. Don't log a bug — the
     test was tracking an obsolete contract.

---

## Open

| ID | Sev | Discovered | Phase | Description | Repro / Workaround |
|---|---|---|---|---|---|
| B-002 | Low | ~2026-06 | 3C | Anonymous POST to `/shopping/undo` returns **400 Bad Request** rather than **302 → /login**. CSRF middleware fires before `@login_required`, so unauthed POSTs are blocked by the wrong layer. Access is still correctly denied. | Test `test_anonymous_user_cannot_undo` in `tests/test_phase_3j.py` accepts 400 as a valid outcome. Real fix requires reordering middleware. |

## Recently closed

Move an entry here when its fix commits — keep the most recent 10-ish.
Older entries can be pruned; git history is the source of truth.

| ID | Closed | Fix commit | Notes |
|---|---|---|---|
| B-001 | 2026-07-09 | (Phase 5B / Chunk B) | Symmetrized onboarding-threshold behavior in `pantry_item_delete` — below-threshold deletes now return `204 + HX-Refresh: true`, matching what below-threshold adds already did. Hero + meal-planner gate reappear correctly on delete-to-empty without a manual refresh. Ripple test updates: `test_phase_5a` (renamed the partial-swap test to `test_deleting_all_items_returns_hx_refresh`); `test_phase_4a` + `test_phase_4c` primed past threshold to keep the sort/filter-preservation tests on the partial-swap path; `test_phase_2a` accepts `{200, 204}` on the shared-household delete since its contract is the auth model, not the response shape. |
