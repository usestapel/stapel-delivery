"""Erasure keeps the economics and pseudonymizes the person."""
import pytest
from stapel_core.gdpr import gdpr_registry, registered_gdpr_owners

from stapel_delivery.gdpr import DeliveryGDPRProvider, erase_subject
from stapel_delivery.models import Address, DeliveryIntent, Shipment

from .factories import HOME
from .shipping import make_shipment

pytestmark = pytest.mark.django_db


def test_owner_and_provider_are_registered():
    assert registered_gdpr_owners()["delivery"] == ("account",)
    assert any(p.section == "delivery" for p in gdpr_registry.providers)


def test_export_has_the_book_and_the_shipments(user, catalog):
    Address.objects.create(user_id=str(user.pk), **HOME)
    make_shipment(user.pk)
    data = DeliveryGDPRProvider().export(user.pk)
    assert data["addresses"][0]["line1"] == HOME["line1"]
    assert data["shipments"][0]["recipient"]["phone"] == HOME["phone"]


def test_erase_keeps_money_and_pseudonymizes(user, catalog):
    Address.objects.create(user_id=str(user.pk), **HOME)
    s = make_shipment(user.pk)
    counts = erase_subject("account", str(user.pk))
    assert counts == {"addresses": 1, "intents": 1, "shipments": 1}
    s.refresh_from_db()
    assert s.user_id != str(user.pk) and str(s.amount) == "5.00"
    assert (s.recipient_name, s.recipient_phone, s.line1, s.line2, s.postal_code, s.region) == (
        "erased", "erased", "erased", "", "", "")
    assert (s.city, s.country) == (HOME["city"], HOME["country"])
    assert not Address.objects.exists() and not DeliveryIntent.objects.exists()
    assert erase_subject("account", str(user.pk)) == {"addresses": 0, "intents": 0, "shipments": 0}


def test_provider_delete_is_the_same_operation(user, catalog):
    make_shipment(user.pk)
    DeliveryGDPRProvider().delete(user.pk)
    assert not Shipment.objects.filter(user_id=str(user.pk)).exists()


def test_other_subject_types_are_not_ours():
    assert erase_subject("workspace", "1") is None
