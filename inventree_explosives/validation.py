"""Data-integrity rules for explosive parts.

Split from core.py so the rules can be tested without instantiating the plugin
registry, and so the hook wiring stays readable.
"""

from django.core.exceptions import ValidationError

from .constants import (
    MASS_UNIT,
    TPL_COMPAT,
    TPL_DIVISION,
    TPL_EXPLOSIVE,
    TPL_GROSS_MASS,
    TPL_MAX_NEQ,
    TPL_NEQ,
    TPL_UN_NUMBER,
)
from .hazard import (
    is_legal_combination,
    is_valid_un_number,
    legal_groups_for,
)
from .parameters import get_parameter_numeric, get_parameter_value, get_template


def is_explosive_part(part) -> bool:
    """True if the part is flagged as a regulated explosive.

    Backed by a checkbox parameter, for which InvenTree stores data_numeric as
    1/0 — so this is also cheaply filterable in the ORM.
    """
    template = get_template(TPL_EXPLOSIVE)

    if template is None:
        return False

    parameter = part.parameters_list.filter(template=template).first()

    return bool(parameter and parameter.data_numeric == 1)


def part_issues(part, require_neq: bool = True, enforce_combo: bool = True) -> list[str]:
    """Return the data-integrity problems with an explosive part.

    Returns a list rather than raising, so the same rules can drive both the
    blocking validation hook and the advisory list shown in the part panel.
    """
    if not is_explosive_part(part):
        return []

    issues = []

    neq = get_parameter_numeric(part, TPL_NEQ)
    gross = get_parameter_numeric(part, TPL_GROSS_MASS)

    if require_neq and neq is None:
        issues.append(
            "Part is flagged as an explosive but has no net explosive quantity. "
            "It will not be counted toward any magazine total until one is set."
        )

    if neq is not None and neq < 0:
        issues.append("Net explosive quantity cannot be negative.")

    if neq is not None and gross is not None and neq > gross:
        issues.append(
            f"Net explosive quantity ({neq} kg) exceeds gross mass ({gross} kg). "
            f"The explosive content cannot weigh more than the packaged article."
        )

    division = get_parameter_value(part, TPL_DIVISION)
    group = get_parameter_value(part, TPL_COMPAT)

    if enforce_combo and not is_legal_combination(division, group):
        legal = ", ".join(legal_groups_for(division)) or "none"
        issues.append(
            f"'{division}{group}' is not a valid UN classification code. "
            f"Division {division} admits compatibility groups: {legal}."
        )

    un_number = get_parameter_value(part, TPL_UN_NUMBER)

    if un_number and not is_valid_un_number(un_number):
        issues.append(f"'{un_number}' is not a valid UN number (expected e.g. UN0241).")

    return issues


def validate_part(part, require_neq: bool = True, enforce_combo: bool = True) -> None:
    """Raise ValidationError if the part has data-integrity problems."""
    issues = part_issues(part, require_neq=require_neq, enforce_combo=enforce_combo)

    if issues:
        raise ValidationError(issues)


def validate_parameter_value(parameter, data, enforce_combo: bool = True) -> None:
    """Validate a single parameter value as it is being saved.

    Single-field checks (UN number format, mass values), plus the
    division/compatibility-group combination.

    The combination is re-checked here because editing one of those two parameters
    alone does not call Part.save(), so the cross-field check in validate_part()
    never fires — a user could otherwise save an illegal 1.1S by editing the
    compatibility group last.
    """
    template = getattr(parameter, "template", None)

    if template is None:
        return

    name = (template.name or "").strip().lower()

    if name == TPL_UN_NUMBER.lower():
        if data and not is_valid_un_number(data):
            raise ValidationError(
                f"'{data}' is not a valid UN number (expected e.g. UN0241)."
            )
        return

    if name in (TPL_NEQ.lower(), TPL_GROSS_MASS.lower(), TPL_MAX_NEQ.lower()):
        validate_mass(data, template)
        return

    if not enforce_combo:
        return

    # Cross-field: read the sibling parameter's stored value and check the
    # proposed value against it.
    if name == TPL_DIVISION.lower():
        division, group = data, _sibling_value(parameter, TPL_COMPAT)
    elif name == TPL_COMPAT.lower():
        division, group = _sibling_value(parameter, TPL_DIVISION), data
    else:
        return

    if not is_legal_combination(division, group):
        legal = ", ".join(legal_groups_for(division)) or "none"
        raise ValidationError(
            f"'{division}{group}' is not a valid UN classification code. "
            f"Division {division} admits compatibility groups: {legal}."
        )


def validate_mass(data, template) -> None:
    """Validate a mass value (NEQ, gross mass, or a magazine's licensed limit).

    Anything unparseable must be rejected here. InvenTree stores an unparseable
    parameter with data_numeric = NULL and the NEQ aggregation skips NULL rows, so
    a value like "approx 5" would not fail loudly — it would silently under-count
    the magazine holding it.

    Parsing is delegated to InvenTree's pint-backed converter, so unit-bearing
    input ("500 g") is accepted as it is elsewhere in the product.
    """
    if data is None:
        return

    text = str(data).strip()

    if text == "":
        return

    from InvenTree.conversion import convert_physical_value

    units = (template.units or "").strip() or MASS_UNIT

    try:
        value = convert_physical_value(text, units)
    except Exception:
        raise ValidationError(
            f"'{data}' is not a valid mass. Enter a number, optionally with a "
            f"unit (for example '2.5', '2.5 kg' or '500 g')."
        )

    if value is not None and float(value) < 0:
        raise ValidationError("Mass values cannot be negative.")


def _sibling_value(parameter, template_name: str):
    """The current stored value of another parameter on the same object."""
    template = get_template(template_name)

    if template is None:
        return None

    from common.models import Parameter

    sibling = Parameter.objects.filter(
        template=template,
        model_type=parameter.model_type,
        model_id=parameter.model_id,
    ).first()

    return sibling.data if sibling else None
