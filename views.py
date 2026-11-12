"""DRF views for stapel-delivery — thin over ``services``.

Every view declares its guest stance. The catalog reads (methods, options,
pickup points) are public. The address book needs a real account (a guest
types its address inline at checkout; orders sends ``user_id: null`` for a
guest, so a guest book could never be used). "My shipments" admits a guest
session (a guest who checked out tracks its parcel). Both are scoped to
``request.user``: a foreign id is a 404 like an absent one, with no staff
bypass. Staff views require ``is_staff``.
"""
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import permissions
from stapel_core.django.api.errors import StapelErrorResponse, StapelResponse
from stapel_core.django.api.permissions import (
    ANONYMOUS_ALLOWED,
    ANONYMOUS_DENIED,
    IsNotAnonymousUser,
    IsStaffUser,
)
from stapel_core.django.api.views import StapelAPIView
from stapel_core.flows import flow_step

from .flows import ADDRESSES, CHOOSE, FULFIL, TRACK
from .models import DeliveryMethod, PickupPoint, ShipmentStatus
from .pagination import PickupPointAnchorPagination, ShipmentAnchorPagination
from .presenters import (
    get_address_presenter,
    get_method_presenter,
    get_options_presenter,
    get_pickup_point_presenter,
    get_shipment_presenter,
)
from .serializers import (
    AddressListSerializer,
    AddressRequestSerializer,
    AddressResponseSerializer,
    DeliveryMethodListSerializer,
    DeliveryOptionsRequestSerializer,
    DeliveryOptionsResponseSerializer,
    PickupPointPageSerializer,
    PickupPointResponseSerializer,
    ShipmentPageSerializer,
    ShipmentResponseSerializer,
    ShipmentTrackingRequestSerializer,
    ShipmentTransitionRequestSerializer,
)
from .services import DeliveryError
from .services import addresses as address_service
from .services import checkout as checkout_service
from .services import shipments as shipment_service

TAGS = ["Delivery"]


class _DeliveryView(StapelAPIView):
    """Renders a service refusal as the fleet error envelope."""

    def handle_exception(self, exc):
        if isinstance(exc, DeliveryError):
            return StapelErrorResponse(exc.status, exc.key, exc.params)
        return super().handle_exception(exc)

    def _user_id(self, request) -> str:
        return str(request.user.pk)

    def _shipment(self, shipment):
        return self.serialized_response(get_shipment_presenter()().present(shipment))

    def _page(self, request, qs, paginator_class, present, serializer_class):
        paginator = paginator_class()
        page = paginator.paginate_queryset(qs, request, view=self)
        data = serializer_class([present(item) for item in page], many=True).data
        return paginator.get_paginated_response(data)


def _anchor_parameters(paginator):
    return [
        OpenApiParameter("anchor", str, OpenApiParameter.QUERY, required=False,
                         description="Opaque anchor from next_anchor/prev_anchor (exclusive)."),
        OpenApiParameter("limit", int, OpenApiParameter.QUERY, required=False,
                         description=f"Page size, default {paginator.page_size}, "
                                     f"max {paginator.max_page_size}."),
        OpenApiParameter("direction", str, OpenApiParameter.QUERY, required=False,
                         enum=["next", "prev"], description="Walk direction from the anchor."),
    ]


SHIPMENT_FILTERS = [
    OpenApiParameter("status", str, OpenApiParameter.QUERY, required=False, many=True,
                     enum=[value for value, _ in ShipmentStatus.choices],
                     description="Filter by status (repeatable)."),
    OpenApiParameter("order_id", str, OpenApiParameter.QUERY, required=False,
                     description="Only the shipment of this order."),
]


# ── catalog ───────────────────────────────────────────────────────────────


@extend_schema(tags=TAGS)
class MethodListView(_DeliveryView):
    """Enabled delivery methods, in display order."""

    permission_classes = [permissions.AllowAny]
    stapel_anonymous_access = ANONYMOUS_ALLOWED
    response_serializer_class = DeliveryMethodListSerializer

    @extend_schema(operation_id="delivery_methods_list", responses={200: DeliveryMethodListSerializer})
    @flow_step(CHOOSE, order=1, note="See which delivery methods the shop offers")
    def get(self, request):
        methods = DeliveryMethod.objects.filter(enabled=True).order_by("sort", "id")
        return self.serialized_response(get_method_presenter()().present_list(methods))


@extend_schema(tags=TAGS)
class OptionsView(_DeliveryView):
    """Methods with prices for a cart and a destination (zero writes)."""

    permission_classes = [permissions.AllowAny]
    stapel_anonymous_access = ANONYMOUS_ALLOWED
    request_serializer_class = DeliveryOptionsRequestSerializer
    response_serializer_class = DeliveryOptionsResponseSerializer

    @extend_schema(operation_id="delivery_options_create", request=DeliveryOptionsRequestSerializer,
                   responses={200: DeliveryOptionsResponseSerializer})
    @flow_step(CHOOSE, order=2, note="Price every method for this cart and address")
    def post(self, request):
        data = self.validated_request_data(request)
        user = request.user
        payload = {
            "currency": data["currency"],
            "subtotal": str(data["subtotal"]),
            "lines": [
                {"quantity": line["quantity"], "attrs": line.get("attrs") or {}}
                for line in data["lines"]
            ],
            "address": dict(data["address"]) if data.get("address") else None,
            "address_id": data.get("address_id"),
            "user_id": str(user.pk) if getattr(user, "is_authenticated", False) else None,
        }
        options = checkout_service.options(payload)
        return self.serialized_response(get_options_presenter()().present(options))


