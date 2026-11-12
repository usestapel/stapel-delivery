"""Action subscriptions of stapel-delivery.

Handlers are idempotent: delivery is at-least-once.

- ``orders.order.placed`` — the order's shipment is created from the
  checkout intent (when the commit hook has not already done it).
- ``orders.order.status_changed`` — an order moved to ``cancelled``: its
  shipment is cancelled if it has not left.
- ``user.merged`` (stapel-auth) — a guest was folded into an account on
  sign-in: its addresses, shipments and intents follow it.
- ``user.deleted`` / ``gdpr.erasure.requested`` are answered by
  ``register_gdpr_owner`` (``apps.py``), not here.

Without stapel-orders installed the two orders facts never arrive and
nothing here runs; the schemas are tolerant readers (extra keys allowed),
because orders owns those facts.
"""
import json
import logging
from pathlib import Path

from stapel_core.comm import on_action

logger = logging.getLogger(__name__)

_CONSUMES = Path(__file__).resolve().parent / "schemas" / "consumes"


def _schema(name: str) -> dict:
    return json.loads((_CONSUMES / f"{name}.json").read_text(encoding="utf-8"))


@on_action("orders.order.placed", schema=_schema("orders.order.placed"))
def handle_order_placed(event):
    from .services.checkout import order_placed

    outcome = order_placed(event.payload or {})
    logger.info("orders.order.placed %s: %s", event.event_id, outcome)


@on_action("orders.order.status_changed", schema=_schema("orders.order.status_changed"))
def handle_order_status_changed(event):
    from .services.checkout import order_status_changed

    outcome = order_status_changed(event.payload or {})
    if outcome not in ("ignored", "none"):
        logger.info("orders.order.status_changed %s: %s", event.event_id, outcome)


@on_action("user.merged", schema=_schema("user.merged"))
def handle_user_merged(event):
    from django.db import transaction

    from .services import addresses, shipments

    payload = event.payload or {}
    from_user_id = str(payload.get("from_user_id") or "")
    into_user_id = str(payload.get("into_user_id") or "")
    if not from_user_id or not into_user_id:
        logger.error("user.merged without from/into user id: %s", event.event_id)
        return
    if from_user_id == into_user_id:
        return
    with transaction.atomic():
        moved = {"addresses": addresses.merge_users(from_user_id, into_user_id),
                 **shipments.merge_users(from_user_id, into_user_id)}
    if any(moved.values()):
        logger.info("user.merged %s -> %s: %s", from_user_id, into_user_id, moved)
