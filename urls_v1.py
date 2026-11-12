"""v1 URL set for stapel-delivery (plain paths, no router)."""
from typing import NamedTuple

from django.urls import path

from .views import (
    AddressDefaultView,
    AddressDetailView,
    AddressListView,
    MethodListView,
    OptionsView,
    PickupPointListView,
    ShipmentDetailView,
    ShipmentListView,
    StaffShipmentListView,
    StaffShipmentTrackingView,
    StaffShipmentTransitionView,
)

urlpatterns = [
    path("methods/", MethodListView.as_view(), name="delivery-methods"),
    path("options/", OptionsView.as_view(), name="delivery-options"),
    path("pickup-points/", PickupPointListView.as_view(), name="delivery-pickup-points"),
    path("addresses/", AddressListView.as_view(), name="delivery-addresses"),
    path("addresses/<int:address_id>/", AddressDetailView.as_view(), name="delivery-address"),
    path("addresses/<int:address_id>/default/", AddressDefaultView.as_view(),
         name="delivery-address-default"),
    path("shipments/", ShipmentListView.as_view(), name="delivery-shipments"),
    path("shipments/<int:shipment_id>/", ShipmentDetailView.as_view(), name="delivery-shipment"),
    path("staff/shipments/", StaffShipmentListView.as_view(), name="delivery-staff-shipments"),
    path("staff/shipments/<int:shipment_id>/tracking/", StaffShipmentTrackingView.as_view(),
         name="delivery-staff-shipment-tracking"),
    path("staff/shipments/<int:shipment_id>/transition/", StaffShipmentTransitionView.as_view(),
         name="delivery-staff-shipment-transition"),
]


class GateEntry(NamedTuple):
    """One gated URL block: which flags gate which url patterns."""

    name: str
    flags: tuple
    patterns: tuple


#: No axis unmounts an endpoint (REQUIRE_METHOD and DEFAULT_CARRIER are
#: behavioural), so the surface is one always-on block.
GATE_REGISTRY: dict = {
    "delivery.api": GateEntry("delivery.api", (), tuple(urlpatterns)),
}
