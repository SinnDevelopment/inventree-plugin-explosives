"""Net explosive quantity aggregation.

Units: the NEQ template is declared in kg, and InvenTree stores
Parameter.data_numeric in the template's declared units (pint converts on the way
in, so "500 g" is stored as 0.5). data_numeric is therefore already kilograms and
can be summed directly. If test_neq.UnitConversionTest ever fails, every total in
this module is wrong and needs a scale factor.

Which stock counts: NEQ is a question about what is physically in the magazine,
not what is available to sell. See present_stock_filter().
"""

from django.db.models import F, FloatField, OuterRef, Q, Subquery, Sum
from django.db.models.functions import Cast, Coalesce

from .constants import (
    TPL_COMPAT,
    TPL_DIVISION,
    TPL_EXPLOSIVE,
    TPL_GROSS_MASS,
    TPL_MAX_NEQ,
    TPL_NEQ,
    TPL_UN_NUMBER,
)
from .hazard import classification_code
from .parameters import get_parameter_numeric, get_template


def present_stock_filter(count_all_present: bool = True) -> Q:
    """Stock that is physically present in its location.

    Deliberately NOT StockItem.IN_STOCK_FILTER. That filter restricts to
    StockStatusGroups.AVAILABLE_CODES (OK, ATTENTION, DAMAGED), which would
    silently exclude QUARANTINED and REJECTED stock. A quarantined detonator is
    still sitting in the magazine and still counts against the licence.

    Set count_all_present=False to fall back to InvenTree's availability
    semantics, for sites that account differently.
    """
    from stock.models import StockItem
    from stock.status_codes import StockStatus

    if not count_all_present:
        return StockItem.IN_STOCK_FILTER

    present = Q(
        quantity__gt=0,
        sales_order=None,
        belongs_to=None,
        customer=None,
        consumed_by=None,
        is_building=False,
    )

    gone = Q(status__in=[StockStatus.DESTROYED.value, StockStatus.LOST.value])

    return present & ~gone


def _part_parameter_subquery(template, numeric: bool = True):
    """A Subquery pulling one parameter value from the StockItem's Part.

    A Subquery rather than a filter + F() across `parameters_list`: that relation
    is multi-valued, so Django may emit a second JOIN and multiply rows, double
    counting the NEQ. The subquery yields exactly one row per part, or NULL.
    """
    from common.models import Parameter
    from django.contrib.contenttypes.models import ContentType
    from part.models import Part

    if template is None:
        return None

    field = "data_numeric" if numeric else "data"

    return Subquery(
        Parameter.objects.filter(
            template=template,
            model_type=ContentType.objects.get_for_model(Part),
            model_id=OuterRef("part_id"),
        ).values(field)[:1],
        output_field=FloatField() if numeric else None,
    )


def neq_annotated_items(locations=None, count_all_present: bool = True):
    """StockItems annotated with neq_per_unit, neq_total and gross_total (all kg).

    Only parts flagged Explosive with an NEQ value count, matching the limit
    check and the exports. A malformed NEQ (data_numeric NULL) silently
    under-counts, which is why validation refuses to store one.
    """
    from stock.models import StockItem

    neq_template = get_template(TPL_NEQ)
    explosive_template = get_template(TPL_EXPLOSIVE)

    if neq_template is None or explosive_template is None:
        # Not bootstrapped yet. config_errors() surfaces the reason in the UI.
        return StockItem.objects.none()

    queryset = StockItem.objects.filter(present_stock_filter(count_all_present))

    if locations is not None:
        queryset = queryset.filter(location__in=locations)

    queryset = queryset.annotate(
        is_explosive=_part_parameter_subquery(explosive_template),  # checkbox: 1 / 0
        neq_per_unit=_part_parameter_subquery(neq_template),
    ).filter(is_explosive=1, neq_per_unit__isnull=False)

    # StockItem.quantity is a Decimal and data_numeric is a Float; multiplying
    # them directly raises on PostgreSQL.
    queryset = queryset.annotate(
        neq_total=Cast("quantity", FloatField()) * F("neq_per_unit"),
    )

    gross_template = get_template(TPL_GROSS_MASS)

    if gross_template is not None:
        queryset = queryset.annotate(
            gross_per_unit=_part_parameter_subquery(gross_template),
        ).annotate(
            gross_total=Cast("quantity", FloatField())
            * Coalesce(F("gross_per_unit"), 0.0, output_field=FloatField()),
        )

    # Annotated, not read per row: _item_dict() would otherwise cost a query
    # per field per stock item, which a magazine summary pays N times over.
    for alias, name in (
        ("division", TPL_DIVISION),
        ("compatibility_group", TPL_COMPAT),
        ("un_number", TPL_UN_NUMBER),
    ):
        template = get_template(name)

        if template is not None:
            queryset = queryset.annotate(
                **{alias: _part_parameter_subquery(template, numeric=False)}
            )

    return queryset


