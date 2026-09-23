"""Tests for the ParameterTemplate bootstrap."""

from common.models import ParameterTemplate
from django.contrib.contenttypes.models import ContentType
from django.db.models.signals import post_save
from InvenTree.unit_test import InvenTreeTestCase

from . import parameters
from .constants import TEMPLATE_COUNT_EXPECTED, TPL_EXPLOSIVE, TPL_NEQ


class BootstrapTest(InvenTreeTestCase):
    def test_creates_all_templates(self):
        result = parameters.ensure_parameter_templates()

        self.assertEqual(len(result["created"]), TEMPLATE_COUNT_EXPECTED)
        self.assertEqual(result["errors"], [])

        for name, _model, _fields in parameters.TEMPLATE_SPECS:
            self.assertIsNotNone(
                parameters.get_template(name), f"template '{name}' was not created"
            )

    def test_neq_template_is_declared_in_kg(self):
        """The unit declaration is load-bearing: data_numeric is stored in it."""
        parameters.ensure_parameter_templates()

        template = parameters.get_template(TPL_NEQ)

        self.assertEqual(template.units, "kg")

    def test_explosive_template_is_a_checkbox(self):
        parameters.ensure_parameter_templates()

        template = parameters.get_template(TPL_EXPLOSIVE)

        self.assertTrue(template.checkbox)
        # A checkbox template must carry no units, or ParameterTemplate.clean()
        # rejects it.
        self.assertFalse(template.units)

    def test_is_idempotent(self):
        first = parameters.ensure_parameter_templates()
        second = parameters.ensure_parameter_templates()

        self.assertEqual(len(first["created"]), TEMPLATE_COUNT_EXPECTED)
        self.assertEqual(second["created"], [])
        self.assertEqual(len(second["existing"]), TEMPLATE_COUNT_EXPECTED)
        self.assertEqual(second["errors"], [])

        self.assertEqual(
            ParameterTemplate.objects.filter(name=TPL_NEQ).count(),
            1,
            "bootstrap created a duplicate template on the second run",
        )

    def test_second_run_issues_no_saves(self):
        """Re-running bootstrap must not re-save existing templates.

        A post_save receiver on ParameterTemplate queues a `rebuild_parameters`
        background task on every update. If bootstrap re-saved its templates on
        each registry reload (as update_or_create would), every reload would
        queue a rebuild for every parameter using them.
        """
        parameters.ensure_parameter_templates()

        saves = []

        def record_save(sender, instance, **kwargs):
            saves.append(instance.name)

        post_save.connect(record_save, sender=ParameterTemplate)

        try:
            parameters.ensure_parameter_templates()
        finally:
            post_save.disconnect(record_save, sender=ParameterTemplate)

        self.assertEqual(
            saves,
            [],
            f"bootstrap re-saved templates on a second run: {saves}. "
            f"This would queue a parameter rebuild on every plugin reload.",
        )

    def test_preexisting_template_is_not_mutated(self):
        """A colliding template is reported, never silently overwritten.

        ParameterTemplate.name is globally unique and case-insensitive. If a site
        already has a 'Net Explosive Quantity' declared in grams, silently
        adopting it would make every total wrong by a factor of 1000 — so we
        refuse to touch it and raise a config error instead.
        """
        existing = ParameterTemplate.objects.create(
            name="net explosive quantity",  # different case, same name
            units="g",
            model_type=ContentType.objects.get(app_label="part", model="part"),
        )

        result = parameters.ensure_parameter_templates()

        existing.refresh_from_db()

        self.assertEqual(existing.units, "g", "pre-existing template was mutated")
        self.assertNotIn(TPL_NEQ, result["created"])

        self.assertTrue(
            any("Net Explosive Quantity" in error for error in result["errors"]),
            f"a units collision was not reported: {result['errors']}",
        )

    def test_config_errors_reports_missing_templates(self):
        errors = parameters.config_errors()

        self.assertEqual(len(errors), TEMPLATE_COUNT_EXPECTED)
        self.assertTrue(all("missing" in error for error in errors))

    def test_config_errors_clean_after_bootstrap(self):
        parameters.ensure_parameter_templates()

        self.assertEqual(parameters.config_errors(), [])

    def test_status_not_ready_when_templates_missing(self):
        status = parameters.status()

        self.assertFalse(status["ready"])
        self.assertEqual(len(status["errors"]), TEMPLATE_COUNT_EXPECTED)
        self.assertEqual(len(status["templates"]), TEMPLATE_COUNT_EXPECTED)
        self.assertTrue(all(not t["present"] for t in status["templates"]))
        self.assertTrue(all(not t["ok"] for t in status["templates"]))

    def test_status_ready_after_bootstrap(self):
        parameters.ensure_parameter_templates()

        status = parameters.status()

        self.assertTrue(status["ready"])
        self.assertEqual(status["errors"], [])
        self.assertTrue(all(t["present"] and t["ok"] for t in status["templates"]))

    def test_status_flags_a_misconfigured_template(self):
        """A colliding template declared in the wrong units is not 'ok'."""
        ParameterTemplate.objects.create(
            name=TPL_NEQ,
            units="g",  # plugin requires kg
            model_type=ContentType.objects.get(app_label="part", model="part"),
        )

        parameters.ensure_parameter_templates()

        status = parameters.status()

        self.assertFalse(status["ready"])

        neq = next(t for t in status["templates"] if t["name"] == TPL_NEQ)
        self.assertTrue(neq["present"])
        self.assertFalse(neq["ok"])


class TemplateCacheTest(InvenTreeTestCase):
    """Templates are memoised, and the memo must not outlive the truth.

    Every parameter read resolves its template by name, so an uncached lookup
    costs a query per field per row. The cache is only safe while a template
    that is renamed, re-declared or deleted invalidates it.
    """

    def setUp(self):
        super().setUp()

        parameters.clear_template_cache()
        parameters.connect_cache_invalidation()
        parameters.ensure_parameter_templates()

    def test_repeat_lookups_do_not_query(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        parameters.get_template(TPL_NEQ)

        with CaptureQueriesContext(connection) as queries:
            for _ in range(5):
                parameters.get_template(TPL_NEQ)

        self.assertEqual(len(queries), 0)

    def test_deleting_a_template_invalidates_the_cache(self):
        self.assertIsNotNone(parameters.get_template(TPL_NEQ))

        ParameterTemplate.objects.filter(name__iexact=TPL_NEQ).delete()

        self.assertIsNone(
            parameters.get_template(TPL_NEQ),
            "a deleted template was still served from the cache",
        )

    def test_renaming_a_template_invalidates_the_cache(self):
        self.assertIsNotNone(parameters.get_template(TPL_NEQ))

        template = ParameterTemplate.objects.get(name__iexact=TPL_NEQ)
        template.name = "Something else entirely"
        template.save()

        self.assertIsNone(parameters.get_template(TPL_NEQ))

    def test_health_checks_read_through_the_cache(self):
        """status() must report the database, not a remembered lookup."""
        ParameterTemplate.objects.filter(name__iexact=TPL_NEQ).delete()

        report = parameters.status()

        missing = [t for t in report["templates"] if not t["present"]]

        self.assertEqual([t["name"] for t in missing], [TPL_NEQ])
        self.assertFalse(report["ready"])

