"""
Phase 4B regression suite — pantry item "added X ago" timestamps.

Chunk B of Theme 4 adds a relative-time line to every pantry item card
("added 2d ago" / "added by Alice · 2d ago") plus a subtle stale-age
treatment that flips the line color from stone-400 to amber-600 once
an item is older than PANTRY_STALE_AGE_DAYS (14 days).

These tests guard:
  1. _humanize_relative_time bucketing — every Slack-style bucket
     boundary (just now / m / h / d / w / absolute date / cross-year).
     Clock-skew safety: future-dated items render as "just now".
  2. _is_pantry_item_stale threshold — boundary at the 14-day cutoff.
  3. Template wiring — relative-time stamp renders on every row,
     <time datetime="..."> is set, stale items get the amber color,
     fresh items stay stone-400, "added by X" wording is preserved
     for cross-household provenance.
  4. Backward compat — existing Phase 2A "no 'added by you' noise"
     behavior still holds in solo households.
"""
from __future__ import annotations

import re
import time
from datetime import datetime, timedelta

from tests.conftest import Client, sign_up


# Pulled in via the app module so any future renaming/refactor surfaces
# here as an import error rather than a silently passing test.
from app import (
    PANTRY_STALE_AGE_DAYS,
    _humanize_relative_time,
    _is_pantry_item_stale,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _add_pantry(c: Client, name: str):
    return c.post("/pantry", htmx=True, data={
        "name": name, "quantity": "", "unit": "", "notes": "",
        "submit": "Add",
    })


def _setup_shared_household(app, alice: Client, bob: Client) -> None:
    """Mirror the Phase 2A test pattern — sign both clients up, then
    rewrite Bob's household_id to point at Alice's so they share a
    pantry. The `two_clients` fixture gives bare clients; household
    sharing is a runtime merge."""
    sign_up(alice, "alice@example.com", "Alice")
    sign_up(bob, "bob@example.com", "Bob")
    with app.app_context():
        from extensions import db
        from models import User
        alice_db = User.query.filter_by(email="alice@example.com").first()
        bob_db = User.query.filter_by(email="bob@example.com").first()
        bob_db.household_id = alice_db.household_id
        db.session.commit()


def _set_added_at(app, item_name: str, when: datetime) -> None:
    """Test helper — push a pantry item's `added_at` to a specific time.
    Without this we'd have to fake `datetime.utcnow` to test stale-age,
    which is far more fragile."""
    from models import PantryItem, db
    with app.app_context():
        item = db.session.query(PantryItem).filter_by(name=item_name).first()
        assert item is not None, f"Couldn't find pantry item {item_name!r}"
        item.added_at = when
        db.session.commit()


def _item_block(html: str, name: str) -> str:
    """Extract a single pantry-item card block from rendered HTML.
    Use regex with a non-greedy capture between the row's id="..." and
    the next pantry-item start (or end of string)."""
    pattern = (
        r'<div id="pantry-item-\d+"(.*?)'
        r'(?=<div id="pantry-item-|</div>\s*</div>|\Z)'
    )
    for match in re.finditer(pattern, html, re.DOTALL):
        block = match.group(0)
        if f">{name}<" in block or f">{name}\n" in block.replace(" ", ""):
            return block
        # Fallback: collapse whitespace and check
        if name in block:
            return block
    return ""


# ---------------------------------------------------------------------------
# 1. _humanize_relative_time — bucket boundaries
# ---------------------------------------------------------------------------

class TestRelativeTimeBuckets:
    def setup_method(self):
        # Pin "now" to a fixed instant — avoids flakes from the test
        # taking long enough that bucket boundaries shift mid-run.
        self.now = datetime(2026, 6, 15, 12, 0, 0)

    def test_under_a_minute_is_just_now(self):
        for delta_seconds in [0, 1, 30, 59]:
            dt = self.now - timedelta(seconds=delta_seconds)
            assert _humanize_relative_time(dt, now=self.now) == "just now", (
                f"{delta_seconds}s ago should be 'just now'"
            )

    def test_minute_bucket(self):
        assert _humanize_relative_time(
            self.now - timedelta(minutes=1), now=self.now,
        ) == "1m ago"
        assert _humanize_relative_time(
            self.now - timedelta(minutes=45), now=self.now,
        ) == "45m ago"
        assert _humanize_relative_time(
            self.now - timedelta(minutes=59), now=self.now,
        ) == "59m ago"

    def test_hour_bucket(self):
        assert _humanize_relative_time(
            self.now - timedelta(hours=1), now=self.now,
        ) == "1h ago"
        assert _humanize_relative_time(
            self.now - timedelta(hours=23), now=self.now,
        ) == "23h ago"

    def test_day_bucket(self):
        assert _humanize_relative_time(
            self.now - timedelta(days=1), now=self.now,
        ) == "1d ago"
        assert _humanize_relative_time(
            self.now - timedelta(days=6, hours=23), now=self.now,
        ) == "6d ago"

    def test_week_bucket(self):
        assert _humanize_relative_time(
            self.now - timedelta(days=7), now=self.now,
        ) == "1w ago"
        assert _humanize_relative_time(
            self.now - timedelta(days=29), now=self.now,
        ) == "4w ago"

    def test_absolute_date_same_year(self):
        """30+ days drops to absolute date. Same calendar year → no
        year suffix."""
        result = _humanize_relative_time(
            datetime(2026, 4, 8, 9, 0), now=self.now,
        )
        assert result == "Apr 8", f"Expected 'Apr 8', got {result!r}"

    def test_absolute_date_cross_year(self):
        """30+ days AND a different year → include "'YY" suffix so the
        user isn't confused about whether something added in December
        was last year or this year."""
        result = _humanize_relative_time(
            datetime(2025, 11, 3, 9, 0), now=self.now,
        )
        assert result == "Nov 3, '25", (
            f"Cross-year should include year suffix; got {result!r}"
        )

    def test_clock_skew_future_dated_renders_as_just_now(self):
        """If `dt` is slightly in the future (NTP drift, multi-process
        clock skew, test-fixture timing), don't render 'in 3 seconds'
        — degrade to 'just now' so the UI never shows nonsense."""
        future = self.now + timedelta(seconds=10)
        assert _humanize_relative_time(future, now=self.now) == "just now"

    def test_none_input_renders_empty(self):
        """Defensive — a missing timestamp returns "" rather than
        raising. Shouldn't happen in production (added_at is NOT NULL)
        but the helper shouldn't depend on that invariant."""
        assert _humanize_relative_time(None, now=self.now) == ""


# ---------------------------------------------------------------------------
# 2. _is_pantry_item_stale — threshold boundary
# ---------------------------------------------------------------------------

class TestStaleAgeThreshold:
    def setup_method(self):
        self.now = datetime(2026, 6, 15, 12, 0, 0)

    def test_under_threshold_is_fresh(self):
        for days in [0, 1, 7, PANTRY_STALE_AGE_DAYS - 1]:
            dt = self.now - timedelta(days=days)
            assert not _is_pantry_item_stale(dt, now=self.now), (
                f"{days}d old should NOT be stale (threshold is "
                f"{PANTRY_STALE_AGE_DAYS}d)"
            )

    def test_at_or_over_threshold_is_stale(self):
        for days in [PANTRY_STALE_AGE_DAYS, PANTRY_STALE_AGE_DAYS + 10, 90]:
            dt = self.now - timedelta(days=days)
            assert _is_pantry_item_stale(dt, now=self.now), (
                f"{days}d old SHOULD be stale (threshold is "
                f"{PANTRY_STALE_AGE_DAYS}d)"
            )

    def test_none_input_is_not_stale(self):
        """Defensive — None timestamps render as fresh rather than
        crashing the template."""
        assert _is_pantry_item_stale(None, now=self.now) is False


# ---------------------------------------------------------------------------
# 3. Template rendering — wiring through the partial
# ---------------------------------------------------------------------------

class TestPantryItemRendering:
    def test_every_item_has_relative_time_stamp(self, client):
        """Pre-Phase-4B, timestamps only appeared via 'added by X' for
        cross-household items. After 4B, every row carries a relative
        time stamp — gives the user temporal context unconditionally."""
        sign_up(client, "alice@example.com", "Alice")
        _add_pantry(client, "Milk")
        html = client.get("/pantry").get_data(as_text=True)
        # Either "just now" (most likely — added moments ago) or "Xm ago".
        # Either way, the word "added" should precede a relative-time
        # phrase on the rendered card.
        assert "just now" in html or "m ago" in html, (
            "Every pantry item should render a relative timestamp. "
            "Looked for 'just now' or 'm ago' — found neither."
        )

    def test_time_element_carries_iso_datetime(self, client):
        """Semantic markup: <time datetime="..."> with ISO 8601 value.
        Screen readers + future browser tooling rely on this attribute,
        not the visible text."""
        sign_up(client, "alice@example.com", "Alice")
        _add_pantry(client, "Milk")
        html = client.get("/pantry").get_data(as_text=True)
        time_match = re.search(
            r'<time datetime="(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[\d.]*Z?)"',
            html,
        )
        assert time_match, (
            "Expected a <time datetime='YYYY-MM-DDTHH:MM:SS...'> element "
            "for screen-reader accessibility"
        )

    def test_solo_household_still_no_added_by_you_noise(self, client):
        """Phase 2A invariant preserved — solo households never say
        'added by you'. Phase 4B only adds 'added 2m ago' style text,
        no "by" attribution to self."""
        sign_up(client, "alice@example.com", "Alice")
        _add_pantry(client, "Milk")
        html = client.get("/pantry").get_data(as_text=True)
        assert "added by" not in html, (
            "Solo households must NOT render 'added by' anywhere — "
            "regressed the Phase 2A solo-noise rule."
        )

    def test_other_household_member_attribution_preserved(self, app, two_clients):
        """The 'added by Alice' wording survives Phase 4B — both
        because it's the existing UX users know and because the
        Phase 2A test still asserts on that exact substring."""
        alice, bob = two_clients
        _setup_shared_household(app, alice, bob)
        _add_pantry(alice, "Sourdough")
        body = bob.get("/pantry").get_data(as_text=True)
        assert "added by Alice" in body, (
            "Cross-household attribution wording 'added by Alice' must "
            "still appear; Phase 4B only adds a ' · 2m ago' suffix."
        )

    def test_fresh_items_render_stone_color(self, client, app):
        """A fresh item gets the soft stone-400 timestamp — visually
        recedes when most of the pantry is fresh."""
        sign_up(client, "alice@example.com", "Alice")
        _add_pantry(client, "Milk")  # added "just now" → fresh
        html = client.get("/pantry").get_data(as_text=True)
        # Find the Milk card and inspect its meta line
        milk_block = _item_block(html, "Milk")
        assert milk_block, "couldn't find Milk row"
        meta_line = re.search(
            r'<p class="mt-1 text-\[11px\] ([^"]+)">',
            milk_block,
        )
        assert meta_line, "meta line not found on Milk card"
        classes = meta_line.group(1)
        assert "text-stone-400" in classes, (
            f"Fresh item should use text-stone-400; got classes: {classes}"
        )
        assert "text-amber-600" not in classes, (
            f"Fresh item must NOT have stale amber treatment; "
            f"got classes: {classes}"
        )

    def test_stale_items_render_amber_color(self, client, app):
        """Items older than PANTRY_STALE_AGE_DAYS flip to text-amber-600
        so the user gets a soft 'this has been here a while' nudge.
        Push added_at back via the test helper rather than time-mocking
        — exercises the actual SQL data path."""
        sign_up(client, "alice@example.com", "Alice")
        _add_pantry(client, "Forgotten")
        _set_added_at(
            app, "Forgotten",
            datetime.utcnow() - timedelta(days=PANTRY_STALE_AGE_DAYS + 5),
        )
        html = client.get("/pantry").get_data(as_text=True)
        block = _item_block(html, "Forgotten")
        assert block, "couldn't find Forgotten row"
        meta_line = re.search(
            r'<p class="mt-1 text-\[11px\] ([^"]+)">',
            block,
        )
        assert meta_line, "meta line not found on Forgotten card"
        classes = meta_line.group(1)
        assert "text-amber-600" in classes, (
            f"Stale item should use text-amber-600; got classes: {classes}. "
            f"If text-stone-400 is present, the is_stale_age filter is "
            f"not wired through the template correctly."
        )
        assert "text-stone-400" not in classes, (
            f"Stale item must NOT carry the fresh stone-400 class too; "
            f"got: {classes}"
        )

    def test_stale_item_shows_absolute_or_week_text(self, client, app):
        """A 30+ day old item should drop out of the "Nd / Nw ago"
        buckets and into the absolute date format. Tests the full
        bucketing chain through the template."""
        sign_up(client, "alice@example.com", "Alice")
        _add_pantry(client, "OldThing")
        # 45 days ago → past the 30d threshold → absolute date
        _set_added_at(
            app, "OldThing", datetime.utcnow() - timedelta(days=45),
        )
        html = client.get("/pantry").get_data(as_text=True)
        block = _item_block(html, "OldThing")
        # Should contain month-abbrev + day number, NOT "Nw ago" / "Nd ago"
        assert re.search(
            r'(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) \d{1,2}',
            block,
        ), f"45-day-old item should show absolute date; block was: {block[:500]}"

    def test_time_element_appears_on_self_added_items_too(self, client):
        """The relative-time stamp shows on items the current_user
        added themselves — that's the visible change from Phase 2A
        which suppressed the whole metadata line in solo households."""
        sign_up(client, "alice@example.com", "Alice")
        _add_pantry(client, "Bread")
        html = client.get("/pantry").get_data(as_text=True)
        # <time> element present even though no "added by X" attribution
        block = _item_block(html, "Bread")
        assert "<time" in block, (
            "Self-added items should still render <time> for the "
            "relative-time stamp."
        )

    def test_added_by_other_includes_separator_and_time(
        self, app, two_clients,
    ):
        """For cross-household items, the line reads 'added by Alice · 2m ago'
        — attribution + ' · ' separator + relative time, all on one line."""
        alice, bob = two_clients
        _setup_shared_household(app, alice, bob)
        _add_pantry(alice, "Olives")
        body = bob.get("/pantry").get_data(as_text=True)
        block = _item_block(body, "Olives")
        # Collapse whitespace for a stable substring assert across
        # Jinja's `-` whitespace-stripping inconsistencies
        compact = re.sub(r"\s+", " ", block)
        assert "added by Alice ·" in compact, (
            f"Cross-household line should read 'added by Alice ·' "
            f"followed by relative time; got: {compact[:400]}"
        )
        # And the <time> element is on the same paragraph
        assert "<time" in block
