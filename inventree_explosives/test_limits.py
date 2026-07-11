"""Edge cases in licence-limit enforcement.

Each test covers a way the limit check could be defeated, and is named for the
failure it prevents.
"""

from django.core.exceptions import ValidationError

from stock.models import StockItem, StockLocation
from stock.status_codes import StockStatus

from . import neq
from .constants import TPL_MAX_NEQ
from .test_neq import ExplosivesTestCase


class SublocationBypassTest(ExplosivesTestCase):
    """A magazine's licence must cover stock stored beneath it.

    Totals roll up from sublocations, so a check that looked only at the item's
    own location could be defeated by storing the explosives one shelf down.
    """

    def setUp(self):
        super().setUp()

        self.set_parameter(self.magazine, TPL_MAX_NEQ, "50")

        # A sublocation with NO licence of its own.
        self.shelf = StockLocation.objects.create(name="Shelf 1", parent=self.magazine)

        self.part = self.make_explosive_part(neq_kg="0.5")

    def test_breach_in_unlicensed_sublocation_is_detected(self):
        proposed = StockItem(part=self.part, quantity=120, location=self.shelf)

        breach = neq.check_prospective_limit(proposed)

        self.assertIsNotNone(
            breach,
            "stock placed in a sublocation evaded the parent magazine's licence",
        )
        self.assertEqual(breach.location.pk, self.magazine.pk)
        self.assertAlmostEqual(breach.prospective, 60.0, places=6)

    def test_block_mode_prevents_the_sublocation_bypass(self):
        self.plugin.set_setting("LIMIT_ACTION", "block")

        with self.assertRaises(ValidationError):
            StockItem.objects.create(
                part=self.part, quantity=120, location=self.shelf
            )

    def test_within_limit_in_sublocation_is_allowed(self):
        self.plugin.set_setting("LIMIT_ACTION", "block")

        item = StockItem.objects.create(
            part=self.part, quantity=80, location=self.shelf
        )  # 40 kg of 50 kg

        self.assertIsNotNone(item.pk)

    def test_sublocation_not_checked_when_setting_disabled(self):
        """With sublocations excluded, the parent's licence does not apply."""
        self.plugin.set_setting("INCLUDE_SUBLOCATIONS", False)

        proposed = StockItem(part=self.part, quantity=120, location=self.shelf)

        self.assertIsNone(
            neq.check_prospective_limit(proposed, include_sublocations=False)
        )


class StaleContributionTest(ExplosivesTestCase):
    """The old row is only subtracted if it actually counted toward the total.

    A row that was LOST or DESTROYED was never in the current total, so
    subtracting it while adding the item's new contribution would let stock return
    to countable status for free.
    """

    def setUp(self):
        super().setUp()

        self.set_parameter(self.magazine, TPL_MAX_NEQ, "100")
        self.part = self.make_explosive_part(neq_kg="1.0")

    def test_restoring_lost_stock_is_checked_against_the_limit(self):
        # 95 kg of countable stock already in the magazine.
        self.add_stock(self.part, 95)

        # A 60 kg item marked LOST: physically written off, not in the total.
        lost = self.add_stock(self.part, 60, status=StockStatus.LOST.value)

        self.assertAlmostEqual(neq.location_neq(self.magazine), 95.0, places=6)

        # Now the item is "found" and returned to OK. It would take the magazine
        # to 155 kg against a 100 kg licence.
        lost.status = StockStatus.OK.value

        breach = neq.check_prospective_limit(lost)

        self.assertIsNotNone(
            breach,
            "restoring lost stock to countable status bypassed the licence check",
        )
        self.assertAlmostEqual(breach.prospective, 155.0, places=6)

    def test_writing_stock_off_never_breaches(self):
        item = self.add_stock(self.part, 95)

        item.status = StockStatus.DESTROYED.value

        # Destroying stock only ever reduces the total.
        self.assertIsNone(neq.check_prospective_limit(item))


