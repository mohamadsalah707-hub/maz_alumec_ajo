
from odoo import fields, api, models
from odoo.tools import float_compare
from odoo.tools import DEFAULT_SERVER_DATETIME_FORMAT
from datetime import datetime, timedelta
from collections import defaultdict
    
import logging
_logger = logging.getLogger('MAZ PO')

class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'         

    def action_open_iso_checklist(self):
        order_ids = self.ids or self.env.context.get('active_ids', [])
        if not order_ids:
            active_id = self.env.context.get('active_id')
            order_ids = [active_id] if active_id else []
        if not order_ids:
            return {'type': 'ir.actions.act_window_close'}

        checklist = self.env['purchase.order.line.checklist'].search(
            [('purchase_order_id', 'in', order_ids)],
            order='id desc',
            limit=1,
        )
        form_view_id = self.env.ref('maz_alumec_ajo.purchase_order_line_checklist_form_view').id
        if checklist:
            return {
                'name': 'ISO Checklist',
                'type': 'ir.actions.act_window',
                'res_model': 'purchase.order.line.checklist',
                'res_id': checklist.id,
                'view_mode': 'form',
                'view_id': form_view_id,
                'views': [(form_view_id, 'form')],
                'target': 'current',
            }

        order = self.browse(order_ids[0])
        first_line = order.order_line[:1]
        if first_line:
            return {
                'name': 'ISO Checklist',
                'type': 'ir.actions.act_window',
                'res_model': 'purchase.order.line.checklist',
                'view_mode': 'form',
                'view_id': form_view_id,
                'views': [(form_view_id, 'form')],
                'target': 'new',
                'context': {'default_purchase_line_id': first_line.id},
            }

        return {'type': 'ir.actions.act_window_close'}

