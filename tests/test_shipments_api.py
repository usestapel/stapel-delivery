"""Buyer tracking and staff operations over HTTP."""
import pytest
from stapel_core.comm import call

from stapel_delivery.models import Shipment

from .factories import HOME, reserve_request
from .shipping import make_shipment

pytestmark = pytest.mark.django_db
V1 = "/delivery/api/v1"


def ship(user, order_id="1", method="courier"):
    delivery = {"method": method, "address": HOME} if method == "courier" else {
        "method": "pickup", "pickup_point": "pp-1"}
    req = reserve_request(user_id=str(user.pk), delivery=delivery)
    call("delivery.reserve", req)
    call("delivery.commit", {"attempt_key": req["attempt_key"], "token": None, "order_id": order_id,
                             "user_id": str(user.pk)})
    return Shipment.objects.get(order_id=order_id)


def test_my_shipments_page_and_filter(auth_client, user, other_user, catalog):
    for i in range(3):
        ship(user, order_id=str(i))
    ship(other_user, order_id="theirs")
    body = auth_client.get(f"{V1}/shipments/?limit=2").json()
    assert body["count"] == 2 and body["has_next"] is True
    assert {s["order_id"] for s in body["items"]} == {"2", "1"}
    assert auth_client.get(f"{V1}/shipments/?order_id=0").json()["items"][0]["order_id"] == "0"
    assert auth_client.get(f"{V1}/shipments/?order_id=theirs").json()["items"] == []
    assert auth_client.get(f"{V1}/shipments/?status=delivered").json()["items"] == []


def test_track_one_with_timeline(auth_client, user, catalog):
    s = ship(user)
    body = auth_client.get(f"{V1}/shipments/{s.pk}/").json()
    assert body["status"] == "pending" and body["recipient"]["line1"] == HOME["line1"]
    assert body["pickup_point"] is None
    assert body["events"] == [{"from_status": None, "to_status": "pending", "actor": "system",
                               "note": "", "location": "", "occurred_at": body["events"][0]["occurred_at"]}]


def test_pickup_shipment_shows_the_point(auth_client, user, catalog):
    s = ship(user, method="pickup")
    body = auth_client.get(f"{V1}/shipments/{s.pk}/").json()
    assert body["recipient"] is None and body["pickup_point"]["code"] == "pp-1"


def test_foreign_shipment_is_404_even_for_staff(auth_client, client_for, other_user, staff, catalog):
    s = ship(other_user)
    for client in (auth_client, client_for(staff)):
        r = client.get(f"{V1}/shipments/{s.pk}/")
        assert r.status_code == 404 and r.json()["localizable_error"] == "error.404.shipment_not_found"


def test_staff_endpoints_refuse_buyers(auth_client, user, catalog):
    s = ship(user)
    assert auth_client.get(f"{V1}/staff/shipments/").status_code == 403
    assert auth_client.post(f"{V1}/staff/shipments/{s.pk}/transition/", {"to": "packed"},
                            format="json").status_code == 403


def test_staff_fulfil(client_for, staff, user, catalog, captured_events):
    s = ship(user)
    c = client_for(staff)
    assert c.get(f"{V1}/staff/shipments/?status=pending").json()["count"] == 1
    r = c.post(f"{V1}/staff/shipments/{s.pk}/tracking/", {"tracking_number": "TRK123"}, format="json")
    assert r.status_code == 200 and r.json()["tracking_url"] == "https://track.example/TRK123"
    r = c.post(f"{V1}/staff/shipments/{s.pk}/transition/", {"to": "shipped", "location": "Hub"},
               format="json")
    assert r.status_code == 200 and r.json()["shipped_at"]
    assert r.json()["events"][-1]["location"] == "Hub"
    changed = [e.payload for e in captured_events if e.event_type == "delivery.shipment.status_changed"]
    assert changed[-1]["tracking_number"] == "TRK123" and changed[-1]["to"] == "shipped"
    r = c.post(f"{V1}/staff/shipments/{s.pk}/transition/", {"to": "cancelled"}, format="json")
    assert r.status_code == 409 and r.json()["localizable_error"] == "error.409.shipment_transition_invalid"


def test_staff_tracking_unknown_carrier(client_for, staff, user, catalog):
    s = ship(user)
    r = client_for(staff).post(f"{V1}/staff/shipments/{s.pk}/tracking/",
                               {"tracking_number": "T", "carrier": "nope"}, format="json")
    assert r.status_code == 400


def test_staff_unknown_shipment(client_for, staff, catalog):
    r = client_for(staff).post(f"{V1}/staff/shipments/999/transition/", {"to": "packed"}, format="json")
    assert r.status_code == 404


def test_status_function(user, catalog):
    s = ship(user, order_id="77")
    by_order = call("delivery.shipment.status", {"order_id": "77"})
    assert by_order["found"] is True and by_order["number"] == s.number
    assert call("delivery.shipment.status", {"shipment_id": s.pk})["status"] == "pending"
    assert call("delivery.shipment.status", {"order_id": "none"}) == {"found": False}
    assert "line1" not in by_order


class TestAllowedTransitions:
    """The UI reads what the caller may do now instead of mirroring the FSM table."""

    def test_staff_sees_the_fsm_targets_of_the_current_status(self, catalog, client_for, staff, user):
        c = client_for(staff)
        shipment = make_shipment(user.pk, order_id="t1")
        assert c.get(f"{V1}/staff/shipments/").json()["items"][0]["allowed_transitions"] == [
            "packed", "shipped", "cancelled"]
        moved = c.post(f"{V1}/staff/shipments/{shipment.pk}/transition/", {"to": "shipped"}, format="json")
        assert moved.json()["allowed_transitions"] == ["delivered", "returned"]
        moved = c.post(f"{V1}/staff/shipments/{shipment.pk}/transition/", {"to": "returned"}, format="json")
        assert moved.json()["allowed_transitions"] == []

    def test_a_buyer_may_move_nothing(self, catalog, auth_client, user):
        shipment = make_shipment(user.pk, order_id="t2")
        assert auth_client.get(f"{V1}/shipments/{shipment.pk}/").json()["allowed_transitions"] == []
        assert auth_client.get(f"{V1}/shipments/").json()["items"][0]["allowed_transitions"] == []


class TestStaffDetail:
    def test_staff_opens_any_shipment(self, catalog, client_for, staff, user):
        shipment = make_shipment(user.pk, order_id="d1")
        body = client_for(staff).get(f"{V1}/staff/shipments/{shipment.pk}/").json()
        assert (body["order_id"], body["allowed_transitions"]) == ("d1", ["packed", "shipped", "cancelled"])
        assert body["events"][0]["to_status"] == "pending"

    def test_unknown_is_404_and_a_buyer_is_refused(self, catalog, client_for, staff, user):
        shipment = make_shipment(user.pk, order_id="d2")
        missing = client_for(staff).get(f"{V1}/staff/shipments/999999/")
        assert missing.status_code == 404
        assert missing.json()["localizable_error"] == "error.404.shipment_not_found"
        assert client_for(user).get(f"{V1}/staff/shipments/{shipment.pk}/").status_code == 403
