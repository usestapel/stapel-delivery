"""The housekeeping schedule — shipped by the library.

Wire it in the settings module itself::

    from stapel_delivery.beat import get_delivery_beat_schedule

    CELERY_BEAT_SCHEDULE = {**get_delivery_beat_schedule(), ...}

Two passes: carrier polling (every minute; the mock carrier advances here)
and the purge of stale checkout intents (hourly). Imports nothing Django at
module level, so it is safe from a settings module. Celery is optional:
``manage.py delivery_housekeeping`` runs the same passes from any scheduler.
"""
from __future__ import annotations

POLL_TASK_NAME = "stapel_delivery.beat.poll_carriers"
PURGE_TASK_NAME = "stapel_delivery.beat.purge_intents"

POLL_BEAT_KEY = "delivery-poll-carriers"
PURGE_BEAT_KEY = "delivery-purge-intents"

POLL_INTERVAL_SECONDS = 60
PURGE_INTERVAL_SECONDS = 60 * 60


def poll_carriers() -> int:
    """One carrier poll pass. A plain callable for hosts without Celery."""
    from .services.shipments import poll_carriers as _poll

    return _poll()


def purge_intents() -> int:
    """Reserved/released intents older than INTENT_TTL_HOURS are deleted."""
    from .services.housekeeping import purge_intents as _purge

    return _purge()


def get_delivery_beat_schedule() -> dict:
    """Beat entries for the two passes. Add to ``CELERY_BEAT_SCHEDULE``."""
    return {
        POLL_BEAT_KEY: {"task": POLL_TASK_NAME, "schedule": float(POLL_INTERVAL_SECONDS)},
        PURGE_BEAT_KEY: {"task": PURGE_TASK_NAME, "schedule": float(PURGE_INTERVAL_SECONDS)},
    }


try:  # pragma: no cover - exercised by whichever profile the host installs
    from celery import shared_task
except ImportError:
    pass
else:
    poll_carriers = shared_task(name=POLL_TASK_NAME)(poll_carriers)
    purge_intents = shared_task(name=PURGE_TASK_NAME)(purge_intents)


__all__ = [
    "POLL_BEAT_KEY", "POLL_TASK_NAME", "PURGE_BEAT_KEY", "PURGE_TASK_NAME",
    "get_delivery_beat_schedule", "poll_carriers", "purge_intents",
]
