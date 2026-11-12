"""Root URLconf for stapel-delivery — v1 canon mount.

The host mounts the module under ``delivery/api/``; this module contributes
the ``v1/`` segment:

    path("delivery/api/", include("stapel_delivery.urls"))   # -> /delivery/api/v1/...
"""
from django.urls import include, path

from stapel_delivery.urls_v1 import GATE_REGISTRY  # noqa: F401  (re-export)

urlpatterns = [
    path("v1/", include("stapel_delivery.urls_v1")),
]
