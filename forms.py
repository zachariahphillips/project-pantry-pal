"""
Flask-WTF forms for auth. CSRF protection is automatic as long as
FLASK_SECRET_KEY is set in the environment.
"""

from flask_wtf import FlaskForm
from wtforms import PasswordField, StringField, SubmitField
from wtforms.validators import DataRequired, Email, Length


class SignupForm(FlaskForm):
    name = StringField(
        "Name",
        validators=[DataRequired(message="Please enter your name."), Length(min=1, max=120)],
        render_kw={"autocomplete": "name", "autofocus": True, "placeholder": "Your name"},
    )
    email = StringField(
        "Email",
        validators=[
            DataRequired(message="Email is required."),
            Email(message="That doesn't look like a valid email."),
            Length(max=255),
        ],
        render_kw={"autocomplete": "email", "inputmode": "email", "placeholder": "you@example.com"},
    )
    password = PasswordField(
        "Password",
        validators=[
            DataRequired(message="Password is required."),
            Length(min=8, max=128, message="Use at least 8 characters."),
        ],
        render_kw={"autocomplete": "new-password", "placeholder": "At least 8 characters"},
    )
    submit = SubmitField("Create account")


class LoginForm(FlaskForm):
    email = StringField(
        "Email",
        validators=[
            DataRequired(message="Email is required."),
            Email(message="That doesn't look like a valid email."),
        ],
        render_kw={"autocomplete": "email", "inputmode": "email", "autofocus": True, "placeholder": "you@example.com"},
    )
    password = PasswordField(
        "Password",
        validators=[DataRequired(message="Password is required.")],
        render_kw={"autocomplete": "current-password", "placeholder": "Your password"},
    )
    submit = SubmitField("Sign in")
