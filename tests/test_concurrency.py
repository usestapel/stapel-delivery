"""The counters: one shipment per order, one default and MAX_ADDRESSES per user.

SQLite has no row locks (Django drops FOR UPDATE there), so threads cannot
prove the locks on this harness. What is proved:

1. the address book's rows are locked (``select_for_update`` on Address)
   BEFORE the cap is counted and the default moved (ordering spy);
2. the database constraints hold the line by themselves: a second default
   and a second shipment for one order are IntegrityErrors (inversion: the
   test inserts them raw);
3. two interleaved writers of one order's shipment (commit hook and the
   placed fact) end as one shipment: the rival commits after our existence
   check and before our insert; we land on the unique constraint and answer
   the rival's row.
On Postgres the lock makes step 1 the only possible interleaving.
"""
import pytest
from django.db import IntegrityError, transaction
from django.db.models import QuerySet

from stapel_delivery.models import Address, DeliveryIntent, Shipment
from stapel_delivery.services import addresses as address_service
from stapel_delivery.services import checkout
from stapel_delivery.services import shipments as shipment_service

from .factories import HOME, placed_event, reserve_request


@pytest.mark.django_db
def test_book_is_locked_before_the_cap_is_counted(user, monkeypatch):
    order = []
    real_sfu = QuerySet.select_for_update

    def sfu_spy(self, *a, **kw):
        order.append(f"lock:{self.model.__name__}")
        return real_sfu(self, *a, **kw)

    real_create = Address.objects.create

    def create_spy(**kw):
        order.append("insert")
        return real_create(**kw)

    monkeypatch.setattr(QuerySet, "select_for_update", sfu_spy)
    monkeypatch.setattr(Address.objects, "create", create_spy)
    address_service.create(str(user.pk), dict(HOME))
    assert order.index("lock:Address") < order.index("insert")


@pytest.mark.django_db
def test_second_default_is_refused_by_the_database(user):
    Address.objects.create(user_id=str(user.pk), is_default=True, **HOME)
    with pytest.raises(IntegrityError), transaction.atomic():
        Address.objects.create(user_id=str(user.pk), is_default=True, **HOME)


@pytest.mark.django_db
def test_second_shipment_for_an_order_is_refused_by_the_database(catalog):
    from .shipping import make_shipment

    s = make_shipment(order_id="o1")
    with pytest.raises(IntegrityError), transaction.atomic():
        Shipment.objects.create(number="20261112-ZZZZZZ", order_id="o1", user_id="1", method_code="c",
                                method_name="c", method_kind="courier", carrier="manual",
                                amount=s.amount, currency="USD")


@pytest.mark.django_db(transaction=True)
def test_interleaved_commit_and_placed_end_as_one_shipment(catalog, monkeypatch):
    req = reserve_request(user_id="1", delivery={"method": "courier", "address": HOME})
    checkout.reserve(req)
    intent = DeliveryIntent.objects.get()
    real_filter = Shipment.objects.filter
    state = {"raced": False}

    def racing_filter(*a, **kw):
        result = real_filter(*a, **kw)
        if kw.get("order_id") == "o2" and not state["raced"]:
            state["raced"] = True
            # The rival (the commit hook) creates the shipment right after our check.
            DeliveryIntent.objects.filter(pk=intent.pk).update(order_id="o2", status="committed")
            rival_intent = DeliveryIntent.objects.get(pk=intent.pk)
            from stapel_core.comm import mutate_and_emit

            with mutate_and_emit() as emit:
                monkeypatch.setattr(Shipment.objects, "filter", real_filter)
                shipment_service.create_from_intent(rival_intent, "o2", [], emit=emit)
                monkeypatch.setattr(Shipment.objects, "filter", racing_filter)
            return real_filter(pk__in=[])
        return result

    monkeypatch.setattr(Shipment.objects, "filter", racing_filter)
    outcome = checkout.order_placed(placed_event("o2", req, user_id="1"))
    monkeypatch.setattr(Shipment.objects, "filter", real_filter)
    assert state["raced"] and outcome in ("created", "exists")
    assert Shipment.objects.filter(order_id="o2").count() == 1
