"""GDPR for stapel-delivery — the ledger rule: the person goes, the economics stay.

Rows are keyed by the owning account id: ``actor_id`` of the orders
payloads (a guest's own id too), ``user_id`` for older payloads — so a
guest's intents and shipments are found by the guest's id.

Erasure of an ``account``:

- the address book and the checkout intents are deleted (they carry no
  economics);
- shipments keep method, status, money, lines, timeline, city and country,
  while ``user_id`` becomes the fleet pseudonym
  (``stapel_core.gdpr.pseudonymize``) and the recipient name, phone,
  street lines, region and postcode are blanked.

One operation, :func:`erase_subject`, reached by the in-process provider and
by ``register_gdpr_owner``'s ``gdpr.erasure.requested`` / ``user.deleted``
subscribers alike.
"""
from __future__ import annotations

from stapel_core.gdpr import GDPRProvider

#: Marker written over erased snapshot text.
ERASED = "erased"


def _address_row(a) -> dict:
    return {
        "label": a.label, "name": a.name, "phone": a.phone, "line1": a.line1, "line2": a.line2,
        "city": a.city, "region": a.region, "postal_code": a.postal_code, "country": a.country,
        "latitude": None if a.latitude is None else str(a.latitude),
        "longitude": None if a.longitude is None else str(a.longitude),
        "is_default": a.is_default, "created_at": a.created_at.isoformat(),
    }


def _shipment_row(s) -> dict:
    return {
        "number": s.number, "order_id": s.order_id, "status": s.status,
        "method": s.method_name, "carrier": s.carrier, "tracking_number": s.tracking_number,
        "recipient": {
            "name": s.recipient_name, "phone": s.recipient_phone, "line1": s.line1,
            "line2": s.line2, "city": s.city, "region": s.region,
            "postal_code": s.postal_code, "country": s.country,
        },
        "pickup_point": s.pickup_point, "amount": str(s.amount), "currency": s.currency,
        "created_at": s.created_at.isoformat(),
    }


def _intent_row(i) -> dict:
    return {
        "status": i.status, "order_id": i.order_id, "method": i.method_name,
        "recipient": i.recipient, "pickup_point": i.pickup_point,
        "amount": str(i.amount), "currency": i.currency, "created_at": i.created_at.isoformat(),
    }


class DeliveryGDPRProvider(GDPRProvider):
    section = "delivery"

    def export(self, user_id) -> dict:
        from .models import Address, DeliveryIntent, Shipment

        user_id = str(user_id)
        return {
            "addresses": [_address_row(a) for a in Address.objects.filter(user_id=user_id).order_by("id")],
            "shipments": [_shipment_row(s) for s in Shipment.objects.filter(user_id=user_id).order_by("id")],
            "checkout_intents": [_intent_row(i) for i in
                                 DeliveryIntent.objects.filter(user_id=user_id).order_by("id")],
        }

    def delete(self, user_id) -> None:
        erase_subject("account", user_id)

    #: After erasure the rows hold amounts and a pseudonym: that IS the
    #: anonymisation, so one operation answers both names.
    anonymize = delete


OWNER = DeliveryGDPRProvider.section
SUBJECT_TYPES = ("account",)


def erase_subject(subject_type, subject_key, workspace_id=None):
    """Erase one account's personal data. Idempotent; counts what it touched."""
    from django.db import transaction
    from stapel_core.gdpr.owners import pseudonymize

    from .models import Address, DeliveryIntent, Shipment

    if subject_type != "account" or not subject_key:
        return None
    user_id = str(subject_key)
    with transaction.atomic():
        addresses, _ = Address.objects.filter(user_id=user_id).delete()
        intents, _ = DeliveryIntent.objects.filter(user_id=user_id).delete()
        shipments = Shipment.objects.filter(user_id=user_id).update(
            user_id=pseudonymize(user_id),
            recipient_name=ERASED,
            recipient_phone=ERASED,
            line1=ERASED,
            line2="",
            region="",
            postal_code="",
        )
    return {"addresses": addresses, "intents": intents, "shipments": shipments}
