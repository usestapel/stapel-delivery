"""System checks, each with the case that must fire and the one that must not."""
import pytest
from django.core import checks

from stapel_delivery import checks as dl_checks
from stapel_delivery import preset
from stapel_delivery.models import DeliveryMethod


def ids(findings):
    return [f.id for f in findings]


class TestCarriers:
    def test_defaults_are_silent(self):
        assert dl_checks.check_carriers(None) == []

    def test_unknown_default_is_e001(self, settings):
        settings.STAPEL_DELIVERY = {"DEFAULT_CARRIER": "pigeon"}
        assert ids(dl_checks.check_carriers(None)) == ["stapel_delivery.E001"]

    def test_bad_registry_is_e001(self, settings):
        settings.STAPEL_DELIVERY = {"CARRIERS": ["mock"]}
        assert ids(dl_checks.check_carriers(None)) == ["stapel_delivery.E001"]

    def test_unimportable_entry_is_e001(self, settings):
        settings.STAPEL_DELIVERY = {"CARRIERS": {"x": "no.such.Carrier"}}
        assert ids(dl_checks.check_carriers(None)) == ["stapel_delivery.E001"]


@pytest.mark.django_db
class TestMockPosture:
    def test_manual_is_silent(self):
        assert dl_checks.check_mock_carrier(None) == []

    def test_mock_default_without_posture_is_e002(self, settings):
        settings.STAPEL_DELIVERY = {"DEFAULT_CARRIER": "mock"}
        findings = dl_checks.check_mock_carrier(None)
        assert ids(findings) == ["stapel_delivery.E002"] and isinstance(findings[0], checks.Error)

    def test_mock_method_in_live_stage_is_e002_under_the_database_tag(self, settings):
        DeliveryMethod.objects.create(code="m", name="m", carrier="mock")
        settings.STAPEL_POSTURE = {"PRESET": "public-space", "OPTIONS": {"stage": "live"}}
        assert dl_checks.check_mock_carrier(None) == []
        assert dl_checks.check_mock_methods(None) == []
        assert ids(dl_checks.check_mock_methods(None, databases=["default"])) == ["stapel_delivery.E002"]

    def test_mock_in_prototype_stage_is_w002(self, settings):
        settings.STAPEL_DELIVERY = {"DEFAULT_CARRIER": "mock"}
        settings.STAPEL_POSTURE = {"PRESET": "public-space", "OPTIONS": {"stage": "prototype"}}
        findings = dl_checks.check_mock_carrier(None)
        assert ids(findings) == ["stapel_delivery.W002"] and isinstance(findings[0], checks.Warning)


class TestOrdersWiring:
    def test_silent_without_orders_installed(self, settings):
        settings.STAPEL_ORDERS = {}
        assert dl_checks.check_orders_wiring(None) == []

    def test_orders_without_the_fragment_is_w003(self, settings, monkeypatch):
        monkeypatch.setattr(dl_checks, "_orders_installed", lambda: True)
        settings.STAPEL_ORDERS = {}
        assert ids(dl_checks.check_orders_wiring(None)) == ["stapel_delivery.W003"] * 2

    def test_orders_with_the_preset_fragment_is_silent(self, settings, monkeypatch):
        monkeypatch.setattr(dl_checks, "_orders_installed", lambda: True)
        settings.STAPEL_ORDERS = preset.SETTINGS_DEFAULTS["STAPEL_ORDERS"]
        assert dl_checks.check_orders_wiring(None) == []

    def test_detection_asks_the_orders_function(self):
        from stapel_core.comm import function_registry, register_function

        assert dl_checks._orders_installed() is False
        register_function(dl_checks.ORDERS_PROBE_FUNCTION, lambda payload: {})
        try:
            assert dl_checks._orders_installed() is True
        finally:
            function_registry._providers.pop(dl_checks.ORDERS_PROBE_FUNCTION, None)
            function_registry._schemas.pop(dl_checks.ORDERS_PROBE_FUNCTION, None)


class TestGeocoder:
    def test_off_is_silent(self):
        assert dl_checks.check_geocoder(None) == []

    def test_unreachable_is_w004(self, settings):
        settings.STAPEL_DELIVERY = {"GEOCODE_FUNCTION": "geo.geocode"}
        assert ids(dl_checks.check_geocoder(None)) == ["stapel_delivery.W004"]


@pytest.mark.django_db
def test_manage_check_is_clean_at_error_level():
    """Django's own JSONField check asks the connection, hence the db mark."""
    from django.core.management import call_command

    call_command("check", "--fail-level", "ERROR")
