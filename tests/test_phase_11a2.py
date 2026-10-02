"""
Phase 11A.2 regression suite — pantry expiry urgency.

Expiry remains informational: labels and colors make dates that are expired
or within three calendar days easier to notice. The app never blocks an item
solely because its date has passed.

Tier-1 dev loop:

    pytest tests/test_phase_11a2.py -q
"""
from __future__ import annotations

import re
from datetime import date, timedelta

from app import (
    PANTRY_EXPIRING_SOON_DAYS,
    _humanize_pantry_expiry,
    _pantry_expiry_status,
)
from tests.conftest import Client, sign_up


def _add_pantry(client: Client, name: str, expiry_date: date) -> None:
    response = client.post("/pantry", htmx=True, data={
        "name": name,
        "quantity": "",
        "unit": "",
        "notes": "",
        "expiry_date": expiry_date.isoformat(),
    })
    assert response.status_code in (200, 204)


def _item_block(html: str, name: str) -> str:
    for match in re.finditer(
        r'id="pantry-item-\d+"(.*?)(?=id="pantry-item-|\Z)',
        html,
        re.DOTALL,
    ):
        if name in match.group(1):
            return match.group(0)
    raise AssertionError(f"Could not find pantry item {name!r}")


class TestExpiryUrgencyRules:
    def setup_method(self):
        self.today = date(2026, 10, 2)

    def test_status_boundaries_are_calendar_day_based(self):
        assert _pantry_expiry_status(None, today=self.today) is None
        assert (
            _pantry_expiry_status(
                self.today - timedelta(days=1), today=self.today,
            )
            == "expired"
        )
        for days in range(PANTRY_EXPIRING_SOON_DAYS + 1):
            assert (
                _pantry_expiry_status(
                    self.today + timedelta(days=days), today=self.today,
                )
                == "soon"
            )
        assert (
            _pantry_expiry_status(
                self.today + timedelta(days=PANTRY_EXPIRING_SOON_DAYS + 1),
                today=self.today,
            )
            is None
        )

    def test_humanized_copy_matches_the_status(self):
        assert _humanize_pantry_expiry(
            self.today - timedelta(days=1), today=self.today,
        ) == "Expired yesterday"
        assert _humanize_pantry_expiry(
            self.today - timedelta(days=2), today=self.today,
        ) == "Expired 2d ago"
        assert _humanize_pantry_expiry(self.today, today=self.today) == "Expires today"
        assert _humanize_pantry_expiry(
            self.today + timedelta(days=1), today=self.today,
        ) == "Expires tomorrow"
        assert _humanize_pantry_expiry(
            self.today + timedelta(days=3), today=self.today,
        ) == "Expires in 3d"
        assert _humanize_pantry_expiry(
            self.today + timedelta(days=4), today=self.today,
        ) == "Expires Oct 6, 2026"


class TestExpiryUrgencyRendering:
    def test_expired_and_soon_dates_have_distinct_labels_and_colors(self, client):
        sign_up(client, "alice@example.com", "Alice")
        today = date.today()
        _add_pantry(client, "Expired milk", today - timedelta(days=1))
        _add_pantry(client, "Use soon eggs", today + timedelta(days=2))
        _add_pantry(
            client,
            "Later pasta",
            today + timedelta(days=PANTRY_EXPIRING_SOON_DAYS + 1),
        )

        html = client.get("/pantry").get_data(as_text=True)
        expired = _item_block(html, "Expired milk")
        soon = _item_block(html, "Use soon eggs")
        later = _item_block(html, "Later pasta")

        assert "Expired yesterday" in expired
        assert "font-semibold text-red-700" in expired
        assert "Expires in 2d" in soon
        assert "font-medium text-amber-700" in soon
        assert 'class="text-stone-500">Expires ' in later

    def test_compact_density_keeps_expiry_urgency_visible(self, client):
        sign_up(client, "alice@example.com", "Alice")
        _add_pantry(client, "Expired milk", date.today() - timedelta(days=1))
        client.post("/pantry/density", data={"density": "compact"}, htmx=True)

        html = client.get("/pantry").get_data(as_text=True)
        expired = _item_block(html, "Expired milk")
        assert "Expired yesterday" in expired
        assert "font-semibold text-red-700" in expired
