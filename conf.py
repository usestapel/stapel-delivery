"""Settings namespace for stapel-delivery.

All configuration is read through ``delivery_settings`` (lazily, at call
time). Resolution order per key: ``settings.STAPEL_DELIVERY`` dict -> flat
Django setting of the same name -> environment variable -> default below.

``DEFAULT_CARRIER`` is a short name from the carrier registry (``manual``,
``mock``, plus whatever ``CARRIERS`` or ``register_carrier`` add) or a
dotted path to a ``Carrier`` subclass. The environment may choose among the
short names only (``env_enum``).
"""
from stapel_core.conf import AppSettings

#: AppSettings-shaped literal dict: a top-level DEFAULTS lets the
#: capabilities.json emitter introspect axis keys/kinds.
DEFAULTS = {
    # Axis: True = a checkout without context.delivery is refused with
    # error.400.delivery_method_required; False = it ships for free (no
    # shipping adjustment).
    "REQUIRE_METHOD": True,
    # Axis: the carrier a method without its own carrier uses. "manual":
    # staff type the tracking number. "mock": auto-advancing demo carrier
    # (prototype posture stage only, check E002/W002).
    "DEFAULT_CARRIER": "manual",
    # {slug: "dotted.path.Carrier" | None}, merged over the built-ins
    # (manual, mock); None removes one.
    "CARRIERS": {},
    # The mock carrier advances one status per this many minutes.
    "MOCK_STEP_MINUTES": 2,
    # Saved addresses per user.
    "MAX_ADDRESSES": 20,
    # A comm Function with the geo.geocode contract that fills missing
    # coordinates of a saved address (best-effort); "" = off.
    "GEOCODE_FUNCTION": "",
    # Best-effort buyer notification delivery.shipment_status_changed.
    "NOTIFY": True,
    # "{shipment_id}"/"{number}"/"{order_id}" template for notification
    # links; empty = no link.
    "SHIPMENT_URL_TEMPLATE": "",
    # Reserved checkout intents older than this are purged by the beat.
    "INTENT_TTL_HOURS": 72,
}

delivery_settings = AppSettings(
    "STAPEL_DELIVERY",
    defaults=DEFAULTS,
    resolvers={"DEFAULT_CARRIER": "stapel_delivery.carriers.resolve_carrier"},
    env_enum={"DEFAULT_CARRIER": "stapel_delivery.carriers.carrier_names"},
)

__all__ = ["delivery_settings", "DEFAULTS"]
