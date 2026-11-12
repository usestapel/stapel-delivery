"""Django system checks for stapel-delivery.

- E001  ``CARRIERS`` is malformed or ``DEFAULT_CARRIER`` names no carrier.
- E002 / W002  the ``mock`` carrier is in use outside / inside the
  prototype posture stage (``DEFAULT_CARRIER`` always; a method naming it
  under the database tag, i.e. ``check --database default`` and migrate).
- W003  stapel-orders is installed but ``STAPEL_ORDERS["ADJUSTERS"]`` does
  not name ``delivery.quote`` (or the hooks are missing): checkouts would
  ship for free and no address would reach the shipment.
- W004  ``GEOCODE_FUNCTION`` is set but not reachable on this transport.

Without stapel-orders installed W003 is silent: the module's own API and
Functions work on their own. Orders is detected by whether its ``orders.order.status``
Function is reachable, never by import or app label.
"""
from django.core import checks
from django.core.exceptions import ImproperlyConfigured

ADJUSTER_FUNCTION = "delivery.quote"
HOOK_FUNCTIONS = {"reserve": "delivery.reserve", "commit": "delivery.commit",
                  "release": "delivery.release"}


@checks.register(checks.Tags.compatibility)
def check_carriers(app_configs, **kwargs):
    from .carriers import _table
    from .conf import delivery_settings

    try:
        table = _table()
        delivery_settings.DEFAULT_CARRIER
    except ImproperlyConfigured as exc:
        return [checks.Error(str(exc), id="stapel_delivery.E001")]
    findings = []
    from .carriers import get_carrier

    for slug in sorted(table):
        try:
            get_carrier(slug)
        except ImproperlyConfigured as exc:
            findings.append(checks.Error(str(exc), id="stapel_delivery.E001"))
    return findings


@checks.register(checks.Tags.compatibility)
def check_mock_carrier(app_configs, **kwargs):
    from .carriers import uses_mock

    return _mock_findings(uses_mock())


@checks.register(checks.Tags.database)
def check_mock_methods(app_configs, databases=None, **kwargs):
    """The method-level half: runs only when checks may read the database."""
    from .carriers import uses_mock

    if not databases:
        return []
    return _mock_findings([w for w in uses_mock(methods=True) if w != "DEFAULT_CARRIER"])


def _mock_findings(where: list[str]) -> list:
    from stapel_core.django.presets import stage_finding

    if not where:
        return []
    finding = checks.Error(
        f"The mock delivery carrier is in use ({', '.join(where)}): shipments "
        "advance to delivered by themselves with no parcel moving.",
        hint="Use the manual carrier (the default) or a real one; the mock is "
             "for a prototype posture only.",
        id="stapel_delivery.E002",
    )
    return [stage_finding(finding, warning_id="stapel_delivery.W002")]


#: A Function stapel-orders provides; answering means orders is reachable.
ORDERS_PROBE_FUNCTION = "orders.order.status"


def _orders_installed() -> bool:
    from stapel_core.comm import function_unreachable_reason

    return not function_unreachable_reason(ORDERS_PROBE_FUNCTION)


def _names(entry, key: str) -> str:
    return str(entry.get(key) or "") if isinstance(entry, dict) else ""


@checks.register(checks.Tags.compatibility)
def check_orders_wiring(app_configs, **kwargs):
    if not _orders_installed():
        return []
    from django.conf import settings

    orders = getattr(settings, "STAPEL_ORDERS", None) or {}
    adjusters = orders.get("ADJUSTERS") or {}
    hooks = orders.get("CHECKOUT_HOOKS") or {}
    findings = []
    if not any(_names(e, "quote") == ADJUSTER_FUNCTION for e in adjusters.values()):
        findings.append(checks.Warning(
            "stapel-orders is installed but STAPEL_ORDERS['ADJUSTERS'] does not name "
            f"{ADJUSTER_FUNCTION!r}: checkouts carry no shipping line.",
            hint="Merge stapel_delivery.preset.SETTINGS_DEFAULTS['STAPEL_ORDERS'] into "
                 "STAPEL_ORDERS.",
            id="stapel_delivery.W003",
        ))
    if not any(all(_names(e, k) == fn for k, fn in HOOK_FUNCTIONS.items()) for e in hooks.values()):
        findings.append(checks.Warning(
            "stapel-orders is installed but STAPEL_ORDERS['CHECKOUT_HOOKS'] has no "
            "delivery.reserve/commit/release entry: the buyer's address never reaches a "
            "shipment.",
            hint="Merge stapel_delivery.preset.SETTINGS_DEFAULTS['STAPEL_ORDERS'] into "
                 "STAPEL_ORDERS.",
            id="stapel_delivery.W003",
        ))
    return findings


@checks.register(checks.Tags.compatibility)
def check_geocoder(app_configs, **kwargs):
    from stapel_core.comm import function_unreachable_reason

    from .conf import delivery_settings

    name = str(delivery_settings.GEOCODE_FUNCTION or "")
    if not name:
        return []
    reason = function_unreachable_reason(name)
    if not reason:
        return []
    return [checks.Warning(
        f"STAPEL_DELIVERY['GEOCODE_FUNCTION'] = {name!r} is not reachable here ({reason}); "
        "saved addresses keep no coordinates.",
        id="stapel_delivery.W004",
    )]
