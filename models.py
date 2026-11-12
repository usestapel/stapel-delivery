"""Models of stapel-delivery.

Nothing here has a foreign key into a sibling module: an order is an opaque
``order_id`` string, a purchasable an opaque pair. Users are referenced by
id strings (``str(user.pk)``), not foreign keys, so an erased shipment keeps
its economics under a pseudonymized id.

Addresses are **snapshots** wherever they leave the address book: a checkout
intent and a shipment copy the recipient; nothing points back at
``Address``.
"""
from __future__ import annotations

from django.db import models
from stapel_core.access import access

from . import money

USER_ID_MAX_LENGTH = 64
ORDER_ID_MAX_LENGTH = 64
CODE_MAX_LENGTH = 32
PICKUP_CODE_MAX_LENGTH = 64
NAME_MAX_LENGTH = 120
DESCRIPTION_MAX_LENGTH = 500
LABEL_MAX_LENGTH = 60
PHONE_MAX_LENGTH = 32
LINE_MAX_LENGTH = 200
CITY_MAX_LENGTH = 100
REGION_MAX_LENGTH = 100
POSTAL_CODE_MAX_LENGTH = 20
COUNTRY_MAX_LENGTH = 2
CURRENCY_MAX_LENGTH = 3
URL_MAX_LENGTH = 500
TRACKING_NUMBER_MAX_LENGTH = 64
SHIPMENT_NUMBER_MAX_LENGTH = 16
NOTE_MAX_LENGTH = 200
LOCATION_MAX_LENGTH = 120
ATTEMPT_KEY_MAX_LENGTH = 64
FINGERPRINT_MAX_LENGTH = 64
RELEASE_REASON_MAX_LENGTH = 32

#: Zone match lists are bounded (admin input, but read on every quote).
MAX_ZONE_ENTRIES = 500
#: Weekly pickup windows per point.
MAX_HOURS_WINDOWS = 42
#: Coordinates: 6 decimal places is ~0.1 m.
COORD_MAX_DIGITS = 9
COORD_DECIMAL_PLACES = 6


def _amount_field(**kwargs):
    return models.DecimalField(
        max_digits=money.AMOUNT_MAX_DIGITS,
        decimal_places=money.DECIMAL_PLACES,
        **kwargs,
    )


def _weight_field(**kwargs):
    return models.DecimalField(
        max_digits=money.WEIGHT_MAX_DIGITS,
        decimal_places=money.WEIGHT_DECIMAL_PLACES,
        **kwargs,
    )


def _coord_field(help_text: str):
    return models.DecimalField(
        max_digits=COORD_MAX_DIGITS, decimal_places=COORD_DECIMAL_PLACES,
        null=True, blank=True, help_text=help_text,
    )


class MethodKind(models.TextChoices):
    COURIER = "courier", "Courier"
    PICKUP = "pickup", "Pickup point"
    DIGITAL = "digital", "Digital"


class ShipmentStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    PACKED = "packed", "Packed"
    SHIPPED = "shipped", "Shipped"
    DELIVERED = "delivered", "Delivered"
    RETURNED = "returned", "Returned"
    CANCELLED = "cancelled", "Cancelled"


#: The one release reason that undoes a committed checkout (orders contract delta 13).
RELEASE_CANCELLED = "cancelled"


class IntentStatus(models.TextChoices):
    RESERVED = "reserved", "Reserved"
    COMMITTED = "committed", "Committed"
    RELEASED = "released", "Released"


#: Statuses a carrier is still polled for.
ACTIVE_STATUSES = (ShipmentStatus.PENDING, ShipmentStatus.PACKED, ShipmentStatus.SHIPPED)


@access.standard
class Zone(models.Model):
    """Where a rate applies: country, region and postcode-prefix lists."""

    code = models.SlugField(max_length=CODE_MAX_LENGTH, unique=True, help_text="Stable zone code.")
    name = models.CharField(max_length=NAME_MAX_LENGTH, help_text="Staff-facing name.")
    countries = models.JSONField(
        default=list, blank=True,
        help_text="ISO 3166 alpha-2 codes; empty = any country.",
    )
    regions = models.JSONField(
        default=list, blank=True,
        help_text="Region names, case-insensitive; empty = any region.",
    )
    postcode_prefixes = models.JSONField(
        default=list, blank=True,
        help_text="Postcode prefixes, spaces ignored, case-insensitive; empty = any postcode.",
    )

    class Meta:
        app_label = "delivery"
        ordering = ["code"]

    def __str__(self) -> str:
        return self.name or self.code


