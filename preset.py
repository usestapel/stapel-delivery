"""The settings fragment that wires stapel-delivery into stapel-orders.

Plain data, importable without Django settings. Installing delivery next to
orders needs exactly this in ``STAPEL_ORDERS`` (merged two levels deep, so a
host's own adjusters and hooks stay):

    from stapel_delivery import preset
    STAPEL_ORDERS = {
        **preset.SETTINGS_DEFAULTS["STAPEL_ORDERS"],
        # ... the host's own keys; for registries merge per key, e.g.
        # "ADJUSTERS": {**preset.SETTINGS_DEFAULTS["STAPEL_ORDERS"]["ADJUSTERS"], ...}
    }

The stapel-tools scaffold merges ``preset.SETTINGS_DEFAULTS`` for composites;
for a companion brick like this one a hand-wired host pastes it (system
check ``stapel_delivery.W003`` says when it is missing).

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
