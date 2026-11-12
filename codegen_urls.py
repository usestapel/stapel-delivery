"""Canonical-prefix URLconf for contract emission: the documented host mount."""
from django.urls import include, path

urlpatterns = [
    path("delivery/api/", include("stapel_delivery.urls")),
]
