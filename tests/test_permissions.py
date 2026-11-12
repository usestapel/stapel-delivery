"""Every view's guest stance and permission list, pinned (the SUR002 decision lives here).

The address book needs a real account but no workspace mandate: it belongs
to a buyer, not to an organization. "My shipments" admits a guest session
(a guest checkout tracks its parcel). Staff views are staff-only.
"""
from rest_framework import permissions
from stapel_core.django.api.permissions import (
    ANONYMOUS_ALLOWED,
    ANONYMOUS_DENIED,
    IsNotAnonymousUser,
    IsStaffUser,
)

from stapel_delivery import views

EXPECTED = {
    "MethodListView": ([permissions.AllowAny], ANONYMOUS_ALLOWED),
    "OptionsView": ([permissions.AllowAny], ANONYMOUS_ALLOWED),
    "PickupPointListView": ([permissions.AllowAny], ANONYMOUS_ALLOWED),
    "AddressListView": ([IsNotAnonymousUser], ANONYMOUS_DENIED),
    "AddressDetailView": ([IsNotAnonymousUser], ANONYMOUS_DENIED),
    "AddressDefaultView": ([IsNotAnonymousUser], ANONYMOUS_DENIED),
    "ShipmentListView": ([permissions.IsAuthenticated], ANONYMOUS_ALLOWED),
    "ShipmentDetailView": ([permissions.IsAuthenticated], ANONYMOUS_ALLOWED),
    "StaffShipmentListView": ([IsStaffUser], ANONYMOUS_DENIED),
    "StaffShipmentTrackingView": ([IsStaffUser], ANONYMOUS_DENIED),
    "StaffShipmentTransitionView": ([IsStaffUser], ANONYMOUS_DENIED),
}


def test_every_view_is_pinned():
    declared = {name for name, obj in vars(views).items()
                if isinstance(obj, type) and name.endswith("View") and obj.__module__ == views.__name__
                and not name.startswith("_")}
    assert declared == set(EXPECTED)


def test_permissions_and_guest_stance():
    for name, (classes, stance) in EXPECTED.items():
        view = getattr(views, name)
        assert list(view.permission_classes) == classes, name
        assert view.stapel_anonymous_access == stance, name
