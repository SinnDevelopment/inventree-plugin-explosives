"""Part validation and the licence-limit enforcement hooks.

The exhaustive division x compatibility-group matrix lives in test_hazard.py.
This module tests that those rules are wired in to InvenTree's validation hooks.
"""

from django.core.exceptions import ValidationError

from stock.models import StockItem, StockLocation

from . import neq, validation
from .constants import (
    TPL_COMPAT,
    TPL_DIVISION,
    TPL_GROSS_MASS,
    TPL_MAX_NEQ,
    TPL_NEQ,
    TPL_UN_NUMBER,
)
from .test_neq import ExplosivesTestCase


class PartValidationTest(ExplosivesTestCase):
    def test_clean_part_has_no_issues(self):
        part = self.make_explosive_part(
            neq_kg="0.5",
            **{
                TPL_GROSS_MASS: "0.8",
                TPL_DIVISION: "1.1",
                TPL_COMPAT: "D",
                TPL_UN_NUMBER: "UN0042",
            },
        )

        self.assertEqual(validation.part_issues(part), [])

    def test_explosive_without_neq_is_flagged(self):
        part = self.make_explosive_part(neq_kg=None)

        issues = validation.part_issues(part, require_neq=True)

        self.assertEqual(len(issues), 1)
        self.assertIn("no net explosive quantity", issues[0])

    def test_explosive_without_neq_allowed_when_not_required(self):
        part = self.make_explosive_part(neq_kg=None)

        self.assertEqual(validation.part_issues(part, require_neq=False), [])

    def test_neq_exceeding_gross_mass_is_flagged(self):
        part = self.make_explosive_part(
            neq_kg="2.0", **{TPL_GROSS_MASS: "1.0"}
        )

        issues = validation.part_issues(part)

        self.assertEqual(len(issues), 1)
        self.assertIn("exceeds gross mass", issues[0])

    def test_neq_equal_to_gross_mass_is_allowed(self):
        # A bare, unpackaged charge: all of its mass is explosive.
        part = self.make_explosive_part(neq_kg="1.0", **{TPL_GROSS_MASS: "1.0"})

        self.assertEqual(validation.part_issues(part), [])

    def test_illegal_classification_code_is_flagged(self):
        # validate=False writes the illegal code directly, simulating data that
        # predates the plugin: rejected on entry, but still reportable.
        part = self.make_explosive_part(
            neq_kg="0.5", validate=False, **{TPL_DIVISION: "1.1", TPL_COMPAT: "S"}
        )

        issues = validation.part_issues(part)

        self.assertEqual(len(issues), 1)
        self.assertIn("1.1S", issues[0])
        self.assertIn("not a valid UN classification code", issues[0])

    def test_legal_classification_code_passes(self):
        part = self.make_explosive_part(
            neq_kg="0.5", **{TPL_DIVISION: "1.4", TPL_COMPAT: "S"}
        )

        self.assertEqual(validation.part_issues(part), [])

    def test_invalid_un_number_is_flagged(self):
        # Pre-existing bad data, as above.
        part = self.make_explosive_part(
            neq_kg="0.5", validate=False, **{TPL_UN_NUMBER: "0241"}
        )

        issues = validation.part_issues(part)

        self.assertEqual(len(issues), 1)
        self.assertIn("not a valid UN number", issues[0])

    def test_non_explosive_part_is_never_flagged(self):
        """Ordinary parts must not be dragged into explosives validation."""
        from part.models import Part

        part = Part.objects.create(
            name="Cardboard box", description="inert", category=self.category
        )

        self.assertEqual(validation.part_issues(part), [])
        self.assertFalse(validation.is_explosive_part(part))

    def test_validate_part_raises(self):
        part = self.make_explosive_part(neq_kg="2.0", **{TPL_GROSS_MASS: "1.0"})

        with self.assertRaises(ValidationError):
            validation.validate_part(part)


