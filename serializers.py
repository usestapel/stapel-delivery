"""Serializers for the stapel-delivery API.

The class names are the codegen contract: drf-spectacular names each
component after its serializer minus the ``Serializer`` suffix
(``AddressResponse``, ``ShipmentPage``, …), and the frontend pair generates
its client from those names. Every CharField declares a ``max_length``;
money is a ``DecimalField`` rendered as a string; instants are ISO 8601.

``AddressSnapshotSerializer`` is also the validator of an inline checkout
address (``services.addresses.validate_snapshot``): one shape rule for the
book and for checkout.
"""
import datetime

from rest_framework import serializers
from stapel_core.django.api.errors import StapelValidationError

from . import fsm, money
from .errors import ERR_400_DELIVERY_ADDRESS_INVALID
from . import models as m

UTC = datetime.timezone.utc

PHONE_RE = r"^\+?[0-9][0-9 ()\-.]{2,31}$"
POSTAL_CODE_RE = r"^[A-Za-z0-9][A-Za-z0-9 \-]{0,19}$"
COUNTRY_RE = r"^[A-Za-z]{2}$"
HHMM = r"^([01][0-9]|2[0-3]):[0-5][0-9]$"
HHMM_END = r"^(([01][0-9]|2[0-3]):[0-5][0-9]|24:00)$"

#: Lines one options request may carry (the orders cart bound).
MAX_LINES = 100


def _money(**kwargs):
    return serializers.DecimalField(
        max_digits=money.AMOUNT_MAX_DIGITS,
        decimal_places=money.DECIMAL_PLACES,
        coerce_to_string=True,
        **kwargs,
    )


def _weight(**kwargs):
    return serializers.DecimalField(
        max_digits=money.WEIGHT_MAX_DIGITS,
        decimal_places=money.WEIGHT_DECIMAL_PLACES,
        coerce_to_string=True,
        **kwargs,
    )


def _coord(limit: int, **kwargs):
    return serializers.DecimalField(
        max_digits=m.COORD_MAX_DIGITS, decimal_places=m.COORD_DECIMAL_PLACES,
        min_value=-limit, max_value=limit, coerce_to_string=True, **kwargs,
    )


class _CountryField(serializers.RegexField):
    def __init__(self, **kwargs):
        super().__init__(COUNTRY_RE, max_length=m.COUNTRY_MAX_LENGTH, min_length=2,
                         help_text="ISO 3166 alpha-2.", **kwargs)

    def to_internal_value(self, data):
        return super().to_internal_value(data).upper()


# ── Addresses ─────────────────────────────────────────────────────────────


class AddressSnapshotSerializer(serializers.Serializer):
    """A recipient address as checkout and the book accept it."""

    name = serializers.CharField(max_length=m.NAME_MAX_LENGTH, help_text="Recipient name.")
    phone = serializers.RegexField(PHONE_RE, max_length=m.PHONE_MAX_LENGTH, help_text="Recipient phone.")
    line1 = serializers.CharField(max_length=m.LINE_MAX_LENGTH)
    line2 = serializers.CharField(max_length=m.LINE_MAX_LENGTH, required=False, allow_blank=True, default="")
    city = serializers.CharField(max_length=m.CITY_MAX_LENGTH)
    region = serializers.CharField(max_length=m.REGION_MAX_LENGTH, required=False, allow_blank=True,
                                   default="")
    postal_code = serializers.RegexField(POSTAL_CODE_RE, max_length=m.POSTAL_CODE_MAX_LENGTH,
                                         required=False, allow_blank=True, default="")
    country = _CountryField()
    latitude = _coord(90, required=False, allow_null=True, default=None)
    longitude = _coord(180, required=False, allow_null=True, default=None)

    def validate(self, attrs):
        if (attrs.get("latitude") is None) != (attrs.get("longitude") is None):
            raise StapelValidationError(ERR_400_DELIVERY_ADDRESS_INVALID, {"field": "latitude"})
        return attrs


