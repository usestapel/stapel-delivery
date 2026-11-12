"""The settings fragment that wires stapel-delivery into stapel-orders.

Plain data, importable without Django settings. Installing delivery next to
orders needs exactly this in ``STAPEL_ORDERS``, merged two levels deep so
the host's own keys and other companions' entries stay:

    from stapel_delivery.preset import SETTINGS_DEFAULTS as _DELIVERY

    STAPEL_ORDERS = globals().get("STAPEL_ORDERS") or {}
    STAPEL_ORDERS = {
        **STAPEL_ORDERS,
        "ADJUSTERS": {**_DELIVERY["STAPEL_ORDERS"]["ADJUSTERS"], **STAPEL_ORDERS.get("ADJUSTERS", {})},
        "CHECKOUT_HOOKS": {**_DELIVERY["STAPEL_ORDERS"]["CHECKOUT_HOOKS"],
                           **STAPEL_ORDERS.get("CHECKOUT_HOOKS", {})},
    }

A scaffolded project adds ``"stapel_delivery.preset"`` to its
``_stapel_merge_preset_defaults(globals(), [...])`` list instead (README,
tested by ``tests/test_readme_wiring.py``); system check
``stapel_delivery.W003`` says when the fragment is missing.

Checkout hooks reserve in an explicit order — inventory 50 (stock first),
promotions 100, delivery 200 — and release in reverse.

Shipping runs at order 200: after discounts (100), so a promotion's
free-shipping marker is in ``adjustments_so_far``, and before tax (300).
"""

ADJUSTER_ORDER = 200
HOOK_ORDER = 200

SETTINGS_DEFAULTS = {
    "STAPEL_ORDERS": {
        "ADJUSTERS": {
            "delivery": {"quote": "delivery.quote", "order": ADJUSTER_ORDER},
        },
        "CHECKOUT_HOOKS": {
            "delivery": {
                "reserve": "delivery.reserve",
                "commit": "delivery.commit",
                "release": "delivery.release",
                "order": HOOK_ORDER,
            },
        },
    },
}
