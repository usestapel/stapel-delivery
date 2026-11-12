"""delivery against the orders seam as orders' own schemas define it (see ``orders_seam``)."""
import pytest
from stapel_core.comm import call

from stapel_delivery.models import DeliveryIntent, Shipment
from stapel_delivery.preset import SETTINGS_DEFAULTS

from .factories import HOME
from .orders_seam import GUEST, check_request, check_result, line, quote_request, run_hook

pytestmark = pytest.mark.django_db

ADJUSTER = SETTINGS_DEFAULTS["STAPEL_ORDERS"]["ADJUSTERS"]["delivery"]["quote"]
HOOK = SETTINGS_DEFAULTS["STAPEL_ORDERS"]["CHECKOUT_HOOKS"]["delivery"]


@pytest.mark.parametrize("user_id,actor_id", [(None, GUEST), ("7", "7")], ids=["guest", "account"])
def test_quote_reserve_commit_release_as_orders_sends_them(catalog, user_id, actor_id):
    request = quote_request([line()], {"delivery": {"method": "courier", "address": HOME}},
                            user_id=user_id, actor_id=actor_id)
    check_request("adjusters", ADJUSTER, request)
    answer = call(ADJUSTER, request)
    check_result("adjusters", answer)
    assert answer["errors"] == [] and answer["adjustments"][0]["code"] == "courier"
    run_hook(HOOK, request, adjuster_answer=answer["adjustments"], adjuster="delivery")
    assert DeliveryIntent.objects.get().user_id == actor_id
    assert (Shipment.objects.get().user_id, Shipment.objects.get().status) == (actor_id, "cancelled")
