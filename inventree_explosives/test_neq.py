"""NEQ aggregation.

Run from an InvenTree checkout:

    invoke dev.test -r inventree_explosives.test_neq

UnitConversionTest is the one to look at first: every total this plugin reports
assumes a parameter declared in kg stores its numeric value in kg, so that "500 g"
becomes 0.5 and quantities can simply be summed. If that assumption is wrong,
every number the plugin produces is wrong.
"""

from django.core.exceptions import ValidationError

from InvenTree.unit_test import InvenTreeTestCase

from part.models import Part, PartCategory
from stock.models import StockItem, StockLocation
from stock.status_codes import StockStatus

from . import neq, parameters
from .constants import (
    TPL_COMPAT,
    TPL_DIVISION,
    TPL_EXPLOSIVE,
    TPL_MAX_NEQ,
    TPL_NEQ,
)


class ExplosivesTestCase(InvenTreeTestCase):
    """Shared fixtures: an active plugin, bootstrapped templates, a magazine."""

    def setUp(self):
        super().setUp()

        # The plugin must be registered and active, or its validation hooks never
        # fire and these tests pass vacuously.
        from plugin.registry import registry

        registry.reload_plugins(full_reload=True, collect=True)
        registry.set_plugin_state("explosives", True)

        self.plugin = registry.get_plugin("explosives")
        self.assertIsNotNone(self.plugin, "explosives plugin failed to load")

        parameters.ensure_parameter_templates()

        self.category = PartCategory.objects.create(name="Explosives")

        self.magazine = StockLocation.objects.create(name="Magazine 1")

    def set_parameter(self, instance, template_name, value, validate=True):
        """Set a parameter value on a Part or StockLocation.

        full_clean() is called because InvenTree runs the plugin
        `validate_parameter` hook from Parameter.clean(), not from save(). The REST
        API and the UI forms both call it; a test that only called save() would
        bypass validation entirely.
        """
        from common.models import Parameter
        from django.contrib.contenttypes.models import ContentType

        template = parameters.get_template(template_name)
        self.assertIsNotNone(template, f"parameter template '{template_name}' missing")

        parameter, _ = Parameter.objects.get_or_create(
            template=template,
            model_type=ContentType.objects.get_for_model(instance),
            model_id=instance.pk,
        )
        parameter.data = str(value)

        if validate:
            parameter.full_clean()

        parameter.save()

        return parameter

    def make_explosive_part(self, name="Booster", neq_kg="0.5", validate=True, **kwargs):
        """Create an explosive part.

        Pass validate=False to write values the plugin would normally reject —
        needed to simulate pre-existing bad data, e.g. rows that were created
        before this plugin was installed.
        """
        part = Part.objects.create(
            name=name, description=name, category=self.category, active=True
        )

        self.set_parameter(part, TPL_EXPLOSIVE, True, validate=validate)

        if neq_kg is not None:
            self.set_parameter(part, TPL_NEQ, neq_kg, validate=validate)

        for template_name, value in kwargs.items():
            self.set_parameter(part, template_name, value, validate=validate)

        return part

    def add_stock(self, part, quantity, location=None, status=None):
        item = StockItem.objects.create(
            part=part,
            quantity=quantity,
            location=location or self.magazine,
        )

        if status is not None:
            item.status = status
            item.save()

        return item


class UnitConversionTest(ExplosivesTestCase):
    """The assumption everything else rests on."""

    def test_unit_conversion_to_kg(self):
        """A value entered in grams must be stored as kilograms.

        The NEQ template declares units='kg', and InvenTree stores data_numeric in
        the template's declared units, so "500 g" must land as 0.5, not 500.
        """
        part = self.make_explosive_part(neq_kg=None)

        parameter = self.set_parameter(part, TPL_NEQ, "500 g")
        parameter.refresh_from_db()

        self.assertAlmostEqual(
            parameter.data_numeric,
            0.5,
            places=6,
            msg=(
                "A parameter declared in kg did not store grams as kilograms. "
                "Every NEQ total in neq.py is therefore wrong and needs a unit "
                "conversion step."
            ),
        )

    def test_plain_value_is_taken_as_kg(self):
        part = self.make_explosive_part(neq_kg=None)

        parameter = self.set_parameter(part, TPL_NEQ, "2.5")
        parameter.refresh_from_db()

        self.assertAlmostEqual(parameter.data_numeric, 2.5, places=6)

    def test_grams_aggregate_correctly(self):
        """The conversion must survive all the way through aggregation."""
        part = self.make_explosive_part(neq_kg="500 g")

        self.add_stock(part, 10)

        # 10 units x 500 g = 5 kg, not 5000.
        self.assertAlmostEqual(neq.location_neq(self.magazine), 5.0, places=6)


