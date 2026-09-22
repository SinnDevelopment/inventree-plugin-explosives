"""Bootstrap and lookup of the ParameterTemplates this plugin depends on.

InvenTree gives plugins no per-instance activation method, so
`ensure_parameter_templates()` is idempotent and is called from four places
(see core.py), any one of which is enough:

  1. the plugin_activated event - the reliable path, fired when the plugin is
     enabled (needs ENABLE_PLUGINS_EVENTS and a worker)
  2. plugin __init__          - best-effort, on registry load of an active plugin
  3. a daily scheduled task   - self-heals if the others ran before the DB was ready
  4. POST api/bootstrap/      - an explicit repair button for an admin

Two constraints shape this module:

* ParameterTemplate.name is globally unique and *case-insensitive*. A site may
  already have a template called "UN Number". We never mutate a template we did
  not create — we report a config error and let a human resolve it.

* A post_save receiver on ParameterTemplate queues a `rebuild_parameters`
  background task on every *update*. So this must use get_or_create and never
  update_or_create, or each registry reload would queue a rebuild for every
  parameter using our templates.
"""

import logging

from .constants import (
    COMPATIBILITY_GROUPS,
    DIVISIONS,
    MASS_UNIT,
    TPL_COMPAT,
    TPL_DIVISION,
    TPL_EXPLOSIVE,
    TPL_GROSS_MASS,
    TPL_MAX_NEQ,
    TPL_NEQ,
    TPL_PSN,
    TPL_UN_NUMBER,
)

logger = logging.getLogger("inventree")

# (name, model, field overrides). A 'checkbox' template must carry no units and
# no choices, or ParameterTemplate.clean() rejects it.
TEMPLATE_SPECS: list[tuple[str, str, dict]] = [
    (
        TPL_EXPLOSIVE,
        "part",
        {
            "checkbox": True,
            "description": "Part is a regulated explosive substance or article",
        },
    ),
    (
        TPL_NEQ,
        "part",
        {
            "units": MASS_UNIT,
            "description": "Net explosive quantity per unit",
        },
    ),
    (
        TPL_GROSS_MASS,
        "part",
        {
            "units": MASS_UNIT,
            "description": "Gross mass per unit, including packaging",
        },
    ),
    (
        TPL_DIVISION,
        "part",
        {
            "choices": ",".join(DIVISIONS),
            "description": "UN hazard division (Class 1)",
        },
    ),
    (
        TPL_COMPAT,
        "part",
        {
            "choices": ",".join(COMPATIBILITY_GROUPS),
            "description": "UN compatibility group",
        },
    ),
    (
        TPL_UN_NUMBER,
        "part",
        {"description": "UN number, e.g. UN0241"},
    ),
    (
        TPL_PSN,
        "part",
        {"description": "UN proper shipping name"},
    ),
    (
        TPL_MAX_NEQ,
        "stocklocation",
        {
            "units": MASS_UNIT,
            "description": "Licensed maximum net explosive quantity for this magazine",
        },
    ),
]

_APP_LABELS = {"part": "part", "stocklocation": "stock"}


def _content_type(model: str):
    from django.contrib.contenttypes.models import ContentType

    return ContentType.objects.get(app_label=_APP_LABELS[model], model=model)


def _database_ready() -> bool:
    """True if it is safe to touch the database right now.

    The plugin registry also loads during migrations, data imports and
    collectstatic, when the tables we need may not exist yet.

    allow_test and allow_shell are on because a plugin legitimately does want to
    create its templates under `manage.py test` and in a shell session — the bare
    canAppAccessDatabase() default excludes both.

    allow_plugins stays off on purpose: it would also permit database access
    while migrations are running, which is exactly when the parameter tables may
    not exist yet.
    """
    try:
        import InvenTree.ready as ready

        return (
            ready.canAppAccessDatabase(allow_test=True, allow_shell=True)
            and not ready.isImportingData()
        )
    except Exception:
        return False


def ensure_parameter_templates() -> dict:
    """Idempotently create this plugin's ParameterTemplates.

    Returns a dict with 'created', 'existing' and 'errors' keys. Never raises:
    a plugin that explodes on load takes the whole registry down with it.
    """
    result = {"created": [], "existing": [], "errors": []}

    if not _database_ready():
        logger.debug("explosives: database not ready, skipping template bootstrap")
        return result

    try:
        from common.models import ParameterTemplate
    except Exception as exc:  # pragma: no cover - only on a broken install
        result["errors"].append(f"cannot import ParameterTemplate: {exc}")
        return result

    for name, model, fields in TEMPLATE_SPECS:
        try:
            existing = ParameterTemplate.objects.filter(name__iexact=name).first()

            if existing is not None:
                # Never updated; only checked for fitness. See module docstring.
                for problem in _check_template(existing, name, model, fields):
                    result["errors"].append(problem)
                result["existing"].append(name)
                continue

            ParameterTemplate.objects.create(
                name=name, model_type=_content_type(model), **fields
            )
            result["created"].append(name)
            logger.info("explosives: created ParameterTemplate '%s'", name)

        except Exception as exc:
            logger.exception("explosives: failed to ensure template '%s'", name)
            result["errors"].append(f"{name}: {exc}")

    return result


