"""Carrier registry, the manual default, the auto-advancing mock, a custom carrier."""
import datetime as dt

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.utils import timezone

from stapel_delivery import carriers
from stapel_delivery.carriers import Carrier, CarrierUpdate, Registration
from stapel_delivery.models import DeliveryMethod
from stapel_delivery.services.shipments import apply_carrier_update, poll_carriers

from .shipping import make_shipment

pytestmark = pytest.mark.django_db


class AcmeCarrier(Carrier):
    def register(self, shipment):
        return Registration(tracking_number=f"ACME{shipment.pk}")

    def tracking_url(self, shipment):
        return f"https://acme.example/t/{shipment.tracking_number}"


def test_builtins_and_default():
    assert carriers.carrier_names() == ("manual", "mock")
    assert carriers.default_carrier().slug == "manual"
    assert not carriers.default_carrier().polls
    assert carriers.get_carrier("mock").polls


def test_settings_registry_merges_and_removes(settings):
    settings.STAPEL_DELIVERY = {"CARRIERS": {"acme": "stapel_delivery.tests.test_carriers.AcmeCarrier",
                                             "mock": None}}
    assert carriers.carrier_names() == ("acme", "manual")
    assert carriers.get_carrier("acme").slug == "acme"


def test_runtime_registration():
    carriers.register_carrier("acme", AcmeCarrier)
    assert "acme" in carriers.carrier_names()


def test_unknown_default_carrier_is_improperly_configured(settings):
    settings.STAPEL_DELIVERY = {"DEFAULT_CARRIER": "pigeon"}
    with pytest.raises(ImproperlyConfigured):
        carriers.default_carrier()


def test_manual_carrier_assigns_nothing(catalog):
    s = make_shipment()
    assert s.carrier == "manual" and s.tracking_number == ""
    assert poll_carriers() == 0


def test_custom_carrier_registers_the_tracking_number(catalog):
    carriers.register_carrier("acme", AcmeCarrier)
    DeliveryMethod.objects.filter(code="courier").update(carrier="acme", tracking_url_template="")
    s = make_shipment()
    assert s.tracking_number == f"ACME{s.pk}"
    assert s.tracking_url == f"https://acme.example/t/ACME{s.pk}"


def test_mock_advances_one_step_per_interval(catalog, settings):
    settings.STAPEL_DELIVERY = {"DEFAULT_CARRIER": "mock", "MOCK_STEP_MINUTES": 2}
    s = make_shipment()
    assert s.tracking_number == f"MOCK-{s.number}"
    now = timezone.now()
    assert poll_carriers(now) == 0
    seen = []
    for step in range(1, 5):
        poll_carriers(now + dt.timedelta(minutes=3 * step))
        s.refresh_from_db()
        seen.append(s.status)
    assert seen == ["packed", "shipped", "delivered", "delivered"]
    assert {e.actor for e in s.events.exclude(from_status="")} == {"carrier"}


def test_stale_or_illegal_carrier_updates_are_ignored(catalog):
    s = make_shipment()
    assert apply_carrier_update(s, CarrierUpdate(status="pending")) is False
    assert apply_carrier_update(s, CarrierUpdate(status="delivered")) is False
    assert apply_carrier_update(s, CarrierUpdate(status="packed", location="Hub")) is True
    assert s.status == "packed" and s.events.last().location == "Hub"


def test_a_failing_carrier_poll_does_not_stop_the_pass(catalog):
    class Broken(Carrier):
        def poll(self, shipment, now):
            raise RuntimeError("carrier down")

    carriers.register_carrier("broken", Broken)
    DeliveryMethod.objects.filter(code="courier").update(carrier="broken")
    make_shipment()
    assert poll_carriers() == 0
