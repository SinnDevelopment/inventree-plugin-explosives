"""The plugin_activated bootstrap trigger.

This covers the path that had no test before: a plugin's __init__-time bootstrap
only runs when the registry constructs the instance, which on a live server is
gated on activation state. The reliable trigger is the plugin_activated event, so
these tests exercise both the handler directly and the real event dispatch.
"""

from unittest.mock import patch

from common.models import InvenTreeSetting, ParameterTemplate
from plugin.base.event.events import trigger_event

from . import parameters
from .constants import TEMPLATE_COUNT_EXPECTED
from .parameters import TEMPLATE_SPECS
from .test_neq import ExplosivesTestCase


class PluginActivatedEventTest(ExplosivesTestCase):
    """The plugin_activated event creates the parameter templates."""

    def _delete_templates(self):
        """Return to the pre-bootstrap state (setUp creates the templates)."""
        for name, _model, _fields in TEMPLATE_SPECS:
            ParameterTemplate.objects.filter(name__iexact=name).delete()

        self.assertTrue(
            all(parameters.get_template(name) is None for name, _m, _f in TEMPLATE_SPECS)
        )

    def _all_templates_present(self) -> bool:
        return all(
            parameters.get_template(name) is not None
            for name, _model, _fields in TEMPLATE_SPECS
        )

    def test_activation_creates_templates(self):
        self._delete_templates()

        self.plugin.process_event(
            "plugin_activated", slug="explosives", active=True
        )

        self.assertTrue(self._all_templates_present())

    def test_ignores_another_plugins_activation(self):
        """The event fires for every plugin toggle; act only on our own."""
        self._delete_templates()

        self.plugin.process_event("plugin_activated", slug="other", active=True)

        self.assertFalse(self._all_templates_present())

    def test_ignores_deactivation(self):
        self._delete_templates()

        self.plugin.process_event(
            "plugin_activated", slug="explosives", active=False
        )

        self.assertFalse(self._all_templates_present())

    def test_stock_event_does_not_bootstrap(self):
        """Only activation bootstraps; a stock event must not."""
        self._delete_templates()

        self.plugin.process_event("stock_stockitem.saved")

        self.assertFalse(self._all_templates_present())

    def test_activation_routes_to_bootstrap_not_audit(self):
        with (
            patch.object(self.plugin, "_run_bootstrap") as bootstrap,
            patch.object(self.plugin, "_audit_magazines") as audit,
        ):
            self.plugin.process_event(
                "plugin_activated", slug="explosives", active=True
            )

        bootstrap.assert_called_once()
        audit.assert_not_called()

    def test_stock_event_routes_to_audit_not_bootstrap(self):
        with (
            patch.object(self.plugin, "_run_bootstrap") as bootstrap,
            patch.object(self.plugin, "_audit_magazines") as audit,
        ):
            self.plugin.process_event("stock_stockitem.saved")

        audit.assert_called_once()
        bootstrap.assert_not_called()

    def test_wants_plugin_activated_event(self):
        self.assertTrue(self.plugin.wants_process_event("plugin_activated"))

    def test_real_event_dispatch_creates_templates(self):
        """End-to-end through InvenTree's event machinery, not just the handler.

        Mirrors plugin/samples/event/test_event_sample.py: the whole
        trigger_event -> register_event -> process_event chain runs synchronously
        when ENABLE_PLUGINS_EVENTS is on and PLUGIN_TESTING_EVENTS is set.
        """
        self._delete_templates()

        InvenTreeSetting.set_setting("ENABLE_PLUGINS_EVENTS", True, change_user=None)

        with self.settings(PLUGIN_TESTING_EVENTS=True):
            trigger_event("plugin_activated", slug="explosives", active=True)

        self.assertTrue(self._all_templates_present())
        self.assertEqual(
            ParameterTemplate.objects.filter(
                name__in=[name for name, _m, _f in TEMPLATE_SPECS]
            ).count(),
            TEMPLATE_COUNT_EXPECTED,
        )
