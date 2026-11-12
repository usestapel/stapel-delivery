"""The shipment FSM table, walked over every pair of statuses and actors."""
import itertools

import pytest

from stapel_delivery import fsm
from stapel_delivery.models import Shipment, ShipmentEvent, ShipmentStatus
from stapel_delivery.services import DeliveryError
from stapel_delivery.services.shipments import transition

from .shipping import make_shipment

STATUSES = list(ShipmentStatus.values)
LEGAL = {
    ("pending", "packed"), ("pending", "shipped"), ("packed", "shipped"), ("shipped", "delivered"),
    ("shipped", "returned"), ("delivered", "returned"), ("pending", "cancelled"), ("packed", "cancelled"),
}


def test_the_table_is_exactly_the_documented_graph():
    assert {(a, b) for a, b in fsm.TRANSITIONS} == LEGAL


@pytest.mark.parametrize("src,dst", list(itertools.product(STATUSES, STATUSES)))
def test_every_edge_for_staff(src, dst):
    assert fsm.allowed(src, dst, fsm.STAFF) == ((src, dst) in LEGAL)


def test_system_only_cancels_what_has_not_left():
    system = {(a, b) for a, b in itertools.product(STATUSES, STATUSES) if fsm.allowed(a, b, fsm.SYSTEM)}
    assert system == {("pending", "cancelled"), ("packed", "cancelled")}


def test_terminal_statuses_have_no_way_out():
    for status in fsm.TERMINAL:
        assert not any(fsm.allowed(status, dst, actor) for dst in STATUSES for actor in fsm.ACTORS)


def test_next_forward_is_the_happy_path():
    assert [fsm.next_forward(s) for s in ("pending", "packed", "shipped", "delivered")] == [
        "packed", "shipped", "delivered", None]


@pytest.mark.django_db
class TestService:
    def test_illegal_edge_is_409_and_writes_nothing(self, catalog):
        s = make_shipment()
        with pytest.raises(DeliveryError) as exc:
            transition(s.pk, "delivered", actor=fsm.STAFF)
        assert exc.value.status == 409 and exc.value.params == {"from": "pending", "to": "delivered"}
        assert Shipment.objects.get().status == "pending"
        assert ShipmentEvent.objects.count() == 1

    def test_walk_records_timestamps_and_steps(self, catalog, captured_events):
        s = make_shipment()
        for target in ("packed", "shipped", "delivered", "returned"):
            transition(s.pk, target, actor=fsm.STAFF)
        s.refresh_from_db()
        assert s.shipped_at and s.delivered_at
        assert [e.to_status for e in s.events.all()] == ["pending", "packed", "shipped", "delivered", "returned"]
        moves = [(e.payload["from"], e.payload["to"]) for e in captured_events
                 if e.event_type == "delivery.shipment.status_changed"]
        assert moves[-1] == ("delivered", "returned")
