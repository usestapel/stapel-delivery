"""``actor_id``: who owns a checkout's intent and shipment, a guest included.

Orders sends ``actor_id`` (always present: the guest's own id or the
account) next to ``user_id`` (null for a guest on the adjuster and hook payloads; the
``orders.order.placed`` fact keeps ``user_id`` = the acting account). Rows are
keyed by ``actor_id`` when present; payloads without it keep today's
behaviour (``user_id``, the lines-fingerprint fallback for the placed fact).
"""
import pytest
from stapel_core.comm import call, emit, mutate_and_emit

from stapel_delivery.gdpr import DeliveryGDPRProvider, erase_subject
from stapel_delivery.models import Address, DeliveryIntent, Shipment
from stapel_delivery.services import checkout

from .factories import HOME, placed_event, reserve_request

pytestmark = pytest.mark.django_db


def guest_checkout(guest, **kw):
    return reserve_request(delivery={"method": "courier", "address": HOME}, user_id=None,
                           **kw) | {"actor_id": str(guest.pk)}


def commit(req, order_id, **ids):
    return call("delivery.commit", {"attempt_key": req["attempt_key"], "token": None,
                                    "order_id": order_id, **ids})


def test_a_guest_owns_the_intent_and_the_shipment_from_reserve(catalog, guest, client_for):
    req = guest_checkout(guest)
    assert call("delivery.reserve", req)["ok"] is True
    assert DeliveryIntent.objects.get().user_id == str(guest.pk)
    commit(req, "801", user_id=None, actor_id=str(guest.pk))
    assert Shipment.objects.get().user_id == str(guest.pk)
    body = client_for(guest).get("/delivery/api/v1/shipments/").json()
    assert [s["order_id"] for s in body["items"]] == ["801"]


def test_the_placed_fact_names_the_guest_by_actor_id(catalog, guest):
    req = guest_checkout(guest)
    call("delivery.reserve", req)
    event = {**placed_event("802", req, user_id=guest.pk), "actor_id": str(guest.pk),
             "attempt_key": req["attempt_key"]}
    with mutate_and_emit():
        emit("orders.order.placed", event, key="802")
    assert Shipment.objects.get(order_id="802").user_id == str(guest.pk)


def test_no_fingerprint_guess_when_the_payload_names_the_actor(catalog, guest):
    req = guest_checkout(guest)
    call("delivery.reserve", req)
    event = {**placed_event("803", req, user_id=guest.pk), "actor_id": str(guest.pk)}
    assert checkout.order_placed(event) == "no_intent"


def test_payloads_without_actor_id_keep_the_fingerprint_fallback(catalog, guest):
    req = reserve_request(delivery={"method": "courier", "address": HOME}, user_id=None)
    call("delivery.reserve", req)
    assert checkout.order_placed(placed_event("807", req, user_id=guest.pk)) == "created"
    assert Shipment.objects.get().user_id == str(guest.pk)


def test_a_guest_has_no_address_book_even_with_an_actor_id(catalog, guest):
    Address.objects.create(user_id=str(guest.pk), **HOME)
    req = reserve_request(delivery={"method": "courier", "address_id": Address.objects.get().pk})
    answer = call("delivery.quote", {**req, "actor_id": str(guest.pk)})
    assert answer["errors"][0]["code"] == "error.404.address_not_found"


def test_user_merged_moves_the_guest_rows(catalog, guest, user):
    req = guest_checkout(guest)
    call("delivery.reserve", req)
    commit(req, "804", user_id=None, actor_id=str(guest.pk))
    with mutate_and_emit():
        emit("user.merged", {"from_user_id": str(guest.pk), "into_user_id": str(user.pk)})
    assert DeliveryIntent.objects.get().user_id == str(user.pk)
    assert Shipment.objects.get().user_id == str(user.pk)


def test_gdpr_covers_the_guest_rows(catalog, guest):
    req = guest_checkout(guest)
    call("delivery.reserve", req)
    commit(req, "805", user_id=None, actor_id=str(guest.pk))
    data = DeliveryGDPRProvider().export(guest.pk)
    assert [s["order_id"] for s in data["shipments"]] == ["805"]
    assert data["checkout_intents"][0]["recipient"]["line1"] == HOME["line1"]
    assert erase_subject("account", str(guest.pk)) == {"addresses": 0, "intents": 1, "shipments": 1}
    assert Shipment.objects.get().line1 == "erased"


def test_a_payload_without_actor_id_keeps_the_user_id_owner(catalog, user):
    req = reserve_request(delivery={"method": "courier", "address": HOME}, user_id=str(user.pk))
    call("delivery.reserve", req)
    commit(req, "806", user_id=str(user.pk))
    assert Shipment.objects.get().user_id == str(user.pk)