class ParameterHookTest(ExplosivesTestCase):
    """The cross-field check must fire when only ONE parameter is edited.

    Editing just the compatibility group does not call Part.save(), so the
    part-level check never runs. Without a check in validate_parameter, a user
    could save an illegal 1.1S simply by setting the division first and the
    group second.
    """

    def test_illegal_combo_rejected_when_editing_group_last(self):
        part = self.make_explosive_part(neq_kg="0.5", **{TPL_DIVISION: "1.1"})

        # Now set an incompatible group on its own. 1.1S is not a legal code.
        with self.assertRaises(ValidationError):
            self.set_parameter(part, TPL_COMPAT, "S")

    def test_illegal_combo_rejected_when_editing_division_last(self):
        part = self.make_explosive_part(neq_kg="0.5", **{TPL_COMPAT: "S"})

        # 1.4S is legal, but 1.1S is not.
        with self.assertRaises(ValidationError):
            self.set_parameter(part, TPL_DIVISION, "1.1")

    def test_legal_combo_accepted_when_editing_group_last(self):
        part = self.make_explosive_part(neq_kg="0.5", **{TPL_DIVISION: "1.4"})

        self.set_parameter(part, TPL_COMPAT, "S")  # 1.4S is legal

        self.assertEqual(validation.part_issues(part), [])

    def test_invalid_un_number_rejected_at_parameter_level(self):
        part = self.make_explosive_part(neq_kg="0.5")

        with self.assertRaises(ValidationError):
            self.set_parameter(part, TPL_UN_NUMBER, "NOTAUN")

    def test_negative_neq_rejected(self):
        part = self.make_explosive_part(neq_kg=None)

        with self.assertRaises(ValidationError):
            self.set_parameter(part, TPL_NEQ, "-5")

    def test_unparseable_neq_is_rejected_not_swallowed(self):
        """An unparseable NEQ must fail loudly, never silently under-count.

        InvenTree stores a value it cannot parse with data_numeric = NULL and the
        aggregation skips NULL rows, so accepting "approx 5" would make every stock
        item of this part contribute 0 kg to its magazine.
        """
        part = self.make_explosive_part(neq_kg=None)

        for bad in ["approx 5", "five kg", "lots"]:
            with self.subTest(value=bad):
                with self.assertRaises(ValidationError):
                    self.set_parameter(part, TPL_NEQ, bad)

    def test_whitespace_neq_is_a_field_error_not_a_crash(self):
        """A whitespace-only value must surface as a validation error on the
        field, not an uncaught exception."""
        part = self.make_explosive_part(neq_kg=None)

        with self.assertRaises(ValidationError):
            self.set_parameter(part, TPL_NEQ, " ")

    def test_unit_bearing_mass_is_accepted(self):
        part = self.make_explosive_part(neq_kg=None)

        self.set_parameter(part, TPL_NEQ, "500 g")

        self.assertAlmostEqual(
            neq.location_neq(self.magazine), 0.0, places=6
        )  # no stock yet, but the value saved

    def test_licence_limit_is_validated(self):
        """The magazine's own limit is a mass too, and was previously unchecked."""
        with self.assertRaises(ValidationError):
            self.set_parameter(self.magazine, TPL_MAX_NEQ, "one hundred")

        with self.assertRaises(ValidationError):
            self.set_parameter(self.magazine, TPL_MAX_NEQ, "-100")


class LimitEnforcementTest(ExplosivesTestCase):
    """warn vs block, at the point a StockItem is saved."""

    def setUp(self):
        super().setUp()

        self.set_parameter(self.magazine, TPL_MAX_NEQ, "50")
        self.part = self.make_explosive_part(neq_kg="0.5")

    def test_block_prevents_the_breaching_save(self):
        self.plugin.set_setting("LIMIT_ACTION", "block")

        self.add_stock(self.part, 80)  # 40 kg, fine

        with self.assertRaises(ValidationError):
            # +20 kg -> 60 kg against a 50 kg licence
            StockItem.objects.create(
                part=self.part, quantity=40, location=self.magazine
            )

    def test_block_allows_a_save_within_the_licence(self):
        self.plugin.set_setting("LIMIT_ACTION", "block")

        self.add_stock(self.part, 80)  # 40 kg

        StockItem.objects.create(part=self.part, quantity=10, location=self.magazine)

        self.assertAlmostEqual(neq.location_neq(self.magazine), 45.0, places=6)

    def test_warn_does_not_prevent_the_save(self):
        self.plugin.set_setting("LIMIT_ACTION", "warn")

        self.add_stock(self.part, 80)

        # Over the licence, but warn mode must not raise.
        item = StockItem.objects.create(
            part=self.part, quantity=40, location=self.magazine
        )

        self.assertIsNotNone(item.pk)

    def test_off_does_not_prevent_the_save(self):
        self.plugin.set_setting("LIMIT_ACTION", "off")

        self.add_stock(self.part, 80)

        item = StockItem.objects.create(
            part=self.part, quantity=1000, location=self.magazine
        )

        self.assertIsNotNone(item.pk)

    def test_non_explosive_stock_is_unaffected_by_block_mode(self):
        """The hook fires on every StockItem.save() — it must not break normal stock."""
        from part.models import Part

        self.plugin.set_setting("LIMIT_ACTION", "block")

        inert = Part.objects.create(
            name="Cardboard box", description="inert", category=self.category
        )

        item = StockItem.objects.create(
            part=inert, quantity=100000, location=self.magazine
        )

        self.assertIsNotNone(item.pk)

    def test_unlicensed_location_is_unaffected_by_block_mode(self):
        self.plugin.set_setting("LIMIT_ACTION", "block")

        unlicensed = StockLocation.objects.create(name="Unlicensed store")

        item = StockItem.objects.create(
            part=self.part, quantity=100000, location=unlicensed
        )

        self.assertIsNotNone(item.pk)
