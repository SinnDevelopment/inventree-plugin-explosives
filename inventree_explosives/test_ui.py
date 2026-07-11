"""UI panel registration.

A panel whose `source` does not resolve to a built JS file, or whose entrypoint
name does not match the exported function, fails silently in the browser. These
tests tie core.py to the built frontend bundle so the mismatch surfaces here
rather than as a blank tab.
"""

from pathlib import Path

from part.models import Part

from .test_neq import ExplosivesTestCase

STATIC_DIR = Path(__file__).parent / "static"

# entrypoint file -> the function core.py asks for
EXPECTED_ENTRYPOINTS = {
    "LocationPanel.js": "RenderLocationPanel",
    "Panel.js": "RenderPartPanel",
    "Dashboard.js": "RenderMagazineDashboard",
    "Settings.js": "RenderPluginSettings",
}


class PanelRegistrationTest(ExplosivesTestCase):
    def request(self):
        """A minimal request object; get_ui_panels only needs `user`."""

        class Request:
            user = self.user

        return Request()

    def test_location_panel_shown_on_every_location(self):
        panels = self.plugin.get_ui_panels(
            self.request(),
            {"target_model": "stocklocation", "target_id": self.magazine.pk},
        )

        self.assertEqual(len(panels), 1)
        self.assertEqual(panels[0]["key"], "explosives-location")
        self.assertIn("LocationPanel.js", panels[0]["source"])
        self.assertIn("RenderLocationPanel", panels[0]["source"])

    def test_part_panel_shown_for_explosive_parts(self):
        part = self.make_explosive_part(neq_kg="0.5")

        panels = self.plugin.get_ui_panels(
            self.request(), {"target_model": "part", "target_id": part.pk}
        )

        self.assertEqual(len(panels), 1)
        self.assertEqual(panels[0]["key"], "explosives-part")

    def test_part_panel_hidden_for_ordinary_parts(self):
        """An inert part must not get an explosives tab."""
        part = Part.objects.create(
            name="Cardboard box", description="inert", category=self.category
        )

        panels = self.plugin.get_ui_panels(
            self.request(), {"target_model": "part", "target_id": part.pk}
        )

        self.assertEqual(panels, [])

    def test_no_panels_on_unrelated_models(self):
        panels = self.plugin.get_ui_panels(
            self.request(), {"target_model": "purchaseorder", "target_id": 1}
        )

        self.assertEqual(panels, [])

    def test_dashboard_item_registered(self):
        items = self.plugin.get_ui_dashboard_items(self.request(), {})

        self.assertEqual(len(items), 1)
        self.assertIn("Dashboard.js", items[0]["source"])


class FrontendBundleTest(ExplosivesTestCase):
    """The built bundle must contain the entrypoints core.py references.

    Skipped when the frontend has not been built (a source checkout without
    `npm run build`); the packaged wheel always contains static/.
    """

    def test_entrypoints_exist_and_are_exported(self):
        if not STATIC_DIR.exists():
            self.skipTest("frontend not built; run `npm run build` in frontend/")

        for filename, function in EXPECTED_ENTRYPOINTS.items():
            path = STATIC_DIR / filename

            self.assertTrue(path.exists(), f"{filename} missing from the build")

            source = path.read_text()

            self.assertIn(
                function,
                source,
                f"{filename} does not export {function}, which core.py asks for",
            )