class LocationAggregationTest(ExplosivesTestCase):
    def test_simple_total(self):
        part = self.make_explosive_part(neq_kg="0.5")
        self.add_stock(part, 80)

        self.assertAlmostEqual(neq.location_neq(self.magazine), 40.0, places=6)

    def test_multiple_items_and_parts(self):
        booster = self.make_explosive_part(name="Booster", neq_kg="0.5")
        detonator = self.make_explosive_part(name="Detonator", neq_kg="0.001")

        self.add_stock(booster, 80)  # 40 kg
        self.add_stock(booster, 20)  # 10 kg
        self.add_stock(detonator, 1000)  # 1 kg

        self.assertAlmostEqual(neq.location_neq(self.magazine), 51.0, places=6)

    def test_sublocations_included(self):
        inner = StockLocation.objects.create(name="Bay A", parent=self.magazine)

        part = self.make_explosive_part(neq_kg="0.5")
        self.add_stock(part, 10, location=self.magazine)  # 5 kg
        self.add_stock(part, 10, location=inner)  # 5 kg

        self.assertAlmostEqual(neq.location_neq(self.magazine), 10.0, places=6)
        self.assertAlmostEqual(neq.location_neq(inner), 5.0, places=6)

    def test_sublocations_excluded_when_disabled(self):
        inner = StockLocation.objects.create(name="Bay A", parent=self.magazine)

        part = self.make_explosive_part(neq_kg="0.5")
        self.add_stock(part, 10, location=self.magazine)
        self.add_stock(part, 10, location=inner)

        self.assertAlmostEqual(
            neq.location_neq(self.magazine, include_sublocations=False), 5.0, places=6
        )

    def test_part_without_neq_contributes_nothing(self):
        """A part with no NEQ must not crash the query, or count as anything."""
        explosive = self.make_explosive_part(name="Booster", neq_kg="0.5")
        inert = Part.objects.create(
            name="Cardboard box", description="inert", category=self.category
        )

        self.add_stock(explosive, 10)  # 5 kg
        self.add_stock(inert, 500)  # nothing

        self.assertAlmostEqual(neq.location_neq(self.magazine), 5.0, places=6)

    def test_no_stock_is_zero_not_none(self):
        self.assertEqual(neq.location_neq(self.magazine), 0.0)

    def test_single_join_no_double_counting(self):
        """A part carrying several parameters must not multiply its own rows.

        `parameters_list` is a multi-valued relation, so a filter+F() query would
        count this item once per parameter.
        """
        part = self.make_explosive_part(
            neq_kg="0.5",
            **{TPL_DIVISION: "1.1", TPL_COMPAT: "D"},
        )
        self.add_stock(part, 10)

        # 10 x 0.5 = 5 kg exactly, regardless of how many parameters the part has.
        self.assertAlmostEqual(neq.location_neq(self.magazine), 5.0, places=6)


class StockStatusTest(ExplosivesTestCase):
    """Which stock counts against a licence."""

    def test_quarantined_stock_is_counted(self):
        """Quarantined stock is still physically in the magazine."""
        part = self.make_explosive_part(neq_kg="0.5")
        self.add_stock(part, 10, status=StockStatus.QUARANTINED.value)

        self.assertAlmostEqual(neq.location_neq(self.magazine), 5.0, places=6)

    def test_rejected_stock_is_counted(self):
        part = self.make_explosive_part(neq_kg="0.5")
        self.add_stock(part, 10, status=StockStatus.REJECTED.value)

        self.assertAlmostEqual(neq.location_neq(self.magazine), 5.0, places=6)

    def test_destroyed_stock_is_not_counted(self):
        part = self.make_explosive_part(neq_kg="0.5")
        self.add_stock(part, 10, status=StockStatus.DESTROYED.value)

        self.assertEqual(neq.location_neq(self.magazine), 0.0)

    def test_lost_stock_is_not_counted(self):
        part = self.make_explosive_part(neq_kg="0.5")
        self.add_stock(part, 10, status=StockStatus.LOST.value)

        self.assertEqual(neq.location_neq(self.magazine), 0.0)

    def test_availability_semantics_excludes_quarantined(self):
        """With count_all_present=False we fall back to InvenTree's availability."""
        part = self.make_explosive_part(neq_kg="0.5")
        self.add_stock(part, 10, status=StockStatus.QUARANTINED.value)

        self.assertEqual(
            neq.location_neq(self.magazine, count_all_present=False), 0.0
        )


