"""``manage.py delivery_housekeeping`` — the beat passes for hosts without Celery."""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Poll carriers and purge stale checkout intents (the stapel-delivery beat passes)."

    def handle(self, *args, **options):
        from stapel_delivery.beat import poll_carriers, purge_intents

        polled = poll_carriers()
        purged = purge_intents()
        self.stdout.write(f"delivery: {polled} carrier update(s), {purged} intent(s) purged")
