"""
Seed two known test accounts so we never have to re-signup during dev.

Run: `python seed.py` (or `.venv/bin/python seed.py`).

What it does:
- (Re-)creates `alice@test.local` and `bob@test.local` with known
  passwords and a small pantry + shopping list each.
- Idempotent: re-running drops the two test users' data and rebuilds
  it. Your real accounts and their data are NEVER touched.
- Prints the credentials at the end so you can copy/paste into the
  login form (or autofill from Keychain after the first save).

Use case becomes load-bearing in Phase 2: the invite/join flow needs
two accounts to test, and this script makes that one command away.
"""
from __future__ import annotations

import sys

from app import create_app
from extensions import db
from models import PantryItem, ShoppingItem, User

# Domain is `example.com` (reserved for documentation/testing per RFC 2606)
# rather than `*.local`, because the `email_validator` package rejects `.local`
# as a reserved mDNS TLD — our LoginForm/SignupForm would refuse to log in.
TEST_USERS = [
    {
        "email": "alice@example.com",
        "name": "Alice (test)",
        "password": "testpass123",
        "pantry": [
            ("Black beans", 3, "cans", "low-sodium"),
            ("Olive oil", 1, "bottle", "EVOO"),
            ("Rice", 2, "lb", None),
            ("Eggs", 1, "dozen", None),
            ("Pasta", 4, "boxes", "spaghetti and penne"),
        ],
        "shopping": [
            # (name, qty, unit, notes, checked)
            ("Tortillas", 2, "bags", "corn", False),
            ("Milk", 1, "gal", None, False),
            ("Avocados", 4, "ea", "ripe", True),
        ],
    },
    {
        "email": "bob@example.com",
        "name": "Bob (test)",
        "password": "testpass123",
        "pantry": [
            ("Peanut butter", 1, "jar", "creamy"),
            ("Bread", 1, "loaf", "sourdough"),
        ],
        "shopping": [
            ("Bananas", 6, "ea", None, False),
        ],
    },
]


def seed():
    app = create_app()
    with app.app_context():
        created, refreshed = [], []

        for spec in TEST_USERS:
            user = db.session.query(User).filter_by(email=spec["email"]).first()

            if user is not None:
                # Existing test user: wipe their items, rebuild from spec.
                # The dynamic relationships have ORDER BY baked in, which
                # SQLAlchemy disallows on Query.delete(); strip it first.
                user.pantry_items.order_by(None).delete(synchronize_session=False)
                user.shopping_items.order_by(None).delete(synchronize_session=False)
                user.name = spec["name"]
                user.set_password(spec["password"])
                refreshed.append(spec["email"])
            else:
                user = User(email=spec["email"], name=spec["name"])
                user.set_password(spec["password"])
                db.session.add(user)
                db.session.flush()  # need user.id for the FKs below
                created.append(spec["email"])

            for name, qty, unit, notes in spec["pantry"]:
                db.session.add(PantryItem(
                    user_id=user.id, name=name, quantity=qty,
                    unit=unit, notes=notes,
                ))
            for name, qty, unit, notes, checked in spec["shopping"]:
                db.session.add(ShoppingItem(
                    user_id=user.id, name=name, quantity=qty,
                    unit=unit, notes=notes, checked=checked,
                ))

        db.session.commit()

        print("Seed complete.")
        if created:
            print(f"  created : {', '.join(created)}")
        if refreshed:
            print(f"  refreshed: {', '.join(refreshed)}")
        print()
        print("Credentials (same password for both):")
        for spec in TEST_USERS:
            print(f"  {spec['email']:24}  {spec['password']}")
        print()
        print("Other users in the DB are untouched.")


if __name__ == "__main__":
    try:
        seed()
    except Exception as e:
        print(f"Seed failed: {e}", file=sys.stderr)
        sys.exit(1)
