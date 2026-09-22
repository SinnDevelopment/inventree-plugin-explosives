"""Tests for the plugin API endpoints and report/export context.

These go through the real URL layer, so they also prove that UrlsMixin actually
mounted the routes.
"""

import json

from django.urls import reverse

from . import exports, neq, parameters
from .constants import (
    TPL_COMPAT,
    TPL_DIVISION,
    TPL_GROSS_MASS,
    TPL_MAX_NEQ,
    TPL_UN_NUMBER,
)
from .test_neq import ExplosivesTestCase


class LocationAPITest(ExplosivesTestCase):
    def setUp(self):
        super().setUp()

        self.set_parameter(self.magazine, TPL_MAX_NEQ, "50")

        self.part = self.make_explosive_part(
            neq_kg="0.5",
            **{
                TPL_GROSS_MASS: "0.8",
                TPL_DIVISION: "1.1",
                TPL_COMPAT: "D",
                TPL_UN_NUMBER: "UN0042",
            },
        )

    def url(self):
        return reverse("plugin:explosives:location-neq", kwargs={"pk": self.magazine.pk})

    def test_location_neq_payload(self):
        self.add_stock(self.part, 80)  # 40 kg of a 50 kg licence

        response = self.client.get(self.url())

        self.assertEqual(response.status_code, 200)

        data = response.json()

        self.assertEqual(data["location_id"], self.magazine.pk)
        self.assertAlmostEqual(data["neq_kg"], 40.0, places=6)
        self.assertAlmostEqual(data["limit_kg"], 50.0, places=6)
        self.assertAlmostEqual(data["utilisation"], 0.8, places=6)
        self.assertFalse(data["over_limit"])
        self.assertAlmostEqual(data["gross_mass_kg"], 64.0, places=6)

        self.assertEqual(data["by_division"], {"1.1": 40.0})

        self.assertEqual(len(data["items"]), 1)

        item = data["items"][0]
        self.assertEqual(item["classification_code"], "1.1D")
        self.assertEqual(item["un_number"], "UN0042")
        self.assertAlmostEqual(item["neq_total_kg"], 40.0, places=6)

    def test_over_limit_is_reported(self):
        self.add_stock(self.part, 120)  # 60 kg of a 50 kg licence

        data = self.client.get(self.url()).json()

        self.assertTrue(data["over_limit"])
        self.assertAlmostEqual(data["utilisation"], 1.2, places=6)

    def test_empty_location(self):
        data = self.client.get(self.url()).json()

        self.assertEqual(data["neq_kg"], 0.0)
        self.assertFalse(data["over_limit"])
        self.assertEqual(data["items"], [])

    def test_requires_authentication(self):
        self.client.logout()

        response = self.client.get(self.url())

        self.assertIn(response.status_code, [401, 403])

    def patch_limit(self, value):
        return self.client.patch(
            self.url(),
            data=json.dumps({"limit_kg": value}),
            content_type="application/json",
        )

    def test_patch_limit_sets_the_licence(self):
        self.user.is_staff = True
        self.user.save()

        response = self.patch_limit("75000 g")  # unit-bearing input, stored in kg

        self.assertEqual(response.status_code, 200)
        self.assertAlmostEqual(response.json()["limit_kg"], 75.0, places=6)
        self.assertAlmostEqual(neq.location_limit(self.magazine), 75.0, places=6)

    def test_patch_zero_limit_means_no_explosives_permitted(self):
        self.user.is_staff = True
        self.user.save()
        self.add_stock(self.part, 1)

        data = self.patch_limit("0").json()

        self.assertEqual(data["limit_kg"], 0.0)
        self.assertTrue(data["over_limit"])

    def test_patch_blank_limit_removes_the_licence(self):
        self.user.is_staff = True
        self.user.save()

        response = self.patch_limit("")

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json()["limit_kg"])
        self.assertIsNone(neq.location_limit(self.magazine))
        self.assertEqual(
            self.client.get(reverse("plugin:explosives:location-summary")).json(), []
        )

    def test_patch_unparseable_limit_is_rejected(self):
        self.user.is_staff = True
        self.user.save()

        response = self.patch_limit("about fifty")

        self.assertEqual(response.status_code, 400)
        self.assertIn("limit_kg", response.json())
        self.assertAlmostEqual(neq.location_limit(self.magazine), 50.0, places=6)

    def test_patch_limit_requires_staff(self):
        self.user.is_staff = False
        self.user.is_superuser = False
        self.user.save()

        response = self.patch_limit("75")

        self.assertEqual(response.status_code, 403)
        self.assertAlmostEqual(neq.location_limit(self.magazine), 50.0, places=6)

    def test_patch_limit_with_template_missing_is_an_error_not_a_silent_noop(self):
        from common.models import ParameterTemplate

        self.user.is_staff = True
        self.user.save()

        ParameterTemplate.objects.filter(name__iexact=TPL_MAX_NEQ).delete()
        self.assertIsNone(parameters.get_template(TPL_MAX_NEQ))

        response = self.patch_limit("75")

        self.assertEqual(response.status_code, 400)
        self.assertIn("limit_kg", response.json())

    def test_location_summary_lists_licensed_magazines(self):
        self.add_stock(self.part, 120)  # over limit

        response = self.client.get(reverse("plugin:explosives:location-summary"))

        self.assertEqual(response.status_code, 200)

        data = response.json()

        self.assertEqual(len(data), 1)
        self.assertTrue(data[0]["over_limit"])
        self.assertEqual(data[0]["location_id"], self.magazine.pk)


