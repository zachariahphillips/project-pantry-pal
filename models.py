"""
SQLAlchemy models for PantryPal.

Phase 1A: User. Phase 1B: PantryItem. Phase 1C adds ShoppingItem, Phase 2
adds Household and re-points the item foreign keys.
"""

from datetime import datetime

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from extensions import db


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    name = db.Column(db.String(120), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    pantry_items = db.relationship(
        "PantryItem",
        backref="owner",
        lazy="dynamic",
        cascade="all, delete-orphan",
        order_by="PantryItem.added_at.desc()",
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
    # Phase 1B owns by user; Phase 2 will rename this column to household_id.
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id"), nullable=False, index=True
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
        return f"<PantryItem {self.name} (user={self.user_id})>"
