# Odoo Label Printing Implementation Patterns

## Overview
Odoo's stock module implements label printing for picking/receipt lines with sophisticated quantity handling. This document shows the exact patterns used.

---

## 1. Report Handler Class: `product_label_report.py`

**Location:** `stock/report/product_label_report.py`

The report class that prepares data for label printing:

```python
from collections import defaultdict
from odoo import _, models
from odoo.exceptions import UserError
import markupsafe

class ReportStockLabel_Product_Product_View(models.AbstractModel):
    _name = 'report.stock.label_product_product_view'
    _description = 'Product Label Report'

    def _get_report_values(self, docids, data):
        if data.get('active_model') == 'product.template':
            Product = self.env['product.template']
        elif data.get('active_model') == 'product.product':
            Product = self.env['product.product']
        else:
            raise UserError(_('Product model not defined, Please contact your administrator.'))

        # KEY PATTERN: Build quantity structure from data dictionary
        quantity_by_product = defaultdict(list)
        for p, q in data.get('quantity_by_product').items():
            product = Product.browse(int(p))
            default_code_markup = markupsafe.Markup(product.default_code) if product.default_code else ''
            product_info = {
                'barcode': markupsafe.Markup(product.barcode) if product.barcode else '',
                'quantity': q,  # This is used by template to loop and print multiple labels
                'display_name_markup': markupsafe.Markup(product.display_name),
                'default_code': (default_code_markup[:15], default_code_markup[15:30])
            }
            quantity_by_product[product].append(product_info)
        
        # CUSTOM BARCODES PATTERN: Support for lot/serial numbers
        if data.get('custom_barcodes'):
            # Expected format: {product: [(barcode, qty_of_barcode)]}
            for product, barcodes_qtys in data.get('custom_barcodes').items():
                product = Product.browse(int(product))
                default_code_markup = markupsafe.Markup(product.default_code) if product.default_code else ''
                for barcode_qty in barcodes_qtys:
                    quantity_by_product[product].append({
                        'barcode': markupsafe.Markup(barcode_qty[0]),
                        'quantity': barcode_qty[1],
                        'display_name_markup': markupsafe.Markup(product.display_name),
                        'default_code': (default_code_markup[:15], default_code_markup[15:30])
                    })
        
        data['quantity'] = quantity_by_product
        layout_wizard = self.env['product.label.layout'].browse(data.get('layout_wizard'))
        data['pricelist'] = layout_wizard.pricelist_id

        return data
```

---

## 2. Data Preparation Wizard: `stock/wizard/product_label_layout.py`

This wizard extends the base product label layout and handles picking/stock data:

```python
from collections import defaultdict
import base64
from odoo import api, fields, models
from odoo.tools.misc import file_open

class ProductLabelLayout(models.TransientModel):
    _inherit = 'product.label.layout'

    # Stock-specific fields
    move_ids = fields.Many2many('stock.move')
    move_quantity = fields.Selection([
        ('move', 'Operation Quantities'),
        ('custom', 'Custom')], string="Quantity to print", required=True, default='custom')

    def _prepare_report_data(self):
        xml_id, data = super()._prepare_report_data()

        if 'zpl' in self.print_format:
            xml_id = 'stock.label_product_product'
            data['zpl_template'] = self.zpl_template

        # KEY PATTERN: Calculate quantities from move lines
        quantities = defaultdict(int)
        uom_unit = self.env.ref('uom.product_uom_unit', raise_if_not_found=False)
        
        # PATTERN 1: When move.move_line_ids are empty, use move quantities directly
        if self.move_quantity == 'move' and self.move_ids and all(ml.product_uom_id.is_zero(ml.quantity) for ml in self.move_ids.move_line_ids):
            for move in self.move_ids:
                use_reserved = move.product_uom.compare(move.quantity, 0) > 0
                useable_qty = move.quantity if use_reserved else move.product_uom_qty
                if not move.product_uom.is_zero(useable_qty):
                    quantities[move.product_id.id] += useable_qty
            data['quantity_by_product'] = {p: int(q) for p, q in quantities.items()}
        
        # PATTERN 2: When move_line_ids exist (track by lot/serial), handle differently
        elif self.move_quantity == 'move' and self.move_ids.move_line_ids:
            custom_barcodes = defaultdict(list)  # For lot/serial tracking
            
            for line in self.move_ids.move_line_ids:
                # Unit-based products: accumulate quantities
                if line.product_uom_id._has_common_reference(uom_unit):
                    # If lot/serial tracked: store as custom barcode with qty
                    if (line.lot_id or line.lot_name) and int(line.quantity):
                        custom_barcodes[line.product_id.id].append(
                            (line.lot_id.name or line.lot_name, int(line.quantity))
                        )
                        continue
                    # Otherwise: accumulate total quantity
                    quantities[line.product_id.id] += line.quantity
                else:
                    # Non-unit products: print 1 label per move line
                    quantities[line.product_id.id] = 1
            
            # Pass only products with some quantity done to the report
            data['quantity_by_product'] = {p: int(q) for p, q in quantities.items() if q}
            data['custom_barcodes'] = custom_barcodes
        
        return xml_id, data
```