class AddressRequestSerializer(AddressSnapshotSerializer):
    label = serializers.CharField(max_length=m.LABEL_MAX_LENGTH, required=False, allow_blank=True,
                                  default="", help_text="Home, Office…")
    is_default = serializers.BooleanField(required=False, default=False,
                                          help_text="Make this the default address.")


class AddressResponseSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    label = serializers.CharField(max_length=m.LABEL_MAX_LENGTH, allow_blank=True)
    name = serializers.CharField(max_length=m.NAME_MAX_LENGTH)
    phone = serializers.CharField(max_length=m.PHONE_MAX_LENGTH)
    line1 = serializers.CharField(max_length=m.LINE_MAX_LENGTH)
    line2 = serializers.CharField(max_length=m.LINE_MAX_LENGTH, allow_blank=True)
    city = serializers.CharField(max_length=m.CITY_MAX_LENGTH)
    region = serializers.CharField(max_length=m.REGION_MAX_LENGTH, allow_blank=True)
    postal_code = serializers.CharField(max_length=m.POSTAL_CODE_MAX_LENGTH, allow_blank=True)
    country = serializers.CharField(max_length=m.COUNTRY_MAX_LENGTH)
    latitude = _coord(90, allow_null=True)
    longitude = _coord(180, allow_null=True)
    is_default = serializers.BooleanField()
    created_at = serializers.DateTimeField(default_timezone=UTC)
    updated_at = serializers.DateTimeField(default_timezone=UTC)


class AddressListSerializer(serializers.Serializer):
    """The whole book: bounded by MAX_ADDRESSES, so it is not paginated."""

    items = AddressResponseSerializer(many=True)
    count = serializers.IntegerField(min_value=0)
    max = serializers.IntegerField(min_value=0, help_text="MAX_ADDRESSES.")


# ── Methods and options ───────────────────────────────────────────────────


class DeliveryMethodResponseSerializer(serializers.Serializer):
    code = serializers.CharField(max_length=m.CODE_MAX_LENGTH)
    name = serializers.CharField(max_length=m.NAME_MAX_LENGTH)
    description = serializers.CharField(max_length=m.DESCRIPTION_MAX_LENGTH, allow_blank=True)
    kind = serializers.ChoiceField(choices=m.MethodKind.choices)
    eta_min_days = serializers.IntegerField(allow_null=True, min_value=0)
    eta_max_days = serializers.IntegerField(allow_null=True, min_value=0)


class DeliveryMethodListSerializer(serializers.Serializer):
    items = DeliveryMethodResponseSerializer(many=True)


class CartLineInputSerializer(serializers.Serializer):
    purchasable_type = serializers.CharField(max_length=32, required=False, allow_blank=True, default="")
    purchasable_key = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")
    quantity = serializers.IntegerField(min_value=1, max_value=999)
    unit_price = _money(required=False, min_value=0, default=None, allow_null=True)
    attrs = serializers.DictField(required=False, default=dict,
                                  help_text="The cart line's attrs; weight_grams is read.")


class DestinationSerializer(serializers.Serializer):
    country = _CountryField()
    region = serializers.CharField(max_length=m.REGION_MAX_LENGTH, required=False, allow_blank=True,
                                   default="")
    postal_code = serializers.CharField(max_length=m.POSTAL_CODE_MAX_LENGTH, required=False,
                                        allow_blank=True, default="")


class DeliveryOptionsRequestSerializer(serializers.Serializer):
    currency = serializers.RegexField(r"^[A-Z]{3}$", max_length=m.CURRENCY_MAX_LENGTH)
    subtotal = _money(min_value=0)
    lines = CartLineInputSerializer(many=True, max_length=MAX_LINES)
    address = DestinationSerializer(required=False, allow_null=True, default=None,
                                    help_text="Where to (country is enough to price).")
    address_id = serializers.IntegerField(required=False, allow_null=True, default=None,
                                          help_text="An entry of my address book instead.")


