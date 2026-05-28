"""
Flask extension singletons.

Kept in their own module so models.py / forms.py / app.py can import `db` and
`login_manager` without circular imports back through app.py.
"""

from flask_login import LoginManager
from flask_sqlalchemy import SQLAlchemy
from flask_wtf.csrf import CSRFProtect

db = SQLAlchemy()
login_manager = LoginManager()
csrf = CSRFProtect()
