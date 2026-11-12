"""Release and commit over every intent state: only ``cancelled`` undoes a commit.

The table is the contract (orders CONTRACT-DELTAS 13, 16, 17, 22): a release
with ``checkout_failed`` or ``orphaned`` for a committed pair is a no-op that
answers ok; ``cancelled`` cancels the shipment. A commit after a release
that was not a cancel still ships (the placed order is the fact); after a
cancel it is a no-op.
"""
import uuid

import pytest
from stapel_core.comm import call

from stapel_delivery.models import DeliveryIntent, IntentStatus, Shipment, ShipmentStatus

from .factories import HOME, reserve_request

pytestmark = pytest.mark.django_db

ORDER_ID = "701"
REASONS = ("checkout_failed", "orphaned", "cancelled")
STATES = ("unknown", "reserved", "committed",
          "released:checkout_failed", "released:orphaned", "released:cancelled")


def _commit(key):
    return call("delivery.commit", {"attempt_key": key, "token": None, "order_id": ORDER_ID, "user_id": None})


def _release(key, reason):
    order_id = ORDER_ID if reason == "cancelled" else None
    return call("delivery.release", {"attempt_key": key, "token": None, "order_id": order_id,
                                     "reason": reason})


def _arrange(state) -> str:
    req = reserve_request(delivery={"method": "courier", "address": HOME})
    key = req["attempt_key"]
    if state == "unknown":
        return str(uuid.uuid4())
    assert call("delivery.reserve", req)["ok"] is True
    if state == "committed":
        _commit(key)
        assert Shipment.objects.get(order_id=ORDER_ID).status == ShipmentStatus.PENDING
    elif state.startswith("released:"):
        _release(key, state.split(":", 1)[1])
    return key


def _observe(key):
    intent = DeliveryIntent.objects.filter(attempt_key=key).first()
    shipment = Shipment.objects.filter(order_id=ORDER_ID).first()
    return (
        None if intent is None else intent.status,
        None if shipment is None else shipment.status,
    )


R, C, X = IntentStatus.RESERVED, IntentStatus.COMMITTED, IntentStatus.RELEASED
PENDING, CANCELLED = ShipmentStatus.PENDING, ShipmentStatus.CANCELLED

#: (state, reason) -> (intent status, shipment status) after the release.
RELEASE_TABLE = {
    ("unknown", "checkout_failed"): (None, None),
    ("unknown", "orphaned"): (None, None),
    ("unknown", "cancelled"): (None, None),
    ("reserved", "checkout_failed"): (X, None),
    ("reserved", "orphaned"): (X, None),
    ("reserved", "cancelled"): (X, None),
    ("committed", "checkout_failed"): (C, PENDING),
    ("committed", "orphaned"): (C, PENDING),
    ("committed", "cancelled"): (C, CANCELLED),
    **{(f"released:{first}", reason): (X, None) for first in REASONS for reason in REASONS},
}

#: state -> (intent status, shipment status) after a commit.
COMMIT_TABLE = {
    "unknown": (None, None),
    "reserved": (C, PENDING),
    "committed": (C, PENDING),
    "released:checkout_failed": (C, PENDING),
    "released:orphaned": (C, PENDING),
    "released:cancelled": (X, None),
}


def test_the_tables_cover_every_pair():
    assert set(RELEASE_TABLE) == {(s, r) for s in STATES for r in REASONS}
    assert set(COMMIT_TABLE) == set(STATES)


@pytest.mark.parametrize("state,reason", sorted(RELEASE_TABLE))
def test_release(catalog, state, reason):
    key = _arrange(state)
    assert _release(key, reason) == {"ok": True}
    assert _observe(key) == RELEASE_TABLE[(state, reason)]
    assert _release(key, reason) == {"ok": True}
    assert _observe(key) == RELEASE_TABLE[(state, reason)]


@pytest.mark.parametrize("state", sorted(COMMIT_TABLE))
def test_commit(catalog, state):
    key = _arrange(state)
    assert _commit(key) == {"ok": True}
    assert _observe(key) == COMMIT_TABLE[state]
    assert Shipment.objects.count() <= 1


@pytest.mark.parametrize("first", ["checkout_failed", "orphaned"])
def test_a_cancel_after_another_release_stops_a_late_commit(catalog, first):
    key = _arrange(f"released:{first}")
    _release(key, "cancelled")
    assert DeliveryIntent.objects.get(attempt_key=key).release_reason == "cancelled"
    _commit(key)
    assert _observe(key) == (X, None)
