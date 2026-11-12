"""The beat schedule and the housekeeping passes."""
import datetime as dt

import pytest
from django.core.management import call_command
from django.utils import timezone

from stapel_delivery import beat
from stapel_delivery.models import DeliveryIntent
from stapel_delivery.services.housekeeping import purge_intents

from .factories import HOME, reserve_request
from .shipping import make_shipment


def test_schedule_names_both_tasks():
    schedule = beat.get_delivery_beat_schedule()
    assert {e["task"] for e in schedule.values()} == {beat.POLL_TASK_NAME, beat.PURGE_TASK_NAME}


@pytest.mark.django_db
def test_purge_keeps_committed_and_fresh_intents(catalog):
    from stapel_delivery.services import checkout

    make_shipment(order_id="keep")
    stale = reserve_request(delivery={"method": "courier", "address": HOME})
    checkout.reserve(stale)
    fresh = reserve_request(delivery={"method": "courier", "address": HOME})
    checkout.reserve(fresh)
    old = timezone.now() - dt.timedelta(hours=100)
    DeliveryIntent.objects.filter(attempt_key=stale["attempt_key"]).update(updated_at=old)
    DeliveryIntent.objects.filter(order_id="keep").update(updated_at=old)
    assert purge_intents() == 1
    assert DeliveryIntent.objects.count() == 2


@pytest.mark.django_db
def test_management_command_runs_both_passes(catalog, capsys):
    call_command("delivery_housekeeping")
    assert "carrier update" in capsys.readouterr().out
