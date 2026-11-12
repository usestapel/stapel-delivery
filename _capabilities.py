"""stapel-delivery capabilities.json emitter — thin shim over stapel_tools.capabilities."""
from pathlib import Path

from stapel_tools.capabilities import axis_group_rules, run_capabilities_cli


def main(argv=None):
    from stapel_delivery._codegen import _configure

    _configure()
    from stapel_delivery.conf import DEFAULTS
    from stapel_delivery.urls import GATE_REGISTRY

    # Two CTO-facing axes, both behavioural (no endpoint is unmounted):
    # REQUIRE_METHOD (must the buyer choose a delivery) and DEFAULT_CARRIER
    # (manual | mock | a registered carrier). CARRIERS is the extension seam.
    axes = {"REQUIRE_METHOD", "DEFAULT_CARRIER"}
    return run_capabilities_cli(
        argv,
        repo=Path(__file__).resolve().parent,
        canonical_prefix="/delivery/api/v1",
        defaults=DEFAULTS,
        registry=GATE_REGISTRY,
        is_axis=lambda k: k in axes,
        axis_group=axis_group_rules(
            exact={
                "REQUIRE_METHOD": "delivery.checkout",
                "DEFAULT_CARRIER": "delivery.carrier",
            }
        ),
        prog="stapel-delivery-capabilities",
    )


if __name__ == "__main__":
    raise SystemExit(main())
