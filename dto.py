"""Dataclass DTOs — the API models of stapel-delivery (never ORM instances).

Built only by the presenters (``presenters.py``); views never instantiate
them. Money is ``Decimal`` here and a string on the wire; instants are UTC.
"""
from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Optional


@dataclass
class AddressDTO:
    """One saved address of the caller's book."""

    id: int
    label: str
    name: str
    phone: str
    line1: str
    line2: str
    city: str
    region: str
    postal_code: str
    country: str
    latitude: Optional[Decimal]
    longitude: Optional[Decimal]
    is_default: bool
    created_at: datetime.datetime
    updated_at: datetime.datetime


@dataclass
class AddressListDTO:
    """The caller's whole address book (bounded by MAX_ADDRESSES)."""

    items: list[AddressDTO] = field(default_factory=list)
    count: int = 0
    max: int = 0


@dataclass
class DeliveryMethodDTO:
    """An enabled delivery method as the buyer sees it."""

    code: str
    name: str
    description: str
    kind: str
    eta_min_days: Optional[int]
    eta_max_days: Optional[int]


@dataclass
class DeliveryMethodListDTO:
    """Enabled delivery methods in display order."""

    items: list[DeliveryMethodDTO] = field(default_factory=list)


@dataclass
class DeliveryOptionDTO:
    """One method priced for a cart and a destination, or why it is not offered."""

    code: str
    name: str
    description: str
    kind: str
    eta_min_days: Optional[int]
    eta_max_days: Optional[int]
    available: bool
    price: Optional[Decimal]
    price_is_minimum: bool
    currency: str
    free_reason: Optional[str]
    reason: Optional[str]


@dataclass
class DeliveryOptionsDTO:
    """Every enabled method priced for one cart and destination."""

    options: list[DeliveryOptionDTO] = field(default_factory=list)


@dataclass
class HoursWindowDTO:
    """A weekly opening window of a pickup point (local wall clock)."""

    weekday: int
    opens: str
    closes: str


@dataclass
class PickupPointDTO:
    """An enabled pickup point with its address, coordinates and hours."""

    code: str
    method: str
    name: str
    line1: str
    line2: str
    city: str
    region: str
    postal_code: str
    country: str
    latitude: Optional[Decimal]
    longitude: Optional[Decimal]
    hours: list[HoursWindowDTO]
    hours_note: str


@dataclass
class RecipientDTO:
    """The recipient address snapshot a courier shipment carries."""

    name: str
    phone: str
    line1: str
    line2: str
    city: str
    region: str
    postal_code: str
    country: str


@dataclass
class PickupPointSnapshotDTO:
    """The pickup point snapshot a pickup shipment carries."""

    code: str
    name: str
    line1: str
    line2: str
    city: str
    region: str
    postal_code: str
    country: str


@dataclass
class ShipmentEventDTO:
    """One step of a shipment's timeline."""

    from_status: Optional[str]
    to_status: str
    actor: str
    note: str
    location: str
    occurred_at: datetime.datetime


@dataclass
class ShipmentDTO:
    """A shipment with its tracking and timeline."""

    id: int
    number: str
    order_id: str
    status: str
    method_code: str
    method_name: str
    method_kind: str
    carrier: str
    tracking_number: Optional[str]
    tracking_url: Optional[str]
    recipient: Optional[RecipientDTO]
    pickup_point: Optional[PickupPointSnapshotDTO]
    amount: Decimal
    currency: str
    weight_kg: Optional[Decimal]
    shipped_at: Optional[datetime.datetime]
    delivered_at: Optional[datetime.datetime]
    created_at: datetime.datetime
    updated_at: datetime.datetime
    events: list[ShipmentEventDTO] = field(default_factory=list)