class PurchaseOrderLine(models.Model):
    """ Add new button in purchase order line """
    _inherit = 'purchase.order.line'


    product_profile = fields.Char(string='Product Profile', )
    color = fields.Char(string='Color', )
    total_length = fields.Float(string='Total Length', digits=(16, 2),)
    area = fields.Float(string='Area/m²', digits=(16, 2), compute='_compute_area', store=True)
    profile_length = fields.Float(string='Profile Length', digits=(16, 2), )
    width = fields.Float(string='Width', digits=(16, 2), )

    # ------------------------------------------------------------------
    # Aluminum profile purchasing by the piece, priced per kg (see
    # PURCHASE_ALUMINUM_WEIGHT_PRICING.md). Deliberately kept on separate
    # 'alu_' prefixed fields - the width/total_length/area fields above are
    # an unrelated, pre-existing area-based costing scheme for flat stock.
    # ------------------------------------------------------------------

    alu_qty_pieces = fields.Integer(
        string='Quantity in Pieces',
        compute='_compute_alu_qty_pieces', inverse='_inverse_alu_qty_pieces',
        store=True, readonly=False,
        help='Number of individual bars/pieces being purchased. Kept in '
             'sync with the standard Quantity field above (which stays the '
             'source of truth for stock/invoicing) so this can be shown '
             'and edited as a whole number.',
    )
    alu_weight_per_meter = fields.Float(
        string='Weight per Meter (kg/lm)', digits=(16, 3),
        help='Weight of one linear meter of this profile, in kg. '
             "Auto-fetched from the product's own Weight per Meter when "
             'the Product is set; editable afterwards.',
    )
    alu_price_per_kg = fields.Monetary(
        string='Price per KG', currency_field='currency_id',
        help='Purchase rate for this profile, per kilogram.',
    )
    alu_unit_cost = fields.Float(
        string='Unit Cost', digits='Product Price',
        compute='_compute_alu_unit_cost', store=True,
        help='Weight per Meter x Length per Piece x Price per KG.',
    )
    alu_total_length = fields.Float(
        string='Total Length (m)', digits=(16, 2),
        compute='_compute_alu_totals', store=True,
        help='Quantity in Pieces x Length per Piece.',
    )
    alu_total_weight = fields.Float(
        string='Total Weight (kg)', digits=(16, 2),
        compute='_compute_alu_totals', store=True,
        help='Total Length x Weight per Meter.',
    )
    alu_total = fields.Monetary(
        string='Total', currency_field='currency_id',
        compute='_compute_alu_totals', store=True,
        help='Quantity in Pieces x Unit Cost.',
    )

    @api.depends('product_qty')
    def _compute_alu_qty_pieces(self):
        for line in self:
            line.alu_qty_pieces = int(line.product_qty)

    def _inverse_alu_qty_pieces(self):
        for line in self:
            line.product_qty = float(line.alu_qty_pieces)

    @api.depends('alu_weight_per_meter', 'profile_length', 'alu_price_per_kg')
    def _compute_alu_unit_cost(self):
        for line in self:
            line.alu_unit_cost = (
                line.alu_weight_per_meter * line.profile_length/1000.0 * line.alu_price_per_kg
            )
            line.price_unit = line.alu_unit_cost if line.product_id.material_type == 'aluminum' else line.price_unit

    @api.depends('alu_qty_pieces', 'profile_length', 'alu_weight_per_meter', 'alu_unit_cost')
    def _compute_alu_totals(self):
        for line in self:
            line.alu_total_length = line.alu_qty_pieces * line.profile_length
            line.alu_total_weight = line.alu_total_length * line.alu_weight_per_meter
            line.alu_total = line.alu_qty_pieces * line.alu_unit_cost

    @api.onchange('alu_weight_per_meter', 'profile_length', 'alu_price_per_kg',
                  'product_id')
    def _onchange_alu_weight_pricing(self):
        for line in self:
            if line.product_id.material_type == 'aluminum':
                line.price_unit = (
                    line.alu_weight_per_meter * line.profile_length/1000.0 * line.alu_price_per_kg
                )

    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        lines._sync_alu_price_unit()
        return lines

    def write(self, vals):
        res = super().write(vals)
        if any(f in vals for f in (
            'alu_weight_per_meter', 'profile_length', 'alu_price_per_kg', 'product_id'
        )):
            self._sync_alu_price_unit()
        return res

    def _sync_alu_price_unit(self):
        """Server-side enforcement of the Price by Weight toggle, so API/
        import paths (not just the form's onchange) keep price_unit correct."""
        for line in self:
            if line.product_id.material_type == 'aluminum' and line.price_unit != line.alu_unit_cost:
                super(PurchaseOrderLine, line).write({'price_unit': line.alu_unit_cost})

    # ISO Checklist fields
    checklist_ids = fields.One2many(
        'purchase.order.line.checklist',
        'purchase_line_id',
        string='ISO Checklists' 
    )
    checklist_count = fields.Integer(
        string='Checklist Count',
        compute='_compute_checklist_count',
        store=True
    )
    latest_checklist_score = fields.Integer(
        string='Latest Score',
        compute='_compute_latest_checklist_score'
    )
    @api.depends('width', 'total_length')
    def _compute_area(self):
        for line in self:
            logging_info = f"Computing area for line ID {line.id}: width={line.width}, total_length={line.total_length}"
            _logger.info(logging_info)
            if line.width and line.total_length:
                line.area = (line.width * line.total_length) / 1000000.0
            else:
                line.area = 0.0
        
    @api.depends('checklist_ids')
    def _compute_checklist_count(self):
        for line in self:
            line.checklist_count = len(line.checklist_ids)
    
    def _compute_latest_checklist_score(self):
        for line in self:
            if line.checklist_ids:
                latest = line.checklist_ids.sorted(lambda x: x.id, reverse=True)[0]
                line.latest_checklist_score = latest.score_total
            else:
                line.latest_checklist_score = 0

    def action_open_iso_checklist(self):
        """Open ISO checklist form for this purchase order line"""
        self.ensure_one()
        
        # Get or create checklist record
        existing_checklist = self.checklist_ids.sorted(lambda x: x.id, reverse=True)
        
        if existing_checklist:
            checklist = existing_checklist[0]
        else:
            checklist = self.env['purchase.order.line.checklist'].create({
                'purchase_line_id': self.id
            })
        
        return {
            'name': 'ISO Checklist - %s' % self.product_id.name,
            'view_type': 'form',
            'view_mode': 'form',
            'res_model': 'purchase.order.line.checklist',
            'res_id': checklist.id,
            'type': 'ir.actions.act_window',
            'target': 'new',
            'context': {'default_purchase_line_id': self.id}
        }



