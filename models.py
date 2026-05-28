"""
SQLAlchemy models for PantryPal.

Phase 1A: just User. Phase 1B adds PantryItem, 1C adds ShoppingItem, Phase 2
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

    def set_password(self, password: str) -> None:
        # Explicitly pbkdf2:sha256 rather than Werkzeug's scrypt default —
        # the macOS system Python links against LibreSSL, which doesn't
        # expose hashlib.scrypt. pbkdf2:sha256 works on every Python.
        self.password_hash = generate_password_hash(password, method="pbkdf2:sha256")

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

    def __repr__(self) -> str:
        return f"<User {self.email}>"