---

## 3. Template Structure: `stock/report/picking_templates.xml`

The key pattern: **Use `t-foreach="range(qty)"` to print multiple labels based on quantity**

### 3.1 ZPL Format (Printer-Ready)

```xml
<template id="label_transfer_template_view_zpl">
    <t t-set="uom_unit" t-value="env.ref('uom.product_uom_unit')"/>
    <t t-foreach="docs" t-as="picking">
        <!-- Check if picking has actual quantities vs reserved quantities -->
        <t t-set="picking_quantity" t-value="any(picking.move_ids.move_line_ids.mapped('quantity'))"/>
        <t t-foreach="picking.move_ids" t-as="move">
            <t t-foreach="move.move_line_ids" t-as="move_line">
                <!-- QUANTITY HANDLING PATTERN -->
                <t t-if="move_line.product_id.uom_id._has_common_reference(uom_unit)">
                    <t t-if="picking_quantity">
                        <!-- Use actual quantity if available -->
                        <t t-set="qty" t-value="int(move_line.quantity)"/>
                    </t>
                    <t t-else="">
                        <!-- Fall back to reserved quantity -->
                        <t t-set="qty" t-value="int(move_line.reserved_uom_qty)"/>
                    </t>
                </t>
                <t t-else="">
                    <!-- Non-unit products: 1 label per line -->
                    <t t-set="qty" t-value="1"/>
                </t>
                
                <!-- KEY PATTERN: MULTIPLY LABELS BY QUANTITY -->
                <t t-foreach="range(qty)" t-as="item">
                    <t t-translation="off">
^XA
^FO100,50
^A0N,44,33^FD<t t-esc="move_line.product_id.display_name"/>^FS
^FO100,100
<!-- Lot/Serial tracking: print lot barcode if tracked -->
<t t-if="move_line.product_id.tracking != 'none' and (move_line.lot_id or move_line.lot_name)">
^A0N,44,33^FDLN/SN: <t t-esc="move_line.lot_id.name or move_line.lot_name"/>^FS
^FO100,150^BY3
^BCN,100,Y,N,N
^FD<t t-esc="move_line.lot_id.name or move_line.lot_name"/>^FS
</t>
<!-- Untracked products: print product barcode -->
<t t-if="move_line.product_id.tracking == 'none' and move_line.product_id.barcode">
^BCN,100,Y,N,N
^FD<t t-esc="move_line.product_id.barcode"/>^FS
</t>
^XZ
                    </t>
                </t>
            </t>
        </t>
    </t>
</template>
```

### 3.2 PDF Format (Human-Readable)

