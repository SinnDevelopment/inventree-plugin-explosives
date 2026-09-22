"""UI panel registration.

A panel whose `source` does not resolve to a built JS file, or whose entrypoint
name does not match the exported function, fails silently in the browser. These
tests tie core.py to the built frontend bundle so the mismatch surfaces here
rather than as a blank tab.
"""

import json
import re
from pathlib import Path

from part.models import Part, PartCategory

from .test_neq import ExplosivesTestCase

STATIC_DIR = Path(__file__).parent / "static"

# entrypoint file -> the function core.py asks for
EXPECTED_ENTRYPOINTS = {
    "LocationPanel.js": "RenderLocationPanel",
    "PartPanel.js": "RenderPartPanel",
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
        self.assertIn("LocationPanel", panels[0]["source"])
        self.assertIn("RenderLocationPanel", panels[0]["source"])

    def _part_panels(self, part):
        return self.plugin.get_ui_panels(
            self.request(), {"target_model": "part", "target_id": part.pk}
        )

    def test_part_panel_shown_for_explosive_parts(self):
        part = self.make_explosive_part(neq_kg="0.5")

        panels = self._part_panels(part)

        self.assertEqual(len(panels), 1)
        self.assertEqual(panels[0]["key"], "explosives-part")

    def test_part_panel_shown_on_ordinary_part_when_no_categories_set(self):
        """With no categories configured the panel is shown everywhere, so the
        feature is discoverable and a part can be marked explosive at all."""
        self.plugin.set_setting("EXPLOSIVE_CATEGORIES", "")

        part = Part.objects.create(
            name="Cardboard box", description="inert", category=self.category
        )

        self.assertEqual(len(self._part_panels(part)), 1)

    def test_part_panel_hidden_when_category_not_configured(self):
        """Once categories are configured, an unrelated part gets no tab."""
        other = PartCategory.objects.create(name="Fasteners")
        self.plugin.set_setting("EXPLOSIVE_CATEGORIES", str(other.pk))

        part = Part.objects.create(
            name="Cardboard box", description="inert", category=self.category
        )

        self.assertEqual(self._part_panels(part), [])

    def test_part_panel_shown_for_configured_category(self):
        self.plugin.set_setting("EXPLOSIVE_CATEGORIES", str(self.category.pk))

        part = Part.objects.create(
            name="Detonator", description="inert-for-now", category=self.category
        )

        self.assertEqual(len(self._part_panels(part)), 1)

    def test_part_panel_shown_for_subcategory_of_configured_category(self):
        """Configuring a parent category covers parts in its sub-categories."""
        sub = PartCategory.objects.create(name="Boosters", parent=self.category)
        self.plugin.set_setting("EXPLOSIVE_CATEGORIES", str(self.category.pk))

        part = Part.objects.create(
            name="Booster", description="inert-for-now", category=sub
        )

        self.assertEqual(len(self._part_panels(part)), 1)

    def test_explosive_part_shown_even_when_outside_configured_category(self):
        other = PartCategory.objects.create(name="Fasteners")
        self.plugin.set_setting("EXPLOSIVE_CATEGORIES", str(other.pk))

        part = self.make_explosive_part(neq_kg="0.5")

        self.assertEqual(len(self._part_panels(part)), 1)

    def test_no_panels_on_unrelated_models(self):
        panels = self.plugin.get_ui_panels(
            self.request(), {"target_model": "purchaseorder", "target_id": 1}
        )

        self.assertEqual(panels, [])

    def test_dashboard_item_registered(self):
        items = self.plugin.get_ui_dashboard_items(self.request(), {})

        self.assertEqual(len(items), 1)
        self.assertIn("Dashboard", items[0]["source"])
        self.assertIn("RenderMagazineDashboard", items[0]["source"])


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


def _inventree_manifest_pattern(filename: str) -> re.Pattern:
    """The pattern InvenTree's hashed_file_lookup() searches the manifest with.

    It is unanchored, so 'Panel.js' matched 'src/LocationPanel.tsx' first and
    the part panel loaded the location bundle.
    """
    stem = filename.split(".")[0]
    return re.compile(rf"{re.escape(stem)}\.(js|jsx|tsx)")


class StaticFileResolutionTest(ExplosivesTestCase):
    """Each panel must resolve to its own bundle."""

    def setUp(self):
        super().setUp()

        if not STATIC_DIR.exists():
            self.skipTest("frontend not built; run `npm run build` in frontend/")

    def test_no_entrypoint_name_matches_another_bundle(self):
        """No entrypoint name may be a suffix of another entrypoint's name."""
        manifest = json.loads((STATIC_DIR / ".vite" / "manifest.json").read_text())

        for filename in EXPECTED_ENTRYPOINTS:
            stem = filename.split(".")[0]
            pattern = _inventree_manifest_pattern(filename)

            matches = [key for key in manifest if pattern.search(key)]

            self.assertEqual(
                matches,
                [f"src/{stem}.tsx"],
                f"InvenTree's manifest lookup for {filename} is ambiguous: {matches}. "
                f"Rename the entrypoint so no other entry ends with '{stem}'.",
            )

    def test_plugin_static_file_resolves_each_entrypoint_to_its_own_bundle(self):
        from plugin.staticfiles import (
            clear_plugin_static_files,
            copy_plugin_static_files,
        )

        # The lookup reads the manifest from STATIC_ROOT, which outlives the
        # test database.
        copy_plugin_static_files(self.plugin.SLUG, check_reload=False)
        self.addCleanup(clear_plugin_static_files, self.plugin.SLUG)

        for filename, function in EXPECTED_ENTRYPOINTS.items():
            stem = filename.split(".")[0]

            with self.subTest(entrypoint=filename):
                url = self.plugin.plugin_static_file(f"{filename}:{function}")

                path, _, resolved_function = url.rpartition(":")
                basename = path.rsplit("/", 1)[-1]

                self.assertEqual(resolved_function, function)
                self.assertRegex(
                    basename,
                    rf"^{re.escape(stem)}(-[\w-]+)?\.js$",
                    f"{filename} resolved to {basename}",
                )
