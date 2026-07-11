"""Compliance data exports.

Adds explosive columns to the standard InvenTree export of Parts, StockItems and
StockLocations, so a compliance inventory can be produced from the normal export
UI rather than a bespoke endpoint.

Wired into the plugin as a DataExportMixin — see core.py.
"""

from collections import OrderedDict

from .constants import (
    TPL_COMPAT,
    TPL_DIVISION,
    TPL_GROSS_MASS,
    TPL_NEQ,
    TPL_PSN,
    TPL_UN_NUMBER,
)
from .hazard import classification_code
from .parameters import get_parameter_numeric, get_parameter_value
from .validation import is_explosive_part

# Column key -> header label. Prefixed so they cannot collide with core columns.
PART_COLUMNS = OrderedDict(
    [
        ("explosive", "Explosive"),
        ("explosive_neq_kg", "NEQ per unit (kg)"),
        ("explosive_gross_mass_kg", "Gross mass per unit (kg)"),
        ("explosive_class", "UN classification code"),
        ("explosive_division", "UN hazard division"),
        ("explosive_compat_group", "UN compatibility group"),
        ("explosive_un_number", "UN number"),
        ("explosive_psn", "Proper shipping name"),
    ]
)

STOCK_COLUMNS = OrderedDict(
    [
        *PART_COLUMNS.items(),
        ("explosive_neq_total_kg", "NEQ total (kg)"),
        ("explosive_gross_mass_total_kg", "Gross mass total (kg)"),
    ]
)

LOCATION_COLUMNS = OrderedDict(
    [
        ("explosive_neq_kg", "NEQ held (kg)"),
        ("explosive_limit_kg", "Licensed NEQ limit (kg)"),
        ("explosive_utilisation", "Licence utilisation (%)"),
        ("explosive_over_limit", "Over limit"),
    ]
)


def columns_for(model_class) -> OrderedDict:
    """The explosive columns applicable to a model, or empty if none are."""
    from part.models import Part
    from stock.models import StockItem, StockLocation

    if issubclass(model_class, StockItem):
        return STOCK_COLUMNS
    if issubclass(model_class, StockLocation):
        return LOCATION_COLUMNS
    if issubclass(model_class, Part):
        return PART_COLUMNS

    return OrderedDict()


def part_row(part) -> dict:
    """Explosive columns for one Part."""
    if not is_explosive_part(part):
        return {"explosive": False}

    division = get_parameter_value(part, TPL_DIVISION)
    group = get_parameter_value(part, TPL_COMPAT)

    return {
        "explosive": True,
        "explosive_neq_kg": get_parameter_numeric(part, TPL_NEQ),
        "explosive_gross_mass_kg": get_parameter_numeric(part, TPL_GROSS_MASS),
        "explosive_class": classification_code(division, group),
        "explosive_division": division,
        "explosive_compat_group": group,
        "explosive_un_number": get_parameter_value(part, TPL_UN_NUMBER),
        "explosive_psn": get_parameter_value(part, TPL_PSN),
    }


def stock_item_row(stock_item) -> dict:
    """Explosive columns for one StockItem, including its NEQ contribution."""
    row = part_row(stock_item.part)

    if not row.get("explosive"):
        return row

    quantity = float(stock_item.quantity)

    neq = row.get("explosive_neq_kg")
    gross = row.get("explosive_gross_mass_kg")

    row["explosive_neq_total_kg"] = (neq * quantity) if neq is not None else None
    row["explosive_gross_mass_total_kg"] = (
        (gross * quantity) if gross is not None else None
    )

    return row


def location_row(location, include_sublocations=True, count_all_present=True) -> dict:
    """Explosive columns for one StockLocation."""
    from . import neq as neq_module

    summary = neq_module.location_summary(
        location,
        include_sublocations=include_sublocations,
        count_all_present=count_all_present,
    )

    utilisation = summary["utilisation"]

    return {
        "explosive_neq_kg": summary["neq_kg"],
        "explosive_limit_kg": summary["limit_kg"],
        "explosive_utilisation": (
            round(utilisation * 100, 1) if utilisation is not None else None
        ),
        "explosive_over_limit": summary["over_limit"],
    }


def row_for(
    instance, include_sublocations: bool = True, count_all_present: bool = True
) -> dict:
    """Explosive columns for any supported instance.

    The location columns depend on the plugin's accounting settings, so callers
    must thread them through — otherwise a CSV export reports different totals
    than the UI for the same magazine.
    """
    from part.models import Part
    from stock.models import StockItem, StockLocation

    if isinstance(instance, StockItem):
        return stock_item_row(instance)
    if isinstance(instance, StockLocation):
        return location_row(instance, include_sublocations, count_all_present)
    if isinstance(instance, Part):
        return part_row(instance)

    return {}
