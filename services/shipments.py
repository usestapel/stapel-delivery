"""Shipments: creation from an order, the FSM, tracking, carrier updates, reads.

Buyer reads are scoped by ``user_id``: a foreign id and an absent id answer
the same 404, with no staff bypass (staff use the staff endpoints). Every
status move goes through :func:`transition`, which checks ``fsm.py``, writes
a ``ShipmentEvent`` and emits ``delivery.shipment.status_changed`` in the
same transaction.
"""
from __future__ import annotations

import datetime as dt
import logging
import secrets

from django.db import IntegrityError, transaction
from django.db.models import QuerySet
from django.utils import timezone
from stapel_core.comm import mutate_and_emit

from .. import fsm
from ..carriers import CarrierUpdate, carrier_by_slug, get_carrier
from ..errors import ERR_404_SHIPMENT_NOT_FOUND, ERR_409_SHIPMENT_TRANSITION_INVALID
from ..models import (
    ACTIVE_STATUSES,
    RELEASE_CANCELLED,
    DeliveryIntent,
    DeliveryMethod,
    IntentStatus,
    MethodKind,
    Shipment,
    ShipmentEvent,
    ShipmentStatus,
)
from . import DeliveryError, events

logger = logging.getLogger(__name__)

_NUMBER_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567"
_NUMBER_ATTEMPTS = 8
#: Upper bound of shipments one carrier poll pass touches.
POLL_BATCH = 200


def _new_number(now: dt.datetime) -> str:
    suffix = "".join(secrets.choice(_NUMBER_ALPHABET) for _ in range(6))
    return f"{now:%Y%m%d}-{suffix}"


def _statuses(statuses) -> list[str]:
    return [s for s in (statuses or []) if s in ShipmentStatus.values]


def for_user(user_id: str, statuses=None, order_id: str | None = None) -> QuerySet:
    qs = Shipment.objects.filter(user_id=str(user_id))
    return _filtered(qs, statuses, order_id)


def for_staff(statuses=None, order_id: str | None = None) -> QuerySet:
    return _filtered(Shipment.objects.all(), statuses, order_id)


def _filtered(qs, statuses, order_id):
    wanted = _statuses(statuses)
    if wanted:
        qs = qs.filter(status__in=wanted)
    if order_id:
        qs = qs.filter(order_id=str(order_id))
    return qs


def _by_id(qs, shipment_id) -> Shipment:
    shipment = qs.filter(pk=shipment_id).first() if str(shipment_id).isdigit() else None
    if shipment is None:
        raise DeliveryError(404, ERR_404_SHIPMENT_NOT_FOUND)
    return shipment


def get_owned(user_id: str, shipment_id) -> Shipment:
    return _by_id(for_user(user_id), shipment_id)


def get_any(shipment_id) -> Shipment:
    return _by_id(Shipment.objects.all(), shipment_id)


def render_tracking_url(shipment: Shipment) -> str:
    """The method's template (if the method still exists), else the carrier's."""
    if not shipment.tracking_number:
        return ""
    method = DeliveryMethod.objects.filter(code=shipment.method_code).first()
    template = method.tracking_url_template if method is not None else ""
    if template:
        try:
            return template.format(tracking_number=shipment.tracking_number, number=shipment.number)
        except (KeyError, IndexError, ValueError):
            logger.warning("delivery: tracking_url_template of %s cannot be formatted", shipment.method_code)
            return ""
    return carrier_by_slug(shipment.carrier).tracking_url(shipment) or ""


# ── creation ──────────────────────────────────────────────────────────────


