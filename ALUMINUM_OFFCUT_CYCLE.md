# Aluminum Cutting Waste Cycle (Offcuts & Scrap)

Tracks what happens to the leftover piece of an aluminum bar every time it's
cut for a window/door, using only Community Odoo 19 mechanisms (core `mrp`
byproducts, `stock.lot`, a dedicated stock location) — no Enterprise Quality
or MRP routing/work-order modules involved.

## 1. Definitions

| Term | Meaning |
|---|---|
| **Raw Profile** | The standard-length aluminum bar product (e.g. a 6000mm "HF008 - E5 Clair" profile) as bought from the supplier. In this module it's the same `product.template` created by the cutlist import / parametric window generator for `material_type = 'aluminum'`. |
| **Offcut** | The leftover piece of a bar after a cut, when that leftover is long enough to be reused for a future smaller cut. Tracked as the **same product**, but as its own `stock.lot` carrying the exact leftover length. |
| **Real Scrap** | A leftover piece too short to ever be reused. Not returned to stock at all — the bar was already fully deducted by normal component consumption, so nothing further happens to it. |
| **Scrap threshold** | The length (mm) below which a leftover counts as Real Scrap instead of an Offcut. Default **2000mm**, configurable per database (see [Configuration](#4-configuration)). |

## 2. Data model changes

| Model | Field | Purpose |
|---|---|---|
| `stock.move` (`models/mrp_dimensions.py`) | `remaining_length` (Float, mm) | Operator input: the exact leftover length measured on the bar after cutting, logged on the **raw material** consumption move before closing the MO. Left empty if the whole bar was used up. |
| `stock.move` | `offcut_processed` (Boolean) | Internal guard so re-running `button_mark_done` (e.g. after a backorder wizard) never double-creates lots. |
| `stock.lot` (`models/mrp_offcut.py`) | `offcut_length` (Float, mm) | The exact usable length of that specific offcut piece. Set automatically when the piece is generated. |
| `stock.warehouse` (`models/warehouse.py`) | `offcut_location_id` (Many2one `stock.location`) | The warehouse's dedicated internal "Offcuts" location. Auto-created the first time it's needed via `_get_or_create_offcut_location()` — no manual setup required. |
| `product.template` | `tracking = 'lot'` | Set automatically whenever a **new** aluminum profile product is created (by the import wizard or the parametric window generator). **Required** for the lot-based offcut mechanism to work on that product. |

## 3. Bill of Materials structure

`ajo_order.action_generate_manufacturing()` builds one BOM per window. For
every **unique** aluminum profile among that window's components, it now
also adds a **Byproduct line for that same product** (`mrp.bom.byproduct`,
qty = 1 placeholder):

```
BOM for "A1-W2"
├── Components (mrp.bom.line)
│   ├── HF008 - E5 Clair   qty 2   (width/height = cut dimensions)
│   ├── HF001 - E5 Clair   qty 2
│   └── ...
└── Byproducts (mrp.bom.byproduct)
    └── HF008 - E5 Clair   qty 1   ← placeholder; real qty/lot set at MO close
```

The offcut is deliberately the **same product** as the component it came
from (an HF008 leftover is still HF008, just shorter) — there is no separate
`ALU-LEFTOVER` SKU. The placeholder quantity is never the real answer: the
actual leftover length can only be known once the bar has actually been cut,
so it's computed at Manufacturing Order close time instead (see below).

## 4. The cutting cycle, step by step

1. **Generate the MO** from the AJO Order (`Generate Manufacturing Order`
   button) — this creates the BOM described above and the Manufacturing
   Order.
2. **Cut the bar.** For each raw aluminum component move on the MO, the
   operator enters the **Remaining Balance (mm)** (`remaining_length`) they
   measured on the leftover piece. This column is shown on the MO's
   Components list, right after Width/Height.
3. **Close the MO** (`Mark as Done` / `button_mark_done`). Before the
   standard Odoo completion logic runs, `mrp.production._ajo_process_offcuts()`
   processes every raw move that has a `remaining_length` set:
   - **`remaining_length < threshold`** (default 2000mm): nothing happens.
     The bar was already fully deducted from stock by ordinary BOM
     consumption; the short leftover is discarded and never tracked as
     inventory.
   - **`remaining_length >= threshold`**: a new `stock.lot` is created
     (sequence `OFFCUT/<year>/0001`, code `ajo.offcut.lot`) with
     `offcut_length` set to the measured value, added as a move line on
     that product's Byproduct move, and received into the warehouse's
     **Offcuts** location instead of ordinary stock.
   - If the **same** profile has multiple qualifying leftovers within one MO
     (e.g. two separate HF008 bars were each cut down with reusable
     leftovers), each gets its own lot on the same Byproduct move — they are
     not merged.
   - If a component's leftover qualifies but no matching Byproduct line
     exists on the BOM (shouldn't happen via the standard generation path,
     but possible on a hand-edited BOM), a `UserError` is raised telling you
     to add one rather than silently losing the leftover.
4. **Reuse the offcut.** The next time that same profile is needed for a
   smaller cut, check `mrp.production._ajo_suggest_offcut_lot(product_id,
   required_length)` — it returns the smallest available offcut lot (from
   the warehouse's Offcuts location) that's still long enough, so a new
   6000mm bar isn't opened unnecessarily. This is a lookup helper, not an
   automatic reservation override (see [Routing](#6-routing-notes) below).

## 5. Configuration

- **Scrap threshold**: Settings → Technical → System Parameters →
  `maz_alumec_ajo.offcut_min_length` (defaults to `2000` if not set).
  Change the value to adjust the mm cutoff without touching code.
- **Offcuts location**: nothing to configure — the first Manufacturing Order
  that needs it will auto-create `<Warehouse>/Offcuts` as an internal
  location and remember it on `stock.warehouse.offcut_location_id`.

## 6. Routing notes

This module does **not** force Odoo's reservation engine to automatically
prefer Offcuts over a fresh bar — building that would mean custom
`stock.rule` chains, which strays into the "advanced MRP routing" territory
this feature was explicitly built to avoid. Instead, `_ajo_suggest_offcut_lot`
is a best-fit *suggestion* an operator (or a future button/wizard) can check
before cutting a new bar. Recommendation: surface this suggestion at the
point where a cut is planned, rather than auto-reserving, since a program
that silently substitutes an offcut could pick a poor-fitting piece.

## 7. Known limitations

- **Existing products aren't retroactively fixed.** `tracking = 'lot'` is
  only set when a **new** aluminum profile product is created. Any aluminum
  profile product created before this feature was added needs its Tracking
  field changed to "By Lots" by hand before offcuts will work on it.
- **Real Scrap is not separately logged.** A leftover below the threshold
  simply isn't tracked anywhere (per the original spec: "written off as
  scrap or ignored for inventory tracking"). If you later want a formal
  waste report, the natural extension point is creating a `stock.scrap`
  record inside `_ajo_process_offcuts` for the `< threshold` branch.
- **Not verified against a running Odoo instance.** All field names and
  lifecycle methods (`stock.move.quantity`/`picked`, `_action_confirm`,
  `button_mark_done`, `mrp.bom.byproduct`) were confirmed by reading this
  server's installed `mrp`/`stock` source directly, and every file was
  syntax-checked, but the end-to-end flow has not been exercised in a live
  database. Test a full cycle (generate MO → log remaining balance → close
  MO → confirm the offcut lot lands in the Offcuts location) before relying
  on it in production.

## 8. Files touched

- `models/mrp_dimensions.py` — `stock.move.remaining_length` /
  `offcut_processed`
- `models/mrp_offcut.py` — `stock.lot.offcut_length`,
  `mrp.production` offcut processing + best-fit suggestion helper
- `models/warehouse.py` — `stock.warehouse.offcut_location_id` +
  `_get_or_create_offcut_location()`
- `models/ajo.py` — `action_generate_manufacturing()` byproduct line
  generation
- `models/product.py`, `wizard/ajo_import_wizard.py` — set
  `tracking = 'lot'` on newly-created aluminum profile products
- `views/mrp_dimensions_views.xml` — `remaining_length` column on the MO's
  Components list; `offcut_length` on the Lots/Serial Numbers form
- `data/ajo_offcut_sequence.xml` — `ajo.offcut.lot` numbering sequence
