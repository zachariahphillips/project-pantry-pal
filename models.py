"""
SQLAlchemy models for PantryPal.

Phase 1A: User. Phase 1B: PantryItem. Phase 1C: ShoppingItem.
Phase 2A: Household — items are now owned by a household, with the
existing `user_id` column re-mapped to mean "who added this" (provenance)
via a Python-level rename. The DB column is intentionally NOT renamed,
which keeps the migration to additive-only (add `households` table +
`household_id` columns), no destructive ALTERs.
Phase 2B: Invite — magic-link tokens that let new (or existing) users
join a household. Pure new-table migration (no column adds), so
db.create_all() is sufficient on this step.
Phase 3A: MealPlan — AI-generated meal plans (meal_name, have, need,
steps). Stores the raw OpenAI JSON response so we can reformat the UI
without re-paying for the API call, plus a denormalized meal_name for
fast list rendering. Also a pure new-table migration.
"""

import json
import secrets
from datetime import datetime, timedelta

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from extensions import db


class Household(db.Model):
    __tablename__ = "households"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    # Items the household owns (the new ownership concept in Phase 2A).
    pantry_items = db.relationship(
        "PantryItem",
        backref="household",
        lazy="dynamic",
        cascade="all, delete-orphan",
        order_by="PantryItem.added_at.desc()",
    )
    shopping_items = db.relationship(
        "ShoppingItem",
        backref="household",
        lazy="dynamic",
        cascade="all, delete-orphan",
        # Unchecked items first (False sorts before True), then within each
        # group: checked items sort by checked_at DESC (most-recently
        # crossed off at the top of the checked section — most likely
        # undo target). Unchecked items all have checked_at IS NULL
        # which sorts LAST in DESC on SQLite, so they tie on that key
        # and fall through to added_at.desc() — preserving the original
        # "newest unchecked at top" behavior. Phase 3G.
        order_by=(
            "ShoppingItem.checked.asc(), "
            "ShoppingItem.checked_at.desc(), "
            "ShoppingItem.added_at.desc()"
        ),
    )

    def __repr__(self) -> str:
        return f"<Household {self.name!r} (id={self.id})>"


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    name = db.Column(db.String(120), nullable=False)
    # Nullable in the DB so existing Phase-1 rows can be migrated lazily; the
    # signup flow + Phase 2A migration always set it. Phase 2B's invite flow
    # also relies on this being settable independently of signup.
    household_id = db.Column(
        db.Integer, db.ForeignKey("households.id"), nullable=True, index=True,
    )
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    household = db.relationship(
        "Household",
        backref=db.backref("members", lazy="dynamic"),
        foreign_keys=[household_id],
    )

    # Items the user has ADDED (provenance), distinct from items their
    # household owns. Useful for "added by" stamps and the seed-script
    # wipe loop. The DB column is still called `user_id` for migration
    # safety — see PantryItem / ShoppingItem below.
    added_pantry_items = db.relationship(
        "PantryItem",
        backref="added_by",
        lazy="dynamic",
        # NB: NOT cascade-delete — deleting a user shouldn't nuke the
        # household's items they happened to add. Phase 2B/2C will handle
        # "user leaves household" by nulling added_by_user_id instead.
        foreign_keys="PantryItem.added_by_user_id",
    )
    added_shopping_items = db.relationship(
        "ShoppingItem",
        backref="added_by",
        lazy="dynamic",
        foreign_keys="ShoppingItem.added_by_user_id",
    )

    def set_password(self, password: str) -> None:
        # Explicitly pbkdf2:sha256 rather than Werkzeug's scrypt default —
        # the macOS system Python links against LibreSSL, which doesn't
        # expose hashlib.scrypt. pbkdf2:sha256 works on every Python.
        self.password_hash = generate_password_hash(password, method="pbkdf2:sha256")

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

    def __repr__(self) -> str:
        return f"<User {self.email}>"


