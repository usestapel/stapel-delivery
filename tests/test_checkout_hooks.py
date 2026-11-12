"""The checkout hooks and the order facts, driven by a fake orders caller.

Payloads are the orders contract as built (wave spec §2 + CONTRACT-DELTAS
12-17): reserve = adjuster request + attempt_key; commit {attempt_key,
token|null, order_id, user_id|null}; release {attempt_key, token|null,
order_id|null, reason}; ``orders.order.placed`` as orders' own schema.
"""
import uuid

import pytest
from stapel_core.comm import call, emit, mutate_and_emit

from stapel_delivery.models import DeliveryIntent, IntentStatus, Shipment, ShipmentStatus
from stapel_delivery.services import checkout

from .factories import HOME, line, placed_event, reserve_request

pytestmark = pytest.mark.django_db


def courier(**kw):
    return reserve_request(delivery={"method": "courier", "address": HOME}, **kw)


def commit(attempt_key, order_id, user_id=None, token=None):
    return call("delivery.commit", {"attempt_key": attempt_key, "token": token, "order_id": order_id,
                                    "user_id": user_id})


def release(attempt_key, reason, order_id=None, token=None):
    return call("delivery.release", {"attempt_key": attempt_key, "token": token, "order_id": order_id,
                                     "reason": reason})


def emit_action(name, payload, key):
    """Deliver an orders fact the way orders does: inside mutate_and_emit."""
    with mutate_and_emit():
        emit(name, payload, key=key)


def placed(payload):
    emit_action("orders.order.placed", payload, key=payload["order_id"])


class TestReserve:
    def test_reserve_stores_the_snapshot_under_the_key(self, catalog, user):
        req = courier(user_id=str(user.pk))
        answer = call("delivery.reserve", req)
        assert answer["ok"] is True and answer["errors"] == [] and answer["token"].startswith("dl-")
        intent = DeliveryIntent.objects.get(attempt_key=req["attempt_key"])
        assert intent.recipient["line1"] == HOME["line1"]
        assert (intent.method_code, str(intent.amount), intent.status) == ("courier", "5.00", "reserved")

    def test_reserve_refuses_like_quote(self, catalog):
        answer = call("delivery.reserve", reserve_request())
        assert answer["ok"] is False and answer["token"] is None
        assert answer["errors"][0]["code"] == "error.400.delivery_method_required"
        assert not DeliveryIntent.objects.exists()

    def test_reserve_is_idempotent(self, catalog):
        req = courier()
        first = call("delivery.reserve", req)
        assert call("delivery.reserve", req) == first
        assert DeliveryIntent.objects.count() == 1

    def test_a_changed_choice_on_the_same_key_updates_the_intent(self, catalog):
        req = courier()
        call("delivery.reserve", req)
        req["context"]["delivery"] = {"method": "pickup", "pickup_point": "pp-1"}
        call("delivery.reserve", req)
        intent = DeliveryIntent.objects.get()
        assert intent.method_code == "pickup" and intent.pickup_point["code"] == "pp-1"
        assert intent.recipient == {}

    def test_reserve_after_release_reserves_anew(self, catalog):
        req = courier()
        call("delivery.reserve", req)
        release(req["attempt_key"], "checkout_failed")
        assert DeliveryIntent.objects.get().status == IntentStatus.RELEASED
        assert call("delivery.reserve", req)["ok"] is True
        assert DeliveryIntent.objects.get().status == IntentStatus.RESERVED

    def test_nothing_to_ship_reserves_nothing(self, catalog):
        answer = call("delivery.reserve", reserve_request(lines=[line(attrs={"shippable": False})]))
        assert answer == {"ok": True, "token": None, "errors": []}
        assert not DeliveryIntent.objects.exists()


class TestCommit:
    def test_commit_creates_the_shipment_with_the_snapshot(self, catalog, user, captured_events):
        req = courier(user_id=str(user.pk))
        token = call("delivery.reserve", req)["token"]
        assert commit(req["attempt_key"], "41", str(user.pk), token) == {"ok": True}
        shipment = Shipment.objects.get(order_id="41")
        assert (shipment.status, shipment.user_id, shipment.line1, str(shipment.amount)) == (
            "pending", str(user.pk), HOME["line1"], "5.00")
        assert [e.event_type for e in captured_events] == ["delivery.shipment.created"]
        assert "line1" not in captured_events[0].payload

    def test_commit_is_idempotent_and_token_optional(self, catalog):
        req = courier()
        call("delivery.reserve", req)
        commit(req["attempt_key"], "42")
        commit(req["attempt_key"], "42")
        assert Shipment.objects.filter(order_id="42").count() == 1

    def test_commit_of_an_unknown_key_is_ok(self, catalog):
        assert commit(str(uuid.uuid4()), "43") == {"ok": True}
        assert not Shipment.objects.exists()

    def test_digital_commit_creates_no_shipment(self, catalog):
        req = reserve_request(delivery={"method": "email"})
        call("delivery.reserve", req)
        commit(req["attempt_key"], "44")
        assert not Shipment.objects.exists()
        assert DeliveryIntent.objects.get().status == IntentStatus.COMMITTED

    def test_snapshot_semantics_editing_the_book_does_not_touch_the_shipment(self, catalog, user):
        from stapel_delivery.models import Address

        a = Address.objects.create(user_id=str(user.pk), **HOME)
        req = reserve_request(user_id=str(user.pk), delivery={"method": "courier", "address_id": a.pk})
        call("delivery.reserve", req)
        commit(req["attempt_key"], "45", str(user.pk))
        a.line1 = "99 Elsewhere"
        a.save()
        a.delete()
        assert Shipment.objects.get(order_id="45").line1 == HOME["line1"]


