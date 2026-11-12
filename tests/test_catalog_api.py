"""Public catalog reads: methods, options, pickup points."""
from decimal import Decimal

import pytest

from stapel_delivery.models import Address, PickupPoint, Rate

from .factories import HOME

pytestmark = pytest.mark.django_db
V1 = "/delivery/api/v1"


def options(client, **body):
    payload = {"currency": "USD", "subtotal": "20.00",
               "lines": [{"purchasable_type": "listing", "purchasable_key": "a", "quantity": 1}], **body}
    r = client.post(f"{V1}/options/", payload, format="json")
    assert r.status_code == 200, r.content
    return {o["code"]: o for o in r.json()["options"]}


def test_methods_are_public_and_sorted(api_client, catalog):
    catalog.digital.enabled = False
    catalog.digital.save()
    body = api_client.get(f"{V1}/methods/").json()
    assert [m["code"] for m in body["items"]] == ["courier", "pickup"]


def test_options_without_address(api_client, catalog):
    opts = options(api_client)
    assert opts["courier"]["available"] is False
    assert opts["courier"]["reason"] == "error.400.delivery_address_required"
    assert (opts["pickup"]["available"], opts["pickup"]["price"]) == (True, "2.00")
    assert opts["email"]["price"] == "0.00"


def test_options_for_a_destination(api_client, catalog):
    opts = options(api_client, address={"country": "US", "postal_code": "62704"})
    assert opts["courier"]["price"] == "5.00"
    opts = options(api_client, address={"country": "DE"})
    assert opts["courier"]["available"] is False
    assert opts["courier"]["reason"] == "error.409.delivery_unavailable"
    assert opts["pickup"]["available"] is False


def test_options_free_threshold(api_client, catalog):
    opts = options(api_client, subtotal="150.00", address={"country": "US"})
    assert (opts["courier"]["price"], opts["courier"]["free_reason"]) == ("0.00", "threshold")


def test_options_from_my_address_book(auth_client, user, catalog):
    a = Address.objects.create(user_id=str(user.pk), **HOME)
    assert options(auth_client, address_id=a.pk)["courier"]["price"] == "5.00"


def test_options_pickup_minimum_flag(api_client, catalog):
    other = PickupPoint.objects.create(method=catalog.pickup, code="pp-2", name="Far", line1="x", city="Y",
                                       country="US", postal_code="99999")
    Rate.objects.create(method=catalog.pickup, zone=catalog.metro, currency="USD", amount=Decimal("1.00"))
    opts = options(api_client)
    assert opts["pickup"]["price"] == "1.00" and opts["pickup"]["price_is_minimum"] is True
    assert other.pk


def test_pickup_points_filter_and_page(api_client, catalog):
    for i in range(3):
        PickupPoint.objects.create(method=catalog.pickup, code=f"pp-x{i}", name=f"P{i}", line1="x",
                                   city="Capital", country="US")
    PickupPoint.objects.create(method=catalog.pickup, code="pp-off", name="Off", line1="x",
                               city="Capital", country="US", enabled=False)
    body = api_client.get(f"{V1}/pickup-points/?city=capital&limit=2").json()
    assert body["count"] == 2 and body["has_next"] is True
    nxt = api_client.get(f"{V1}/pickup-points/?city=capital&limit=2&anchor={body['next_anchor']}").json()
    assert [p["code"] for p in nxt["items"]] == ["pp-x2"]
    one = api_client.get(f"{V1}/pickup-points/?method=pickup&country=us&city=Springfield").json()
    assert one["items"][0]["hours"][0] == {"weekday": 0, "opens": "09:00", "closes": "20:00"}
    assert api_client.get(f"{V1}/pickup-points/?anchor=garbage").status_code == 200
