
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



