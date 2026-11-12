"""Presenters for stapel-delivery — the DTO-building layer (§55).

Views never instantiate a ``dto.py`` dataclass (SWAP002) nor import a
concrete presenter (SWAP001); they resolve one through ``get_presenter`` so
a host can swap the presentation via ``STAPEL_SWAP`` without forking.
"""
from __future__ import annotations

from stapel_core.django.swappable import declare_swap, get_presenter

from .dto import (
    AddressDTO,
    AddressListDTO,
    DeliveryMethodDTO,
    DeliveryMethodListDTO,
    DeliveryOptionDTO,
    DeliveryOptionsDTO,
    HoursWindowDTO,
    PickupPointDTO,
    PickupPointSnapshotDTO,
    RecipientDTO,
    ShipmentDTO,
    ShipmentEventDTO,
)

ADDRESS_PRESENTER_KEY = "STAPEL_DELIVERY_ADDRESS_PRESENTER"
METHOD_PRESENTER_KEY = "STAPEL_DELIVERY_METHOD_PRESENTER"
OPTIONS_PRESENTER_KEY = "STAPEL_DELIVERY_OPTIONS_PRESENTER"
PICKUP_POINT_PRESENTER_KEY = "STAPEL_DELIVERY_PICKUP_POINT_PRESENTER"
SHIPMENT_PRESENTER_KEY = "STAPEL_DELIVERY_SHIPMENT_PRESENTER"

DEFAULT_ADDRESS_PRESENTER = "stapel_delivery.presenters.AddressPresenter"
DEFAULT_METHOD_PRESENTER = "stapel_delivery.presenters.MethodPresenter"
DEFAULT_OPTIONS_PRESENTER = "stapel_delivery.presenters.OptionsPresenter"
DEFAULT_PICKUP_POINT_PRESENTER = "stapel_delivery.presenters.PickupPointPresenter"
DEFAULT_SHIPMENT_PRESENTER = "stapel_delivery.presenters.ShipmentPresenter"

declare_swap(ADDRESS_PRESENTER_KEY, DEFAULT_ADDRESS_PRESENTER)
declare_swap(METHOD_PRESENTER_KEY, DEFAULT_METHOD_PRESENTER)
declare_swap(OPTIONS_PRESENTER_KEY, DEFAULT_OPTIONS_PRESENTER)
declare_swap(PICKUP_POINT_PRESENTER_KEY, DEFAULT_PICKUP_POINT_PRESENTER)
declare_swap(SHIPMENT_PRESENTER_KEY, DEFAULT_SHIPMENT_PRESENTER)


def _or_none(value):
    return value or None


class AddressPresenter:
    def present(self, address) -> AddressDTO:
        return AddressDTO(
            id=address.pk, label=address.label, name=address.name, phone=address.phone,
            line1=address.line1, line2=address.line2, city=address.city, region=address.region,
            postal_code=address.postal_code, country=address.country,
            latitude=address.latitude, longitude=address.longitude,
            is_default=address.is_default, created_at=address.created_at,
            updated_at=address.updated_at,
        )

    def present_list(self, addresses, cap: int) -> AddressListDTO:
        items = [self.present(a) for a in addresses]
        return AddressListDTO(items=items, count=len(items), max=cap)


class MethodPresenter:
    def present(self, method) -> DeliveryMethodDTO:
        return DeliveryMethodDTO(
            code=method.code, name=method.name, description=method.description, kind=method.kind,
            eta_min_days=method.eta_min_days, eta_max_days=method.eta_max_days,
        )

    def present_list(self, methods) -> DeliveryMethodListDTO:
        return DeliveryMethodListDTO(items=[self.present(m) for m in methods])


class OptionsPresenter:
    """The option dicts of ``services.checkout.options`` -> DeliveryOptionsDTO."""

    def present(self, options: list[dict]) -> DeliveryOptionsDTO:
        from decimal import Decimal

        return DeliveryOptionsDTO(options=[
            DeliveryOptionDTO(
                code=o["code"], name=o["name"], description=o["description"], kind=o["kind"],
                eta_min_days=o["eta_min_days"], eta_max_days=o["eta_max_days"],
                available=o["available"],
                price=None if o["price"] is None else Decimal(o["price"]),
                price_is_minimum=o["price_is_minimum"], currency=o["currency"],
                free_reason=o["free_reason"], reason=o["reason"],
            )
            for o in options
        ])


class PickupPointPresenter:
    def present(self, point) -> PickupPointDTO:
        return PickupPointDTO(
            code=point.code, method=point.method.code, name=point.name,
            line1=point.line1, line2=point.line2, city=point.city, region=point.region,
            postal_code=point.postal_code, country=point.country,
            latitude=point.latitude, longitude=point.longitude,
            hours=[HoursWindowDTO(weekday=int(w["weekday"]), opens=w["opens"], closes=w["closes"])
                   for w in (point.hours or [])],
            hours_note=point.hours_note,
        )


class ShipmentPresenter:
    """Shipment -> ShipmentDTO, with its timeline."""

    def present(self, shipment) -> ShipmentDTO:
        recipient = None
        if shipment.method_kind == "courier":
            recipient = RecipientDTO(
                name=shipment.recipient_name, phone=shipment.recipient_phone,
                line1=shipment.line1, line2=shipment.line2, city=shipment.city,
                region=shipment.region, postal_code=shipment.postal_code, country=shipment.country,
            )
        point = None
        if shipment.pickup_point:
            p = shipment.pickup_point
            point = PickupPointSnapshotDTO(
                code=p.get("code", ""), name=p.get("name", ""), line1=p.get("line1", ""),
                line2=p.get("line2", ""), city=p.get("city", ""), region=p.get("region", ""),
                postal_code=p.get("postal_code", ""), country=p.get("country", ""),
            )
        return ShipmentDTO(
            id=shipment.pk, number=shipment.number, order_id=shipment.order_id,
            status=shipment.status, method_code=shipment.method_code,
            method_name=shipment.method_name, method_kind=shipment.method_kind,
            carrier=shipment.carrier, tracking_number=_or_none(shipment.tracking_number),
            tracking_url=_or_none(shipment.tracking_url), recipient=recipient, pickup_point=point,
            amount=shipment.amount, currency=shipment.currency, weight_kg=shipment.weight_kg,
            shipped_at=shipment.shipped_at, delivered_at=shipment.delivered_at,
            created_at=shipment.created_at, updated_at=shipment.updated_at,
            events=[
                ShipmentEventDTO(
                    from_status=_or_none(e.from_status), to_status=e.to_status, actor=e.actor,
                    note=e.note, location=e.location, occurred_at=e.occurred_at,
                )
                for e in shipment.events.all()
            ],
        )


def get_address_presenter() -> type:
    return get_presenter(ADDRESS_PRESENTER_KEY, default=DEFAULT_ADDRESS_PRESENTER)


def get_method_presenter() -> type:
    return get_presenter(METHOD_PRESENTER_KEY, default=DEFAULT_METHOD_PRESENTER)


def get_options_presenter() -> type:
    return get_presenter(OPTIONS_PRESENTER_KEY, default=DEFAULT_OPTIONS_PRESENTER)


def get_pickup_point_presenter() -> type:
    return get_presenter(PICKUP_POINT_PRESENTER_KEY, default=DEFAULT_PICKUP_POINT_PRESENTER)


def get_shipment_presenter() -> type:
    return get_presenter(SHIPMENT_PRESENTER_KEY, default=DEFAULT_SHIPMENT_PRESENTER)