class DeliveryOptionSerializer(serializers.Serializer):
    code = serializers.CharField(max_length=m.CODE_MAX_LENGTH)
    name = serializers.CharField(max_length=m.NAME_MAX_LENGTH)
    description = serializers.CharField(max_length=m.DESCRIPTION_MAX_LENGTH, allow_blank=True)
    kind = serializers.ChoiceField(choices=m.MethodKind.choices)
    eta_min_days = serializers.IntegerField(allow_null=True, min_value=0)
    eta_max_days = serializers.IntegerField(allow_null=True, min_value=0)
    available = serializers.BooleanField()
    price = _money(allow_null=True, help_text="null when not available.")
    price_is_minimum = serializers.BooleanField(help_text="Pickup: the cheapest point's price.")
    currency = serializers.CharField(max_length=m.CURRENCY_MAX_LENGTH)
    free_reason = serializers.ChoiceField(choices=[("threshold", "threshold"), ("promotion", "promotion")],
                                          allow_null=True)
    reason = serializers.CharField(max_length=64, allow_null=True,
                                   help_text="Error key why it is not available.")


class DeliveryOptionsResponseSerializer(serializers.Serializer):
    options = DeliveryOptionSerializer(many=True)


# ── Pickup points ─────────────────────────────────────────────────────────


class HoursWindowSerializer(serializers.Serializer):
    weekday = serializers.IntegerField(min_value=0, max_value=6, help_text="0 = Monday … 6 = Sunday.")
    opens = serializers.RegexField(HHMM, max_length=5)
    closes = serializers.RegexField(HHMM_END, max_length=5)


class PickupPointResponseSerializer(serializers.Serializer):
    code = serializers.CharField(max_length=m.PICKUP_CODE_MAX_LENGTH)
    method = serializers.CharField(max_length=m.CODE_MAX_LENGTH)
    name = serializers.CharField(max_length=m.NAME_MAX_LENGTH)
    line1 = serializers.CharField(max_length=m.LINE_MAX_LENGTH)
    line2 = serializers.CharField(max_length=m.LINE_MAX_LENGTH, allow_blank=True)
    city = serializers.CharField(max_length=m.CITY_MAX_LENGTH)
    region = serializers.CharField(max_length=m.REGION_MAX_LENGTH, allow_blank=True)
    postal_code = serializers.CharField(max_length=m.POSTAL_CODE_MAX_LENGTH, allow_blank=True)
    country = serializers.CharField(max_length=m.COUNTRY_MAX_LENGTH)
    latitude = _coord(90, allow_null=True)
    longitude = _coord(180, allow_null=True)
    hours = HoursWindowSerializer(many=True, max_length=m.MAX_HOURS_WINDOWS)
    hours_note = serializers.CharField(max_length=m.NOTE_MAX_LENGTH, allow_blank=True)


class _PageSerializer(serializers.Serializer):
    next_anchor = serializers.CharField(max_length=64, allow_null=True)
    prev_anchor = serializers.CharField(max_length=64, allow_null=True)
    has_next = serializers.BooleanField()
    has_prev = serializers.BooleanField()
    count = serializers.IntegerField()


class PickupPointPageSerializer(_PageSerializer):
    items = PickupPointResponseSerializer(many=True)


# ── Shipments ─────────────────────────────────────────────────────────────


class _PlaceSerializer(serializers.Serializer):
    line1 = serializers.CharField(max_length=m.LINE_MAX_LENGTH, allow_blank=True)
    line2 = serializers.CharField(max_length=m.LINE_MAX_LENGTH, allow_blank=True)
    city = serializers.CharField(max_length=m.CITY_MAX_LENGTH, allow_blank=True)
    region = serializers.CharField(max_length=m.REGION_MAX_LENGTH, allow_blank=True)
    postal_code = serializers.CharField(max_length=m.POSTAL_CODE_MAX_LENGTH, allow_blank=True)
    country = serializers.CharField(max_length=m.COUNTRY_MAX_LENGTH, allow_blank=True)


