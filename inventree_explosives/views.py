"""API endpoints for the explosives plugin.

Mounted by UrlsMixin under /plugin/explosives/. These require the global
ENABLE_PLUGINS_URL setting; if it is off the frontend panels will report that
rather than failing silently.
"""

from typing import ClassVar

from django.core.exceptions import ValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import permissions
from rest_framework import serializers as drf_serializers
from rest_framework.response import Response
from rest_framework.views import APIView

from . import parameters
from .constants import (
    TPL_COMPAT,
    TPL_DIVISION,
    TPL_EXPLOSIVE,
    TPL_GROSS_MASS,
    TPL_MAX_NEQ,
    TPL_NEQ,
    TPL_PSN,
    TPL_UN_NUMBER,
)
from .serializers import (
    BootstrapSerializer,
    LocationLimitUpdateSerializer,
    LocationNEQSerializer,
    PartExplosiveSerializer,
    PartExplosiveUpdateSerializer,
    StatusSerializer,
)

# PATCH field -> the parameter template it writes. is_explosive is handled
# separately (it is a checkbox, set via set_explosive_flag).
_UPDATE_FIELD_TEMPLATES = {
    "neq_per_unit_kg": TPL_NEQ,
    "gross_mass_per_unit_kg": TPL_GROSS_MASS,
    "division": TPL_DIVISION,
    "compatibility_group": TPL_COMPAT,
    "un_number": TPL_UN_NUMBER,
    "proper_shipping_name": TPL_PSN,
}


def _as_api_error(exc: ValidationError) -> drf_serializers.ValidationError:
    """Convert a Django ValidationError into a DRF 400."""
    detail = exc.message_dict if hasattr(exc, "message_dict") else exc.messages
    return drf_serializers.ValidationError(detail)


def _missing_template_error(field: str, template_name: str):
    """400 for a write whose parameter template does not exist."""
    return drf_serializers.ValidationError({
        field: (
            f"Parameter template '{template_name}' is missing. "
            f"Use the plugin settings to re-run setup."
        )
    })


class PluginView(APIView):
    """Base view holding a reference to the plugin instance.

    The plugin passes itself in via as_view(plugin=self) so that views can read
    plugin settings. Django's View.as_view() only accepts kwargs that already
    exist as class attributes, hence the declaration here.
    """

    plugin = None
    permission_classes: ClassVar[list] = [permissions.IsAuthenticated]


class AdminWritesView(PluginView):
    """Anyone signed in may read; only an admin may write."""

    WRITE_METHODS = ("POST", "PATCH", "PUT", "DELETE")

    def get_permissions(self):
        if self.request.method in self.WRITE_METHODS:
            return [permissions.IsAdminUser()]
        return [permissions.IsAuthenticated()]


class LocationNEQView(AdminWritesView):
    """Total NEQ, licensed limit and contributing items for one location."""

    def get(self, request, pk: int):
        from stock.models import StockLocation

        location = get_object_or_404(StockLocation, pk=pk)
        summary = self.plugin.location_summary(location)

        return Response(LocationNEQSerializer(summary).data)

    def patch(self, request, pk: int):
        """Set the licensed NEQ limit; a blank value removes it."""
        from stock.models import StockLocation

        location = get_object_or_404(StockLocation, pk=pk)

        incoming = LocationLimitUpdateSerializer(data=request.data)
        incoming.is_valid(raise_exception=True)
        value = incoming.validated_data["limit_kg"].strip()

        if parameters.get_template(TPL_MAX_NEQ) is None:
            raise _missing_template_error("limit_kg", TPL_MAX_NEQ)

        try:
            if value == "":
                parameters.clear_parameter_value(location, TPL_MAX_NEQ)
            else:
                parameters.set_parameter_value(location, TPL_MAX_NEQ, value)
        except ValidationError as exc:
            raise drf_serializers.ValidationError({"limit_kg": exc.messages}) from exc

        return Response(LocationNEQSerializer(self.plugin.location_summary(location)).data)


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


class PartExplosiveView(AdminWritesView):
    """Read, and for an admin edit, the explosive properties of one part."""

    def get(self, request, pk: int):
        from part.models import Part

        part = get_object_or_404(Part, pk=pk)

        return Response(PartExplosiveSerializer(self.plugin.part_context(part)).data)

    def patch(self, request, pk: int):
        """Set the part's explosive parameters, creating any missing rows.

        Written in two passes inside one transaction: pass 1 upserts every
        provided field with validation deferred, so all sibling rows exist; pass 2
        validates them together. The cross-field division/compatibility-group
        check (validate_parameter_value) reads its sibling from the database, so
        validating field-by-field during pass 1 could reject a legal pair against
        a stale sibling. A ValidationError in pass 2 rolls the whole PATCH back.
        """
        from part.models import Part

        part = get_object_or_404(Part, pk=pk)

        incoming = PartExplosiveUpdateSerializer(data=request.data, partial=True)
        incoming.is_valid(raise_exception=True)
        data = incoming.validated_data

        try:
            with transaction.atomic():
                written = []

                if "is_explosive" in data:
                    flag = parameters.set_explosive_flag(part, data["is_explosive"])
                    if flag is None:
                        raise _missing_template_error("is_explosive", TPL_EXPLOSIVE)

                # Pass 1: write every provided value, validation deferred. A blank
                # value clears the field (an absent row is the "unset" state).
                for field, template_name in _UPDATE_FIELD_TEMPLATES.items():
                    if field not in data:
                        continue

                    value = data[field]

                    if isinstance(value, str) and value.strip() == "":
                        parameters.clear_parameter_value(part, template_name)
                        continue

                    parameter = parameters.set_parameter_value(
                        part, template_name, value, validate=False
                    )
                    if parameter is None:
                        raise _missing_template_error(field, template_name)
                    written.append(parameter)

                # Pass 2: validate the final state together.
                for parameter in written:
                    parameter.full_clean()
        except ValidationError as exc:
            raise _as_api_error(exc) from exc

        return Response(PartExplosiveSerializer(self.plugin.part_context(part)).data)


class BootstrapView(AdminWritesView):
    """Report, and on demand repair, the parameter template setup.

    GET returns the current status (read-only) so the settings page can warn when
    templates are missing. POST re-runs the bootstrap — the manual repair path,
    for when the templates were not created at load time (e.g. the plugin was
    first loaded during a migration).
    """

    def get(self, request):
        return Response(StatusSerializer(parameters.status()).data)

    def post(self, request):
        result = parameters.ensure_parameter_templates()

        return Response(BootstrapSerializer(result).data)
