"""Explosives inventory management for InvenTree.

Adds the properties required to keep a lawful inventory of explosives — net
explosive quantity, gross mass and UN classification — and enforces the licensed
NEQ limit of each magazine.

Kept deliberately thin: this module is hook wiring. The logic lives in
neq.py (aggregation), validation.py (rules), hazard.py (UN classification) and
parameters.py (template bootstrap).
"""

import logging

from django.core.exceptions import ValidationError

from plugin import InvenTreePlugin
from plugin.mixins import (
    DataExportMixin,
    EventMixin,
    ReportMixin,
    ScheduleMixin,
    SettingsMixin,
    UrlsMixin,
    UserInterfaceMixin,
    ValidationMixin,
)

from . import PLUGIN_VERSION
from . import exports, neq, parameters, validation
from .constants import TPL_COMPAT, TPL_DIVISION, TPL_GROSS_MASS, TPL_NEQ, TPL_PSN, TPL_UN_NUMBER
from .hazard import classification_code

logger = logging.getLogger("inventree")

# Passes the model class from export_data() to update_headers(), which InvenTree
# otherwise gives no way to determine.
MODEL_CONTEXT_KEY = "_explosives_model_class"

# Bulk paths that use QuerySet.update() bypass Model.save() and never fire
# validation, so these events are the only way a breach they cause is noticed.
WATCHED_EVENTS = [
    "stockitem.moved",
    "stockitem.quantityupdated",
    "stockitem.counted",
    "stockitem.split",
    "stock_stockitem.saved",
    "stock_stockitem.created",
    "stock_stockitem.deleted",
]


