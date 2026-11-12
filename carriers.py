"""Carrier strategies — who moves a parcel and reports where it is.

A method names a carrier slug (blank = ``DEFAULT_CARRIER``). The registry is
``CARRIERS`` (dotted paths, merged over the built-ins, ``None`` removes one)
plus :func:`register_carrier` at runtime.

Built-ins:

- ``manual`` (default) — staff set the tracking number and move the status;
  nothing is polled.
- ``mock`` — a demo carrier: assigns ``MOCK-<number>`` and advances one
  status per ``MOCK_STEP_MINUTES`` (pending → packed → shipped → delivered)
  when the beat polls it. Allowed in the ``prototype`` posture stage only
  (check E002/W002); never a ``USE_MOCK_*`` switch.

A real carrier subclasses :class:`Carrier`. ``register`` runs once in the
shipment-creation transaction (book the parcel, return the tracking
number); ``poll`` runs from the beat for active shipments and returns
updates; a push-style carrier's webhook view (host code) calls
``services.shipments.apply_carrier_update`` instead. No real carrier ships
with this package: credentials and hosts are per deployment.
"""
from __future__ import annotations

import abc
import datetime as dt
from dataclasses import dataclass, field
from typing import Callable

from django.core.exceptions import ImproperlyConfigured


@dataclass
class Registration:
    """What a carrier assigned when the shipment was booked with it."""

    tracking_number: str = ""
    tracking_url: str = ""


@dataclass
class CarrierUpdate:
    """One status report from a carrier."""

    status: str
    occurred_at: dt.datetime | None = None
    note: str = ""
    location: str = ""
    meta: dict = field(default_factory=dict)


class Carrier(abc.ABC):
    """The carrier seam. Subclass it and register the class by slug."""

    #: Registry slug; set by the registry when blank.
    slug = ""

    def register(self, shipment) -> Registration | None:
        """Book the parcel. Runs inside the creation transaction; ``None`` = nothing assigned."""
        return None

    def poll(self, shipment, now: dt.datetime) -> list[CarrierUpdate]:
        """Updates since the shipment's current status (beat, active shipments only)."""
        return []

    def tracking_url(self, shipment) -> str:
        """A tracking link for the shipment's number; ``""`` = none."""
        return ""

    @property
    def polls(self) -> bool:
        """Whether the beat should call :meth:`poll` at all."""
        return type(self).poll is not Carrier.poll


class ManualCarrier(Carrier):
    slug = "manual"


class MockCarrier(Carrier):
    """Auto-advancing demo carrier; every update is a fact like a real one."""

    slug = "mock"

    def register(self, shipment) -> Registration:
        return Registration(tracking_number=f"MOCK-{shipment.number}")

    def poll(self, shipment, now: dt.datetime) -> list[CarrierUpdate]:
        from .conf import delivery_settings
        from .fsm import next_forward

        target = next_forward(shipment.status)
        if target is None:
            return []
        step = dt.timedelta(minutes=max(0, int(delivery_settings.MOCK_STEP_MINUTES)))
        last = shipment.events.order_by("-occurred_at", "-id").first()
        since = last.occurred_at if last is not None else shipment.created_at
        if now - since < step:
            return []
        return [CarrierUpdate(status=target, occurred_at=now, note="mock carrier")]


_BUILTINS: dict[str, Callable[[], Carrier] | str] = {
    "manual": ManualCarrier,
    "mock": MockCarrier,
}
_registered: dict[str, Callable[[], Carrier] | str] = {}


def register_carrier(slug: str, factory: Callable[[], Carrier] | str | None) -> None:
    """Register (or with ``None`` remove) a carrier under a slug at runtime."""
    _registered[slug] = factory


def reset_carriers() -> None:
    """Tests only."""
    _registered.clear()


def _table() -> dict:
    from .conf import delivery_settings

    configured = delivery_settings.CARRIERS or {}
    if not isinstance(configured, dict):
        raise ImproperlyConfigured('STAPEL_DELIVERY["CARRIERS"] must be a dict {slug: dotted path | None}')
    merged: dict = dict(_BUILTINS)
    for source in (configured, _registered):
        for slug, entry in source.items():
            if entry is None:
                merged.pop(slug, None)
            else:
                merged[slug] = entry
    return merged


def carrier_names() -> tuple[str, ...]:
    """The slugs a method and ``DEFAULT_CARRIER`` accept (also the env vocabulary)."""
    try:
        return tuple(sorted(_table()))
    except ImproperlyConfigured:
        return tuple(sorted(_BUILTINS))


def _build(slug: str, factory) -> Carrier:
    if isinstance(factory, str):
        from django.utils.module_loading import import_string

        try:
            factory = import_string(factory)
        except ImportError as exc:
            raise ImproperlyConfigured(f"carrier {slug!r}: cannot import {factory!r} ({exc})") from None
    carrier = factory() if callable(factory) else factory
    if not isinstance(carrier, Carrier):
        raise ImproperlyConfigured(f"carrier {slug!r} does not produce a Carrier")
    if not carrier.slug:
        carrier.slug = slug
    return carrier


def get_carrier(slug: str) -> Carrier:
    """The carrier registered under ``slug``; ImproperlyConfigured when unknown."""
    table = _table()
    if slug not in table:
        raise ImproperlyConfigured(
            f"carrier {slug!r} is not registered. Known: {', '.join(sorted(table))}."
        )
    return _build(slug, table[slug])


def resolve_carrier(value) -> Carrier:
    """Resolver for ``delivery_settings.DEFAULT_CARRIER``: slug or dotted path."""
    if isinstance(value, Carrier):
        return value
    name = str(value or "manual")
    if name in _table() or "." not in name:
        return get_carrier(name)
    return _build(name.rsplit(".", 1)[-1].lower(), name)


def default_carrier() -> Carrier:
    from .conf import delivery_settings

    return delivery_settings.DEFAULT_CARRIER


def carrier_for_method(method) -> Carrier:
    """The method's own carrier, or the default."""
    return get_carrier(method.carrier) if method.carrier else default_carrier()


def carrier_by_slug(slug: str) -> Carrier:
    """A shipment's carrier; an unregistered slug falls back to ``manual``."""
    try:
        return get_carrier(slug)
    except ImproperlyConfigured:
        return ManualCarrier()


def uses_mock(*, methods: bool = False) -> list[str]:
    """Where the mock carrier is in use: ``DEFAULT_CARRIER`` and (``methods=True``,
    a database read) the codes of methods that name it."""
    from django.db import DatabaseError

    from .conf import delivery_settings
    from .models import DeliveryMethod

    where = []
    try:
        if getattr(delivery_settings.DEFAULT_CARRIER, "slug", "") == "mock":
            where.append("DEFAULT_CARRIER")
    except ImproperlyConfigured:
        pass
    if not methods:
        return where
    try:
        where.extend(
            f"method {code}" for code in DeliveryMethod.objects.filter(carrier="mock")
            .values_list("code", flat=True)
        )
    except DatabaseError:  # the table may not exist yet (check before migrate)
        pass
    return where
