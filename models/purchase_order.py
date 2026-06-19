
from odoo import fields, api, models
from odoo.tools import float_compare
from odoo.tools import DEFAULT_SERVER_DATETIME_FORMAT
from datetime import datetime, timedelta
from collections import defaultdict

class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'
    x_is_taxable = fields.Boolean(string="Official",default=True, store=True)
    x_defaultwh_id = fields.Integer(string="Default WH",default=1, store=True)
    x_priority = fields.Selection([('Urgent','Urgent'),('Top Urgent','Top Urgent'),('Normal','Normal')],'Priority', required=True, default='Normal')
    @api.onchange('x_is_taxable')
    def _onchange_x_is_taxable(self):
        if not self._context.get('default_partner_id'):
            self.partner_id = False
        else:
            self.partner_id = self._context.get('default_partner_id')
        self.order_line=False
        if self.x_is_taxable:
            self.x_defaultwh_id = 1  
        else:
            self.x_defaultwh_id = 2 
            

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('x_is_taxable'):
                vals['name'] = self.env['ir.sequence'].next_by_code('purchase.order')
            else:
                vals['name'] = self.env['ir.sequence'].next_by_code('purchase.order2')
        res = super(PurchaseOrder, self).create(vals_list)
        return res

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
        form_view_id = self.env.ref('maz_stock_management.purchase_order_line_checklist_form_view').id
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

    # @api.model
    # def _default_product_warehouse_id(self):
        # return self.order_id.x_defaultwh_id
        # , default=_default_product_warehouse_id
           
    product_warehouse_id = fields.Many2one(
        'stock.warehouse', string='Warehouse', help='Choose warehouses', compute='_compute_product_warehouse')#
    x_description = fields.Text('Description')
    
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
    
    @api.depends('order_id.x_defaultwh_id')
    def _compute_product_warehouse(self):
        for line in self:
            line.product_warehouse_id = line.order_id.x_defaultwh_id
        
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
        
    @api.onchange('product_id')
    def onchange_product_id(self):
        if self._context.get('y'):
            self.product_uom = self.product_id.uom_po_id or self.product_id.uom_id
            self._compute_tax_id()
            self.with_context({})
            return
        self.x_description = self.product_id.description
        res = super(PurchaseOrderLine, self).onchange_product_id()
    
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