def _locations_for(location, include_sublocations: bool = True):
    """The location, plus its descendants if requested (StockLocation is MPTT)."""
    if include_sublocations:
        return location.get_descendants(include_self=True)

    return [location]


def location_neq(
    location, include_sublocations: bool = True, count_all_present: bool = True
) -> float:
    """Total NEQ in kg physically held in `location` (and its sublocations)."""
    items = neq_annotated_items(
        _locations_for(location, include_sublocations), count_all_present
    )

    return items.aggregate(
        total=Coalesce(
            Sum("neq_total", output_field=FloatField()), 0.0, output_field=FloatField()
        )
    )["total"]


def location_limit(location) -> float | None:
    """The licensed maximum NEQ for this location, or None if unlicensed."""
    return get_parameter_numeric(location, TPL_MAX_NEQ)


def location_summary(
    location, include_sublocations: bool = True, count_all_present: bool = True
) -> dict:
    """Everything the location panel and the magazine register report need."""
    items = list(
        neq_annotated_items(
            _locations_for(location, include_sublocations), count_all_present
        ).select_related("part", "location")
    )

    neq_kg = sum(item.neq_total or 0.0 for item in items)
    gross_kg = sum(getattr(item, "gross_total", 0.0) or 0.0 for item in items)

    # A limit of 0 ("no explosives permitted") is not the same as no limit set.
    limit_kg = location_limit(location)
    licensed = limit_kg is not None

    by_division: dict[str, float] = {}

    for item in items:
        division = getattr(item, "division", None) or "unclassified"
        by_division[division] = by_division.get(division, 0.0) + (item.neq_total or 0.0)

    return {
        "location_id": location.pk,
        "location_name": location.name,
        "neq_kg": neq_kg,
        "gross_mass_kg": gross_kg,
        "limit_kg": limit_kg,
        # Against a 0 kg limit, utilisation is undefined rather than 0.
        "utilisation": (neq_kg / limit_kg) if licensed and limit_kg else None,
        "over_limit": licensed and neq_kg > limit_kg,
        "include_sublocations": include_sublocations,
        "by_division": dict(sorted(by_division.items())),
        "items": [_item_dict(item) for item in items],
    }


def _item_dict(item) -> dict:
    division = getattr(item, "division", None)
    group = getattr(item, "compatibility_group", None)

    return {
        "stock_item_id": item.pk,
        "part_id": item.part_id,
        "part_name": item.part.name,
        "location_id": item.location_id,
        "location_name": item.location.name if item.location else None,
        "quantity": float(item.quantity),
        "neq_per_unit_kg": item.neq_per_unit,
        "neq_total_kg": item.neq_total,
        "division": division,
        "compatibility_group": group,
        "classification_code": classification_code(division, group),
        "un_number": getattr(item, "un_number", None),
    }


