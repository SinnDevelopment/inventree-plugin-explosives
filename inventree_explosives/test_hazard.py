"""Exhaustive tests for the UN Class 1 classification table.

hazard.py has no Django imports, so this module runs standalone:

    python -m unittest inventree_explosives.test_hazard -v

The 78-cell matrix asserts every division/compatibility-group combination against
an independently written expectation, so a single mistyped cell cannot pass
silently.
"""

import unittest

from .constants import COMPATIBILITY_GROUPS, DIVISIONS
from .hazard import (
    LEGAL_COMBINATIONS,
    classification_code,
    is_legal_combination,
    is_valid_un_number,
    legal_groups_for,
)

# An independent transcription of the classification-code table, written out in
# full rather than derived from hazard.py, so that the test genuinely checks the
# implementation instead of restating it.
EXPECTED_CODES = {
    # Division 1.1 - mass explosion hazard
    "1.1A", "1.1B", "1.1C", "1.1D", "1.1E", "1.1F", "1.1G", "1.1J", "1.1L",
    # Division 1.2 - projection hazard
    "1.2B", "1.2C", "1.2D", "1.2E", "1.2F", "1.2G", "1.2H", "1.2J", "1.2K", "1.2L",
    # Division 1.3 - fire hazard
    "1.3C", "1.3F", "1.3G", "1.3H", "1.3J", "1.3K", "1.3L",
    # Division 1.4 - no significant hazard
    "1.4B", "1.4C", "1.4D", "1.4E", "1.4F", "1.4G", "1.4S",
    # Divisions 1.5 / 1.6 - very / extremely insensitive
    "1.5D",
    "1.6N",
}


class ClassificationMatrixTest(unittest.TestCase):
    """Assert all 6 x 13 = 78 cells of the division x group matrix."""

    def test_all_78_cells(self):
        checked = 0

        for division in DIVISIONS:
            for group in COMPATIBILITY_GROUPS:
                code = f"{division}{group}"
                expected_legal = code in EXPECTED_CODES

                self.assertEqual(
                    is_legal_combination(division, group),
                    expected_legal,
                    msg=(
                        f"{code} should be "
                        f"{'LEGAL' if expected_legal else 'ILLEGAL'} but is not"
                    ),
                )
                checked += 1

        self.assertEqual(checked, 78, "matrix must cover every cell")

    def test_exactly_35_legal_codes(self):
        self.assertEqual(len(LEGAL_COMBINATIONS), 35)
        self.assertEqual(len(EXPECTED_CODES), 35)

    def test_named_cases_from_the_spec(self):
        self.assertTrue(is_legal_combination("1.4", "S"), "1.4S is legal")
        self.assertFalse(is_legal_combination("1.1", "S"), "1.1S is not legal")
        self.assertTrue(is_legal_combination("1.3", "F"), "1.3F is legal (easily missed)")
        self.assertFalse(is_legal_combination("1.5", "C"), "1.5 admits D only")
        self.assertTrue(is_legal_combination("1.5", "D"))
        self.assertTrue(is_legal_combination("1.6", "N"), "1.6 admits N only")
        self.assertFalse(is_legal_combination("1.6", "D"))

    def test_group_a_only_in_division_1_1(self):
        self.assertTrue(is_legal_combination("1.1", "A"))
        for division in ["1.2", "1.3", "1.4", "1.5", "1.6"]:
            self.assertFalse(is_legal_combination(division, "A"))

    def test_group_n_only_in_division_1_6(self):
        self.assertTrue(is_legal_combination("1.6", "N"))
        for division in ["1.1", "1.2", "1.3", "1.4", "1.5"]:
            self.assertFalse(is_legal_combination(division, "N"))

    def test_group_s_only_in_division_1_4(self):
        self.assertTrue(is_legal_combination("1.4", "S"))
        for division in ["1.1", "1.2", "1.3", "1.5", "1.6"]:
            self.assertFalse(is_legal_combination(division, "S"))


class NormalisationTest(unittest.TestCase):
    def test_case_and_whitespace_insensitive(self):
        self.assertTrue(is_legal_combination(" 1.4 ", " s "))
        self.assertFalse(is_legal_combination("1.1", "s"))

    def test_incomplete_pair_is_not_illegal(self):
        # Not yet classified is not the same as misclassified.
        self.assertTrue(is_legal_combination("1.1", None))
        self.assertTrue(is_legal_combination(None, "S"))
        self.assertTrue(is_legal_combination(None, None))

    def test_classification_code_rendering(self):
        self.assertEqual(classification_code("1.4", "s"), "1.4S")
        self.assertIsNone(classification_code("1.4", None))
        self.assertIsNone(classification_code(None, "S"))

    def test_legal_groups_for_is_ordered(self):
        self.assertEqual(legal_groups_for("1.1"), list("ABCDEFGJL"))
        self.assertEqual(legal_groups_for("1.3"), list("CFGHJKL"))
        self.assertEqual(legal_groups_for("1.5"), ["D"])
        self.assertEqual(legal_groups_for("9.9"), [])


class UNNumberTest(unittest.TestCase):
    def test_valid(self):
        for value in ["UN0241", "UN0084", "un0241", " UN0001 "]:
            self.assertTrue(is_valid_un_number(value), value)

    def test_invalid(self):
        for value in ["0241", "UN241", "UN02411", "UNXXXX", "", None]:
            self.assertFalse(is_valid_un_number(value), repr(value))


if __name__ == "__main__":
    unittest.main()
