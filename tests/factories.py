"""Catalog and payload builders shared by the suite.

``order_request`` builds exactly the orders adjuster request of the wave
contract §2 (as orders 0.2.0 sends it), so the tests speak to delivery the
way a real orders caller does.
"""
from __future__ import annotations

import uuid
from decimal import Decimal

from stapel_delivery.models import DeliveryMethod, MethodKind, PickupPoint, Rate, Zone

HOME = {
    "name": "Ada Buyer", "phone": "+1 555 0100", "line1": "1 Main St", "line2": "Apt 2",
    "city": "Springfield", "region": "IL", "postal_code": "62701", "country": "US",
}


class Catalog:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def make_catalog() -> Catalog:
    domestic = Zone.objects.create(code="domestic", name="Domestic", countries=["US"])
    metro = Zone.objects.create(code="metro", name="Metro", countries=["US"], postcode_prefixes=["627"])
    courier = DeliveryMethod.objects.create(code="courier", name="Courier", kind=MethodKind.COURIER,
                                            sort=10, eta_min_days=1, eta_max_days=3,
                                            tracking_url_template="https://track.example/{tracking_number}")
    Rate.objects.create(method=courier, zone=domestic, currency="USD", amount=Decimal("9.00"),
                        free_above=Decimal("100.00"), per_kg=Decimal("1.50"))
    Rate.objects.create(method=courier, zone=metro, currency="USD", amount=Decimal("5.00"),
                        free_above=Decimal("100.00"))
    pickup = DeliveryMethod.objects.create(code="pickup", name="Pickup point", kind=MethodKind.PICKUP, sort=20)
    Rate.objects.create(method=pickup, zone=None, currency="USD", amount=Decimal("2.00"))
    point = PickupPoint.objects.create(
        method=pickup, code="pp-1", name="Corner shop", line1="5 Side St", city="Springfield",
        region="IL", postal_code="62702", country="US", latitude=Decimal("39.781721"),
        longitude=Decimal("-89.650148"),
        hours=[{"weekday": d, "opens": "09:00", "closes": "20:00"} for d in range(6)],
    )
    digital = DeliveryMethod.objects.create(code="email", name="E-mail delivery", kind=MethodKind.DIGITAL, sort=30)
    return Catalog(domestic=domestic, metro=metro, courier=courier, pickup=pickup, point=point,
                   digital=digital)


def line(index=0, *, key="sku-1", quantity=1, unit_price="20.00", attrs=None, ptype="listing"):
    total = (Decimal(unit_price) * quantity).quantize(Decimal("0.01"))
    return {"index": index, "purchasable_type": ptype, "purchasable_key": key, "quantity": quantity,
            "unit_price": unit_price, "line_total": str(total), "attrs": attrs or {}}


def order_request(*, lines=None, delivery=None, user_id=None, currency="USD", adjustments=None,
                  extra_context=None):
    lines = lines if lines is not None else [line()]
    subtotal = sum((Decimal(entry["line_total"]) for entry in lines), Decimal("0.00"))
    context = dict(extra_context or {})
    if delivery is not None:
        context["delivery"] = delivery
    return {
        "currency": currency,
        "subtotal": str(subtotal.quantize(Decimal("0.01"))),
        "user_id": user_id,
        "lines": lines,
        "adjustments_so_far": adjustments or [],
        "context": context,
    }


def reserve_request(**kwargs):
    attempt_key = kwargs.pop("attempt_key", None) or str(uuid.uuid4())
    return {**order_request(**kwargs), "attempt_key": attempt_key}


def placed_event(order_id, request, user_id="1"):
    """``orders.order.placed`` for an order made from ``request`` (orders' own schema)."""
    return {
        "order_id": str(order_id),
        "user_id": str(user_id),
        "currency": request["currency"],
        "total": request["subtotal"],
        "placed_at": "2026-11-12T10:00:00+00:00",
        "lines": [
            {"purchasable_type": entry["purchasable_type"], "purchasable_key": entry["purchasable_key"],
             "quantity": entry["quantity"], "unit_price": entry["unit_price"], "seller_id": None}
            for entry in request["lines"]
        ],
    }