class ExplosivesPlugin(
    SettingsMixin,
    UrlsMixin,
    UserInterfaceMixin,
    ValidationMixin,
    EventMixin,
    ReportMixin,
    ScheduleMixin,
    DataExportMixin,
    InvenTreePlugin,
):
    """Track net explosive quantity and enforce magazine licence limits."""

    TITLE = "Explosives"
    NAME = "Explosives"
    SLUG = "explosives"
    DESCRIPTION = (
        "Net explosive quantity, gross mass and UN classification for explosive "
        "parts, with per-magazine licensed NEQ limits and compliance reporting."
    )
    VERSION = PLUGIN_VERSION

    AUTHOR = "Sinn Development Ltd"
    WEBSITE = "https://github.com/sinndevelopment/inventree-plugin-explosives"
    LICENSE = "MIT"

    # The generic Parameter model this plugin is built on landed in 1.0.
    MIN_VERSION = "1.0.0"

    ADMIN_SOURCE = "Settings.js:RenderPluginSettings"

    SETTINGS = {
        "LIMIT_ACTION": {
            "name": "Licence limit action",
            "description": (
                "What to do when a stock movement would push a magazine over its "
                "licensed net explosive quantity"
            ),
            "choices": [
                ("off", "Ignore"),
                ("warn", "Warn only"),
                ("block", "Block the movement"),
            ],
            "default": "warn",
        },
        "INCLUDE_SUBLOCATIONS": {
            "name": "Include sublocations in magazine totals",
            "description": (
                "Count stock held in sublocations toward a location's NEQ total"
            ),
            "validator": bool,
            "default": True,
        },
        "COUNT_ALL_PRESENT_STOCK": {
            "name": "Count quarantined and rejected stock",
            "description": (
                "Count stock that is physically present but not available "
                "(quarantined, rejected) toward magazine totals. "
                "Such stock still occupies the magazine and counts against a licence."
            ),
            "validator": bool,
            "default": True,
        },
        "REQUIRE_NEQ": {
            "name": "Require a net explosive quantity on explosive parts",
            "validator": bool,
            "default": True,
        },
        "ENFORCE_COMPAT_GROUP": {
            "name": "Enforce the UN classification-code table",
            "description": (
                "Reject division/compatibility-group combinations that are not "
                "valid UN classification codes (e.g. 1.1S)"
            ),
            "validator": bool,
            "default": True,
        },
        "EXPLOSIVE_CATEGORIES": {
            "name": "Explosive part categories",
            "description": (
                "Comma-separated PartCategory IDs whose parts are expected to be "
                "flagged as explosive. Used for integrity reporting only."
            ),
            "default": "",
        },
    }

    SCHEDULED_TASKS = {
        "ensure_templates": {
            "func": "ensure_templates",
            "schedule": "D",
        },
    }

    def __init__(self, *args, **kwargs):
        """Bootstrap parameter templates on registry load.

        InvenTree has no plugin activation hook, so this is the earliest place we
        can create the templates. It is a no-op when the database is not ready
        (migrations, imports), which is why the scheduled task and the manual
        repair endpoint also exist.
        """
        super().__init__(*args, **kwargs)

        try:
            parameters.ensure_parameter_templates()
        except Exception:
            # A plugin that raises on load takes the whole registry down.
            logger.exception("explosives: parameter template bootstrap failed")

    def _include_sublocations(self) -> bool:
        return bool(self.get_setting("INCLUDE_SUBLOCATIONS"))

    def _count_all_present(self) -> bool:
        return bool(self.get_setting("COUNT_ALL_PRESENT_STOCK"))

    def location_summary(self, location) -> dict:
        """Summary for a location, honouring this plugin's settings."""
        summary = neq.location_summary(
            location,
            include_sublocations=self._include_sublocations(),
            count_all_present=self._count_all_present(),
        )
        summary["config_errors"] = parameters.config_errors()
        return summary

    def licensed_locations(self) -> list[dict]:
        """Every licensed magazine, honouring this plugin's settings.

        Reporting surfaces must go through here rather than calling neq.*
        directly, or they pick up the module defaults instead of the site's
        settings and report totals that contradict the location panel.
        """
        return neq.licensed_locations(
            include_sublocations=self._include_sublocations(),
            count_all_present=self._count_all_present(),
        )

    # --- ScheduleMixin -------------------------------------------------------

    def ensure_templates(self):
        """Daily self-heal, in case bootstrap ran before the database was ready."""
        result = parameters.ensure_parameter_templates()

        if result["created"]:
            logger.info(
                "explosives: created missing parameter templates: %s",
                ", ".join(result["created"]),
            )

    # --- ValidationMixin -----------------------------------------------------

    def validate_model_instance(self, instance, deltas=None, **kwargs):
        """Validate explosive parts, and check magazine limits on stock moves."""
        from part.models import Part
        from stock.models import StockItem

        if isinstance(instance, Part):
            validation.validate_part(
                instance,
                require_neq=bool(self.get_setting("REQUIRE_NEQ")),
                enforce_combo=bool(self.get_setting("ENFORCE_COMPAT_GROUP")),
            )
            return

        if isinstance(instance, StockItem):
            self._check_stock_limit(instance)

    def validate_parameter(self, parameter, data, **kwargs):
        """Validate a single parameter value (Part or StockLocation)."""
        validation.validate_parameter_value(
            parameter,
            data,
            enforce_combo=bool(self.get_setting("ENFORCE_COMPAT_GROUP")),
        )

    def _check_stock_limit(self, stock_item):
        """Warn or block if this save would push a magazine over its licence."""
        action = self.get_setting("LIMIT_ACTION")

        if action == "off":
            return

        # This hook fires on EVERY StockItem.save() in the system, so bail out
        # cheaply for the overwhelming majority of items, which are not explosive.
        if not stock_item.part_id or not validation.is_explosive_part(stock_item.part):
            return

        breach = neq.check_prospective_limit(
            stock_item,
            include_sublocations=self._include_sublocations(),
            count_all_present=self._count_all_present(),
        )

        if breach is None:
            return

        if action == "block":
            raise ValidationError(str(breach))

        logger.warning("explosives: %s", breach)

    # --- EventMixin ----------------------------------------------------------

    def wants_process_event(self, event: str) -> bool:
        return event in WATCHED_EVENTS

    def process_event(self, event: str, *args, **kwargs):
        """Audit affected magazines after the fact.

        Validation prevents breaches on the normal save path; this notices the
        ones that arrive via bulk updates, which never call save() at all.
        """
        if self.get_setting("LIMIT_ACTION") == "off":
            return

        for summary in self.licensed_locations():
            if summary["over_limit"]:
                self._notify_breach(summary)

    def _notify_breach(self, summary: dict):
        from stock.models import StockLocation

        logger.warning(
            "explosives: magazine '%s' holds %.3f kg NEQ against a licensed limit "
            "of %.3f kg",
            summary["location_name"],
            summary["neq_kg"],
            summary["limit_kg"],
        )

        try:
            from common.notifications import trigger_notification

            location = StockLocation.objects.filter(pk=summary["location_id"]).first()

            if location is None:
                return

            trigger_notification(
                location,
                "explosives.limit_breach",
                context={
                    "name": f"NEQ limit exceeded: {summary['location_name']}",
                    "message": (
                        f"{summary['neq_kg']:.3f} kg NEQ held against a licensed "
                        f"limit of {summary['limit_kg']:.3f} kg."
                    ),
                },
            )
        except Exception:
            logger.exception("explosives: failed to send limit-breach notification")

    # --- UrlsMixin -----------------------------------------------------------

    def setup_urls(self):
        from django.urls import path

        from .views import (
            BootstrapView,
            LocationNEQView,
            LocationSummaryView,
            PartExplosiveView,
        )

        return [
            path(
                "api/location/<int:pk>/neq/",
                LocationNEQView.as_view(plugin=self),
                name="location-neq",
            ),
            path(
                "api/location/summary/",
                LocationSummaryView.as_view(plugin=self),
                name="location-summary",
            ),
            path(
                "api/part/<int:pk>/",
                PartExplosiveView.as_view(plugin=self),
                name="part-explosive",
            ),
            path(
                "api/bootstrap/",
                BootstrapView.as_view(plugin=self),
                name="bootstrap",
            ),
        ]

    # --- UserInterfaceMixin --------------------------------------------------

    def get_ui_panels(self, request, context: dict, **kwargs):
        panels = []

        target_model = context.get("target_model")
        target_id = context.get("target_id")

        if target_model == "stocklocation" and target_id:
            # Shown on every location, not just licensed ones: otherwise there is
            # no affordance to *set* a limit on a location that lacks one.
            panels.append(
                {
                    "key": "explosives-location",
                    "title": "Explosives / NEQ",
                    "icon": "ti:flame:outline",
                    "source": self.plugin_static_file(
                        "LocationPanel.js:RenderLocationPanel"
                    ),
                    "context": {
                        "location_id": target_id,
                        "settings": self.get_settings_dict(),
                    },
                }
            )

        if target_model == "part" and target_id and self._is_explosive_part_id(target_id):
            panels.append(
                {
                    "key": "explosives-part",
                    "title": "Explosive Data",
                    "icon": "ti:alert-triangle:outline",
                    "source": self.plugin_static_file("Panel.js:RenderPartPanel"),
                    "context": {
                        "part_id": target_id,
                        "settings": self.get_settings_dict(),
                    },
                }
            )

        return panels

    def get_ui_dashboard_items(self, request, context: dict, **kwargs):
        return [
            {
                "key": "explosives-magazines",
                "title": "Magazine NEQ",
                "description": "Licensed magazines by net explosive quantity",
                "icon": "ti:flame:outline",
                "source": self.plugin_static_file("Dashboard.js:RenderMagazineDashboard"),
                "options": {"width": 4, "height": 4},
                "context": {"settings": self.get_settings_dict()},
            }
        ]

    def _is_explosive_part_id(self, part_id) -> bool:
        from part.models import Part

        part = Part.objects.filter(pk=part_id).first()

        return bool(part and validation.is_explosive_part(part))

    # --- ReportMixin ---------------------------------------------------------

    def add_report_context(self, report_instance, model_instance, user, context, **kwargs):
        """Inject explosive data into report templates.

        The third positional argument is the User, not a request.

        Everything lands under a single `explosives` key so report templates have
        a stable surface: {{ explosives.neq_kg }}, {{ explosives.items }} etc.
        """
        from part.models import Part
        from stock.models import StockItem, StockLocation

        if isinstance(model_instance, StockLocation):
            context["explosives"] = self.location_summary(model_instance)
        elif isinstance(model_instance, StockItem):
            context["explosives"] = self.stock_item_context(model_instance)
        elif isinstance(model_instance, Part):
            context["explosives"] = self.part_context(model_instance)

    def add_label_context(self, label_instance, model_instance, user, context, **kwargs):
        self.add_report_context(label_instance, model_instance, user, context, **kwargs)

    def part_context(self, part) -> dict:
        """The explosive properties of a part, for reports, labels and the API."""
        division = parameters.get_parameter_value(part, TPL_DIVISION)
        group = parameters.get_parameter_value(part, TPL_COMPAT)

        return {
            "is_explosive": validation.is_explosive_part(part),
            "neq_per_unit_kg": parameters.get_parameter_numeric(part, TPL_NEQ),
            "gross_mass_per_unit_kg": parameters.get_parameter_numeric(
                part, TPL_GROSS_MASS
            ),
            "division": division,
            "compatibility_group": group,
            "classification_code": classification_code(division, group),
            "un_number": parameters.get_parameter_value(part, TPL_UN_NUMBER),
            "proper_shipping_name": parameters.get_parameter_value(part, TPL_PSN),
            "issues": validation.part_issues(
                part,
                require_neq=bool(self.get_setting("REQUIRE_NEQ")),
                enforce_combo=bool(self.get_setting("ENFORCE_COMPAT_GROUP")),
            ),
        }

    def stock_item_context(self, stock_item) -> dict:
        """Explosive data for one stock item — a transport manifest line."""
        data = self.part_context(stock_item.part)

        neq_per_unit = data["neq_per_unit_kg"]
        gross_per_unit = data["gross_mass_per_unit_kg"]
        quantity = float(stock_item.quantity)

        data.update(
            {
                "quantity": quantity,
                "neq_total_kg": (neq_per_unit * quantity) if neq_per_unit else None,
                "gross_mass_total_kg": (
                    (gross_per_unit * quantity) if gross_per_unit else None
                ),
            }
        )

        return data

    # --- DataExportMixin -----------------------------------------------------

    def supports_export(self, model_class, user, *args, **kwargs) -> bool:
        """Only offer this exporter for models that can carry explosive data."""
        return bool(exports.columns_for(model_class))

    def export_data(
        self, queryset, serializer_class, headers, context, output, *args, **kwargs
    ):
        """Export the standard rows, with the explosive columns merged in."""
        rows = super().export_data(
            queryset, serializer_class, headers, context, output, *args, **kwargs
        )

        # InvenTree calls export_data() before update_headers() with the same
        # context dict, which is the only per-export channel between them. The
        # plugin instance is shared, so stashing the model on `self` would race
        # between concurrent exports.
        if context is not None:
            context[MODEL_CONTEXT_KEY] = queryset.model

        include_sublocations = self._include_sublocations()
        count_all_present = self._count_all_present()

        # Serializer rows come back in queryset order.
        for row, instance in zip(rows, queryset):
            try:
                row.update(
                    exports.row_for(
                        instance,
                        include_sublocations=include_sublocations,
                        count_all_present=count_all_present,
                    )
                )
            except Exception:
                logger.exception(
                    "explosives: failed to add export columns for %s", instance
                )

        return rows

    def update_headers(self, headers, context, **kwargs):
        """Append the explosive columns to the standard export headers."""
        model_class = (context or {}).get(MODEL_CONTEXT_KEY)

        if model_class is None:
            return headers

        headers.update(exports.columns_for(model_class))

        return headers
