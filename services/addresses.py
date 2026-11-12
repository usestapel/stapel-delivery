"""The per-user address book and recipient snapshots.

Rows are scoped by ``user_id``: a foreign id and an absent id answer the
same 404. The default flag and the ``MAX_ADDRESSES`` cap are decided under
``select_for_update()`` on the owner's rows (plus a conditional unique
constraint), so two concurrent saves cannot leave two defaults or one
address over the cap.

Whatever leaves the book is a :class:`Recipient` snapshot — a copy, never a
reference.
"""
from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation

from django.db import transaction

from ..errors import (
    ERR_400_DELIVERY_ADDRESS_INVALID,
    ERR_404_ADDRESS_NOT_FOUND,
    ERR_409_TOO_MANY_ADDRESSES,
)
from ..models import Address
from . import DeliveryError
from .rates import Destination

logger = logging.getLogger(__name__)

SNAPSHOT_FIELDS = ("name", "phone", "line1", "line2", "city", "region", "postal_code", "country")


@dataclass
class Recipient:
    """A validated recipient address snapshot."""

    name: str
    phone: str
    line1: str
    city: str
    country: str
    line2: str = ""
    region: str = ""
    postal_code: str = ""
    latitude: str | None = None
    longitude: str | None = None

    def destination(self) -> Destination:
        return Destination(country=self.country, region=self.region, postal_code=self.postal_code)

    def as_dict(self) -> dict:
        return asdict(self)


def _coord(value) -> str | None:
    if value is None:
        return None
    return str(value)


def from_address(address: Address) -> Recipient:
    return Recipient(
        name=address.name, phone=address.phone, line1=address.line1, line2=address.line2,
        city=address.city, region=address.region, postal_code=address.postal_code,
        country=address.country, latitude=_coord(address.latitude),
        longitude=_coord(address.longitude),
    )


def validate_snapshot(raw, *, field_prefix: str = "delivery.address") -> Recipient:
    """An untrusted address dict (checkout context) as a Recipient, or a 400.

    The shape rules are the HTTP ones (``AddressSnapshotSerializer``), so a
    checkout and the address book accept exactly the same addresses.
    """
    from ..serializers import AddressSnapshotSerializer

    if not isinstance(raw, dict):
        raise DeliveryError(400, ERR_400_DELIVERY_ADDRESS_INVALID, field=field_prefix)
    serializer = AddressSnapshotSerializer(data=raw)
    if not serializer.is_valid():
        first = sorted(serializer.errors)[0]
        if first == "non_field_errors":  # the coordinate pair rule
            first = "latitude"
        raise DeliveryError(400, ERR_400_DELIVERY_ADDRESS_INVALID,
                            {"field": first}, field=f"{field_prefix}.{first}")
    data = serializer.validated_data
    return Recipient(
        name=data["name"], phone=data["phone"], line1=data["line1"], line2=data.get("line2", ""),
        city=data["city"], region=data.get("region", ""), postal_code=data.get("postal_code", ""),
        country=data["country"],
        latitude=_coord(data.get("latitude")), longitude=_coord(data.get("longitude")),
    )


def for_user(user_id: str):
    return Address.objects.filter(user_id=str(user_id))


def get_owned(user_id: str, address_id) -> Address:
    address = for_user(user_id).filter(pk=address_id).first() if str(address_id).isdigit() else None
    if address is None:
        raise DeliveryError(404, ERR_404_ADDRESS_NOT_FOUND, field="delivery.address_id")
    return address


def _lock_book(user_id: str) -> list[Address]:
    return list(Address.objects.select_for_update().filter(user_id=str(user_id)).order_by("id"))


def _clear_default(user_id: str, except_id=None) -> None:
    qs = Address.objects.filter(user_id=str(user_id), is_default=True)
    if except_id is not None:
        qs = qs.exclude(pk=except_id)
    qs.update(is_default=False)