class LimitTest(ExplosivesTestCase):
    def set_limit(self, location, limit_kg):
        return self.set_parameter(location, TPL_MAX_NEQ, limit_kg)

    def test_location_limit_read(self):
        self.set_limit(self.magazine, "50")

        self.assertAlmostEqual(neq.location_limit(self.magazine), 50.0, places=6)

    def test_unlicensed_location_has_no_limit(self):
        self.assertIsNone(neq.location_limit(self.magazine))

    def test_summary_reports_over_limit(self):
        self.set_limit(self.magazine, "50")

        part = self.make_explosive_part(neq_kg="0.5")
        self.add_stock(part, 120)  # 60 kg against a 50 kg licence

        summary = neq.location_summary(self.magazine)

        self.assertAlmostEqual(summary["neq_kg"], 60.0, places=6)
        self.assertAlmostEqual(summary["limit_kg"], 50.0, places=6)
        self.assertTrue(summary["over_limit"])
        self.assertAlmostEqual(summary["utilisation"], 1.2, places=6)

    def test_summary_within_limit(self):
        self.set_limit(self.magazine, "50")

        part = self.make_explosive_part(neq_kg="0.5")
        self.add_stock(part, 80)  # 40 kg

        summary = neq.location_summary(self.magazine)

        self.assertFalse(summary["over_limit"])
        self.assertAlmostEqual(summary["utilisation"], 0.8, places=6)

    def test_prospective_limit_new_item(self):
        """A brand new item that would breach is caught before it is saved."""
        self.set_limit(self.magazine, "50")

        part = self.make_explosive_part(neq_kg="0.5")
        self.add_stock(part, 80)  # 40 kg already present

        # Proposing another 40 units = 20 kg -> 60 kg total, over the 50 kg limit.
        proposed = StockItem(part=part, quantity=40, location=self.magazine)

        breach = neq.check_prospective_limit(proposed)

        self.assertIsNotNone(breach)
        self.assertAlmostEqual(breach.prospective, 60.0, places=6)
        self.assertAlmostEqual(breach.limit, 50.0, places=6)

    def test_prospective_limit_within_licence(self):
        self.set_limit(self.magazine, "50")

        part = self.make_explosive_part(neq_kg="0.5")
        self.add_stock(part, 80)  # 40 kg

        proposed = StockItem(part=part, quantity=10, location=self.magazine)  # +5 kg

        self.assertIsNone(neq.check_prospective_limit(proposed))

    def test_prospective_quantity_edit_is_not_double_counted(self):
        """Editing an existing item's quantity must not count its old row twice.

        Validation runs before save, so the database still holds the OLD quantity.
        A naive `current_total + proposed` would see 40 kg + 45 kg = 85 kg and
        wrongly reject. The correct answer subtracts the item's stale row first:
        40 - 40 + 45 = 45 kg, which is inside the 50 kg licence.
        """
        self.set_limit(self.magazine, "50")

        part = self.make_explosive_part(neq_kg="0.5")
        item = self.add_stock(part, 80)  # 40 kg

        item.quantity = 90  # 45 kg -- an increase, but still within the licence

        self.assertIsNone(
            neq.check_prospective_limit(item),
            "editing quantity double-counted the item's existing stock",
        )

    def test_prospective_move_checks_destination_only(self):
        """Moving stock between magazines: only the destination can breach.

        The source magazine only ever gets emptier, and the item's stale row
        belongs to the source, so it must NOT be subtracted from the destination.
        """
        other = StockLocation.objects.create(name="Magazine 2")

        self.set_limit(self.magazine, "50")
        self.set_limit(other, "50")

        part = self.make_explosive_part(neq_kg="0.5")

        # 45 kg already sitting in the destination.
        self.add_stock(part, 90, location=other)

        # 20 kg in the source, about to move into the destination.
        item = self.add_stock(part, 40, location=self.magazine)

        item.location = other  # 45 + 20 = 65 kg, over the 50 kg licence

        breach = neq.check_prospective_limit(item)

        self.assertIsNotNone(breach, "move into a full magazine was not caught")
        self.assertAlmostEqual(breach.prospective, 65.0, places=6)
        self.assertEqual(breach.location.pk, other.pk)

    def test_unlicensed_location_never_breaches(self):
        part = self.make_explosive_part(neq_kg="0.5")
        item = self.add_stock(part, 10000)

        self.assertIsNone(neq.check_prospective_limit(item))

    def test_licensed_locations_sorted_by_utilisation(self):
        other = StockLocation.objects.create(name="Magazine 2")

        self.set_limit(self.magazine, "50")
        self.set_limit(other, "50")

        part = self.make_explosive_part(neq_kg="0.5")
        self.add_stock(part, 20, location=self.magazine)  # 10 kg -> 20%
        self.add_stock(part, 180, location=other)  # 90 kg -> 180%

        summaries = neq.licensed_locations()

        self.assertEqual(len(summaries), 2)
        self.assertEqual(summaries[0]["location_name"], "Magazine 2")
        self.assertTrue(summaries[0]["over_limit"])
        self.assertFalse(summaries[1]["over_limit"])