```xml
<template id="label_transfer_template_view_pdf">
    <t t-call="web.basic_layout">
        <div class="page">
            <t t-set="uom_unit" t-value="env.ref('uom.product_uom_unit')"/>
            <t t-foreach="docs" t-as="picking">
                <t t-set="picking_quantity" t-value="any(picking.move_ids.move_line_ids.mapped('quantity'))"/>
                <t t-foreach="picking.move_ids" t-as="move">
                    <t t-foreach="move.move_line_ids" t-as="move_line">
                        <!-- Determine quantity to print -->
                        <t t-if="move_line.product_id.uom_id._has_common_reference(uom_unit)">
                            <t t-if="picking_quantity">
                                <t t-set="qty" t-value="int(move_line.quantity)"/>
                            </t>
                            <t t-else="">
                                <t t-set="qty" t-value="int(move_line.reserved_uom_qty)"/>
                            </t>
                        </t>
                        <t t-else="">
                            <t t-set="qty" t-value="1"/>
                        </t>
                        
                        <!-- Loop: Print qty labels -->
                        <t t-foreach="range(qty)" t-as="item">
                            <t t-translation="off">
                                <div style="display: inline-table; height: 10rem; width: 32%;">
                                    <table class="table table-bordered" style="border: 2px solid black;">
                                        <tr>
                                            <th class="table-active text-start" style="height:4rem;">
                                                <span t-esc="move.product_id.display_name"/>
                                            </th>
                                        </tr>
                                        <!-- Show lot/serial if tracked -->
                                        <t t-if="move_line.product_id.tracking != 'none'">
                                            <tr>
                                                <td class="text-center align-middle">
                                                    <t t-if="move_line.lot_name or move_line.lot_id">
                                                        <div t-field="move_line.lot_name" t-options="{'widget': 'barcode', 'width': 600, 'height': 150, 'img_style': 'width:100%;height:4rem'}"/>
                                                        <span t-esc="move_line.lot_name or move_line.lot_id.name"/>
                                                    </t>
                                                    <t t-else="">
                                                        <span class="text-muted">No barcode available</span>
                                                    </t>
                                                </td>
                                            </tr>
                                        </t>
                                        <!-- Show product barcode if untracked -->
                                        <t t-if="move_line.product_id.tracking == 'none'">
                                            <tr>
                                                <td class="text-center align-middle" style="height: 6rem;">
                                                    <t t-if="move_line.product_id.barcode">
                                                        <div t-field="move_line.product_id.barcode" t-options="{'widget': 'barcode', 'width': 600, 'height': 150, 'img_style': 'width:100%;height:4rem'}"/>
                                                        <span t-esc="move_line.product_id.barcode"/>
                                                    </t>
                                                    <t t-else="">
                                                        <span class="text-muted">No barcode available</span>
                                                    </t>
                                                </td>
                                            </tr>
                                        </t>
                                    </table>
                                </div>
                            </t>
                        </t>
                    </t>
                </t>
            </t>
        </div>
    </t>
</template>
```

---

## Key Patterns Summary

### Pattern 1: Quantity Determination
```python
# Choose between actual quantity or reserved quantity based on what's available
if picking_quantity:
    qty = int(move_line.quantity)  # Actual quantity done
else:
    qty = int(move_line.reserved_uom_qty)  # Reserved/planned quantity
```

### Pattern 2: Multi-Label Generation
```xml
<!-- Print qty copies of the label -->
<t t-foreach="range(qty)" t-as="item">
    <!-- Label content repeated qty times -->
</t>
```

### Pattern 3: Data Structure for Report
```python
# Structure 1: Simple quantity multiplication
data['quantity_by_product'] = {
    product_id: int_quantity,  # Template uses range(qty) to print qty labels
    ...
}

# Structure 2: Lot/Serial tracking with quantities
data['custom_barcodes'] = {
    product_id: [
        (barcode_value_1, qty_1),
        (barcode_value_2, qty_2),
        ...
    ],
    ...
}
```

### Pattern 3: Handling Different Product Types

**Unit-based products (with standard UOM):**
- Accumulate quantities across move lines
- Print `qty` copies of each label

**Lot/Serial tracked products:**
- Store as (barcode, qty) tuples in `custom_barcodes`
- Each tuple generates qty labels with that specific barcode

**Non-unit products (weight, volume, etc.):**
- Print 1 label per move line
- Don't accumulate quantities

---

## Data Flow Diagram

```
User selects pickings to print labels
    ↓
stock_label_type.py wizard → choose product vs lot labels
    ↓
product_label_layout.py (stock variant) → _prepare_report_data()
    ↓
Builds data structure:
  - quantity_by_product: {product_id: qty}
  - custom_barcodes: {product_id: [(barcode, qty), ...]}
    ↓
Report renders with picking_templates.xml
    ↓
For each move_line:
  - Determine qty (quantity or reserved_uom_qty)
  - Loop range(qty) times
  - Print one label per iteration
    ↓
Output: Multiple labels based on quantities
```

---

## Implementation Notes

1. **Markupsafe escaping**: Barcodes and names are wrapped in `markupsafe.Markup()` to prevent XSS and preserve special characters
2. **UOM checking**: Use `_has_common_reference(uom_unit)` to determine if product uses standard units
3. **Fallback logic**: Check both `quantity` (done) and `reserved_uom_qty` (reserved) for flexibility
4. **Lot/Serial handling**: Uses `lot_id` or `lot_name` (for temporary lots) for tracking
5. **Custom barcode pattern**: Supports arbitrary barcodes (not just product barcodes) with associated quantities