def create(user_id: str, data: dict) -> Address:
    from ..conf import delivery_settings

    user_id = str(user_id)
    cap = int(delivery_settings.MAX_ADDRESSES)
    with transaction.atomic():
        book = _lock_book(user_id)
        if len(book) >= cap:
            raise DeliveryError(409, ERR_409_TOO_MANY_ADDRESSES, {"max": cap})
        make_default = bool(data.get("is_default")) or not book
        if make_default:
            _clear_default(user_id)
        address = Address.objects.create(
            user_id=user_id, is_default=make_default,
            **{k: v for k, v in data.items() if k != "is_default"},
        )
    _geocode_after_commit(address.pk)
    return address


def update(user_id: str, address_id, data: dict) -> Address:
    with transaction.atomic():
        _lock_book(user_id)
        address = get_owned(user_id, address_id)
        make_default = data.pop("is_default", None)
        moved = any(k in data for k in ("line1", "city", "postal_code", "country", "region"))
        for key, value in data.items():
            setattr(address, key, value)
        if moved and "latitude" not in data:
            address.latitude = address.longitude = None
        if make_default:
            _clear_default(user_id, except_id=address.pk)
            address.is_default = True
        address.save()
    if moved:
        _geocode_after_commit(address.pk)
    return address


def delete(user_id: str, address_id) -> None:
    with transaction.atomic():
        _lock_book(user_id)
        address = get_owned(user_id, address_id)
        was_default = address.is_default
        address.delete()
        if was_default:
            newest = for_user(user_id).order_by("-id").first()
            if newest is not None:
                newest.is_default = True
                newest.save(update_fields=["is_default", "updated_at"])


def make_default(user_id: str, address_id) -> Address:
    with transaction.atomic():
        _lock_book(user_id)
        address = get_owned(user_id, address_id)
        _clear_default(user_id, except_id=address.pk)
        if not address.is_default:
            address.is_default = True
            address.save(update_fields=["is_default", "updated_at"])
    return address


def merge_users(from_user_id: str, into_user_id: str) -> int:
    """The guest's book follows it; the survivor's default wins. Idempotent."""
    with transaction.atomic():
        _lock_book(into_user_id)
        _lock_book(from_user_id)
        if Address.objects.filter(user_id=into_user_id, is_default=True).exists():
            Address.objects.filter(user_id=from_user_id).update(is_default=False)
        return Address.objects.filter(user_id=from_user_id).update(user_id=into_user_id)


# ── geocoding (optional neighbour, by Function name only) ─────────────────


def _geocode_after_commit(address_id: int) -> None:
    from ..conf import delivery_settings

    if not delivery_settings.GEOCODE_FUNCTION:
        return
    transaction.on_commit(lambda: geocode(address_id))


def geocode(address_id: int) -> bool:
    """Fill missing coordinates through ``GEOCODE_FUNCTION``. Best-effort."""
    from stapel_core.comm import CommError, call, function_unreachable_reason

    from ..conf import delivery_settings

    name = str(delivery_settings.GEOCODE_FUNCTION or "")
    address = Address.objects.filter(pk=address_id, latitude__isnull=True).first()
    if not name or address is None or function_unreachable_reason(name):
        return False
    query = ", ".join(p for p in (address.line1, address.city, address.postal_code, address.country) if p)
    try:
        reply = call(name, {"q": query, "limit": 1})
        lon, lat = reply["features"][0]["geometry"]["coordinates"][:2]
        lat, lon = Decimal(str(lat)).quantize(Decimal("0.000001")), Decimal(str(lon)).quantize(Decimal("0.000001"))
    except (CommError, KeyError, IndexError, TypeError, ValueError, InvalidOperation):
        logger.info("delivery: geocoding address %s gave no coordinates", address_id)
        return False
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return False
    return bool(Address.objects.filter(pk=address_id, latitude__isnull=True)
                .update(latitude=lat, longitude=lon))


__all__ = [
    "Recipient", "create", "delete", "for_user", "from_address", "geocode", "get_owned",
    "make_default", "merge_users", "update", "validate_snapshot",
]
