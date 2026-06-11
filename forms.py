"""
Flask-WTF forms for auth. CSRF protection is automatic as long as
FLASK_SECRET_KEY is set in the environment.
"""

from flask_wtf import FlaskForm
from wtforms import BooleanField, FloatField, PasswordField, StringField, SubmitField
from wtforms.validators import DataRequired, Email, Length, NumberRange, Optional

# Single source of truth for the unit-dropdown options.
# Used by both the pantry add/edit forms and the shopping add/edit forms.
# Order is intentional: most common first (ea, g, kg…) so the dropdown
# matches how a phone-thumb user would scan it. Inputs are NOT
# validated against this list — the user can still type "bottle" or
# "head of garlic" and submit it. The list is a UX shortcut, not a
# constraint.
UNIT_SUGGESTIONS = (
    "ea", "g", "kg", "oz", "lb",
    "ml", "L", "cup", "tbsp", "tsp",
    "cans", "boxes", "bags", "bunches",
)


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
    # Defaults to True so a fresh install is "phone-friendly" by default.
    # Flask-Login's remember-me cookie lives 365 days (REMEMBER_COOKIE_DURATION
    # default); the user can uncheck on shared/public devices.
    remember = BooleanField("Keep me signed in", default=True)
    submit = SubmitField("Sign in")


class PantryItemForm(FlaskForm):
    name = StringField(
        "Item",
        validators=[
            DataRequired(message="What did you add?"),
            Length(min=1, max=120),
        ],
        render_kw={"autocomplete": "off", "placeholder": "e.g. black beans"},
    )
    quantity = FloatField(
        "Qty",
        validators=[Optional(), NumberRange(min=0, message="Use a number \u2265 0.")],
        render_kw={
            "autocomplete": "off",
            "inputmode": "decimal",
            "step": "any",
            "placeholder": "2",
        },
    )
    unit = StringField(
        "Unit",
        validators=[Optional(), Length(max=40)],
        # NB: no `list=` attribute — the unit dropdown is a custom
        # combobox (see _macros.html / base.html JS), NOT an HTML5
        # <datalist>. The native datalist popup renders as an OS-styled
        # floating menu that's visually disconnected from the input,
        # which looks broken on every browser. The combobox renders as
        # a styled menu anchored directly below the input.
        render_kw={
            "autocomplete": "off",
            "placeholder": "cans",
        },
    )
    notes = StringField(
        "Notes",
        validators=[Optional(), Length(max=280)],
        render_kw={"autocomplete": "off", "placeholder": "Optional notes"},
    )
    submit = SubmitField("Add")


class ShoppingItemForm(PantryItemForm):
    """Same fields as PantryItemForm today. Kept as a separate class so
    pantry-only fields (expiry, location) or shopping-only fields (priority,
    store) can be added in Phase 4 without coupling."""
    pass