class ZeroLimitTest(ExplosivesTestCase):
    """A 0 kg limit means 'no explosives permitted', not 'no limit set'."""

    def setUp(self):
        super().setUp()

        self.no_explosives = StockLocation.objects.create(name="Receiving office")
        self.set_parameter(self.no_explosives, TPL_MAX_NEQ, "0")

        self.part = self.make_explosive_part(neq_kg="0.5")

    def test_any_stock_breaches_a_zero_limit(self):
        proposed = StockItem(part=self.part, quantity=1, location=self.no_explosives)

        breach = neq.check_prospective_limit(proposed)

        self.assertIsNotNone(
            breach, "a 0 kg limit was treated as 'unlicensed' and not enforced"
        )
        self.assertEqual(breach.limit, 0.0)

    def test_block_mode_enforces_a_zero_limit(self):
        self.plugin.set_setting("LIMIT_ACTION", "block")

        with self.assertRaises(ValidationError):
            StockItem.objects.create(
                part=self.part, quantity=1, location=self.no_explosives
            )

    def test_summary_reports_a_zero_limit_as_breached(self):
        self.add_stock(self.part, 10, location=self.no_explosives)

        summary = neq.location_summary(self.no_explosives)

        self.assertEqual(summary["limit_kg"], 0.0)
        self.assertTrue(summary["over_limit"])

    def test_unlicensed_location_is_still_unlicensed(self):
        """An absent limit must remain distinct from a zero limit."""
        summary = neq.location_summary(self.magazine)

        self.assertIsNone(summary["limit_kg"])
        self.assertFalse(summary["over_limit"])


class PresentStockPredicateTest(ExplosivesTestCase):
    """is_present() must agree with present_stock_filter().

    The two encode the same rule, one as a Python predicate for unsaved objects
    and one as a queryset filter. If they drift apart, the prospective limit check
    and the reported total disagree.
    """

    def test_predicate_matches_the_queryset_filter(self):
        part = self.make_explosive_part(neq_kg="1.0")

        statuses = [
            StockStatus.OK.value,
            StockStatus.ATTENTION.value,
            StockStatus.DAMAGED.value,
            StockStatus.QUARANTINED.value,
            StockStatus.REJECTED.value,
            StockStatus.LOST.value,
            StockStatus.DESTROYED.value,
        ]

        for count_all_present in [True, False]:
            for status in statuses:
                item = self.add_stock(part, 1, status=status)

                counted_by_queryset = (
                    StockItem.objects.filter(pk=item.pk)
                    .filter(neq.present_stock_filter(count_all_present))
                    .exists()
                )

                with self.subTest(status=status, count_all=count_all_present):
                    self.assertEqual(
                        neq.is_present(item, count_all_present),
                        counted_by_queryset,
                        "is_present() disagrees with present_stock_filter()",
                    )

                item.delete()


class SettingsConsistencyTest(ExplosivesTestCase):
    """Every surface must report the same numbers under the same settings.

    The dashboard, the summary endpoint and the export must honour
    INCLUDE_SUBLOCATIONS, or they report a breach the location panel denies.
    """

    def setUp(self):
        super().setUp()

        self.set_parameter(self.magazine, TPL_MAX_NEQ, "50")
        self.shelf = StockLocation.objects.create(name="Shelf 1", parent=self.magazine)

        part = self.make_explosive_part(neq_kg="0.5")

        self.add_stock(part, 20, location=self.magazine)  # 10 kg directly
        self.add_stock(part, 180, location=self.shelf)  # 90 kg in the sublocation

    def test_dashboard_agrees_with_panel_when_sublocations_excluded(self):
        self.plugin.set_setting("INCLUDE_SUBLOCATIONS", False)

        panel = self.plugin.location_summary(self.magazine)
        dashboard = self.plugin.licensed_locations()

        self.assertAlmostEqual(panel["neq_kg"], 10.0, places=6)
        self.assertFalse(panel["over_limit"])

        magazine_row = next(
            row for row in dashboard if row["location_id"] == self.magazine.pk
        )

        self.assertAlmostEqual(magazine_row["neq_kg"], panel["neq_kg"], places=6)
        self.assertEqual(magazine_row["over_limit"], panel["over_limit"])

    def test_dashboard_agrees_with_panel_when_sublocations_included(self):
        self.plugin.set_setting("INCLUDE_SUBLOCATIONS", True)

        panel = self.plugin.location_summary(self.magazine)
        dashboard = self.plugin.licensed_locations()

        self.assertAlmostEqual(panel["neq_kg"], 100.0, places=6)
        self.assertTrue(panel["over_limit"])

        magazine_row = next(
            row for row in dashboard if row["location_id"] == self.magazine.pk
        )

        self.assertAlmostEqual(magazine_row["neq_kg"], 100.0, places=6)
        self.assertTrue(magazine_row["over_limit"])
