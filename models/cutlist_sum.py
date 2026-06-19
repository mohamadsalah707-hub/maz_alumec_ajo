from odoo import models, fields, api
from odoo.tools import float_compare


class CutlistSum(models.Model):
    _name = 'cutlist_sum'
    _description = 'Cut List Summary'
    _order = 'date desc, id desc'

    ajo_order_id = fields.Many2one(
        'ajo_order',
        string='AJO Order',
        required=True,
        ondelete='cascade',
    )
    name = fields.Char(
        string='AJO No.',
        related='ajo_order_id.name',
        store=True,
        readonly=True,
    )
    project_code = fields.Char(
        string='Project Code',
        related='ajo_order_id.project_code',
        store=True,
        readonly=True,
    )
    warehouse_id = fields.Many2one(
        'stock.warehouse',
        string='Warehouse',
        related='ajo_order_id.warehouse_id',
        store=True,
        readonly=True,
    )
    vendor_id = fields.Many2one(
        'res.partner',
        string='Vendor',
        required=False,
    )
    date = fields.Date(
        string='Date',
        related='ajo_order_id.date',
        store=True,
        readonly=True,
    )
    currency_id = fields.Many2one(
        'res.currency',
        string='Currency',
        default=lambda self: self.env.company.currency_id,
    )
    line_ids = fields.One2many(
        'cutlist_sum_lines',
        'cutlist_id',
        string='Lines',
    )
    totqtytoorder = fields.Float(
        string='Total Qty to Order',
        compute='_compute_totals',
        store=True,
    )
    totmaxqtyneeded = fields.Float(
        string='Total Max Qty Needed',
        compute='_compute_totals',
        store=True,
    )

    @api.depends('line_ids.qtytoorder', 'line_ids.max_qty_needed')
    def _compute_totals(self):
        for record in self:
            record.totqtytoorder = sum(record.line_ids.mapped('qtytoorder'))
            record.totmaxqtyneeded = sum(record.line_ids.mapped('max_qty_needed'))

    def action_generate_lines(self):
        self.ensure_one()
        self.line_ids.unlink()
        order = self.ajo_order_id
        if not order:
            return

        lines = order.order_line_ids
        grouped = {}
        for line in lines:
            tmpl = line.product_tmpl_id
            if not tmpl:
                continue
            grouped.setdefault(tmpl.id, {
                'lines': [],
                'tmpl': tmpl,
                'warehouse_id': order.warehouse_id.id,
                'qty': 0,
                'total_length': 0.0,
                'widths': [],
                'max_qty': 0,
                'min_qty': 0,
            })
            entry = grouped[tmpl.id]
            entry['lines'].append(line)
            entry['qty'] += line.qty
            entry['total_length'] += line.qty * tmpl.length
            entry['widths'].append(line.width)
            if entry['max_qty'] == 0 or line.qty > entry['max_qty']:
                entry['max_qty'] = line.qty
            if entry['min_qty'] == 0 or line.qty < entry['min_qty']:
                entry['min_qty'] = line.qty

        vals_list = []
        for tmpl_id, entry in grouped.items():
            tmpl = entry['tmpl']
            product = tmpl.product_variant_id[:1]
            available_qty = 0.0
            if product and entry['warehouse_id']:
                available_qty = product.with_context(
                    warehouse=entry['warehouse_id']
                ).free_qty

            max_qty = entry['max_qty']
            qtytoorder = max(0.0, max_qty - available_qty)

            if available_qty > 0 and max_qty > 0:
                increase_percent = ((max_qty - available_qty) / available_qty) * 100
            elif max_qty > 0:
                increase_percent = 100.0
            else:
                increase_percent = 0.0

            vals_list.append({
                'cutlist_id': self.id,
                'product_tmpl_id': tmpl_id,
                'warehouse_id': entry['warehouse_id'],
                'warehouse_code': tmpl.warehouse.code or '',
                'product_profile': tmpl.alum_profile.name or '',
                'color': tmpl.color_id.name or '',
                'total_length': entry['total_length'],
                'profile_length': tmpl.length or 0.0,
                'width': max(entry['widths']) if entry['widths'] else 0.0,
                'available_qty': available_qty,
                'max_qty_needed': max_qty,
                'min_qty_needed': entry['min_qty'],
                'increase_percent': increase_percent,
                'qtytoorder': qtytoorder,
            })

        self.env['cutlist_sum_lines'].create(vals_list)


class CutlistSumLines(models.Model):
    _name = 'cutlist_sum_lines'
    _description = 'Cut List Summary Lines'

    cutlist_id = fields.Many2one(
        'cutlist_sum',
        string='Cutlist Summary',
        required=True,
        ondelete='cascade',
    )
    product_tmpl_id = fields.Many2one(
        'product.template',
        string='Product Template',
        required=True,
    )
    warehouse_id = fields.Many2one(
        'stock.warehouse',
        string='Warehouse',
    )
    warehouse_code = fields.Char(
        string='Warehouse Code',
    )
    product_profile = fields.Char(
        string='Product Profile',
    )
    color = fields.Char(
        string='Color',
    )
    total_length = fields.Float(
        string='Total Length',
        digits=(16, 2),
    )
    profile_length = fields.Float(
        string='Profile Length',
        digits=(16, 2),
    )
    width = fields.Float(
        string='Width',
        digits=(16, 2),
    )
    available_qty = fields.Float(
        string='Available Qty',
        digits=(16, 2),
    )
    max_qty_needed = fields.Float(
        string='Max Qty Needed',
        digits=(16, 2),
    )
    min_qty_needed = fields.Float(
        string='Min Qty Needed',
        digits=(16, 2),
    )
    increase_percent = fields.Float(
        string='Increase %',
        digits=(16, 2),
    )
    qtytoorder = fields.Float(
        string='Qty to Order',
        digits=(16, 2),
    )
