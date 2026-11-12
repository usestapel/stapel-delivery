"""comm Functions provided by stapel-delivery (schemas in ``schemas/functions/``).

- ``delivery.options`` — methods with prices for a cart and a destination.
- ``delivery.quote`` — the orders adjuster (``kind=shipping``).
- ``delivery.reserve`` / ``.commit`` / ``.release`` — the orders checkout hook.
- ``delivery.shipment.status`` — a shipment's state for another service.

Registered by name only: orders reaches them through
``STAPEL_ORDERS["ADJUSTERS"]`` / ``["CHECKOUT_HOOKS"]`` (``preset.py``), and
nothing here imports orders.
"""
from stapel_core.comm import function


@function("delivery.options")
def delivery_options(payload):
    from .services.checkout import options

    return {"options": options(payload)}


@function("delivery.quote")
def delivery_quote(payload):
    from .services.checkout import quote

    return quote(payload)


@function("delivery.reserve")
def delivery_reserve(payload):
    from .services.checkout import reserve

    return reserve(payload)


@function("delivery.commit")
def delivery_commit(payload):
    from .services.checkout import commit

    return commit(payload)


@function("delivery.release")
def delivery_release(payload):
    from .services.checkout import release

    return release(payload)


@function("delivery.shipment.status")
def shipment_status(payload):
    from .models import Shipment

    if payload.get("order_id"):
        shipment = Shipment.objects.filter(order_id=str(payload["order_id"])).first()
    else:
        key = str(payload.get("shipment_id") or "")
        shipment = Shipment.objects.filter(pk=int(key)).first() if key.isdigit() else None
    if shipment is None:
        return {"found": False}
    return {
        "found": True,
        "shipment_id": str(shipment.pk),
        "number": shipment.number,
        "order_id": shipment.order_id,
        "status": shipment.status,
        "method": shipment.method_code,
        "carrier": shipment.carrier,
        "tracking_number": shipment.tracking_number or None,
        "tracking_url": shipment.tracking_url or None,
        "shipped_at": shipment.shipped_at.isoformat() if shipment.shipped_at else None,
        "delivered_at": shipment.delivered_at.isoformat() if shipment.delivered_at else None,
    }
