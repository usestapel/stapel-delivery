"""The SETTINGS_DEFAULTS fragment: Django-free, and the contract orders reads."""
import os
import subprocess
import sys

from stapel_delivery import preset


def test_fragment_registers_the_adjuster_and_the_hook():
    orders = preset.SETTINGS_DEFAULTS["STAPEL_ORDERS"]
    assert orders["ADJUSTERS"] == {"delivery": {"quote": "delivery.quote", "order": 200}}
    assert orders["CHECKOUT_HOOKS"] == {"delivery": {
        "reserve": "delivery.reserve", "commit": "delivery.commit", "release": "delivery.release",
        "order": 200}}


def test_every_named_function_is_registered():
    from stapel_core.comm import function_unreachable_reason

    orders = preset.SETTINGS_DEFAULTS["STAPEL_ORDERS"]
    names = [orders["ADJUSTERS"]["delivery"]["quote"],
             *(v for k, v in orders["CHECKOUT_HOOKS"]["delivery"].items() if k != "order")]
    assert [n for n in names if function_unreachable_reason(n)] == []


def test_shipping_runs_after_discounts_and_before_tax():
    assert 100 < preset.ADJUSTER_ORDER < 300


def test_preset_import_is_django_free():
    env = {k: v for k, v in os.environ.items() if k != "DJANGO_SETTINGS_MODULE"}
    code = (
        "import sys\n"
        "from stapel_delivery import preset\n"
        'assert not [m for m in sys.modules if m == "django" or m.startswith("django.")]\n'
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env,
                            cwd=os.path.dirname(sys.executable))
    assert result.returncode == 0, result.stderr
