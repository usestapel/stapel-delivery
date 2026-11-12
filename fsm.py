"""The shipment lifecycle table — the only source of legal status moves.

``staff`` and ``carrier`` may take any edge; ``system`` (an order cancelled
through orders, a released checkout) only cancels what has not left yet.
"""
from __future__ import annotations

from .models import ShipmentStatus as S

STAFF = "staff"
CARRIER = "carrier"
SYSTEM = "system"
ACTORS = (STAFF, CARRIER, SYSTEM)

#: (from, to) -> actors allowed to take the edge.
TRANSITIONS: dict[tuple[str, str], frozenset[str]] = {
    (S.PENDING, S.PACKED): frozenset({STAFF, CARRIER}),
    (S.PENDING, S.SHIPPED): frozenset({STAFF, CARRIER}),
    (S.PACKED, S.SHIPPED): frozenset({STAFF, CARRIER}),
    (S.SHIPPED, S.DELIVERED): frozenset({STAFF, CARRIER}),
    (S.SHIPPED, S.RETURNED): frozenset({STAFF, CARRIER}),
    (S.DELIVERED, S.RETURNED): frozenset({STAFF, CARRIER}),
    (S.PENDING, S.CANCELLED): frozenset({STAFF, CARRIER, SYSTEM}),
    (S.PACKED, S.CANCELLED): frozenset({STAFF, CARRIER, SYSTEM}),
}

TERMINAL = frozenset({S.RETURNED, S.CANCELLED})

#: Targets a staff transition request may name (the enum on the wire).
STAFF_TARGETS = (S.PACKED, S.SHIPPED, S.DELIVERED, S.RETURNED, S.CANCELLED)


class TransitionInvalid(Exception):
    pass


def allowed(from_status: str, to_status: str, actor: str) -> bool:
    return actor in TRANSITIONS.get((str(from_status), str(to_status)), frozenset())


def check(from_status: str, to_status: str, actor: str) -> None:
    if not allowed(from_status, to_status, actor):
        raise TransitionInvalid(f"{from_status} -> {to_status} by {actor}")


def next_forward(status: str) -> str | None:
    """The happy-path successor (what the demo carrier advances to)."""
    return {S.PENDING: S.PACKED, S.PACKED: S.SHIPPED, S.SHIPPED: S.DELIVERED}.get(status)
