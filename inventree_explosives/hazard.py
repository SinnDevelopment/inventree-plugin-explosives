"""Pure UN Class 1 classification logic.

No Django imports, no database access — everything here is a pure function so
the classification table can be tested exhaustively without a test database.
"""

import re

from .constants import COMPATIBILITY_GROUPS, DIVISIONS

# Only 35 of the 78 division/compatibility-group combinations are legal UN
# classification codes. A wrong cell here either blocks a lawful article or admits
# an unlawful one.
#
# Transcribed against the UN Model Regulations / ADR 2.2.1.1.4 classification-code
# table. Confirm against the ADR/IMDG edition your licence is issued under before
# relying on this in a regulated setting.
LEGAL_GROUPS_BY_DIVISION: dict[str, frozenset[str]] = {
    "1.1": frozenset("ABCDEFGJL"),          # 9  - no H, K, N, S
    "1.2": frozenset("BCDEFGHJKL"),         # 10 - no A, N, S
    "1.3": frozenset("CFGHJKL"),            # 7  - includes F; no A, B, D, E, N, S
    "1.4": frozenset("BCDEFGS"),            # 7  - includes S; no A, H, J, K, L, N
    "1.5": frozenset("D"),                  # 1  - 1.5D only
    "1.6": frozenset("N"),                  # 1  - 1.6N only
}

LEGAL_COMBINATIONS: frozenset[tuple[str, str]] = frozenset(
    (division, group)
    for division, groups in LEGAL_GROUPS_BY_DIVISION.items()
    for group in groups
)

# Not an assert: `python -O` strips those, and this is the guard on the table
# the whole classification rule rests on.
if len(LEGAL_COMBINATIONS) != 35:
    raise ValueError(
        f"Expected 35 UN Class 1 classification codes, got {len(LEGAL_COMBINATIONS)}"
    )

UN_NUMBER_RE = re.compile(r"^UN\d{4}$")


def normalise_division(value: str | None) -> str | None:
    """Normalise a hazard division, e.g. ' 1.1 ' -> '1.1'."""
    if not value:
        return None
    return str(value).strip()


def normalise_group(value: str | None) -> str | None:
    """Normalise a compatibility group, e.g. ' d ' -> 'D'."""
    if not value:
        return None
    return str(value).strip().upper()


def is_legal_combination(division: str | None, group: str | None) -> bool:
    """Return True if this division/compatibility-group pair is a legal UN code.

    An incomplete pair (either side missing) is not judged here — it is not
    *illegal*, merely not yet classified. Completeness is a separate rule.
    """
    division = normalise_division(division)
    group = normalise_group(group)

    if division is None or group is None:
        return True

    return (division, group) in LEGAL_COMBINATIONS


def classification_code(division: str | None, group: str | None) -> str | None:
    """Render the combined classification code, e.g. '1.4S'. None if incomplete."""
    division = normalise_division(division)
    group = normalise_group(group)

    if division is None or group is None:
        return None

    return f"{division}{group}"


def legal_groups_for(division: str | None) -> list[str]:
    """Return the compatibility groups legal for a division, in canonical order."""
    division = normalise_division(division)
    groups = LEGAL_GROUPS_BY_DIVISION.get(division, frozenset())
    return [g for g in COMPATIBILITY_GROUPS if g in groups]


def is_valid_un_number(value: str | None) -> bool:
    """Return True if `value` looks like a UN number, e.g. 'UN0241'."""
    if not value:
        return False
    return bool(UN_NUMBER_RE.match(str(value).strip().upper()))


def is_valid_division(value: str | None) -> bool:
    """Return True if `value` is a recognised hazard division."""
    return normalise_division(value) in DIVISIONS


def is_valid_group(value: str | None) -> bool:
    """Return True if `value` is a recognised compatibility group."""
    return normalise_group(value) in COMPATIBILITY_GROUPS
