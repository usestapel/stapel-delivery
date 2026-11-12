"""The address book over HTTP: owner scope, default flag, cap, validation."""
import pytest

from stapel_delivery.models import Address

from .factories import HOME

pytestmark = pytest.mark.django_db
V1 = "/delivery/api/v1"


def add(client, **over):
    return client.post(f"{V1}/addresses/", {**HOME, **over}, format="json")


def test_anonymous_is_refused(api_client):
    assert api_client.get(f"{V1}/addresses/").status_code in (401, 403)


def test_first_address_becomes_default(auth_client):
    r = add(auth_client, label="Home")
    assert r.status_code == 201, r.content
    assert r.json()["is_default"] is True and r.json()["country"] == "US"


def test_country_is_upper_cased(auth_client):
    assert add(auth_client, country="us").json()["country"] == "US"


def test_one_default_moves(auth_client, user):
    first = add(auth_client).json()
    second = add(auth_client, is_default=True).json()
    assert second["is_default"] is True
    assert Address.objects.get(pk=first["id"]).is_default is False
    r = auth_client.post(f"{V1}/addresses/{first['id']}/default/")
    assert r.status_code == 200 and r.json()["is_default"] is True
    assert Address.objects.filter(user_id=str(user.pk), is_default=True).count() == 1


def test_list_is_default_first_and_bounded(auth_client, settings):
    settings.STAPEL_DELIVERY = {"MAX_ADDRESSES": 2}
    add(auth_client)
    add(auth_client, label="Office")
    body = auth_client.get(f"{V1}/addresses/").json()
    assert body["count"] == 2 and body["max"] == 2 and body["items"][0]["is_default"] is True
    r = add(auth_client, label="Third")
    assert r.status_code == 409 and r.json()["localizable_error"] == "error.409.too_many_addresses"


def test_patch_and_delete_promotes_a_new_default(auth_client, user):
    first = add(auth_client).json()
    second = add(auth_client, label="Office").json()
    r = auth_client.patch(f"{V1}/addresses/{second['id']}/", {"city": "Shelbyville"}, format="json")
    assert r.status_code == 200 and r.json()["city"] == "Shelbyville"
    assert auth_client.delete(f"{V1}/addresses/{first['id']}/").status_code == 204
    assert Address.objects.get(pk=second["id"]).is_default is True


def test_patch_that_moves_the_address_drops_old_coordinates(auth_client):
    a = add(auth_client, latitude="10.000000", longitude="20.000000").json()
    r = auth_client.patch(f"{V1}/addresses/{a['id']}/", {"line1": "2 Main St"}, format="json")
    assert r.json()["latitude"] is None


def test_foreign_address_is_404_like_absent(auth_client, client_for, other_user):
    theirs = add(client_for(other_user)).json()
    for method, path in (("get", ""), ("patch", ""), ("delete", ""), ("post", "default/")):
        r = getattr(auth_client, method)(f"{V1}/addresses/{theirs['id']}/{path}", {}, format="json")
        assert r.status_code == 404, (method, r.content)
        assert r.json()["localizable_error"] == "error.404.address_not_found"
    assert auth_client.get(f"{V1}/addresses/999999/").status_code == 404


def test_guest_session_has_no_address_book(client_for, guest):
    """Orders sends user_id null for a guest, so a guest book could never be used."""
    assert add(client_for(guest)).status_code == 403
    assert client_for(guest).get(f"{V1}/addresses/").status_code == 403


@pytest.mark.parametrize("field,value", [("country", "USA"), ("phone", "x"), ("postal_code", "#1"),
                                         ("name", ""), ("latitude", "91")])
def test_validation(auth_client, field, value):
    over = {field: value}
    if field == "latitude":
        over["longitude"] = "0"
    assert add(auth_client, **over).status_code == 400


def test_coordinates_come_in_pairs(auth_client):
    assert add(auth_client, latitude="1.0").status_code == 400


class TestGeocoding:
    def test_off_by_default(self, auth_client):
        a = add(auth_client).json()
        assert a["latitude"] is None

    def test_named_function_fills_coordinates(self, auth_client, settings, django_capture_on_commit_callbacks):
        from stapel_core.comm import register_function

        calls = []

        def fake_geocode(payload):
            calls.append(payload)
            return {"type": "FeatureCollection", "lang": "en",
                    "features": [{"geometry": {"coordinates": [-89.65, 39.78]}}]}

        register_function("delivery_test.geocode", fake_geocode)
        settings.STAPEL_DELIVERY = {"GEOCODE_FUNCTION": "delivery_test.geocode"}
        with django_capture_on_commit_callbacks(execute=True):
            a = add(auth_client).json()
        row = Address.objects.get(pk=a["id"])
        assert (str(row.latitude), str(row.longitude)) == ("39.780000", "-89.650000")
        assert calls and "Springfield" in calls[0]["q"]

    def test_unreachable_geocoder_is_silent(self, auth_client, settings, django_capture_on_commit_callbacks):
        settings.STAPEL_DELIVERY = {"GEOCODE_FUNCTION": "nobody.geocode"}
        with django_capture_on_commit_callbacks(execute=True):
            a = add(auth_client).json()
        assert Address.objects.get(pk=a["id"]).latitude is None
