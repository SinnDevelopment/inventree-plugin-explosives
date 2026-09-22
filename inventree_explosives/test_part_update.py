"""The part explosive-data PATCH endpoint.

Exercised through the DRF view with APIRequestFactory, so no running server is
needed. This is the write path that lets a user mark a part explosive and set its
fields from the plugin's own panel, rather than hand-adding parameters.
"""

from django.contrib.auth import get_user_model

from rest_framework.test import APIRequestFactory, force_authenticate

from common.models import Parameter
from part.models import Part

from . import parameters, validation
from .constants import TPL_COMPAT, TPL_DIVISION, TPL_NEQ, TPL_UN_NUMBER
from .test_neq import ExplosivesTestCase
from .views import PartExplosiveView


class PartUpdateTest(ExplosivesTestCase):
    factory = APIRequestFactory()

    def plain_part(self, name="Widget"):
        return Part.objects.create(
            name=name, description=name, category=self.category, active=True
        )

    def patch(self, part, payload, user=None):
        view = PartExplosiveView.as_view(plugin=self.plugin)
        request = self.factory.patch(f"/part/{part.pk}/", payload, format="json")
        force_authenticate(request, user=user or self.user)
        return view(request, pk=part.pk)

    def get(self, part, user=None):
        view = PartExplosiveView.as_view(plugin=self.plugin)
        request = self.factory.get(f"/part/{part.pk}/")
        force_authenticate(request, user=user or self.user)
        return view(request, pk=part.pk)

    def neq_rows(self, part):
        template = parameters.get_template(TPL_NEQ)
        return Parameter.objects.filter(
            template=template,
            model_id=part.pk,
        )

    def test_mark_explosive(self):
        part = self.plain_part()
        self.assertFalse(validation.is_explosive_part(part))

        response = self.patch(part, {"is_explosive": True})

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.data["is_explosive"])
        self.assertTrue(validation.is_explosive_part(part))

    def test_set_fields_including_unit_bearing_mass(self):
        part = self.plain_part()

        response = self.patch(
            part,
            {
                "is_explosive": True,
                "neq_per_unit_kg": "500 g",
                "division": "1.4",
                "compatibility_group": "S",
                "un_number": "UN0241",
            },
        )

        self.assertEqual(response.status_code, 200)
        # "500 g" is stored in the template's kg units as 0.5.
        self.assertAlmostEqual(
            parameters.get_parameter_numeric(part, TPL_NEQ), 0.5, places=6
        )
        self.assertEqual(response.data["classification_code"], "1.4S")
        self.assertEqual(response.data["un_number"], "UN0241")
        # The select vocabularies travel with the payload.
        self.assertIn("1.4", response.data["divisions"])
        self.assertIn("S", response.data["compatibility_groups"])

    def test_illegal_combination_rejected_and_rolled_back(self):
        part = self.plain_part()

        response = self.patch(
            part,
            {"is_explosive": True, "division": "1.1", "compatibility_group": "S"},
        )

        self.assertEqual(response.status_code, 400)
        # Nothing from the failed PATCH persisted.
        self.assertIsNone(parameters.get_parameter_value(part, TPL_DIVISION))
        self.assertIsNone(parameters.get_parameter_value(part, TPL_COMPAT))

    def test_unparseable_mass_rejected(self):
        part = self.plain_part()

        response = self.patch(
            part, {"is_explosive": True, "neq_per_unit_kg": "approx 5"}
        )

        self.assertEqual(response.status_code, 400)
        self.assertIsNone(parameters.get_parameter_numeric(part, TPL_NEQ))

    def test_non_admin_patch_forbidden(self):
        part = self.plain_part()

        nonadmin = get_user_model().objects.create_user(
            username="viewer", password="pw", email="v@example.com"
        )
        nonadmin.is_staff = False
        nonadmin.save()

        response = self.patch(part, {"is_explosive": True}, user=nonadmin)

        self.assertEqual(response.status_code, 403)
        self.assertFalse(validation.is_explosive_part(part))

    def test_get_allowed_for_non_admin(self):
        part = self.plain_part()

        nonadmin = get_user_model().objects.create_user(
            username="viewer2", password="pw", email="v2@example.com"
        )
        nonadmin.is_staff = False
        nonadmin.save()

        response = self.get(part, user=nonadmin)

        self.assertEqual(response.status_code, 200)

    def test_repatch_does_not_duplicate_rows(self):
        part = self.plain_part()

        self.patch(part, {"is_explosive": True, "neq_per_unit_kg": "0.5"})
        self.patch(part, {"neq_per_unit_kg": "0.75"})

        self.assertEqual(self.neq_rows(part).count(), 1)
        self.assertAlmostEqual(
            parameters.get_parameter_numeric(part, TPL_NEQ), 0.75, places=6
        )

    def test_missing_template_is_an_error_not_a_silent_noop(self):
        """A PATCH must not report success for a field it could not store."""
        from common.models import ParameterTemplate

        part = self.plain_part()
        ParameterTemplate.objects.filter(name__iexact=TPL_NEQ).delete()

        response = self.patch(part, {"is_explosive": True, "neq_per_unit_kg": "0.5"})

        self.assertEqual(response.status_code, 400)
        self.assertIn("neq_per_unit_kg", response.data)
        self.assertFalse(validation.is_explosive_part(part))

    def test_blank_value_clears_field(self):
        part = self.plain_part()

        self.patch(part, {"is_explosive": True, "un_number": "UN0241"})
        self.assertEqual(parameters.get_parameter_value(part, TPL_UN_NUMBER), "UN0241")

        response = self.patch(part, {"un_number": ""})

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(parameters.get_parameter_value(part, TPL_UN_NUMBER))
