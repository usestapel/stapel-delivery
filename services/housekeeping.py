"""Housekeeping: stale checkout intents.

A reserved intent whose checkout never finished (orders releases orphans
after 900 s) and a released one are deleted after ``INTENT_TTL_HOURS``.
Committed intents stay: they are the link from an order to its shipment.
"""
from __future__ import annotations

import datetime as dt

from django.utils import timezone

from ..models import DeliveryIntent, IntentStatus


def purge_intents(hours: int | None = None, now: dt.datetime | None = None) -> int:
    from ..conf import delivery_settings

    hours = int(hours if hours is not None else delivery_settings.INTENT_TTL_HOURS)
    now = now or timezone.now()
    removed, _ = DeliveryIntent.objects.filter(
        status__in=(IntentStatus.RESERVED, IntentStatus.RELEASED),
        updated_at__lt=now - dt.timedelta(hours=hours),
    ).delete()
    return removed