@access.standard
class DeliveryMethod(models.Model):
    code = models.SlugField(max_length=CODE_MAX_LENGTH, unique=True,
                            help_text="Stable method code the client sends in context.delivery.method.")
    name = models.CharField(max_length=NAME_MAX_LENGTH, help_text="Buyer-facing name.")
    description = models.CharField(max_length=DESCRIPTION_MAX_LENGTH, blank=True, default="",
                                   help_text="Buyer-facing description.")
    kind = models.CharField(max_length=16, choices=MethodKind.choices, default=MethodKind.COURIER,
                            help_text="courier needs an address, pickup a pickup point, digital nothing.")
    enabled = models.BooleanField(default=True, help_text="Disabled methods are never offered.")
    sort = models.IntegerField(default=100, help_text="Ascending display order.")
    carrier = models.SlugField(max_length=CODE_MAX_LENGTH, blank=True, default="",
                               help_text="Carrier slug; blank = DEFAULT_CARRIER.")
    tracking_url_template = models.CharField(
        max_length=URL_MAX_LENGTH, blank=True, default="",
        help_text="{tracking_number}/{number} template; blank = the carrier's own.",
    )
    eta_min_days = models.PositiveSmallIntegerField(null=True, blank=True,
                                                    help_text="Earliest delivery, days.")
    eta_max_days = models.PositiveSmallIntegerField(null=True, blank=True,
                                                    help_text="Latest delivery, days.")

    class Meta:
        app_label = "delivery"
        ordering = ["sort", "id"]

    def __str__(self) -> str:
        return f"{self.name} ({self.code})"


@access.standard
class Rate(models.Model):
    method = models.ForeignKey(DeliveryMethod, on_delete=models.CASCADE, related_name="rates",
                               help_text="The method this rate prices.")
    zone = models.ForeignKey(Zone, on_delete=models.CASCADE, null=True, blank=True,
                             related_name="rates", help_text="NULL = everywhere (least specific).")
    currency = models.CharField(max_length=CURRENCY_MAX_LENGTH,
                                help_text="ISO 4217; only carts in this currency use the rate.")
    amount = _amount_field(default=0, help_text="Flat price (and the base of a weight price).")
    free_above = _amount_field(null=True, blank=True,
                               help_text="Cart subtotal at or above this ships free; NULL = never.")
    per_kg = _amount_field(null=True, blank=True,
                           help_text="Added per kilogram when every line has a weight; NULL = flat.")
    max_weight_kg = _weight_field(null=True, blank=True,
                                  help_text="A known weight above this is not offered; NULL = no cap.")
    enabled = models.BooleanField(default=True, help_text="Disabled rates never apply.")
    sort = models.IntegerField(default=100, help_text="Tie-break between equally specific rates.")

    class Meta:
        app_label = "delivery"
        ordering = ["method_id", "sort", "id"]

    def __str__(self) -> str:
        return f"{self.method_id}:{self.zone_id or '*'} {self.amount} {self.currency}"


class _AddressFields(models.Model):
    line1 = models.CharField(max_length=LINE_MAX_LENGTH, help_text="Street and house.")
    line2 = models.CharField(max_length=LINE_MAX_LENGTH, blank=True, default="",
                             help_text="Apartment, floor, entrance.")
    city = models.CharField(max_length=CITY_MAX_LENGTH, help_text="City or locality.")
    region = models.CharField(max_length=REGION_MAX_LENGTH, blank=True, default="",
                              help_text="Region, state or province.")
    postal_code = models.CharField(max_length=POSTAL_CODE_MAX_LENGTH, blank=True, default="",
                                   help_text="Postcode.")
    country = models.CharField(max_length=COUNTRY_MAX_LENGTH, help_text="ISO 3166 alpha-2, upper case.")
    latitude = _coord_field("Latitude, NULL when unknown.")
    longitude = _coord_field("Longitude, NULL when unknown.")

    class Meta:
        abstract = True


@access.standard
class PickupPoint(_AddressFields):
    method = models.ForeignKey(DeliveryMethod, on_delete=models.CASCADE, related_name="pickup_points",
                               help_text="The pickup method this point serves.")
    code = models.CharField(max_length=PICKUP_CODE_MAX_LENGTH, unique=True,
                            help_text="Stable code the client sends in context.delivery.pickup_point.")
    name = models.CharField(max_length=NAME_MAX_LENGTH, help_text="Buyer-facing name.")
    hours = models.JSONField(default=list, blank=True,
                             help_text="Weekly windows [{weekday 0-6, opens HH:MM, closes HH:MM}].")
    hours_note = models.CharField(max_length=NOTE_MAX_LENGTH, blank=True, default="",
                                  help_text="Free-text note on hours (holidays, breaks).")
    enabled = models.BooleanField(default=True, help_text="Disabled points are never offered.")
    sort = models.IntegerField(default=100, help_text="Ascending display order.")

    class Meta:
        app_label = "delivery"
        ordering = ["sort", "id"]
        indexes = [models.Index(fields=["method", "country", "city"], name="delivery_pickup_place")]

    def __str__(self) -> str:
        return f"{self.name} ({self.code})"


