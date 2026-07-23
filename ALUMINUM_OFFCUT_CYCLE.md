# Aluminum Cutting Waste Cycle (Offcuts & Scrap)

Tracks what happens to the leftover piece of an aluminum bar every time it's
cut for a window/door, using only Community Odoo 19 mechanisms (standard
`stock.move`/`stock.quant`, a distinct product per reusable offcut, a
dedicated stock location) — no Enterprise Quality or MRP routing/work-order
modules involved.

## 1. Definitions

| Term | Meaning |
|---|---|
| **Raw Profile** | The standard-length aluminum bar product (e.g. a 6000mm "HF008 - E5 Clair" profile) as bought from the supplier. In this module it's the `product.template` created by the cutlist import / parametric window generator for `material_type = 'aluminum'`. |
| **Offcut** | The leftover piece of a bar after a cut, when that leftover is long enough to be reused for a future smaller cut. Tracked as its **own distinct product** - same profile/color (and the same Category/Sub Category) as the bar it came from, but keyed by its exact leftover `length`, shown in the name as a bare number (e.g. `"700 - RAL8014 - 2500"`), not `"L:2500mm"`. |
| **Real Scrap** | A leftover piece too short to ever be reused. Not returned to stock at all — the bar was already fully deducted by normal component consumption, so nothing further happens to it. |
| **Scrap threshold** | The length (mm) below which a leftover counts as Real Scrap instead of an Offcut. Default **2000mm**, configurable per database (see [Configuration](#5-configuration)). |

## 2. Why a distinct product instead of a lot

The first version of this feature tracked offcuts as `stock.lot` records on
the *same* profile product (lot-tracked). That was reworked: making the
profile product lot-tracked forces Odoo to require a lot/serial number on
**every** move of that product, including ordinary raw-material consumption
- a much bigger behavioral change than intended, and one the automated tests
actually caught (see [Automated tests](#8-automated-tests)).

Instead, each distinct offcut length is its own **product** - same
`alum_profile` and `color_id` as the master bar, `material_type='aluminum'`,
but with `length` set to the exact leftover. `_compute_name` (in
`models/product.py`) builds the name from Profile + Color + Length as a bare
number (e.g. `"700 - RAL8014 - 2500"`) - the `"L:"` prefix and `"mm"` suffix
it used to append are gone, but the length itself is still part of the name,
so two different offcut lengths of the same profile/color still get
distinct, readable names (the master profile product, having no length set,
just reads `"700 - RAL8014"`). `get_or_create_offcut_product` also inserts
(on creation) or backfills (if missing on an already-existing offcut
product) the offcut's Category and Sub Category from the base profile
product of the same profile/color, so it's never left uncategorized. The
master profile product itself is left completely untouched (still
`tracking='none'`, ordinary consumption unaffected).

## 3. Data model changes

| Model | Field | Purpose |
|---|---|---|
| `stock.move` (`models/mrp_dimensions.py`) | `remaining_length` (Float, mm) | Operator input: the exact leftover length measured on the bar after cutting, logged on the **raw material** consumption move before closing the MO. Left empty if the whole bar was used up. |
| `stock.move` | `offcut_processed` (Boolean) | Internal guard so re-running `button_mark_done` (e.g. after a backorder wizard) never double-processes the same move. |
| `stock.warehouse` (`models/warehouse.py`) | `offcut_location_id` (Many2one `stock.location`) | The warehouse's dedicated internal "Offcuts" location. Auto-created the first time it's needed via `_get_or_create_offcut_location()` — no manual setup required. |
| `product.template` | `is_storable = True` | Set on every aluminum/material product this module creates (`get_or_create_material_product`, `get_or_create_offcut_product`, and the import wizard's own copy). This defaults to `False` on a fresh product in this Odoo version ("Track Inventory") - without it, `stock.quant` never tracks on-hand quantity for the product at all, which the automated tests also caught (see below). |

There is **no** BOM change needed for this feature: offcuts are not declared
as BOM byproducts at all (an earlier version did this; removed - see below).

## 4. The cutting cycle, step by step

1. **Generate the MO** from the AJO Order (`Generate Manufacturing Order`
   button) as before - no BOM changes are needed for offcut handling.
2. **Cut the bar.** For each raw aluminum component move on the MO, the
   operator enters the **Remaining Balance (mm)** (`remaining_length`) they
   measured on the leftover piece. This column is shown on the MO's
   Components list, right after Width/Height.
3. **Close the MO** (`Mark as Done` / `button_mark_done`). Before the
   standard Odoo completion logic runs, `mrp.production._ajo_process_offcuts()`
   processes every raw move that has a `remaining_length` set and hasn't
   already been processed:
   - **`remaining_length < threshold`** (default 2000mm): nothing happens.
     The bar was already fully deducted from stock by ordinary component
     consumption; the short leftover is discarded and never tracked as
     inventory.
   - **`remaining_length >= threshold`**: `product.template.get_or_create_offcut_product()`
     finds or creates the matching offcut product for this exact
     profile/color/length, and a standalone `stock.move` (created,
     confirmed, assigned, and validated within `_ajo_create_offcut_move`)
     receives **one unit** of it from the company's virtual Production
     location into the warehouse's **Offcuts** location. This move is
     entirely independent of the MO's own component/finished moves.
   - If the **same** profile has multiple qualifying leftovers within one MO
     (e.g. two separate HF008 bars were each cut down with reusable
     leftovers, at *different* lengths), each becomes its own product and
     its own move - they are never merged into one quantity, since a 2500mm
     offcut and a 3200mm offcut are not interchangeable stock.

## 5. Configuration

- **Scrap threshold**: Settings → Technical → System Parameters →
  `maz_alumec_ajo.offcut_min_length` (defaults to `2000` if not set).
  Change the value to adjust the mm cutoff without touching code.
- **Offcuts location**: nothing to configure — the first Manufacturing Order
  that needs it will auto-create `<Warehouse>/Offcuts` as an internal
  location and remember it on `stock.warehouse.offcut_location_id`.

## 6. Reusing an offcut later

`mrp.production._ajo_suggest_offcut_product(alum_profile_id, color_id,
required_length)` is a best-fit lookup: it searches existing offcut
products for that profile/color with `length >= required_length` (smallest
first) and returns the first one that actually has stock in the warehouse's
Offcuts location - so operators/planners can be pointed at using up a
leftover before opening a brand new bar. It's a suggestion, not an
automatic substitution (see below).

## 7. Routing notes

This module does **not** force Odoo's reservation engine to automatically
prefer Offcuts over a fresh bar — building that would mean custom
`stock.rule` chains, which strays into the "advanced MRP routing" territory
this feature was explicitly built to avoid. `_ajo_suggest_offcut_product`
is a lookup an operator (or a future button/wizard) can check before
cutting a new bar; a program that silently substitutes an offcut into a BOM
line could pick a poor-fitting piece or surprise whoever is planning the cut.

## 8. Automated tests

`tests/test_offcut_cycle.py` exercises the full cycle against a real MRP
Manufacturing Order (`action_confirm`, `button_mark_done`) — not just static
code reading:

- offcut at/above threshold → a distinct offcut product is created with the
  right `length`, the same name and Category/Sub Category as the base
  profile product, and a `stock.quant` of 1.0 lands in the warehouse's
  Offcuts location;
- offcut below threshold → no offcut product is created at all;
- calling `_ajo_process_offcuts()` twice is a no-op the second time (no
  duplicate products/moves).

Verified green on this server's `demo19` database via the exact command from
this module's `security/CLAUDE.md`:

```
python odoo-bin -c odoo.conf -d demo19 -u maz_alumec_ajo --test-enable --test-tags=maz_alumec_ajo --stop-after-init
```

Result: `0 failed, 0 error(s) of 3 tests`, no tracebacks, exit code 0.

**Bugs the tests caught along the way** (fixed, in order found):
1. An earlier lot-based design wasn't actually idempotent - it reset a
   Byproduct move's quantity to 0 on every call, wiping out a previous run's
   lots.
2. Writing `move_line_ids` as an add-only list left Odoo's own
   auto-generated placeholder move line sitting alongside the new one,
   tripping a "Lot/Serial Number required" check.
3. Making the profile product lot-tracked required a lot on *every* move of
   that product, not just the byproduct - the behavioral consequence
   documented above that motivated switching away from lots entirely.
4. `stock.move` in this Odoo version has no `name` field at all (`Invalid
   field 'name' in 'stock.move'`) - the first cut of `_ajo_create_offcut_move`
   tried to set one, copying a pattern from an older Odoo version.
5. Setting `move.quantity` alone did not reliably create a move line when
   `_action_assign()` (from a virtual source location) didn't produce one on
   its own - the move validated with `state='done'` but moved zero actual
   quantity. Fixed by explicitly (re)creating the move line before calling
   `_action_done()`.
6. **The big one**: `product.template.is_storable` defaults to `False` in
   this Odoo version. None of this module's product-creation helpers set it,
   so `stock.quant` silently never tracked on-hand quantity for *any*
   product this module creates - moves validated successfully and looked
   fine, but zero quants ever existed anywhere. Fixed by setting
   `is_storable=True` in `get_or_create_material_product`,
   `get_or_create_offcut_product`, and the import wizard's own copy.

## 9. Known limitations

- **Real Scrap is not separately logged.** A leftover below the threshold
  simply isn't tracked anywhere (per the original spec: "written off as
  scrap or ignored for inventory tracking"). If you later want a formal
  waste report, the natural extension point is creating a `stock.scrap`
  record inside `_ajo_process_offcuts` for the `< threshold` branch.
- **Existing products aren't retroactively fixed.** `is_storable=True` is
  only set when a product is created through this module's helper methods.
  Any aluminum/material product created before this fix (or by some other
  path) needs "Track Inventory" enabled by hand for its on-hand quantity to
  be tracked.
- **No automatic reservation cascade.** As noted above, using up an offcut
  before opening a new bar is a suggestion an operator checks, not something
  the system enforces automatically.

## 10. Files touched

- `models/mrp_dimensions.py` — `stock.move.remaining_length` /
  `offcut_processed`
- `models/mrp_offcut.py` — `mrp.production` offcut processing
  (`_ajo_process_offcuts`, `_ajo_create_offcut_move`) + best-fit suggestion
  helper (`_ajo_suggest_offcut_product`)
- `models/warehouse.py` — `stock.warehouse.offcut_location_id` +
  `_get_or_create_offcut_location()`
- `models/product.py` — `get_or_create_offcut_product()` (Category/Sub
  Category insert-or-update from the base profile product); `is_storable=True`
  added to both `get_or_create_material_product()` and the new method;
  `_compute_name` now appends the bare length number (no `"L:"`/`"mm"`)
- `wizard/ajo_import_wizard.py` — `is_storable=True` added to its own
  material-product creation copy
- `views/mrp_dimensions_views.xml` — `remaining_length` column on the MO's
  Components list
- `tests/test_offcut_cycle.py` — automated coverage described above
