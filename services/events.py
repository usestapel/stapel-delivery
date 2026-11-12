"""Facts and courtesies stapel-delivery sends: emits and notifications.

Emits go through the caller's ``mutate_and_emit`` emitter (key = shipment
id), so the outbox row commits with the mutation. Recipient fields never
ride the bus. Notifications are best-effort and leave only after commit.
"""
from __future__ import annotations

import logging

from django.db import transaction

from ..money import to_wire

logger = logging.getLogger(__name__)

EVENT_CREATED = "delivery.shipment.created"
EVENT_STATUS_CHANGED = "delivery.shipment.status_changed"

NOTIFY_STATUS_CHANGED = "delivery.shipment_status_changed"


def created_payload(shipment) -> dict:
    return {
        "shipment_id": str(shipment.pk),
        "number": shipment.number,
        "order_id": shipment.order_id,
        "user_id": shipment.user_id,
        "method": shipment.method_code,
        "kind": shipment.method_kind,
        "carrier": shipment.carrier,
        "status": shipment.status,
        "amount": to_wire(shipment.amount),
        "currency": shipment.currency,
    }


def status_changed_payload(shipment, from_status: str, actor: str, note: str = "") -> dict:
    payload = {
        "shipment_id": str(shipment.pk),
        "number": shipment.number,
        "order_id": shipment.order_id,
        "user_id": shipment.user_id,
        "from": from_status,
        "to": shipment.status,
        "actor": actor,
        "carrier": shipment.carrier,
        "tracking_number": shipment.tracking_number or None,
    }
    if note:
        payload["note"] = note
    return payload


def shipment_url(shipment) -> str:
    from ..conf import delivery_settings

    template = delivery_settings.SHIPMENT_URL_TEMPLATE or ""
    if not template:
        return ""
    try:
        return template.format(shipment_id=shipment.pk, number=shipment.number, order_id=shipment.order_id)
    except (KeyError, IndexError, ValueError):
        logger.warning("SHIPMENT_URL_TEMPLATE %r cannot be formatted", template)
        return ""


def variables(shipment, **extra) -> dict:
    return {
        "shipment_id": str(shipment.pk),
        "shipment_number": shipment.number,
        "order_id": shipment.order_id,
        "method": shipment.method_name,
        "status": shipment.status,
        "tracking_number": shipment.tracking_number,
        "tracking_url": shipment.tracking_url,
        "shipment_url": shipment_url(shipment),
        **extra,
    }


def notify(notification_type: str, user_id: str, data: dict) -> bool:
    """Send one notification now (best-effort). Returns whether it was queued."""
    from ..conf import delivery_settings

    if not delivery_settings.NOTIFY or not user_id:
        return False
    try:
        from stapel_core.notifications.publish import request_notification

        return bool(request_notification(
            notification_type,
            user_id=user_id,
            variables=data,
            source_service="delivery",
        ))
    except Exception:
        logger.warning(
            "delivery: %s notification for shipment %s not sent",
            notification_type, data.get("shipment_id"), exc_info=True,
        )
        return False


def notify_after_commit(notification_type: str, user_id: str, shipment, **extra) -> None:
    from ..conf import delivery_settings

    if not delivery_settings.NOTIFY or not user_id:
        return
    data = variables(shipment, **extra)
    transaction.on_commit(lambda: notify(notification_type, user_id, data))
