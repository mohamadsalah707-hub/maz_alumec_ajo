# Purchasing Aluminum Profiles by the Piece, Priced per KG

Extends the standard Odoo 19 Community `purchase.order` / `purchase.order.line`
so a purchasing agent can buy aluminum profiles by the piece while the system
computes total meters, total weight, and pricing from a per-kilogram rate.

## 1. Scope note: two unrelated costing schemes coexist on the same model

`purchase.order.line` in this module **already** carries `width` /
`total_length` / `area` / `color` / `profile_length` fields, used for an
existing area-based costing scheme (flat stock such as glass, priced by m²:
`area = width * total_length / 1,000,000`). Those fields are also written to
by `cutlist_sum.action_new_rfq` when generating an RFQ from a Cut List
Summary.

This feature is **new and independent**: it uses its own `alu_`-prefixed
fields throughout, so it neither reads nor overwrites the existing
width/total_length/area fields, and doesn't interfere with the RFQ flow that
already populates them. The two schemes can appear on different lines of the
same PO without conflict.

## 2. Data model

### 2.1 `product.template` (new field)

| Field | Type | Purpose |
|---|---|---|
| `weight_per_meter` | Float (kg/m) | Weight of one linear meter of this profile. Set once on the product; auto-fetched onto new PO lines for that product. |

### 2.2 `purchase.order.line` (new fields)

| Field | Type | Purpose |
|---|---|---|
| `alu_qty_pieces` | Integer | Quantity in Pieces. Kept in sync (both directions) with the standard `product_qty` (Float) - `product_qty` remains the real field driving stock/invoicing, `alu_qty_pieces` is a whole-number view/edit of the same value. |
| `profile_length` | Float (m) | Length of a single bar/piece. |
| `alu_weight_per_meter` | Float (kg/m) | Weight per linear meter for *this line*. Auto-fetched from the product's `weight_per_meter` when the Product is set (onchange); editable afterwards, so a line can diverge from the product's default if needed. |
| `alu_price_per_kg` | Monetary | Purchase rate per kilogram. |
| `alu_unit_cost` | Float, computed, stored | `alu_weight_per_meter * profile_length/1000 * alu_price_per_kg`. |
| `alu_total_length` | Float (mm), computed, stored | `alu_qty_pieces * profile_length`. |
| `alu_total_weight` | Float (kg), computed, stored | `alu_total_length * alu_weight_per_meter`. |
| `alu_total` | Monetary, computed, stored | `alu_qty_pieces * alu_unit_cost`. |

There is no opt-in toggle: `price_unit` is kept in sync with `alu_unit_cost`
automatically whenever `product_id.material_type == 'aluminum'` (both via
`_onchange_alu_weight_pricing` for form feedback and `_sync_alu_price_unit`,
called from `create()`/`write()`, for the server-side/API path). Non-aluminum
lines are left completely alone.

### 2.3 Legacy Purchase Order screen parity

The following fields/columns were added to `purchase.order.line` to match
columns present on this business's previous (pre-Odoo) Purchase Order
screen that had no equivalent yet:

| Field | Type | Purpose |
|---|---|---|
| `product_code` | Char, related (`product_id.default_code`) | "Product code" column. |
| `categ_id` | Many2one `product.category`, related | "Category" column. |
| `sub_categ_id` | Many2one `product_sub_category`, related | "Sub-Category" column. |
| `glass_type_id` | Many2one `ajo_glass_type` | "G.Type" column. |
| `vat_applicable` | Boolean, default True | "VAT Y/N" column. |