class LimitBreach:
    """A magazine that is, or would be, over its licensed NEQ."""

    def __init__(self, location, current: float, prospective: float, limit: float):
        self.location = location
        self.current = current
        self.prospective = prospective
        self.limit = limit

    @property
    def excess(self) -> float:
        return self.prospective - self.limit

    def __str__(self) -> str:
        return (
            f"Location '{self.location}' would hold {self.prospective:.3f} kg NEQ, "
            f"exceeding its licensed limit of {self.limit:.3f} kg "
            f"by {self.excess:.3f} kg"
        )


def is_present(stock_item, count_all_present: bool = True) -> bool:
    """Python mirror of present_stock_filter(), for an unsaved instance.

    check_prospective_limit() must judge an item's proposed state before it is
    saved, which a queryset filter cannot do. Keep the two rules in step;
    test_limits.PresentStockPredicateTest asserts they agree.
    """
    from stock.status_codes import StockStatus, StockStatusGroups

    if stock_item.quantity is None or float(stock_item.quantity) <= 0:
        return False

    if any(
        [
            stock_item.sales_order_id,
            stock_item.belongs_to_id,
            stock_item.customer_id,
            stock_item.consumed_by_id,
            stock_item.is_building,
        ]
    ):
        return False

    if count_all_present:
        return stock_item.status not in [
            StockStatus.DESTROYED.value,
            StockStatus.LOST.value,
        ]

    return stock_item.status in StockStatusGroups.AVAILABLE_CODES


def licensed_ancestors(location, include_sublocations: bool = True) -> list:
    """Every location whose licence this location's stock counts against.

    Stock in a sublocation rolls up into its parent's total, so a magazine's
    licence applies to stock placed anywhere beneath it, not only to stock placed
    in the magazine itself.

    When sublocations are not counted, only the location itself is relevant.
    """
    if not include_sublocations:
        return [location] if location_limit(location) is not None else []

    return [
        ancestor
        for ancestor in location.get_ancestors(include_self=True)
        if location_limit(ancestor) is not None
    ]


def check_prospective_limit(
    stock_item, include_sublocations: bool = True, count_all_present: bool = True
) -> LimitBreach | None:
    """Would saving `stock_item` push any magazine over its licensed NEQ?

    This runs before the save (PluginValidationMixin.save() calls plugin
    validation ahead of super().save()), so the database still holds the item's
    old quantity, location and status. The total must therefore be reconstructed:

        prospective = current_total
                    - this item's stale contribution to that total
                    + this item's proposed contribution

    The check runs for every ancestor magazine, not just the item's own location,
    because totals roll up (see licensed_ancestors).

    The stale contribution is subtracted only if the old row actually counted
    toward the total: a row that was LOST, or assigned to a customer, was never in
    `current`, and subtracting it would let the item return to countable stock for
    free.

    Returns the worst breach found, or None.
    """
    location = stock_item.location

    if location is None:
        return None

    neq_per_unit = get_parameter_numeric(stock_item.part, TPL_NEQ)

    if not neq_per_unit:
        return None

    from stock.models import StockItem

    previous = (
        StockItem.objects.filter(pk=stock_item.pk).first() if stock_item.pk else None
    )

    # The stale contribution is what the *stored* row added to `current`, so it
    # is priced with the part that row held. Using the proposed part's NEQ would
    # subtract a quantity that was never in the total when the part changed.
    previous_neq_per_unit = (
        neq_per_unit
        if previous is None or previous.part_id == stock_item.part_id
        else (get_parameter_numeric(previous.part, TPL_NEQ) or 0.0)
    )

    proposed = (
        float(stock_item.quantity) * neq_per_unit
        if is_present(stock_item, count_all_present)
        else 0.0
    )

    breaches = []

    for magazine in licensed_ancestors(location, include_sublocations):
        _lock_magazine(magazine)

        limit = location_limit(magazine)
        current = location_neq(magazine, include_sublocations, count_all_present)

        stale = 0.0

        if (
            previous is not None
            and previous.location_id is not None
            # A row that did not count toward `current` must not be subtracted.
            and is_present(previous, count_all_present)
            and _within_scope(magazine, previous.location_id, include_sublocations)
        ):
            stale = float(previous.quantity) * previous_neq_per_unit

        prospective = current - stale + proposed

        if prospective > limit:
            breaches.append(LimitBreach(magazine, current, prospective, limit))

    if not breaches:
        return None

    return max(breaches, key=lambda breach: breach.excess)