def create_from_intent(intent: DeliveryIntent, order_id: str, lines: list[dict], *, emit,
                       now: dt.datetime | None = None) -> tuple[Shipment | None, bool]:
    """One shipment for the order from the checkout intent. Idempotent on ``order_id``.

    Runs inside the caller's ``mutate_and_emit`` block. A digital or
    unshippable intent creates nothing. Returns ``(shipment, created)``.
    """
    order_id = str(order_id)
    existing = Shipment.objects.filter(order_id=order_id).first()
    if existing is not None:
        return existing, False
    if intent.method_kind == MethodKind.DIGITAL or not intent.shippable:
        return None, False
    now = now or timezone.now()
    recipient = intent.recipient or {}
    fields = dict(
        order_id=order_id,
        user_id=intent.user_id,
        method_code=intent.method_code,
        method_name=intent.method_name,
        method_kind=intent.method_kind,
        carrier=intent.carrier,
        recipient_name=recipient.get("name", ""),
        recipient_phone=recipient.get("phone", ""),
        line1=recipient.get("line1", ""),
        line2=recipient.get("line2", ""),
        city=recipient.get("city", ""),
        region=recipient.get("region", ""),
        postal_code=recipient.get("postal_code", ""),
        country=recipient.get("country", ""),
        pickup_point=intent.pickup_point or {},
        amount=intent.amount,
        currency=intent.currency,
        weight_kg=intent.weight_kg,
        lines=[
            {"purchasable_type": line.get("purchasable_type"),
             "purchasable_key": line.get("purchasable_key"),
             "quantity": int(line.get("quantity") or 0)}
            for line in lines
        ],
    )
    shipment = None
    for _ in range(_NUMBER_ATTEMPTS):
        try:
            with transaction.atomic():
                shipment = Shipment.objects.create(number=_new_number(now), **fields)
            break
        except IntegrityError:
            existing = Shipment.objects.filter(order_id=order_id).first()
            if existing is not None:
                return existing, False
    if shipment is None:  # pragma: no cover - 32^6 numbers per day
        raise RuntimeError("delivery: could not allocate a shipment number")
    ShipmentEvent.objects.create(shipment=shipment, from_status="", to_status=shipment.status,
                                 actor=fsm.SYSTEM, occurred_at=now)
    registration = carrier_by_slug(shipment.carrier).register(shipment)
    if registration is not None and registration.tracking_number:
        shipment.tracking_number = registration.tracking_number[:64]
        shipment.tracking_url = (registration.tracking_url or render_tracking_url(shipment))[:500]
        shipment.save(update_fields=["tracking_number", "tracking_url", "updated_at"])
    emit(  # emit-check: ok — emit is always a caller's mutate_and_emit emitter
        events.EVENT_CREATED, events.created_payload(shipment), key=str(shipment.pk),
    )
    return shipment, True


def link_and_create(intent_id: int, order_id: str, lines: list[dict]) -> Shipment | None:
    """Commit an intent to an order and create its shipment, in one transaction."""
    with mutate_and_emit() as emit:
        intent = DeliveryIntent.objects.select_for_update().get(pk=intent_id)
        if intent.order_id and intent.order_id != str(order_id):
            logger.warning("delivery: intent %s already belongs to order %s, not %s",
                           intent.attempt_key, intent.order_id, order_id)
            return None
        if intent.status == IntentStatus.RELEASED and intent.release_reason == RELEASE_CANCELLED:
            logger.info("delivery: intent %s was cancelled; no shipment for order %s",
                        intent.attempt_key, order_id)
            return None
        if intent.status == IntentStatus.RELEASED:
            logger.warning("delivery: intent %s was released (%s) before its order %s committed; "
                           "the order is the fact, shipping it", intent.attempt_key,
                           intent.release_reason or "no reason", order_id)
        intent.order_id = str(order_id)
        intent.status = IntentStatus.COMMITTED
        intent.save(update_fields=["order_id", "status", "updated_at"])
        shipment, _ = create_from_intent(intent, order_id, lines, emit=emit)
        return shipment


# ── lifecycle ─────────────────────────────────────────────────────────────


def _invalid(shipment: Shipment, to_status: str) -> DeliveryError:
    return DeliveryError(409, ERR_409_SHIPMENT_TRANSITION_INVALID,
                         {"from": shipment.status, "to": to_status})


def transition(shipment_id, to_status: str, *, actor: str, note: str = "", location: str = "",
               occurred_at: dt.datetime | None = None, emit=None) -> Shipment:
    """Move a shipment along the FSM as *actor*; records the step and emits the fact."""
    if emit is None:
        with mutate_and_emit() as scoped:
            return transition(shipment_id, to_status, actor=actor, note=note, location=location,
                              occurred_at=occurred_at, emit=scoped)
    now = timezone.now()
    shipment = Shipment.objects.select_for_update().get(pk=shipment_id)
    try:
        fsm.check(shipment.status, to_status, actor)
    except fsm.TransitionInvalid:
        raise _invalid(shipment, to_status) from None
    from_status = shipment.status
    shipment.status = to_status
    fields = ["status", "updated_at"]
    if to_status == ShipmentStatus.SHIPPED and shipment.shipped_at is None:
        shipment.shipped_at = occurred_at or now
        fields.append("shipped_at")
    if to_status == ShipmentStatus.DELIVERED:
        shipment.delivered_at = occurred_at or now
        fields.append("delivered_at")
    shipment.save(update_fields=fields)
    ShipmentEvent.objects.create(
        shipment=shipment, from_status=from_status, to_status=to_status, actor=actor,
        note=(note or "")[:200], location=(location or "")[:120], occurred_at=occurred_at or now,
    )
    emit(  # emit-check: ok — emit is always a caller's mutate_and_emit emitter (see top)
        events.EVENT_STATUS_CHANGED,
        events.status_changed_payload(shipment, from_status, actor, note),
        key=str(shipment.pk),
    )
    events.notify_after_commit(events.NOTIFY_STATUS_CHANGED, shipment.user_id, shipment,
                               from_status=from_status)
    return shipment