class RecipientSnapshotSerializer(_PlaceSerializer):
    name = serializers.CharField(max_length=m.NAME_MAX_LENGTH, allow_blank=True)
    phone = serializers.CharField(max_length=m.PHONE_MAX_LENGTH, allow_blank=True)


class PickupPointSnapshotSerializer(_PlaceSerializer):
    code = serializers.CharField(max_length=m.PICKUP_CODE_MAX_LENGTH)
    name = serializers.CharField(max_length=m.NAME_MAX_LENGTH)


class ShipmentEventSerializer(serializers.Serializer):
    from_status = serializers.ChoiceField(choices=m.ShipmentStatus.choices, allow_null=True)
    to_status = serializers.ChoiceField(choices=m.ShipmentStatus.choices)
    actor = serializers.ChoiceField(choices=[(a, a) for a in fsm.ACTORS])
    note = serializers.CharField(max_length=m.NOTE_MAX_LENGTH, allow_blank=True)
    location = serializers.CharField(max_length=m.LOCATION_MAX_LENGTH, allow_blank=True)
    occurred_at = serializers.DateTimeField(default_timezone=UTC)


class ShipmentResponseSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    number = serializers.CharField(max_length=m.SHIPMENT_NUMBER_MAX_LENGTH)
    order_id = serializers.CharField(max_length=m.ORDER_ID_MAX_LENGTH)
    status = serializers.ChoiceField(choices=m.ShipmentStatus.choices)
    method_code = serializers.CharField(max_length=m.CODE_MAX_LENGTH)
    method_name = serializers.CharField(max_length=m.NAME_MAX_LENGTH)
    method_kind = serializers.ChoiceField(choices=m.MethodKind.choices)
    carrier = serializers.CharField(max_length=m.CODE_MAX_LENGTH)
    tracking_number = serializers.CharField(max_length=m.TRACKING_NUMBER_MAX_LENGTH, allow_null=True)
    tracking_url = serializers.CharField(max_length=m.URL_MAX_LENGTH, allow_null=True)
    recipient = RecipientSnapshotSerializer(allow_null=True, help_text="Courier: where it goes.")
    pickup_point = PickupPointSnapshotSerializer(allow_null=True, help_text="Pickup: where to collect.")
    amount = _money(help_text="Shipping charged.")
    currency = serializers.CharField(max_length=m.CURRENCY_MAX_LENGTH)
    weight_kg = _weight(allow_null=True)
    shipped_at = serializers.DateTimeField(default_timezone=UTC, allow_null=True)
    delivered_at = serializers.DateTimeField(default_timezone=UTC, allow_null=True)
    created_at = serializers.DateTimeField(default_timezone=UTC)
    updated_at = serializers.DateTimeField(default_timezone=UTC)
    events = ShipmentEventSerializer(many=True, help_text="Timeline, oldest first.")
    allowed_transitions = serializers.ListField(
        child=serializers.ChoiceField(choices=[(s, s) for s in fsm.STAFF_TARGETS]),
        help_text="Statuses the caller may move this shipment to now (the FSM table and the "
                  "caller's role); empty for a buyer.",
    )


class ShipmentPageSerializer(_PageSerializer):
    items = ShipmentResponseSerializer(many=True)


class ShipmentTransitionRequestSerializer(serializers.Serializer):
    to = serializers.ChoiceField(choices=[(s, s) for s in fsm.STAFF_TARGETS])
    note = serializers.CharField(max_length=m.NOTE_MAX_LENGTH, required=False, allow_blank=True, default="")
    location = serializers.CharField(max_length=m.LOCATION_MAX_LENGTH, required=False, allow_blank=True,
                                     default="")


class ShipmentTrackingRequestSerializer(serializers.Serializer):
    tracking_number = serializers.CharField(max_length=m.TRACKING_NUMBER_MAX_LENGTH)
    carrier = serializers.SlugField(max_length=m.CODE_MAX_LENGTH, required=False, allow_blank=True,
                                    default="")