@extend_schema(tags=TAGS)
class PickupPointListView(_DeliveryView):
    """Enabled pickup points, filterable by method, country and city."""

    permission_classes = [permissions.AllowAny]
    stapel_anonymous_access = ANONYMOUS_ALLOWED
    pagination_class = PickupPointAnchorPagination
    response_serializer_class = PickupPointResponseSerializer

    @extend_schema(
        operation_id="delivery_pickup_points_list",
        parameters=[
            OpenApiParameter("method", str, OpenApiParameter.QUERY, required=False,
                             description="Method code."),
            OpenApiParameter("country", str, OpenApiParameter.QUERY, required=False,
                             description="ISO 3166 alpha-2."),
            OpenApiParameter("city", str, OpenApiParameter.QUERY, required=False,
                             description="City, case-insensitive."),
            *_anchor_parameters(PickupPointAnchorPagination),
        ],
        responses={200: PickupPointPageSerializer},
    )
    @flow_step(CHOOSE, order=3, note="Pick a pickup point")
    def get(self, request):
        qs = PickupPoint.objects.filter(enabled=True, method__enabled=True).select_related("method")
        params = request.query_params
        if params.get("method"):
            qs = qs.filter(method__code=params["method"][:32])
        if params.get("country"):
            qs = qs.filter(country=params["country"][:2].upper())
        if params.get("city"):
            qs = qs.filter(city__iexact=params["city"][:100])
        return self._page(request, qs, self.pagination_class,
                          get_pickup_point_presenter()().present, PickupPointResponseSerializer)


# ── address book ──────────────────────────────────────────────────────────


@extend_schema(tags=TAGS)
class AddressListView(_DeliveryView):
    """My address book (bounded by MAX_ADDRESSES) and adding to it."""

    # A buyer's book is personal, not an organization's: no workspace mandate
    # (pinned by tests/test_permissions.py).
    permission_classes = [IsNotAnonymousUser]  # noqa: SUR002
    stapel_anonymous_access = ANONYMOUS_DENIED
    request_serializer_class = AddressRequestSerializer
    response_serializer_class = AddressResponseSerializer

    @extend_schema(operation_id="delivery_addresses_list", responses={200: AddressListSerializer})
    @flow_step(ADDRESSES, order=1, note="Open my addresses, the default first")
    def get(self, request):
        from .conf import delivery_settings

        items = address_service.for_user(self._user_id(request)).order_by("-is_default", "-id")
        cap = int(delivery_settings.MAX_ADDRESSES)
        dto = get_address_presenter()().present_list(items[:cap], cap)
        return StapelResponse(AddressListSerializer(dto).data)

    @extend_schema(operation_id="delivery_addresses_create", request=AddressRequestSerializer,
                   responses={201: AddressResponseSerializer})
    @flow_step(ADDRESSES, order=2, note="Save an address")
    def post(self, request):
        data = dict(self.validated_request_data(request))
        address = address_service.create(self._user_id(request), data)
        return self.serialized_response(get_address_presenter()().present(address), status=201)


@extend_schema(tags=TAGS)
class AddressDetailView(_DeliveryView):
    """One of my addresses; a foreign id is a 404 like an absent one."""

    permission_classes = [IsNotAnonymousUser]
    stapel_anonymous_access = ANONYMOUS_DENIED
    request_serializer_class = AddressRequestSerializer
    response_serializer_class = AddressResponseSerializer

    @extend_schema(operation_id="delivery_addresses_retrieve", responses={200: AddressResponseSerializer})
    @flow_step(ADDRESSES, order=6, note="Open one address")
    def get(self, request, address_id):
        address = address_service.get_owned(self._user_id(request), address_id)
        return self.serialized_response(get_address_presenter()().present(address))

    @extend_schema(operation_id="delivery_addresses_partial_update", request=AddressRequestSerializer,
                   responses={200: AddressResponseSerializer})
    @flow_step(ADDRESSES, order=3, note="Edit an address")
    def patch(self, request, address_id):
        data = dict(self.validated_request_data(request, partial=True))
        address = address_service.update(self._user_id(request), address_id, data)
        return self.serialized_response(get_address_presenter()().present(address))

    @extend_schema(operation_id="delivery_addresses_destroy", responses={204: None})
    @flow_step(ADDRESSES, order=4, note="Remove an address")
    def delete(self, request, address_id):
        address_service.delete(self._user_id(request), address_id)
        return StapelResponse(status=204)