class PantryItem(db.Model):
    __tablename__ = "pantry_items"

    id = db.Column(db.Integer, primary_key=True)

    # Phase 2A: this column was Phase 1B's "user_id" (ownership). It's been
    # semantically retired to "who added this" — we keep the DB column name
    # as `user_id` so the migration is purely additive. The Python attribute
    # is `added_by_user_id` for clarity; SQLAlchemy bridges via `name=`.
    added_by_user_id = db.Column(
        "user_id", db.Integer, db.ForeignKey("users.id"),
        nullable=False, index=True,
    )

    # The new owner of the item. Nullable in the DB to let the
    # Phase 2A migration backfill existing rows lazily; the application
    # ALWAYS sets it on create.
    household_id = db.Column(
        db.Integer, db.ForeignKey("households.id"),
        nullable=True, index=True,
    )

    name = db.Column(db.String(120), nullable=False)
    quantity = db.Column(db.Float, nullable=True)
    unit = db.Column(db.String(40), nullable=True)
    notes = db.Column(db.String(280), nullable=True)
    added_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    def display_quantity(self) -> str:
        """Render quantity + unit for the UI, gracefully handling missing values."""
        if self.quantity is None and not self.unit:
            return ""
        qty = ""
        if self.quantity is not None:
            # Drop trailing zeros: 2.0 -> "2", 1.50 -> "1.5"
            qty = f"{self.quantity:g}"
        if self.unit:
            return f"{qty} {self.unit}".strip()
        return qty

    def __repr__(self) -> str:
        return (
            f"<PantryItem {self.name} "
            f"household={self.household_id} added_by={self.added_by_user_id}>"
        )


class ShoppingItem(db.Model):
    __tablename__ = "shopping_items"

    id = db.Column(db.Integer, primary_key=True)

    # See PantryItem.added_by_user_id for the rationale on the
    # Python-name-vs-DB-name split.
    added_by_user_id = db.Column(
        "user_id", db.Integer, db.ForeignKey("users.id"),
        nullable=False, index=True,
    )

    household_id = db.Column(
        db.Integer, db.ForeignKey("households.id"),
        nullable=True, index=True,
    )

    name = db.Column(db.String(120), nullable=False)
    quantity = db.Column(db.Float, nullable=True)
    unit = db.Column(db.String(40), nullable=True)
    notes = db.Column(db.String(280), nullable=True)
    checked = db.Column(db.Boolean, default=False, nullable=False, index=True)
    added_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    # Phase 3G: timestamp of the most recent False→True toggle. NULL
    # while the item is unchecked. Powers "most-recently-checked at
    # top of the checked section" sort + a future "undo last check"
    # feature. Cleared (set to None) when the user un-checks an item.
    # Added as a lazy ALTER in `_ensure_shopping_checked_at_column`;
    # legacy checked rows get backfilled with added_at so the sort
    # order is stable across the migration boundary.
    checked_at = db.Column(db.DateTime, nullable=True, index=True)

    def display_quantity(self) -> str:
        if self.quantity is None and not self.unit:
            return ""
        qty = ""
        if self.quantity is not None:
            qty = f"{self.quantity:g}"
        if self.unit:
            return f"{qty} {self.unit}".strip()
        return qty

    def __repr__(self) -> str:
        return (
            f"<ShoppingItem {self.name} checked={self.checked} "
            f"household={self.household_id} added_by={self.added_by_user_id}>"
        )


# --- Phase 2B: invites -----------------------------------------------------

# Tunables. Generous-but-not-silly defaults; the UI doesn't expose per-invite
# overrides yet (Phase 2C can add a "send to spouse only" 1-use variant).
INVITE_DEFAULT_TTL_DAYS = 7
INVITE_DEFAULT_MAX_USES = 10
# 16 url-safe bytes -> 22 char token. ~10^38 keyspace, plenty for v1 even
# with no rate-limiting; revisit only if we ever expose enumeration on a
# public endpoint.
INVITE_TOKEN_BYTES = 16


class Invite(db.Model):
    __tablename__ = "invites"

    id = db.Column(db.Integer, primary_key=True)
    token = db.Column(db.String(48), unique=True, nullable=False, index=True)
    household_id = db.Column(
        db.Integer, db.ForeignKey("households.id"),
        nullable=False, index=True,
    )
    created_by_user_id = db.Column(
        db.Integer, db.ForeignKey("users.id"), nullable=False,
    )
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)
    max_uses = db.Column(db.Integer, nullable=False, default=INVITE_DEFAULT_MAX_USES)
    used_count = db.Column(db.Integer, nullable=False, default=0)

    household = db.relationship(
        "Household",
        backref=db.backref(
            "invites", lazy="dynamic", cascade="all, delete-orphan",
            order_by="Invite.created_at.desc()",
        ),
    )
    created_by = db.relationship("User", foreign_keys=[created_by_user_id])

    @classmethod
    def mint(
        cls, *,
        household_id: int,
        created_by_user_id: int,
        ttl_days: int = INVITE_DEFAULT_TTL_DAYS,
        max_uses: int = INVITE_DEFAULT_MAX_USES,
    ) -> "Invite":
        """Build an unsaved Invite with a fresh token + sensible TTL. Caller
        is responsible for `db.session.add()` + `commit()`."""
        return cls(
            token=secrets.token_urlsafe(INVITE_TOKEN_BYTES),
            household_id=household_id,
            created_by_user_id=created_by_user_id,
            expires_at=datetime.utcnow() + timedelta(days=ttl_days),
            max_uses=max_uses,
            used_count=0,
        )

    def is_active(self) -> bool:
        """True iff the invite can still accept a join (not expired, has
        uses remaining)."""
        return (
            datetime.utcnow() < self.expires_at
            and self.used_count < self.max_uses
        )

    def reason_inactive(self) -> str:
        """For the join landing page so we can tell the user *why* a link
        is dead rather than just saying 'invalid'."""
        if datetime.utcnow() >= self.expires_at:
            return "This invite link has expired."
        if self.used_count >= self.max_uses:
            return "This invite link has already been used the maximum number of times."
        return "This invite link is no longer valid."

    def consume(self) -> None:
        """Increment usage counter. Single-threaded for the dev server;
        Phase 2C deploy notes flag this as a race-condition spot worth
        revisiting under multi-worker gunicorn."""
        self.used_count += 1

    def __repr__(self) -> str:
        return (
            f"<Invite token={self.token[:8]}… household={self.household_id} "
            f"uses={self.used_count}/{self.max_uses}>"
        )