@access.standard
class Address(_AddressFields):
    """One entry of a user's address book."""

    user_id = models.CharField(max_length=USER_ID_MAX_LENGTH, db_index=True,
                               help_text="str(user.pk) of the owner.")
    label = models.CharField(max_length=LABEL_MAX_LENGTH, blank=True, default="",
                             help_text="Owner's label: Home, Office.")
    name = models.CharField(max_length=NAME_MAX_LENGTH, help_text="Recipient name.")
    phone = models.CharField(max_length=PHONE_MAX_LENGTH, help_text="Recipient phone.")
    is_default = models.BooleanField(default=False, help_text="At most one per user.")
    created_at = models.DateTimeField(auto_now_add=True, help_text="When the entry was saved.")
    updated_at = models.DateTimeField(auto_now=True, help_text="Last edit.")

    class Meta:
        app_label = "delivery"
        ordering = ["-is_default", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["user_id"], condition=models.Q(is_default=True),
                name="delivery_address_one_default",
            ),
        ]

    def __str__(self) -> str:
        return f"Address({self.user_id}: {self.city})"


@access.ops
class DeliveryIntent(models.Model):
    """The buyer's delivery choice at one checkout attempt (orders hook state)."""

    attempt_key = models.CharField(max_length=ATTEMPT_KEY_MAX_LENGTH, unique=True,
                                   help_text="The orders checkout idempotency key.")
    user_id = models.CharField(max_length=USER_ID_MAX_LENGTH, blank=True, default="", db_index=True,
                               help_text="str(user.pk) of the buyer; blank for a guest-less call.")
    status = models.CharField(max_length=16, choices=IntentStatus.choices, default=IntentStatus.RESERVED,
                              help_text="reserved -> committed | released.")
    method_code = models.CharField(max_length=CODE_MAX_LENGTH, help_text="Chosen method code.")
    method_name = models.CharField(max_length=NAME_MAX_LENGTH, help_text="Method name at checkout.")
    method_kind = models.CharField(max_length=16, choices=MethodKind.choices, help_text="Method kind.")
    carrier = models.SlugField(max_length=CODE_MAX_LENGTH, help_text="Resolved carrier slug.")
    recipient = models.JSONField(default=dict, blank=True, help_text="Recipient address snapshot.")
    pickup_point = models.JSONField(default=dict, blank=True, help_text="Pickup point snapshot.")
    amount = _amount_field(help_text="Shipping price quoted at reserve.")
    currency = models.CharField(max_length=CURRENCY_MAX_LENGTH, help_text="Cart currency.")
    weight_kg = _weight_field(null=True, blank=True, help_text="Known cart weight, NULL when unknown.")
    shippable = models.BooleanField(default=True, help_text="False: nothing in the cart ships.")
    lines_fingerprint = models.CharField(max_length=FINGERPRINT_MAX_LENGTH, db_index=True,
                                         help_text="sha256 of currency + sorted lines.")
    order_id = models.CharField(max_length=ORDER_ID_MAX_LENGTH, blank=True, default="", db_index=True,
                                help_text="The order this intent became; blank until known.")
    release_reason = models.CharField(max_length=RELEASE_REASON_MAX_LENGTH, blank=True, default="",
                                      help_text="Reason of the release that ended a reserved intent.")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True, help_text="First reserve.")
    updated_at = models.DateTimeField(auto_now=True, help_text="Last change.")

    class Meta:
        app_label = "delivery"

    def __str__(self) -> str:
        return f"DeliveryIntent({self.attempt_key}: {self.status})"


