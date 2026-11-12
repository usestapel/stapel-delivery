"""``user.merged``: the guest's book, shipments and intents follow it."""
import pytest
from stapel_core.comm import emit, mutate_and_emit

from stapel_delivery.models import Address, Shipment

from .factories import HOME
from .shipping import make_shipment

pytestmark = pytest.mark.django_db


def merged(frm, into):
    with mutate_and_emit():
        emit("user.merged", {"from_user_id": str(frm), "into_user_id": str(into)})


def test_guest_rows_follow_and_the_survivor_default_wins(user, guest, catalog):
    mine = Address.objects.create(user_id=str(user.pk), is_default=True, **HOME)
    theirs = Address.objects.create(user_id=str(guest.pk), is_default=True, **HOME)
    make_shipment(guest.pk, order_id="g1")
    merged(guest.pk, user.pk)
    assert Address.objects.filter(user_id=str(user.pk)).count() == 2
    assert Address.objects.get(pk=mine.pk).is_default and not Address.objects.get(pk=theirs.pk).is_default
    assert Shipment.objects.get(order_id="g1").user_id == str(user.pk)
    merged(guest.pk, user.pk)
    assert Address.objects.filter(user_id=str(user.pk), is_default=True).count() == 1


def test_guest_default_survives_when_the_account_has_none(user, guest):
    a = Address.objects.create(user_id=str(guest.pk), is_default=True, **HOME)
    merged(guest.pk, user.pk)
    assert Address.objects.get(pk=a.pk).is_default


def test_self_merge_is_a_no_op(user):
    Address.objects.create(user_id=str(user.pk), is_default=True, **HOME)
    merged(user.pk, user.pk)
    assert Address.objects.get().is_default
