"""API endpoints for the explosives plugin.

Mounted by UrlsMixin under /plugin/explosives/. These require the global
ENABLE_PLUGINS_URL setting; if it is off the frontend panels will report that
rather than failing silently.
"""

from django.shortcuts import get_object_or_404

from rest_framework import permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from . import parameters
from .serializers import (
    BootstrapSerializer,
    LocationNEQSerializer,
    PartExplosiveSerializer,
)


class PluginView(APIView):
    """Base view holding a reference to the plugin instance.

    The plugin passes itself in via as_view(plugin=self) so that views can read
    plugin settings. Django's View.as_view() only accepts kwargs that already
    exist as class attributes, hence the declaration here.
    """

    plugin = None
    permission_classes = [permissions.IsAuthenticated]


class LocationNEQView(PluginView):
    """Total NEQ, licensed limit and contributing items for one location."""

    def get(self, request, pk: int):
        from stock.models import StockLocation

        location = get_object_or_404(StockLocation, pk=pk)
        summary = self.plugin.location_summary(location)

        return Response(LocationNEQSerializer(summary).data)


class LocationSummaryView(PluginView):
    """Every location with a licensed NEQ limit, worst utilisation first.

    Backs both the dashboard item and the magazine register report.
    """

    def get(self, request):
        summaries = self.plugin.licensed_locations()

        errors = parameters.config_errors()

        for summary in summaries:
            summary["config_errors"] = errors

        return Response(LocationNEQSerializer(summaries, many=True).data)


class PartExplosiveView(PluginView):
    """The explosive properties and data-integrity issues of one part."""

    def get(self, request, pk: int):
        from part.models import Part

        part = get_object_or_404(Part, pk=pk)

        return Response(PartExplosiveSerializer(self.plugin.part_context(part)).data)


class BootstrapView(PluginView):
    """Re-run the parameter template bootstrap.

    The manual repair path, for when the templates were not created at load time
    (e.g. the plugin was first loaded during a migration).
    """

    permission_classes = [permissions.IsAdminUser]

    def post(self, request):
        result = parameters.ensure_parameter_templates()

        return Response(BootstrapSerializer(result).data)
