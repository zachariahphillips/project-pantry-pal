"""
PantryPal — household-shared pantry + shopping list with AI meal planning.

Phase 0: hello-world Flask app to confirm setup works end-to-end.
See PLAN.md for the full phased build plan.
"""

import os

from dotenv import load_dotenv
from flask import Flask, render_template

load_dotenv()

app = Flask(__name__)

app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-secret-change-me-in-env")


@app.route("/")
def home():
    return render_template("index.html")


@app.route("/healthz")
def healthz():
    return {"status": "ok", "phase": 0}


if __name__ == "__main__":
    app.run(debug=True, port=5001, host="0.0.0.0")
