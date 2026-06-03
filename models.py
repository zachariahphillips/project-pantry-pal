"""
SQLAlchemy models for PantryPal.

Phase 1A: User. Phase 1B: PantryItem. Phase 1C: ShoppingItem.
Phase 2A: Household — items are now owned by a household, with the
existing `user_id` column re-mapped to mean "who added this" (provenance)
via a Python-level rename. The DB column is intentionally NOT renamed,
which keeps the migration to additive-only (add `households` table +
`household_id` columns), no destructive ALTERs.
"""

from datetime import datetime

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
        # Unchecked items first (False sorts before True), then newest within
        # each group. Keeps "what still needs buying" at the top of the list.
        order_by="ShoppingItem.checked.asc(), ShoppingItem.added_at.desc()",
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