@access.standard
class Shipment(models.Model):
    number = models.CharField(max_length=SHIPMENT_NUMBER_MAX_LENGTH, unique=True,
                              help_text="Human shipment number YYYYMMDD-XXXXXX; never the pk.")
    order_id = models.CharField(max_length=ORDER_ID_MAX_LENGTH, unique=True,
                                help_text="The order (opaque id); one shipment per order.")
    user_id = models.CharField(max_length=USER_ID_MAX_LENGTH, db_index=True,
                               help_text="str(user.pk) of the buyer; a pseudonym after erasure.")
    method_code = models.CharField(max_length=CODE_MAX_LENGTH, help_text="Method code at checkout.")
    method_name = models.CharField(max_length=NAME_MAX_LENGTH, help_text="Method name at checkout.")
    method_kind = models.CharField(max_length=16, choices=MethodKind.choices, help_text="Method kind.")
    carrier = models.SlugField(max_length=CODE_MAX_LENGTH, help_text="Carrier slug.")
    status = models.CharField(max_length=16, choices=ShipmentStatus.choices,
                              default=ShipmentStatus.PENDING, db_index=True,
                              help_text="Moved only through the FSM (fsm.py).")
    tracking_number = models.CharField(max_length=TRACKING_NUMBER_MAX_LENGTH, blank=True, default="",
                                       help_text="Carrier tracking number; blank until known.")
    tracking_url = models.CharField(max_length=URL_MAX_LENGTH, blank=True, default="",
                                    help_text="Rendered tracking link; blank when none.")
    recipient_name = models.CharField(max_length=NAME_MAX_LENGTH, blank=True, default="",
                                      help_text="Recipient snapshot: name.")
    recipient_phone = models.CharField(max_length=PHONE_MAX_LENGTH, blank=True, default="",
                                       help_text="Recipient snapshot: phone.")
    line1 = models.CharField(max_length=LINE_MAX_LENGTH, blank=True, default="",
                             help_text="Recipient snapshot: street and house.")
    line2 = models.CharField(max_length=LINE_MAX_LENGTH, blank=True, default="",
                             help_text="Recipient snapshot: apartment.")
    city = models.CharField(max_length=CITY_MAX_LENGTH, blank=True, default="",
                            help_text="Recipient snapshot: city.")
    region = models.CharField(max_length=REGION_MAX_LENGTH, blank=True, default="",
                              help_text="Recipient snapshot: region.")
    postal_code = models.CharField(max_length=POSTAL_CODE_MAX_LENGTH, blank=True, default="",
                                   help_text="Recipient snapshot: postcode.")
    country = models.CharField(max_length=COUNTRY_MAX_LENGTH, blank=True, default="",
                               help_text="Recipient snapshot: country.")
    pickup_point = models.JSONField(default=dict, blank=True,
                                    help_text="Pickup point snapshot {code, name, address}; {} for courier.")
    amount = _amount_field(help_text="Shipping charged at checkout.")
    currency = models.CharField(max_length=CURRENCY_MAX_LENGTH, help_text="Order currency.")
    weight_kg = _weight_field(null=True, blank=True, help_text="Known weight at checkout.")
    lines = models.JSONField(default=list, blank=True,
                             help_text="[{purchasable_type, purchasable_key, quantity}] from the order.")
    shipped_at = models.DateTimeField(null=True, blank=True, help_text="First move to shipped.")
    delivered_at = models.DateTimeField(null=True, blank=True, help_text="Move to delivered.")
    created_at = models.DateTimeField(auto_now_add=True, help_text="When the order was placed here.")
    updated_at = models.DateTimeField(auto_now=True, help_text="Last change.")

    class Meta:
        app_label = "delivery"
        ordering = ["-id"]
        indexes = [
            models.Index(fields=["user_id", "-id"], name="delivery_shipment_user_desc"),
            models.Index(fields=["status", "id"], name="delivery_shipment_status"),
        ]

    def __str__(self) -> str:
        return f"Shipment {self.number} ({self.status})"


@access.standard
class ShipmentEvent(models.Model):
    """One step of a shipment's timeline (what the buyer's tracking shows)."""

    shipment = models.ForeignKey(Shipment, on_delete=models.CASCADE, related_name="events",
                                 help_text="The shipment this step belongs to.")
    from_status = models.CharField(max_length=16, blank=True, default="",
                                   help_text="Status before; blank for the creation step.")
    to_status = models.CharField(max_length=16, choices=ShipmentStatus.choices,
                                 help_text="Status after.")
    actor = models.CharField(max_length=16, help_text="staff | carrier | system.")
    note = models.CharField(max_length=NOTE_MAX_LENGTH, blank=True, default="",
                            help_text="Buyer-visible note.")
    location = models.CharField(max_length=LOCATION_MAX_LENGTH, blank=True, default="",
                                help_text="Where it happened, when the carrier says.")
    occurred_at = models.DateTimeField(help_text="When it happened (carrier time when given).")
    created_at = models.DateTimeField(auto_now_add=True, help_text="When it was recorded.")

    class Meta:
        app_label = "delivery"
        ordering = ["occurred_at", "id"]

    def __str__(self) -> str:
        return f"{self.shipment_id}: {self.from_status} -> {self.to_status}"