# --- Phase 3A: AI meal plans -----------------------------------------------

# Hard caps on what we ask the AI to produce + show in the UI. These are
# intentionally generous (a real recipe rarely needs >10 ingredients or
# >12 steps); the cap is mostly to prevent a runaway response from
# blowing up the rendered card.
MEAL_PLAN_MAX_HAVE = 15
MEAL_PLAN_MAX_NEED = 15
MEAL_PLAN_MAX_STEPS = 12


class MealPlan(db.Model):
    """A single AI-generated meal plan stored against the household.

    We persist the raw JSON the model returned so future UI changes
    (Phase 3B card polish, Phase 3C suggested-recipes-from-pantry) don't
    require re-paying for the OpenAI call. The denormalized `meal_name`
    column is just for fast "recent meals" rendering — saves a JSON
    parse per row in list views.

    Household-scoped (so roommates see each other's plans), with
    provenance (`created_by_user_id`) for the "asked by Alice" stamp
    we'll likely want in Phase 3B.
    """
    __tablename__ = "meal_plans"

    id = db.Column(db.Integer, primary_key=True)
    household_id = db.Column(
        db.Integer, db.ForeignKey("households.id"),
        nullable=False, index=True,
    )
    created_by_user_id = db.Column(
        db.Integer, db.ForeignKey("users.id"), nullable=False, index=True,
    )
    # The free-text prompt the user typed ("I want to make pasta carbonara").
    # Keep as TEXT so we don't cap meal ideas at some arbitrary length;
    # validation at the form layer keeps abuse small.
    prompt = db.Column(db.Text, nullable=False)
    # The raw JSON we got back from OpenAI, stored verbatim. Parsing
    # happens lazily via `parsed`. If a future model spec changes the
    # schema (e.g. adds "prep_time"), old rows still render via the
    # existing have/need/steps fields.
    response_json = db.Column(db.Text, nullable=False)
    # Denormalized convenience for list views — `parsed.get("meal_name")`
    # would also work but means a json.loads on every row.
    meal_name = db.Column(db.String(200), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    household = db.relationship(
        "Household",
        backref=db.backref(
            "meal_plans", lazy="dynamic", cascade="all, delete-orphan",
            order_by="MealPlan.created_at.desc()",
        ),
    )
    created_by = db.relationship("User", foreign_keys=[created_by_user_id])

    @property
    def parsed(self) -> dict:
        """Cached parse of `response_json`. Returns {} if the stored
        value is somehow malformed (shouldn't happen post-validation in
        the route, but defensive)."""
        try:
            data = json.loads(self.response_json)
        except (json.JSONDecodeError, TypeError):
            return {}
        return data if isinstance(data, dict) else {}

    def _list_field(self, key: str, cap: int) -> list:
        """Pull a list-typed field from `parsed`, defensively coerce to
        strings, and cap to `cap` entries."""
        value = self.parsed.get(key)
        if not isinstance(value, list):
            return []
        cleaned = [str(v).strip() for v in value if str(v).strip()]
        return cleaned[:cap]

    @property
    def have(self) -> list:
        return self._list_field("have", MEAL_PLAN_MAX_HAVE)

    @property
    def need(self) -> list:
        return self._list_field("need", MEAL_PLAN_MAX_NEED)

    @property
    def steps(self) -> list:
        return self._list_field("steps", MEAL_PLAN_MAX_STEPS)

    def __repr__(self) -> str:
        return (
            f"<MealPlan {self.meal_name!r} household={self.household_id} "
            f"created_by={self.created_by_user_id}>"
        )