def _check_template(template, name: str, model: str, fields: dict) -> list[str]:
    """Report ways a pre-existing template is unfit for our use.

    The dangerous case is a units mismatch: if a site already has a template
    called "Net Explosive Quantity" declared in grams, every total this plugin
    computes would be wrong by 1000x. That must be loud, not silent.
    """
    problems = []

    expected_units = fields.get("units")
    actual_units = (template.units or "").strip()

    if expected_units and actual_units != expected_units:
        shown_units = actual_units or "(none)"
        problems.append(
            f"Parameter template '{name}' already exists with units "
            f"'{shown_units}', but this plugin requires '{expected_units}'. "
            f"All quantities for this field will be wrong until this is corrected."
        )

    if fields.get("checkbox") and not template.checkbox:
        problems.append(
            f"Parameter template '{name}' already exists and is not a checkbox."
        )

    if template.model_type is not None:
        actual_model = template.model_type.model
        if actual_model != model:
            problems.append(
                f"Parameter template '{name}' already exists but applies to "
                f"'{actual_model}', not '{model}'."
            )

    return problems


def get_template(name: str):
    """Look up one of our ParameterTemplates by name, or None if absent.

    Not cached at import time: the database is not up when this module is
    imported. Not memoised on a None result either, because bootstrap may
    create the template later in the same process.
    """
    try:
        from common.models import ParameterTemplate

        return ParameterTemplate.objects.filter(name__iexact=name).first()
    except Exception:
        return None


def get_parameter_value(instance, template_name: str):
    """Return the raw string value of a parameter on a Part or StockLocation."""
    template = get_template(template_name)

    if template is None:
        return None

    parameter = instance.parameters_list.filter(template=template).first()
    return parameter.data if parameter else None


def get_parameter_numeric(instance, template_name: str) -> float | None:
    """Return the numeric value of a parameter, in the template's declared units."""
    template = get_template(template_name)

    if template is None:
        return None

    parameter = instance.parameters_list.filter(template=template).first()

    if parameter is None or parameter.data_numeric is None:
        return None

    return float(parameter.data_numeric)


def set_parameter_value(instance, template_name: str, value, validate: bool = True):
    """Create or update a parameter value on a Part or StockLocation.

    Upserts on the (template, model_type, model_id) unique key, so calling it
    twice does not create a duplicate row.

    full_clean() is called when validating because InvenTree runs the plugin
    `validate_parameter` hook (and choice/unit checks) from Parameter.clean(), not
    from save() — a bare save() would bypass validation entirely. save() then
    recomputes data_numeric and coerces checkbox values.

    Returns the Parameter row, or None if the template does not exist (the caller
    surfaces missing-template state via config_errors()).
    """
    from django.contrib.contenttypes.models import ContentType
    from common.models import Parameter

    template = get_template(template_name)

    if template is None:
        return None

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


def set_explosive_flag(part, on: bool):
    """Mark (or unmark) a part as a regulated explosive."""
    return set_parameter_value(part, TPL_EXPLOSIVE, bool(on))


def clear_parameter_value(instance, template_name: str) -> None:
    """Remove a parameter from a Part or StockLocation, if present.

    Used to clear a field: storing an empty string on a choices parameter would
    fail its clean() check, and an absent row is the correct "unset" state (a
    missing NEQ, for instance, is what part_issues() warns about).
    """
    from django.contrib.contenttypes.models import ContentType
    from common.models import Parameter

    template = get_template(template_name)

    if template is None:
        return

    Parameter.objects.filter(
        template=template,
        model_type=ContentType.objects.get_for_model(instance),
        model_id=instance.pk,
    ).delete()


def config_errors() -> list[str]:
    """Return current configuration problems, for display in the UI panels.

    Cheap enough to call per request: one query per template.
    """
    errors = []

    if not _database_ready():
        return errors

    for name, model, fields in TEMPLATE_SPECS:
        template = get_template(name)

        if template is None:
            errors.append(
                f"Parameter template '{name}' is missing. "
                f"Use the plugin settings to re-run setup."
            )
            continue

        errors.extend(_check_template(template, name, model, fields))

    return errors


def status() -> dict:
    """A structured health report for the plugin settings page.

    Returns 'ready' (True only when every template exists and is fit for use),
    the same human-readable 'errors' config_errors() produces, and a per-template
    breakdown so the settings page can show exactly what is missing or wrong
    without an admin having to read the server log.
    """
    templates = []

    for name, model, fields in TEMPLATE_SPECS:
        template = get_template(name)
        present = template is not None
        ok = present and not _check_template(template, name, model, fields)

        templates.append({"name": name, "present": present, "ok": ok})

    errors = config_errors()

    return {
        "ready": not errors and all(t["ok"] for t in templates),
        "errors": errors,
        "templates": templates,
    }