class PartAPITest(ExplosivesTestCase):
    def test_part_payload(self):
        part = self.make_explosive_part(
            neq_kg="0.5", **{TPL_DIVISION: "1.4", TPL_COMPAT: "S"}
        )

        url = reverse("plugin:explosives:part-explosive", kwargs={"pk": part.pk})

        data = self.client.get(url).json()

        self.assertTrue(data["is_explosive"])
        self.assertAlmostEqual(data["neq_per_unit_kg"], 0.5, places=6)
        self.assertEqual(data["classification_code"], "1.4S")
        self.assertEqual(data["issues"], [])

    def test_issues_are_reported(self):
        part = self.make_explosive_part(
            neq_kg="2.0", validate=False, **{TPL_GROSS_MASS: "1.0"}
        )

        url = reverse("plugin:explosives:part-explosive", kwargs={"pk": part.pk})

        data = self.client.get(url).json()

        self.assertEqual(len(data["issues"]), 1)
        self.assertIn("exceeds gross mass", data["issues"][0])


class BootstrapAPITest(ExplosivesTestCase):
    def test_bootstrap_requires_staff(self):
        self.user.is_staff = False
        self.user.is_superuser = False
        self.user.save()

        response = self.client.post(reverse("plugin:explosives:bootstrap"))

        self.assertEqual(response.status_code, 403)

    def test_bootstrap_is_idempotent_via_api(self):
        self.user.is_staff = True
        self.user.save()

        response = self.client.post(reverse("plugin:explosives:bootstrap"))

        self.assertEqual(response.status_code, 200)

        data = response.json()

        # setUp already bootstrapped, so nothing new should be created.
        self.assertEqual(data["created"], [])
        self.assertEqual(data["errors"], [])


class ReportContextTest(ExplosivesTestCase):
    """The context injected into report templates."""

    def test_location_context(self):
        self.set_parameter(self.magazine, TPL_MAX_NEQ, "50")

        part = self.make_explosive_part(neq_kg="0.5")
        self.add_stock(part, 80)

        context = {}
        self.plugin.add_report_context(None, self.magazine, self.user, context)

        self.assertIn("explosives", context)
        self.assertAlmostEqual(context["explosives"]["neq_kg"], 40.0, places=6)

    def test_stock_item_context_is_a_manifest_line(self):
        part = self.make_explosive_part(
            neq_kg="0.5",
            **{
                TPL_GROSS_MASS: "0.8",
                TPL_DIVISION: "1.4",
                TPL_COMPAT: "S",
                TPL_UN_NUMBER: "UN0042",
            },
        )
        item = self.add_stock(part, 10)

        context = {}
        self.plugin.add_report_context(None, item, self.user, context)

        data = context["explosives"]

        self.assertEqual(data["classification_code"], "1.4S")
        self.assertEqual(data["un_number"], "UN0042")
        self.assertAlmostEqual(data["neq_total_kg"], 5.0, places=6)
        self.assertAlmostEqual(data["gross_mass_total_kg"], 8.0, places=6)