def _lock_magazine(magazine) -> bool:
    """Serialise concurrent limit checks against one magazine.

    The check is read-then-write: it totals what the magazine holds, and the
    caller then saves. Two transfers into the same magazine that both read the
    pre-move total can both be judged compliant and together breach the licence.

    Taking a row lock on the magazine before reading the total closes that
    window, because the lock is held until the surrounding transaction commits
    — which is after the save the check is guarding.

    That only works inside a transaction. Outside one there is nothing to hold
    the lock, and SELECT ... FOR UPDATE raises; the check then runs unprotected
    and the post-event magazine audit remains the backstop. Returns whether the
    lock was actually taken, so callers can be tested on both paths.
    """
    from django.db import connection
    from stock.models import StockLocation

    if not connection.in_atomic_block:
        return False

    # Databases without row locking (sqlite) cannot take it; they also serialise
    # writers, which gives the same protection by other means.
    if not connection.features.has_select_for_update:
        return False

    # Evaluated, not just built: the lock is taken when the query runs, and held
    # until the surrounding transaction commits.
    list(
        StockLocation.objects.select_for_update()
        .filter(pk=magazine.pk)
        .values_list("pk", flat=True)
    )

    return True


def _within_scope(magazine, location_id: int, include_sublocations: bool) -> bool:
    """Is `location_id` inside the total that `magazine` reports?"""
    if location_id == magazine.pk:
        return True

    if not include_sublocations:
        return False

    return magazine.get_descendants().filter(pk=location_id).exists()


def licensed_location_queryset():
    """Every StockLocation that actually has a licensed limit stored.

    Filtered on the stored value, not merely on the presence of a parameter row:
    a row whose value is blank is not a licence, and treating it as one puts a
    magazine with no limit on the dashboard.
    """
    from stock.models import StockLocation

    template = get_template(TPL_MAX_NEQ)

    if template is None:
        return StockLocation.objects.none()

    return StockLocation.objects.filter(
        parameters_list__template=template,
        parameters_list__data_numeric__isnull=False,
    ).distinct()


def location_totals(
    include_sublocations: bool = True, count_all_present: bool = True
) -> list[dict]:
    """Held-versus-licensed totals for every licensed magazine.

    The cheap counterpart to licensed_locations(): no per-item detail, so the
    cost is a fixed handful of queries per magazine rather than one per stock
    item. Used by the post-event audit, which runs on every stock movement and
    only needs to know whether a magazine is over its licence.
    """
    totals = []

    for location in licensed_location_queryset():
        limit_kg = location_limit(location)

        if limit_kg is None:
            continue

        neq_kg = location_neq(location, include_sublocations, count_all_present)

        totals.append({
            "location_id": location.pk,
            "location_name": location.name,
            "neq_kg": neq_kg,
            "limit_kg": limit_kg,
            "over_limit": neq_kg > limit_kg,
        })

    return totals


def licensed_locations(
    include_sublocations: bool = True, count_all_present: bool = True
) -> list[dict]:
    """Summaries for every location that has a licensed NEQ limit set.

    Backs the dashboard item, the summary endpoint and the post-event audit. All
    of them must use the same accounting rules as the location panel, or the
    dashboard reports a breach the panel says does not exist.
    """
    summaries = [
        location_summary(
            location,
            include_sublocations=include_sublocations,
            count_all_present=count_all_present,
        )
        for location in licensed_location_queryset()
    ]

    # Breached first, then by utilisation: a 0 kg limit has a null utilisation
    # but still belongs at the top when anything is stored there.
    return sorted(
        summaries,
        key=lambda summary: (summary["over_limit"], summary["utilisation"] or 0.0),
        reverse=True,
    )