def staff_transition(shipment_id, to_status: str, note: str = "", location: str = "") -> Shipment:
    shipment = get_any(shipment_id)
    if to_status not in fsm.STAFF_TARGETS:
        raise _invalid(shipment, to_status)
    return transition(shipment.pk, to_status, actor=fsm.STAFF, note=note, location=location)


def set_tracking(shipment_id, tracking_number: str, carrier: str | None = None) -> Shipment:
    """Staff record the carrier's tracking number (and optionally the carrier)."""
    from django.core.exceptions import ImproperlyConfigured

    from ..errors import ERR_400_DELIVERY_METHOD_UNKNOWN

    with transaction.atomic():
        shipment = Shipment.objects.select_for_update().filter(pk=get_any(shipment_id).pk).get()
        if carrier:
            try:
                get_carrier(carrier)
            except ImproperlyConfigured:
                raise DeliveryError(400, ERR_400_DELIVERY_METHOD_UNKNOWN, {"carrier": carrier},
                                    field="carrier") from None
            shipment.carrier = carrier
        shipment.tracking_number = tracking_number
        shipment.tracking_url = render_tracking_url(shipment)[:500]
        shipment.save(update_fields=["carrier", "tracking_number", "tracking_url", "updated_at"])
    return shipment


def cancel_for_order(order_id: str, *, reason: str) -> str:
    """The order went away: cancel its shipment if it has not left. Returns the outcome."""
    shipment = Shipment.objects.filter(order_id=str(order_id)).first()
    if shipment is None:
        return "none"
    if not fsm.allowed(shipment.status, ShipmentStatus.CANCELLED, fsm.SYSTEM):
        if shipment.status != ShipmentStatus.CANCELLED:
            logger.info("delivery: order %s cancelled but shipment %s is %s; left as is",
                        order_id, shipment.number, shipment.status)
        return "kept"
    try:
        transition(shipment.pk, ShipmentStatus.CANCELLED, actor=fsm.SYSTEM, note=reason)
    except DeliveryError:
        return "kept"  # moved by someone else since the read
    return "cancelled"


def apply_carrier_update(shipment: Shipment, update: CarrierUpdate) -> bool:
    """Apply one carrier report. A stale or illegal one is logged and skipped."""
    if update.status == shipment.status:
        return False
    if not fsm.allowed(shipment.status, update.status, fsm.CARRIER):
        logger.info("delivery: carrier %s reported %s for shipment %s in %s; ignored",
                    shipment.carrier, update.status, shipment.number, shipment.status)
        return False
    try:
        transition(shipment.pk, update.status, actor=fsm.CARRIER, note=update.note,
                   location=update.location, occurred_at=update.occurred_at)
    except DeliveryError:
        return False
    shipment.refresh_from_db()
    return True


def poll_carriers(now: dt.datetime | None = None) -> int:
    """One pass over active shipments of polling carriers. Returns updates applied."""
    now = now or timezone.now()
    applied = 0
    carriers: dict = {}
    for shipment in Shipment.objects.filter(status__in=ACTIVE_STATUSES).order_by("id")[:POLL_BATCH]:
        carrier = carriers.setdefault(shipment.carrier, carrier_by_slug(shipment.carrier))
        if not carrier.polls:
            continue
        try:
            updates = carrier.poll(shipment, now)
        except Exception:
            logger.warning("delivery: carrier %s poll failed for shipment %s",
                           shipment.carrier, shipment.number, exc_info=True)
            continue
        for update in updates:
            if apply_carrier_update(shipment, update):
                applied += 1
    return applied


def merge_users(from_user_id: str, into_user_id: str) -> dict:
    shipments = Shipment.objects.filter(user_id=from_user_id).update(user_id=into_user_id)
    intents = DeliveryIntent.objects.filter(user_id=from_user_id).update(user_id=into_user_id)
    return {"shipments": shipments, "intents": intents}


__all__ = [
    "apply_carrier_update", "cancel_for_order", "create_from_intent", "for_staff", "for_user",
    "get_any", "get_owned", "link_and_create", "merge_users", "poll_carriers",
    "render_tracking_url", "set_tracking", "staff_transition", "transition",
]