class TestRelease:
    def test_cancel_after_commit_cancels_the_pending_shipment(self, catalog, captured_events):
        req = courier()
        call("delivery.reserve", req)
        commit(req["attempt_key"], "50")
        assert release(req["attempt_key"], "cancelled", order_id="50") == {"ok": True}
        assert Shipment.objects.get(order_id="50").status == ShipmentStatus.CANCELLED
        assert captured_events[-1].payload["actor"] == "system"

    def test_cancel_after_shipping_leaves_the_shipment(self, catalog):
        from stapel_delivery import fsm
        from stapel_delivery.services.shipments import transition

        req = courier()
        call("delivery.reserve", req)
        commit(req["attempt_key"], "51")
        transition(Shipment.objects.get().pk, "shipped", actor=fsm.STAFF)
        release(req["attempt_key"], "cancelled", order_id="51")
        assert Shipment.objects.get().status == ShipmentStatus.SHIPPED

    def test_release_is_idempotent_and_tolerates_unknown_keys(self, catalog):
        req = courier()
        call("delivery.reserve", req)
        release(req["attempt_key"], "orphaned")
        release(req["attempt_key"], "orphaned")
        assert release(str(uuid.uuid4()), "checkout_failed") == {"ok": True}

    def test_order_status_changed_to_cancelled(self, catalog):
        req = courier()
        call("delivery.reserve", req)
        commit(req["attempt_key"], "52")
        emit_action("orders.order.status_changed",
                    {"order_id": "52", "user_id": "1", "from": "new", "to": "cancelled", "actor": "owner"},
                    key="52")
        assert Shipment.objects.get().status == ShipmentStatus.CANCELLED

    def test_other_status_changes_are_ignored(self, catalog):
        assert checkout.order_status_changed({"order_id": "x", "to": "confirmed"}) == "ignored"


class TestOrderPlaced:
    def test_placed_before_commit_finds_the_intent_by_fingerprint(self, catalog, user):
        req = courier(user_id=str(user.pk))
        call("delivery.reserve", req)
        placed(placed_event("60", req, user_id=user.pk))
        shipment = Shipment.objects.get(order_id="60")
        assert shipment.lines == [{"purchasable_type": "listing", "purchasable_key": "sku-1", "quantity": 1}]
        commit(req["attempt_key"], "60", str(user.pk))
        assert Shipment.objects.count() == 1

    def test_commit_then_placed_fills_lines_once(self, catalog, user):
        req = courier(user_id=str(user.pk))
        call("delivery.reserve", req)
        commit(req["attempt_key"], "61", str(user.pk))
        placed(placed_event("61", req, user_id=user.pk))
        placed(placed_event("61", req, user_id=user.pk))
        shipment = Shipment.objects.get(order_id="61")
        assert shipment.lines and Shipment.objects.count() == 1

    def test_guest_shipment_gets_the_guest_id_from_the_fact(self, catalog, guest):
        req = courier(user_id=None)
        call("delivery.reserve", req)
        commit(req["attempt_key"], "62", None)
        assert Shipment.objects.get().user_id == ""
        placed(placed_event("62", req, user_id=guest.pk))
        assert Shipment.objects.get().user_id == str(guest.pk)

    def test_placed_with_an_attempt_key_uses_it(self, catalog, user):
        req = courier(user_id=str(user.pk))
        call("delivery.reserve", req)
        event = {**placed_event("63", req, user_id=user.pk), "attempt_key": req["attempt_key"]}
        placed(event)
        assert Shipment.objects.filter(order_id="63").exists()

    def test_fingerprint_must_match_lines_and_user(self, catalog, user, other_user):
        req = courier(user_id=str(user.pk))
        call("delivery.reserve", req)
        assert checkout.order_placed(placed_event("64", req, user_id=other_user.pk)) == "no_intent"
        other = {**placed_event("64", req, user_id=user.pk)}
        other["lines"] = [{**other["lines"][0], "quantity": 2}]
        assert checkout.order_placed(other) == "no_intent"
        assert not Shipment.objects.exists()

    def test_a_released_intent_ships_nothing(self, catalog, user):
        req = courier(user_id=str(user.pk))
        call("delivery.reserve", req)
        release(req["attempt_key"], "checkout_failed")
        assert checkout.order_placed(placed_event("65", req, user_id=user.pk)) == "no_intent"

    def test_order_without_delivery_choice_logs_and_skips(self, catalog):
        req = reserve_request()
        assert checkout.order_placed(placed_event("66", req)) == "no_intent"