class ExportTest(ExplosivesTestCase):
    def test_part_row(self):
        part = self.make_explosive_part(
            neq_kg="0.5", **{TPL_DIVISION: "1.4", TPL_COMPAT: "S"}
        )

        row = exports.row_for(part)

        self.assertTrue(row["explosive"])
        self.assertEqual(row["explosive_class"], "1.4S")
        self.assertAlmostEqual(row["explosive_neq_kg"], 0.5, places=6)

    def test_non_explosive_part_row(self):
        from part.models import Part

        part = Part.objects.create(
            name="Cardboard box", description="inert", category=self.category
        )

        row = exports.row_for(part)

        self.assertFalse(row["explosive"])

    def test_stock_item_row_includes_totals(self):
        part = self.make_explosive_part(neq_kg="0.5", **{TPL_GROSS_MASS: "0.8"})
        item = self.add_stock(part, 10)

        row = exports.row_for(item)

        self.assertAlmostEqual(row["explosive_neq_total_kg"], 5.0, places=6)
        self.assertAlmostEqual(row["explosive_gross_mass_total_kg"], 8.0, places=6)

    def test_location_row(self):
        self.set_parameter(self.magazine, TPL_MAX_NEQ, "50")

        part = self.make_explosive_part(neq_kg="0.5")
        self.add_stock(part, 120)  # 60 kg -> over the 50 kg licence

        row = exports.row_for(self.magazine)

        self.assertAlmostEqual(row["explosive_neq_kg"], 60.0, places=6)
        self.assertAlmostEqual(row["explosive_limit_kg"], 50.0, places=6)
        self.assertAlmostEqual(row["explosive_utilisation"], 120.0, places=1)
        self.assertTrue(row["explosive_over_limit"])

    def test_supports_export_only_for_relevant_models(self):
        from order.models import PurchaseOrder
        from part.models import Part
        from stock.models import StockItem, StockLocation

        for model in [Part, StockItem, StockLocation]:
            self.assertTrue(self.plugin.supports_export(model, self.user))

        self.assertFalse(self.plugin.supports_export(PurchaseOrder, self.user))

    def test_headers_match_the_model_being_exported(self):
        """export_data() must tell update_headers() which model is in play.

        InvenTree calls export_data() first and update_headers() second with the
        same context dict, which carries no model information of its own. If the
        handoff breaks, a Part export gains stock-only columns no Part row fills in.
        """
        from collections import OrderedDict

        from common.models import DataOutput
        from part.models import Part
        from part.serializers import PartSerializer
        from stock.models import StockItem
        from stock.serializers import StockItemSerializer

        self.make_explosive_part(neq_kg="0.5")

        cases = [
            (Part, PartSerializer, exports.PART_COLUMNS, exports.STOCK_COLUMNS),
            (
                StockItem,
                StockItemSerializer,
                exports.STOCK_COLUMNS,
                exports.LOCATION_COLUMNS,
            ),
        ]

        for model, serializer, expected, unexpected in cases:
            with self.subTest(model=model.__name__):
                context = {}
                output = DataOutput.objects.create(total=0, progress=0, complete=False)

                self.plugin.export_data(
                    model.objects.all(),
                    serializer,
                    OrderedDict(),
                    context,
                    output,
                )

                headers = self.plugin.update_headers(OrderedDict(), context)

                for column in expected:
                    self.assertIn(column, headers)

                # Columns belonging to a *different* model must not leak in.
                for column in unexpected:
                    if column not in expected:
                        self.assertNotIn(column, headers)
