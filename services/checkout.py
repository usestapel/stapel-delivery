"""The orders seam: options, the shipping adjuster, the checkout hooks, order facts.

Payload shapes are the wave contract (SPEC-BRICKS-WAVE-2026-11-12 §2) as
built by stapel-orders (its CONTRACT-DELTAS): the adjuster request
``{currency, subtotal, user_id|null, actor_id?, lines, adjustments_so_far,
context}``; reserve = that plus ``attempt_key``; commit ``{attempt_key,
token|null, order_id, user_id|null, actor_id?}``; release ``{attempt_key,
token|null, order_id|null, reason}``. ``user_id`` is null for a guest;
``actor_id`` (the guest's own id, or the account) owns intents and
shipments when present (:func:`owner_of`). Orders is never imported.

The address snapshot never rides an adjustment's ``meta`` (orders keeps
meta past GDPR erasure): reserve stores it in a ``DeliveryIntent`` keyed on
``attempt_key``, and commit (or ``orders.order.placed``) turns the intent
into a shipment.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import logging
from dataclasses import dataclass, field

from django.db import IntegrityError, transaction
from django.utils import timezone

from .. import money
from ..carriers import carrier_for_method
from ..errors import (
    ERR_400_DELIVERY_ADDRESS_REQUIRED,
    ERR_400_DELIVERY_METHOD_REQUIRED,
    ERR_400_DELIVERY_METHOD_UNKNOWN,
    ERR_400_PICKUP_POINT_REQUIRED,
    ERR_400_PICKUP_POINT_UNKNOWN,
    ERR_404_ADDRESS_NOT_FOUND,
    ERR_409_DELIVERY_UNAVAILABLE,
)
from ..models import (
    RELEASE_CANCELLED,
    RELEASE_REASON_MAX_LENGTH,
    DeliveryIntent,
    DeliveryMethod,
    IntentStatus,
    MethodKind,
    PickupPoint,
    Shipment,
)
from . import DeliveryError
from . import addresses as address_service
from . import rates
from . import shipments as shipment_service

logger = logging.getLogger(__name__)

ADJUSTMENT_KIND = "shipping"


@dataclass
class Choice:
    """A validated delivery choice for one cart."""

    method: DeliveryMethod
    carrier: str
    price: rates.Price
    cart: rates.CartShape
    recipient: address_service.Recipient | None = None
    pickup_point: PickupPoint | None = None


@dataclass
class Evaluation:
    """What the adjuster answers, and the choice reserve stores."""

    choice: Choice | None = None
    errors: list[dict] = field(default_factory=list)
    shippable: bool = True

    def adjustments(self) -> list[dict]:
        if self.choice is None:
            return []
        c = self.choice
        meta = {
            "method": c.method.code,
            "kind": c.method.kind,
            "carrier": c.carrier,
            "zone": c.price.zone,
            "weight_basis": c.price.weight_basis,
        }
        if c.price.free_reason:
            meta["free_reason"] = c.price.free_reason
        if c.pickup_point is not None:
            meta["pickup_point"] = c.pickup_point.code
        return [{
            "kind": ADJUSTMENT_KIND,
            "code": c.method.code,
            "label": c.method.name,
            "amount": money.to_wire(c.price.amount),
            "line_index": None,
            "meta": meta,
        }]


def pickup_snapshot(point: PickupPoint) -> dict:
    return {
        "code": point.code,
        "name": point.name,
        "line1": point.line1,
        "line2": point.line2,
        "city": point.city,
        "region": point.region,
        "postal_code": point.postal_code,
        "country": point.country,
    }


def _destination_of_point(point: PickupPoint) -> rates.Destination:
    return rates.Destination(country=point.country, region=point.region, postal_code=point.postal_code)


def _choose(request: dict) -> Choice | None:
    """Validate ``context.delivery`` against the catalog; raises DeliveryError."""
    from ..conf import delivery_settings

    cart = rates.cart_shape(request["currency"], request["subtotal"], request.get("lines") or [])
    if not cart.shippable:
        return None
    context = request.get("context") or {}
    delivery = context.get("delivery") if isinstance(context, dict) else None
    if not isinstance(delivery, dict) or not delivery.get("method"):
        if delivery_settings.REQUIRE_METHOD:
            raise DeliveryError(400, ERR_400_DELIVERY_METHOD_REQUIRED, field="delivery.method")
        return None
    code = str(delivery["method"])
    method = DeliveryMethod.objects.filter(code=code, enabled=True).first()
    if method is None:
        raise DeliveryError(400, ERR_400_DELIVERY_METHOD_UNKNOWN, {"method": code[:32]},
                            field="delivery.method")
    recipient = point = None
    dest = None
    if method.kind == MethodKind.COURIER:
        user_id = request.get("user_id")
        if delivery.get("address_id") is not None:
            if not user_id:
                raise DeliveryError(404, ERR_404_ADDRESS_NOT_FOUND,
                                    field="delivery.address_id")
            recipient = address_service.from_address(
                address_service.get_owned(str(user_id), delivery["address_id"]))
        elif delivery.get("address") is not None:
            recipient = address_service.validate_snapshot(delivery["address"])
        else:
            raise DeliveryError(400, ERR_400_DELIVERY_ADDRESS_REQUIRED, field="delivery.address")
        dest = recipient.destination()
    elif method.kind == MethodKind.PICKUP:
        point_code = delivery.get("pickup_point")
        if not point_code:
            raise DeliveryError(400, ERR_400_PICKUP_POINT_REQUIRED, field="delivery.pickup_point")
        point = PickupPoint.objects.filter(code=str(point_code), method=method, enabled=True).first()
        if point is None:
            raise DeliveryError(400, ERR_400_PICKUP_POINT_UNKNOWN, {"pickup_point": str(point_code)[:64]},
                                field="delivery.pickup_point")
        dest = _destination_of_point(point)
    price = rates.price_for(method, cart, dest, request.get("adjustments_so_far"))
    if price is None:
        raise DeliveryError(409, ERR_409_DELIVERY_UNAVAILABLE, {"method": method.code},
                            field="delivery.method")
    return Choice(method=method, carrier=carrier_for_method(method).slug, price=price, cart=cart,
                  recipient=recipient, pickup_point=point)


def evaluate(request: dict) -> Evaluation:
    try:
        choice = _choose(request)
    except DeliveryError as exc:
        return Evaluation(errors=[exc.as_contract_error()])
    if choice is None:
        cart = rates.cart_shape(request["currency"], request["subtotal"], request.get("lines") or [])
        return Evaluation(shippable=cart.shippable)
    return Evaluation(choice=choice)


def quote(request: dict) -> dict:
    """The ``delivery.quote`` adjuster answer."""
    result = evaluate(request)
    return {"adjustments": result.adjustments(), "errors": result.errors}


# ── options (what the checkout page lists) ────────────────────────────────


def options(request: dict) -> list[dict]:
    """Every enabled method with its price for this cart and destination.

    ``address`` may be partial here (country / region / postal_code are
    enough to price); ``address_id`` names an entry of ``user_id``'s book.
    Pickup methods are priced at their cheapest matching point
    (``price_is_minimum``).
    """
    cart = rates.cart_shape(request["currency"], request["subtotal"], request.get("lines") or [])
    dest = None
    user_id = request.get("user_id")
    if request.get("address_id") is not None and user_id:
        dest = address_service.from_address(
            address_service.get_owned(str(user_id), request["address_id"])).destination()
    elif isinstance(request.get("address"), dict) and request["address"].get("country"):
        raw = request["address"]
        dest = rates.Destination(country=str(raw["country"]).upper()[:2],
                                 region=str(raw.get("region") or "")[:100],
                                 postal_code=str(raw.get("postal_code") or "")[:20])
    answer = []
    for method in DeliveryMethod.objects.filter(enabled=True).order_by("sort", "id"):
        answer.append(_option(method, cart, dest, request.get("adjustments_so_far")))
    return answer


def _option(method, cart, dest, adjustments_so_far) -> dict:
    option = {
        "code": method.code,
        "name": method.name,
        "description": method.description,
        "kind": method.kind,
        "eta_min_days": method.eta_min_days,
        "eta_max_days": method.eta_max_days,
        "available": False,
        "price": None,
        "price_is_minimum": False,
        "currency": cart.currency,
        "free_reason": None,
        "reason": None,
    }
    price = None
    if method.kind == MethodKind.PICKUP:
        points = method.pickup_points.filter(enabled=True)
        if dest is not None:
            points = points.filter(country=dest.country)
        prices = [p for p in (rates.price_for(method, cart, _destination_of_point(pt), adjustments_so_far)
                              for pt in points[:200]) if p is not None]
        if prices:
            price = min(prices, key=lambda p: p.amount)
            option["price_is_minimum"] = len({p.amount for p in prices}) > 1
    elif method.kind == MethodKind.COURIER and dest is None:
        price = rates.price_for(method, cart, None, adjustments_so_far)
        if price is None:
            option["reason"] = ERR_400_DELIVERY_ADDRESS_REQUIRED
            return option
    else:
        price = rates.price_for(method, cart, dest, adjustments_so_far)
    if price is None:
        option["reason"] = ERR_409_DELIVERY_UNAVAILABLE
        return option
    option.update(available=True, price=money.to_wire(price.amount), free_reason=price.free_reason)
    return option


# ── checkout hooks ────────────────────────────────────────────────────────


def lines_fingerprint(currency: str, lines: list[dict]) -> str:
    """Currency + sorted (type, key, quantity, unit price): what reserve and placed share."""
    rows = sorted(
        (str(line.get("purchasable_type")), str(line.get("purchasable_key")),
         int(line.get("quantity") or 0),
         money.to_wire(money.parse_decimal(line.get("unit_price") or "0", field="unit_price")))
        for line in lines
    )
    raw = json.dumps([str(currency).upper(), rows], separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def owner_of(payload: dict) -> str:
    """Who owns this checkout's rows: ``actor_id`` (a guest's own id too), else ``user_id``.

    Orders sends ``actor_id`` next to ``user_id`` (null for a guest); payloads
    of an orders that predates it carry ``user_id`` only.
    """
    return str(payload.get("actor_id") or payload.get("user_id") or "")


def _token(intent: DeliveryIntent) -> str:
    return f"dl-{intent.pk}"


def reserve(request: dict) -> dict:
    """Stash the validated choice under ``attempt_key``. Idempotent; re-reserves after release."""
    attempt_key = str(request["attempt_key"])
    result = evaluate(request)
    if result.errors:
        return {"ok": False, "token": None, "errors": result.errors}
    if result.choice is None:
        return {"ok": True, "token": None, "errors": []}
    c = result.choice
    fields = dict(
        user_id=owner_of(request),
        status=IntentStatus.RESERVED,
        method_code=c.method.code,
        method_name=c.method.name,
        method_kind=c.method.kind,
        carrier=c.carrier,
        recipient=c.recipient.as_dict() if c.recipient is not None else {},
        pickup_point=pickup_snapshot(c.pickup_point) if c.pickup_point is not None else {},
        amount=c.price.amount,
        currency=c.cart.currency,
        weight_kg=c.cart.weight_kg,
        shippable=c.cart.shippable,
        lines_fingerprint=lines_fingerprint(request["currency"], request.get("lines") or []),
        order_id="",
    )
    with transaction.atomic():
        intent = DeliveryIntent.objects.select_for_update().filter(attempt_key=attempt_key).first()
        if intent is not None and intent.status == IntentStatus.COMMITTED:
            return {"ok": True, "token": _token(intent), "errors": []}
        if intent is None:
            try:
                with transaction.atomic():
                    intent = DeliveryIntent.objects.create(attempt_key=attempt_key, **fields)
            except IntegrityError:
                intent = DeliveryIntent.objects.select_for_update().get(attempt_key=attempt_key)
                if intent.status == IntentStatus.COMMITTED:
                    return {"ok": True, "token": _token(intent), "errors": []}
        if intent.status != IntentStatus.RESERVED or any(
                getattr(intent, k) != v for k, v in fields.items()):
            for key, value in fields.items():
                setattr(intent, key, value)
            intent.save()
    return {"ok": True, "token": _token(intent), "errors": []}


def commit(payload: dict) -> dict:
    """Bind the intent to the order and create the shipment. Idempotent."""
    attempt_key = str(payload["attempt_key"])
    order_id = str(payload.get("order_id") or "")
    intent = DeliveryIntent.objects.filter(attempt_key=attempt_key).first()
    if intent is None or not order_id:
        return {"ok": True}
    owner = owner_of(payload)
    if not intent.user_id and owner:
        DeliveryIntent.objects.filter(pk=intent.pk, user_id="").update(user_id=owner)
    shipment_service.link_and_create(intent.pk, order_id, [])
    return {"ok": True}


def release(payload: dict) -> dict:
    """Undo a reservation; only ``cancelled`` undoes a committed one.

    reserved + any reason -> released (a cancelled one also cancels the
    order's shipment, if any; a cancel after another release is recorded so
    a late commit does not ship); committed + ``cancelled`` -> the shipment is
    cancelled if it has not left; committed + ``checkout_failed`` /
    ``orphaned`` -> no-op: the pair belongs to a placed order.
    """
    attempt_key = str(payload["attempt_key"])
    reason = str(payload.get("reason") or "")[:RELEASE_REASON_MAX_LENGTH]
    with transaction.atomic():
        intent = DeliveryIntent.objects.select_for_update().filter(attempt_key=attempt_key).first()
        if intent is None:
            return {"ok": True}
        if intent.status == IntentStatus.COMMITTED and reason != RELEASE_CANCELLED:
            logger.info("delivery: release(%s) of committed intent %s ignored", reason, attempt_key)
            return {"ok": True}
        order_id = intent.order_id or str(payload.get("order_id") or "")
        if intent.status == IntentStatus.RESERVED or (
                intent.status == IntentStatus.RELEASED and reason == RELEASE_CANCELLED
                and intent.release_reason != RELEASE_CANCELLED):
            # A cancel is remembered over an earlier release: a late commit must not ship.
            intent.status = IntentStatus.RELEASED
            intent.release_reason = reason
            intent.save(update_fields=["status", "release_reason", "updated_at"])
    if order_id and reason == RELEASE_CANCELLED:
        shipment_service.cancel_for_order(order_id, reason="order cancelled")
    return {"ok": True}


# ── order facts ───────────────────────────────────────────────────────────


def _find_intent(payload: dict, now: dt.datetime) -> DeliveryIntent | None:
    order_id = str(payload["order_id"])
    if payload.get("attempt_key"):
        intent = DeliveryIntent.objects.filter(attempt_key=str(payload["attempt_key"])).first()
        if intent is not None:
            return intent
    intent = DeliveryIntent.objects.filter(order_id=order_id).first()
    if intent is not None:
        return intent
    if payload.get("actor_id"):
        # An orders that names the actor also sends attempt_key: no guessing.
        return None
    from ..conf import delivery_settings

    horizon = now - dt.timedelta(hours=int(delivery_settings.INTENT_TTL_HOURS))
    fingerprint = lines_fingerprint(payload["currency"], payload.get("lines") or [])
    return (
        DeliveryIntent.objects.filter(
            lines_fingerprint=fingerprint, order_id="",
            status__in=(IntentStatus.RESERVED, IntentStatus.COMMITTED),
            user_id__in=(str(payload.get("user_id") or ""), ""),
            created_at__gte=horizon,
        ).order_by("created_at", "id").first()
    )


def order_placed(payload: dict, now: dt.datetime | None = None) -> str:
    """``orders.order.placed`` → the order's shipment. Returns what happened."""
    now = now or timezone.now()
    order_id = str(payload["order_id"])
    user_id = owner_of(payload)
    shipment = Shipment.objects.filter(order_id=order_id).first()
    if shipment is None:
        intent = _find_intent(payload, now)
        if intent is None:
            logger.info("delivery: order %s placed without a delivery choice; no shipment", order_id)
            return "no_intent"
        shipment = shipment_service.link_and_create(intent.pk, order_id, payload.get("lines") or [])
        if shipment is None:
            return "no_shipment"
        outcome = "created"
    else:
        outcome = "exists"
    updates = {}
    if user_id and not shipment.user_id:
        updates["user_id"] = user_id
    if not shipment.lines and payload.get("lines"):
        updates["lines"] = [
            {"purchasable_type": line.get("purchasable_type"),
             "purchasable_key": line.get("purchasable_key"),
             "quantity": int(line.get("quantity") or 0)}
            for line in payload["lines"]
        ]
    if updates:
        Shipment.objects.filter(pk=shipment.pk).update(**updates, updated_at=now)
    return outcome


def order_status_changed(payload: dict) -> str:
    if payload.get("to") != "cancelled":
        return "ignored"
    return shipment_service.cancel_for_order(str(payload["order_id"]), reason="order cancelled")


__all__ = [
    "evaluate", "commit", "owner_of", "lines_fingerprint", "options", "order_placed", "order_status_changed",
    "quote", "release", "reserve",
]