@extend_schema(tags=TAGS)
class AddressDefaultView(_DeliveryView):
    """Make one of my addresses the default."""

    permission_classes = [IsNotAnonymousUser]
    stapel_anonymous_access = ANONYMOUS_DENIED
    response_serializer_class = AddressResponseSerializer

    @extend_schema(operation_id="delivery_addresses_make_default", request=None,
                   responses={200: AddressResponseSerializer})
    @flow_step(ADDRESSES, order=5, note="Pick the default address")
    def post(self, request, address_id):
        address = address_service.make_default(self._user_id(request), address_id)
        return self.serialized_response(get_address_presenter()().present(address))


# ── buyer shipments ───────────────────────────────────────────────────────


@extend_schema(tags=TAGS)
class ShipmentListView(_DeliveryView):
    """My shipments, newest first."""

    permission_classes = [permissions.IsAuthenticated]
    stapel_anonymous_access = ANONYMOUS_ALLOWED
    pagination_class = ShipmentAnchorPagination
    response_serializer_class = ShipmentResponseSerializer

    @extend_schema(operation_id="delivery_shipments_list",
                   parameters=[*SHIPMENT_FILTERS, *_anchor_parameters(ShipmentAnchorPagination)],
                   responses={200: ShipmentPageSerializer})
    @flow_step(TRACK, order=1, note="Page through my shipments")
    def get(self, request):
        qs = shipment_service.for_user(self._user_id(request), request.query_params.getlist("status"),
                                       request.query_params.get("order_id"))
        return self._page(request, qs.prefetch_related("events"), self.pagination_class,
                          get_shipment_presenter()().present, ShipmentResponseSerializer)


@extend_schema(tags=TAGS)
class ShipmentDetailView(_DeliveryView):
    """Track one of my shipments: status, tracking link, timeline."""

    permission_classes = [permissions.IsAuthenticated]
    stapel_anonymous_access = ANONYMOUS_ALLOWED
    response_serializer_class = ShipmentResponseSerializer

    @extend_schema(operation_id="delivery_shipments_retrieve", responses={200: ShipmentResponseSerializer})
    @flow_step(TRACK, order=2, note="Open one shipment and its timeline")
    def get(self, request, shipment_id):
        return self._shipment(shipment_service.get_owned(self._user_id(request), shipment_id))


# ── staff ─────────────────────────────────────────────────────────────────


@extend_schema(tags=TAGS)
class StaffShipmentListView(_DeliveryView):
    """Every shipment, newest first (staff)."""

    permission_classes = [IsStaffUser]
    stapel_anonymous_access = ANONYMOUS_DENIED
    pagination_class = ShipmentAnchorPagination
    response_serializer_class = ShipmentResponseSerializer

    @extend_schema(operation_id="delivery_staff_shipments_list",
                   parameters=[*SHIPMENT_FILTERS, *_anchor_parameters(ShipmentAnchorPagination)],
                   responses={200: ShipmentPageSerializer})
    @flow_step(FULFIL, order=1, note="Work through pending shipments")
    def get(self, request):
        qs = shipment_service.for_staff(request.query_params.getlist("status"),
                                        request.query_params.get("order_id"))
        return self._page(request, qs.prefetch_related("events"), self.pagination_class,
                          get_shipment_presenter()().present, ShipmentResponseSerializer)


@extend_schema(tags=TAGS)
class StaffShipmentTrackingView(_DeliveryView):
    """Record the carrier's tracking number (staff)."""

    permission_classes = [IsStaffUser]
    stapel_anonymous_access = ANONYMOUS_DENIED
    request_serializer_class = ShipmentTrackingRequestSerializer
    response_serializer_class = ShipmentResponseSerializer

    @extend_schema(operation_id="delivery_staff_shipments_tracking",
                   request=ShipmentTrackingRequestSerializer,
                   responses={200: ShipmentResponseSerializer})
    @flow_step(FULFIL, order=2, note="Record the tracking number")
    def post(self, request, shipment_id):
        data = self.validated_request_data(request)
        shipment = shipment_service.set_tracking(shipment_id, data["tracking_number"],
                                                 data.get("carrier") or None)
        return self._shipment(shipment)


@extend_schema(tags=TAGS)
class StaffShipmentTransitionView(_DeliveryView):
    """Move a shipment along its lifecycle (staff)."""

    permission_classes = [IsStaffUser]
    stapel_anonymous_access = ANONYMOUS_DENIED
    request_serializer_class = ShipmentTransitionRequestSerializer
    response_serializer_class = ShipmentResponseSerializer

    @extend_schema(operation_id="delivery_staff_shipments_transition",
                   request=ShipmentTransitionRequestSerializer,
                   responses={200: ShipmentResponseSerializer})
    @flow_step(FULFIL, order=3, note="Mark packed, shipped, delivered, returned or cancelled")
    def post(self, request, shipment_id):
        data = self.validated_request_data(request)
        shipment = shipment_service.staff_transition(shipment_id, data["to"], data.get("note", ""),
                                                     data.get("location", ""))
        return self._shipment(shipment_service.get_any(shipment.pk))
