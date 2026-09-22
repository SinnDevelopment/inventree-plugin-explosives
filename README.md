# InvenTree Explosives Plugin

Adds the properties needed to keep a lawful inventory of explosives in
[InvenTree](https://inventree.org): **net explosive quantity (NEQ)**, **gross
mass**, and **UN classification** — and enforces the **licensed NEQ limit** of
each magazine.

The point is not just to record fields. A licensed magazine may only hold so much
net explosive quantity, and ordinary stock movements can breach that limit. This
plugin aggregates NEQ per storage location, compares it against the licence, and
warns (or blocks) when a movement would take it over.

## What it does

- **Part properties** — NEQ per unit, gross mass per unit, UN hazard division,
  compatibility group, UN number, proper shipping name.
- **Magazine totals** — total NEQ held in a stock location (including
  sublocations), against a per-location licensed limit, with a utilisation ring
  and an alert when exceeded.
- **Validation** — rejects explosive parts with no NEQ, an NEQ greater than the
  gross mass, invalid UN numbers, and illegal classification codes (`1.1S` is not
  a thing; `1.4S` is).
- **Compliance output** — a magazine register and a transport-manifest report,
  plus explosive columns on the standard Part / Stock / Location CSV exports.

## How the data is modelled

Everything is stored as **native InvenTree parameters** — no custom database
tables, no migrations, nothing to break on upgrade.

| Field                            | Lives on           | Units         |
|----------------------------------|--------------------|---------------|
| `Explosive` (checkbox)           | Part               | —             |
| `Net Explosive Quantity`         | Part               | kg            |
| `Explosive Gross Mass`           | Part               | kg            |
| `UN Hazard Division`             | Part               | 1.1 – 1.6     |
| `UN Compatibility Group`         | Part               | A – S         |
| `UN Number`                      | Part               | e.g. `UN0241` |
| `Proper Shipping Name`           | Part               | —             |
| `Maximum Net Explosive Quantity` | **Stock Location** | kg            |

NEQ is recorded **per unit** on the Part. A magazine's total is computed as
`Σ (stock quantity × NEQ per unit)`.

This means two lots of the same part are assumed to have the same NEQ per unit.
That is true of manufactured explosive articles, which is the common case. If you
need per-lot NEQ (a weighed actual mass at receipt, say), that is not supported
in this version — InvenTree does not currently support parameters on stock items
([upstream PR #11459](https://github.com/inventree/InvenTree/pull/11459) is
deferred).

Because the parameters are unit-aware, entering `500 g` into a kg field stores
`0.5`. You can enter mass in whatever unit is convenient.

## Installation

```bash
pip install inventree-plugin-explosives
```

Then in InvenTree:

1. Enable the plugin (Admin Center → Plugins).
2. Enable the global settings **`ENABLE_PLUGINS_URL`** (for the API) and
   **`ENABLE_PLUGINS_INTERFACE`** (for the panels). Both are off by default and
   the plugin's UI will not work without them.
3. The parameter templates are created automatically when the plugin is enabled,
   re-checked daily, and can be repaired on demand. The plugin settings page
   shows a red banner if any template is missing or misconfigured — press
   **Run setup** there to create them (this works even if automatic creation was
   skipped, e.g. the plugin first loaded during a migration). Automatic creation
   on enable also relies on `ENABLE_PLUGINS_EVENTS` and a running background
   worker; the daily check and the button are the fallbacks when those are off.

Requires InvenTree **1.2+** — the generic `common.models.ParameterTemplate` this
plugin is built on landed in 1.2.0. Tested against 1.4.1.

## Usage

1. Open a part's **Explosive Data** panel, press **Mark as explosive**, and set
   its NEQ, gross mass and UN classification directly in the panel (the same
   values can also be edited on the generic Parameters tab).
2. Open the **Explosives / NEQ** panel on the stock location that is your
   licensed magazine and set its **Licensed limit** (staff only; the same value
   is the `Maximum Net Explosive Quantity` parameter on the location's
   Parameters tab). Enter `0` for a location where no explosives are permitted;
   remove the limit to stop tracking the location.
3. The same panel shows what is held against the licence, and which stock items
   contribute. The dashboard item lists every licensed magazine by utilisation.

Only stock of a part that is **flagged Explosive** and has an NEQ counts toward
a magazine. Pressing **Not an explosive** on a part keeps its stored values but
removes it from every total, the limit check and the exports.

### Licence limit enforcement

The `LIMIT_ACTION` setting controls what happens when a stock movement would take
a magazine over its licensed NEQ:

- **`warn`** (default) — the movement proceeds; the panel, the dashboard and a
  notification report the breach.
- **`block`** — the movement is rejected with a validation error.
- **`off`** — no checking.

It ships as `warn` on purpose. The check runs on every stock save, including
purchase-order receipts, build outputs and stocktakes, and a hard failure inside
one of those workflows is opaque and disruptive. Run in `warn` until you trust
the numbers against your real data, then switch to `block`.

**`block` is a strong deterrent, not a guarantee.** Bulk operations that use
`QuerySet.update()` bypass Django's `save()` entirely and cannot be intercepted.
The plugin also audits locations on stock events and raises a notification after
the fact, but a licence holder should not treat this plugin as making a breach
*impossible*.

A magazine's licence covers **everything stored beneath it**, not just stock
placed in the location directly. Putting explosives in a sublocation of a
licensed magazine counts against that magazine's limit (unless
`INCLUDE_SUBLOCATIONS` is off).

A limit of **0 kg** means "no explosives permitted here" and is enforced as such
— it is not the same as leaving the limit unset, which means "unlicensed, not
tracked".

### What counts toward the total

By default, **all physically present stock counts**, including stock that is
`QUARANTINED` or `REJECTED` — such stock is still sitting in the magazine and
still counts against the licence. Only `DESTROYED` and `LOST` stock is excluded.
Set `COUNT_ALL_PRESENT_STOCK` to false to fall back to InvenTree's ordinary
"available stock" semantics.

## Reports

Two templates ship in `inventree_explosives/report_templates/`. InvenTree has no
hook to install report templates automatically, so upload them yourself under
Admin Center → Reports:

- `magazine_register.html` — model **Stock Location**. What is held, against the
  licence, broken down by hazard division.
- `transport_manifest.html` — model **Stock Item**. The dangerous-goods
  description for a consignment.

Both read from a single `explosives` context key, so custom templates can use the
same data: `{{ explosives.neq_kg }}`, `{{ explosives.items }}`,
`{{ explosives.classification_code }}`, and so on.

## ⚠️ Regulatory sign-off

The UN classification table in `hazard.py` encodes the 35 legal
division/compatibility-group combinations. It has been transcribed against the UN
Model Regulations / ADR 2.2.1.1.4 classification-code table and is verified by an
exhaustive 78-cell test.

**Before relying on this in a regulated setting, confirm the table against the
ADR/IMDG edition your licence is issued under, and record that edition here.**

> Classification table checked against: _(record your edition here)_

This plugin is an inventory aid. It does not discharge any duty of the licence
holder, the consignor, or the responsible person.

## Development

```bash
# this plugin
git clone https://github.com/sinndevelopment/inventree-plugin-explosives \
    ~/git/inventree-plugin-explosives

# InvenTree checkout to develop against
git clone https://github.com/inventree/InvenTree ~/git/InvenTree
cd ~/git/InvenTree && git checkout 1.4.1
python3.12 -m venv .venv && source .venv/bin/activate
pip install -U invoke && invoke install && invoke dev.setup-dev

# the plugin, editable
pip install -e ~/git/inventree-plugin-explosives
```

Build the frontend before packaging, or the wheel ships an empty `static/` and
every panel silently fails to render:

```bash
cd frontend && npm install && npm run build
```

For frontend hot reload, set `DEBUG=True`, `PLUGIN_DEV_SLUG=explosives` and
`PLUGIN_DEV_HOST=http://localhost:5173`, then run `npm run dev`.

No frontend entrypoint name may be a suffix of another's: InvenTree matches
panel sources against the vite manifest with an unanchored regex, so `Panel.tsx`
resolved to `LocationPanel.tsx`. `test_ui` enforces this.

### Releasing

Publishing to PyPI happens automatically when a GitHub release is published, via
the `publish.yml` workflow. It uses **trusted publishing (OIDC)** — there is no API
token to store or rotate.

Before the first release, register the trusted publisher on PyPI (Project →
Settings → Publishing, or as a *pending publisher* if the project does not exist
there yet):

| Field | Value |
|---|---|
| Owner | `sinndevelopment` |
| Repository | `inventree-plugin-explosives` |
| Workflow | `publish.yml` |
| Environment | `pypi` |

Then create a `pypi` environment under repository Settings → Environments. Any
protection rules on it (required reviewers, tag restrictions) gate every release.

The workflow builds the frontend and refuses to publish a wheel that does not
contain the compiled panels. The full test suite runs first, against a real
InvenTree, and a failure blocks the release.

### Continuous integration

| Workflow | When | What |
|---|---|---|
| `ci.yaml` | every push and PR | ruff, biome, package build, frontend build, and the standalone classification-table tests |
| `test.yaml` | pushes to `main`, and before every release | the full suite against a real InvenTree checkout |
| `publish.yml` | published release | full suite → build → publish via OIDC |

`test.yaml` is a reusable workflow. It pins the InvenTree version it tests
against (currently 1.4.1); bump the `inventree-ref` default when upgrading, or
run it manually against another ref from the Actions tab.

### Tests

The pure classification logic runs standalone:

```bash
python -m unittest inventree_explosives.test_hazard -v
```

The rest need an InvenTree checkout:

```bash
cd ~/git/InvenTree
export INVENTREE_PLUGINS_ENABLED=true INVENTREE_PLUGIN_TESTING=true \
       INVENTREE_PLUGIN_TESTING_SETUP=true
python src/backend/InvenTree/manage.py test inventree_explosives
```

## Licence

MIT — Copyright (c) 2026 Sinn Development Ltd. See [LICENSE](LICENSE).

Source: <https://github.com/sinndevelopment/inventree-plugin-explosives>