"Unit cost", "Net cost" and "Total" from the legacy grid map onto fields
that already existed, just not yet exposed in this module's grid: `alu_unit_cost`
(or `price_unit` for non-aluminum lines), core's `price_unit_discounted`
(`price_unit` after the line's own `discount` %), and core's `price_subtotal`
respectively - no new fields needed for those three.

And the following were added at the `purchase.order` (header) level:

| Field | Type | Purpose |
|---|---|---|
| `shipping_method` / `shipping_terms` | Char | Free text, no core equivalent. |
| `global_discount_percent` | Float | Order-level discount %, distinct from the existing per-line `discount`. |
| `global_discount_amount` | Monetary, computed, stored | `amount_untaxed * global_discount_percent / 100`. |
| `approved_by_id` | Many2one `res.users` | "Approved by". |
| `nb_pages` | Integer | "Nb. of pages". |
| `memo_1` / `memo_2` / `memo_3` | Char | The three free-text memo lines. |
| `extra_cost_line_ids` | One2many `purchase.order.extra.cost` | The small G.Type/Description/Cost table (freight, handling, etc. not tied to a product line). |

"Grand Total"/"Net Total"/11% TVA and "Comments" from the legacy footer
already map onto core Odoo (`amount_untaxed`/`amount_total`/the tax totals
widget, and `note`) - no new fields needed there.

## 3. Compute dependency graph

```
alu_weight_per_meter ---\
profile_length -----+--> alu_unit_cost --\
alu_price_per_kg --------/                       |
                                                  v
alu_qty_pieces ----------------------------> alu_total
alu_qty_pieces + profile_length -----> alu_total_length --> alu_total_weight
                                                                    (x alu_weight_per_meter)
```

- `_compute_alu_unit_cost` — `@api.depends('alu_weight_per_meter', 'profile_length', 'alu_price_per_kg')`
- `_compute_alu_totals` — `@api.depends('alu_qty_pieces', 'profile_length', 'alu_weight_per_meter', 'alu_unit_cost')`, computes all three totals together since they share the same trigger fields
- `price_unit` sync is **not** implemented as a second `@api.depends` on top of
  core's own `price_unit` compute (a field can only have one official
  `compute`) - instead:
  - `_onchange_alu_weight_pricing` (`@api.onchange` on the four driver fields)
    gives immediate form feedback, and
  - `create()` / `write()` are extended to call `_sync_alu_price_unit()`,
    which enforces the same rule server-side (via `super().write()` on the
    single line, to avoid recursing back into the same `write()` override)
    for any path that doesn't go through the form's onchange (API calls,
    imports, `default_get` context, etc).

## 4. User interface

`views/purchase_order_views.xml` (`purchase_order_form_inherit`) inserts the
new fields into the existing PO/RFQ line grid, right before the standard
Quantity column (alongside - not replacing - the existing area-based
columns). Marked `optional="show"`/`optional="hide"` (list column picker)
rather than always-visible, so a purchasing agent working on flat-stock
lines isn't shown an equally-wide, unrelated set of columns by default:

| Field | Default visibility |
|---|---|
| `profile_length` | shown |
| `alu_price_per_kg` | shown |
| `alu_price_by_weight` | shown |
| `alu_unit_cost` | shown (readonly, computed) |
| `alu_total_weight` | shown (readonly, computed) |
| `alu_weight_per_meter` | hidden (auto-fetched, rarely needs eyeballing) |
| `alu_qty_pieces` | hidden (standard Quantity column already shows the count) |
| `alu_total_length` | hidden |
| `alu_total` | hidden (`price_subtotal`, already on-screen, matches it when `alu_price_by_weight` is on) |

## 5. Document printing (QWeb)

`report/purchase_order_alu_report_templates.xml` inherits
`purchase.report_purchaseorder_document` and inserts three columns -
**Length (m)**, **Total Length (m)**, **Total Weight (kg)** - right after
the existing Qty column and before Unit Price, in both the header (`<thead>`)
and each line's row (`<tbody>`). Quantity, Unit Price and Subtotal don't need
new columns - the core report already prints `line.product_qty`,
`line.price_unit` and `line.price_subtotal`, and those reflect the
weight-based Unit Cost automatically once `alu_price_by_weight` is enabled
on a line (Section 3). The three new cells are blank for non-aluminum lines
(`t-if` on a truthy value) rather than printing `0.00` everywhere.

## 6. Files touched

- `models/product.py` — `product.template.weight_per_meter`
- `models/purchase_order.py` — all new `purchase.order.line` fields/computes/
  onchanges/`create()`/`write()` overrides described above
- `views/product_views.xml` — expose `weight_per_meter` in the Aluminium
  Specs tab
- `views/purchase_order_views.xml` — new grid columns
- `report/purchase_order_alu_report_templates.xml` — QWeb report columns
- `__manifest__.py` — registers the new report template file
- `tests/test_purchase_aluminum_pricing.py` — automated coverage (see below)

## 7. Automated tests

`tests/test_purchase_aluminum_pricing.py` creates a real `purchase.order`
with a line for a `weight_per_meter`-carrying product and verifies:

- the product's `weight_per_meter` is auto-fetched onto a new line
  (simulating the form onchange directly, since onchange isn't triggered by
  ORM `create()`);
- `alu_unit_cost` / `alu_total_length` / `alu_total_weight` / `alu_total`
  compute correctly from `alu_weight_per_meter` x `profile_length` x
  `alu_price_per_kg` x `alu_qty_pieces`;
- `alu_qty_pieces` and `product_qty` stay in sync in both directions;
- with `alu_price_by_weight` enabled, `price_unit` (and therefore
  `price_subtotal`) matches `alu_unit_cost`, including after a later change
  to `alu_price_per_kg` via `write()` (server-side sync path, not just the
  onchange).

Run via this module's `security/CLAUDE.md` command:

```
python odoo-bin -c odoo.conf -d demo19 -u maz_alumec_ajo --test-enable --test-tags=maz_alumec_ajo --stop-after-init
```
