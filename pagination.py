"""Anchor paginators (``ShipmentPage``, ``PickupPointPage``).

Both walk the id and declare the anchor as an opaque **string**, so the
page envelope is the same component shape for every list.
"""
from __future__ import annotations

from stapel_core.django.api.pagination import AnchorPagination


def _without_anchor(request, param):
    """A bad anchor reads as no anchor (the head of the list), never a 500."""

    class _Request:
        def __init__(self, inner):
            self._inner = inner
            self.query_params = inner.query_params.copy()
            self.query_params.pop(param, None)

        def __getattr__(self, name):
            return getattr(self._inner, name)

    return _Request(request)


class _IdAnchorPagination(AnchorPagination):
    anchor_field = "id"
    anchor_type = "string"

    def paginate_queryset(self, queryset, request, view=None):
        anchor = request.query_params.get(self.anchor_param)
        if anchor is not None and not anchor.isdigit():
            request = _without_anchor(request, self.anchor_param)
        return super().paginate_queryset(queryset, request, view)

    def get_paginated_response(self, data):
        response = super().get_paginated_response(data)
        for key in ("next_anchor", "prev_anchor"):
            if response.data[key] is not None:
                response.data[key] = str(response.data[key])
        return response


class ShipmentAnchorPagination(_IdAnchorPagination):
    """Shipments, newest first."""

    page_size = 20
    max_page_size = 100
    ordering = "-id"


class PickupPointAnchorPagination(_IdAnchorPagination):
    """Pickup points in id order (a stable walk; the map sorts client-side)."""

    page_size = 50
    max_page_size = 200
    ordering = "id"
