"""Names and vocabularies used by the explosives plugin.

Everything the plugin looks up by name lives here, so that a rename is a
one-line change rather than a grep.
"""

# ParameterTemplate.name is globally unique and case-insensitive across the whole
# InvenTree instance, so these can collide with templates a site already has.

TPL_EXPLOSIVE = "Explosive"
TPL_NEQ = "Net Explosive Quantity"
TPL_GROSS_MASS = "Explosive Gross Mass"
TPL_DIVISION = "UN Hazard Division"
TPL_COMPAT = "UN Compatibility Group"
TPL_UN_NUMBER = "UN Number"
TPL_PSN = "Proper Shipping Name"

# Applied to StockLocation, not Part.
TPL_MAX_NEQ = "Maximum Net Explosive Quantity"

PART_TEMPLATES = [
    TPL_EXPLOSIVE,
    TPL_NEQ,
    TPL_GROSS_MASS,
    TPL_DIVISION,
    TPL_COMPAT,
    TPL_UN_NUMBER,
    TPL_PSN,
]

LOCATION_TEMPLATES = [TPL_MAX_NEQ]

TEMPLATE_COUNT_EXPECTED = len(PART_TEMPLATES) + len(LOCATION_TEMPLATES)

# Mass templates are declared in kg so that Parameter.data_numeric is itself in
# kg and can be summed directly; pint converts user input ("500 g" -> 0.5) on the
# way in. Changing this changes the meaning of every stored value.
MASS_UNIT = "kg"

DIVISIONS = ["1.1", "1.2", "1.3", "1.4", "1.5", "1.6"]

# The letters are not contiguous: there is no I, M, O, P, Q or R.
COMPATIBILITY_GROUPS = ["A", "B", "C", "D", "E", "F", "G", "H", "J", "K", "L", "N", "S"]
