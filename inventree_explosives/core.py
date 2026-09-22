"""Explosives inventory management for InvenTree.

Adds the properties required to keep a lawful inventory of explosives — net
explosive quantity, gross mass and UN classification — and enforces the licensed
NEQ limit of each magazine.

Kept deliberately thin: this module is hook wiring. The logic lives in
neq.py (aggregation), validation.py (rules), hazard.py (UN classification) and
parameters.py (template bootstrap).
"""

import logging
from typing import ClassVar

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

from . import PLUGIN_VERSION, exports, neq, parameters, validation
from .constants import (
    COMPATIBILITY_GROUPS,
    DIVISIONS,
    TPL_COMPAT,
    TPL_DIVISION,
    TPL_GROSS_MASS,
    TPL_NEQ,
    TPL_PSN,
    TPL_UN_NUMBER,
)
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

# Fired by PluginConfig.activate() when any plugin is enabled/disabled, with
# kwargs slug=<plugin key>, active=<bool>. This is the closest thing InvenTree
# has to an "on enable" hook, so it is our primary template-bootstrap trigger —
# see PluginEvents.PLUGIN_ACTIVATED. It only fires when the ENABLE_PLUGINS_EVENTS
# global is on and a worker is running, so the daily schedule and the settings
# "Run setup" button remain as fallbacks.
EVENT_PLUGIN_ACTIVATED = "plugin_activated"


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

    # The generic Parameter/ParameterTemplate model this plugin is built on
    # landed in 1.2.0 (PR #10699, which removed the old PartParameter models).
    # A lower floor makes the plugin import-fail on load.
    MIN_VERSION = "1.2.0"

    ADMIN_SOURCE = "Settings.js:RenderPluginSettings"

    SETTINGS: ClassVar[dict] = {
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
                "Comma-separated PartCategory IDs whose parts (and sub-category "
                "parts) may hold explosive data. Controls which parts show the "
                "Explosive Data panel. Leave blank to show it on every part."
            ),
            "default": "",
        },
    }

    SCHEDULED_TASKS: ClassVar[dict] = {
        "ensure_templates": {
            "func": "ensure_templates",
            "schedule": "D",
        },
    }

    def __init__(self, *args, **kwargs):
        """Bootstrap parameter templates on registry load.

        This is a best-effort early attempt. It only runs when the registry
        constructs the instance (a plugin that is active, or under test), and is a
        no-op when the database is not ready (migrations, imports). The reliable
        trigger is the plugin_activated event (see process_event); the daily
        scheduled task and the manual repair endpoint are the other fallbacks.
        """
        super().__init__(*args, **kwargs)

        try:
            self._run_bootstrap("load")
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

    def _run_bootstrap(self, trigger: str) -> dict:
        """Ensure the parameter templates exist, logging the outcome loudly.

        Shared by every bootstrap path (load, plugin_activated event, daily
        schedule). Created templates are logged at INFO; any errors — such as a
        colliding template declared in the wrong units — are logged at WARNING so
        they are noticed rather than swallowed into a discarded return dict.
        """
        result = parameters.ensure_parameter_templates()

        if result["created"]:
            logger.info(
                "explosives: created missing parameter templates (%s): %s",
                trigger,
                ", ".join(result["created"]),
            )

        if result["errors"]:
            logger.warning(
                "explosives: parameter template problems (%s): %s",
                trigger,
                "; ".join(result["errors"]),
            )

        return result

    # --- ScheduleMixin -------------------------------------------------------

    def ensure_templates(self):
        """Daily self-heal, in case bootstrap ran before the database was ready."""
        self._run_bootstrap("schedule")

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
        return event in WATCHED_EVENTS or event == EVENT_PLUGIN_ACTIVATED

    def process_event(self, event: str, *args, **kwargs):
        """React to the events this plugin cares about.

        plugin_activated is our reliable template-bootstrap trigger; the stock
        events drive the after-the-fact magazine audit.
        """
        if event == EVENT_PLUGIN_ACTIVATED:
            # Fires for every plugin's toggle, so act only on our own activation.
            if kwargs.get("slug") == self.SLUG and kwargs.get("active"):
                self._run_bootstrap("activation")
            return

        self._audit_magazines()

    def _audit_magazines(self):
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

        if target_model == "part" and target_id and self._should_show_part_panel(target_id):
            panels.append(
                {
                    "key": "explosives-part",
                    "title": "Explosive Data",
                    "icon": "ti:alert-triangle:outline",
                    "source": self.plugin_static_file("PartPanel.js:RenderPartPanel"),
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

    def _explosive_category_ids(self) -> set[int]:
        """Parse the comma-separated EXPLOSIVE_CATEGORIES setting into IDs.

        Tolerates whitespace and stray non-numeric entries rather than raising in
        the middle of building a panel list.
        """
        raw = self.get_setting("EXPLOSIVE_CATEGORIES") or ""

        ids = set()
        for chunk in raw.split(","):
            chunk = chunk.strip()
            if chunk.isdigit():
                ids.add(int(chunk))

        return ids

    def _should_show_part_panel(self, part_id) -> bool:
        """Whether a part gets the Explosive Data panel.

        Shown for a part that is already flagged explosive, OR whose category (or
        an ancestor of it) is configured in EXPLOSIVE_CATEGORIES. When no
        categories are configured the panel shows on every part, so the feature is
        discoverable out of the box — mirroring the location panel, which is shown
        on every location so a limit can be set in the first place.
        """
        from part.models import Part

        part = Part.objects.filter(pk=part_id).first()

        if part is None:
            return False

        if validation.is_explosive_part(part):
            return True

        category_ids = self._explosive_category_ids()

        if not category_ids:
            return True

        if part.category_id is None:
            return False

        # Match the part's category or any ancestor of it, so configuring a parent
        # category covers its sub-categories (PartCategory is an MPTT tree).
        ancestors = part.category.get_ancestors(include_self=True).values_list(
            "pk", flat=True
        )

        return any(pk in category_ids for pk in ancestors)

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
            "divisions": list(DIVISIONS),
            "compatibility_groups": list(COMPATIBILITY_GROUPS),
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

        # Serializer rows come back in queryset order. strict=True: a length
        # mismatch would silently misalign every row, and these are compliance
        # numbers — fail loudly rather than export the wrong ones.
        for row, instance in zip(rows, queryset, strict=True):
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
