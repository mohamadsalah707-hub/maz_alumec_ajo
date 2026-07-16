from odoo import _, api, fields, models
from odoo.exceptions import UserError
import logging
_logger = logging.getLogger("MAZ")

class AjoOrder(models.Model):
    _name = 'ajo_order'
    _description = 'AJO Order'
    _order = 'date desc, id desc'
    # 1. Inherit the mail mixins here
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _check_company_auto = True

    name = fields.Char(
        string='AJO Nb.', 
        required=True
    )
    company_id = fields.Many2one(
        comodel_name='res.company',
        required=True, index=True,
        default=lambda self: self.env.company)
    project_ref = fields.Char(string='Project Ref', required=True)
    project_code = fields.Char(string='Project Code', required=True)
    pm_id = fields.Many2one('res.users', string='P.M.', required=True, default=lambda self: self.env.user)
    date = fields.Date(string='Date', required=True, default=fields.Date.context_today)
    block = fields.Char(string='Block')
    handle = fields.Char(string='Handle')
    floor = fields.Char(string='Floor')

    # New Native Warehouse Integration
    warehouse_id = fields.Many2one(
        'stock.warehouse', 
        string='Warehouse Name', 
        required=True,
        help="Select the project destination warehouse."
    )
    
    # Automatically fetches the short code from the selected warehouse
    warehouse_code = fields.Char(
        string='Warehouse Code', 
        related='warehouse_id.code', 
        store=True, 
        readonly=True
    )
    
    active = fields.Boolean(default=True)
    
    # Link to the lines model
    order_line_ids = fields.One2many(
        'ajo_order_line', 
        'order_id', 
        string='Order Lines',
        tracking=True
    ) # Filtered fields for the two pages
    alum_order_line_ids = fields.One2many(
        'ajo_order_line', 
        'order_id', 
        string='Alums',
        domain=[('material_type', '=', 'aluminum')]
    )
    glass_order_line_ids = fields.One2many(
        'ajo_order_line', 
        'order_id', 
        string='Glass',
        domain=[('material_type', '=', 'glass')]
    )
    acc_order_line_ids = fields.One2many(
        'ajo_order_line', 
        'order_id', 
        string='Accessories',
        domain=[('material_type', '=', 'accessory')]
    )
    acp_order_line_ids = fields.One2many(
        'ajo_order_line', 
        'order_id', 
        string='Aluminum Composite Panel (ACP)',
        domain=[('material_type', '=', 'acp')]
    )
    steel_order_line_ids = fields.One2many(
        'ajo_order_line', 
        'order_id', 
        string='Steel',
        domain=[('material_type', '=', 'steel')]
    )
# to change this action for printing barcodes    
    def action_mopen_label_layout(self):
        _logger.warning(' begin22 ')
        _logger.warning(self.order_line_ids.product_id.ids)
        _logger.warning(self.order_line_ids.product_tmpl_id.ids)
        view = self.env.ref('maz_alumec_ajo.product_label_layout_form')
        return {
            'name': _('Choose Labels Layout'),
            'type': 'ir.actions.act_window',
            'res_model': 'maz_alumec_ajo.product_label_layout',
            'views': [(view.id, 'form')],
            'target': 'new',
            'context': {
                'default_product_ids': self.order_line_ids.product_id.ids,
                'default_ajo_line_ids': self.order_line_ids.ids,
                'default_print': 'child',
                'default_quantity': 1},
        }

    def _open_cutlist_sum_for_material(self, material_type):
        self.ensure_one()
        existing = self.env['cutlist_sum'].search([
            ('ajo_order_id', '=', self.id),
            ('material_type', '=', material_type)
        ], limit=1)
        if existing:
            return {
                'name': _('Cut List Summary'),
                'type': 'ir.actions.act_window',
                'res_model': 'cutlist_sum',
                'view_mode': 'form',
                'res_id': existing.id,
                'target': 'current',
            }
        return {
            'name': _('Cut List Summary'),
            'type': 'ir.actions.act_window',
            'res_model': 'cutlist_sum',
            'view_mode': 'form',
            'target': 'current',
            'context': {
                'default_ajo_order_id': self.id,
                'default_material_type': material_type,
            },
        }

    def action_generate_manufacturing(self):
        self.ensure_one()
        Production = self.env['mrp.production']
        Bom = self.env['mrp.bom']

        lines_by_item = {}
        for line in self.order_line_ids:
            if not line.item_ref:
                continue
            lines_by_item.setdefault(line.item_ref, self.env['ajo_order_line'])
            lines_by_item[line.item_ref] |= line

        if not lines_by_item:
            raise UserError(_('No order lines with an Item Ref (finished good) to manufacture.'))

        productions = Production
        for item_product, lines in lines_by_item.items():
            existing = Production.search([
                ('origin', '=', self.name),
                ('product_id', '=', item_product.id),
            ], limit=1)
            if existing:
                productions |= existing
                continue

            bom = Bom.create({
                'product_tmpl_id': item_product.product_tmpl_id.id,
                'product_id': item_product.id,
                'product_qty': 1.0,
                'product_uom_id': item_product.uom_id.id,
                'code': self.name,
                'company_id': self.company_id.id,
                'bom_line_ids': [(0, 0, {
                    'product_id': line.product_id.id,
                    'product_qty': line.qty or 0.0,
                    'product_uom_id': line.product_uom_id.id,
                }) for line in lines],
            })

            production = Production.create({
                'product_id': item_product.id,
                'product_qty': 1.0,
                'product_uom_id': item_product.uom_id.id,
                'bom_id': bom.id,
                'origin': self.name,
                'company_id': self.company_id.id,
            })
            productions |= production

        self.message_post(body=_('Generated %s Manufacturing Order(s).') % len(productions))

        action = {
            'name': _('Manufacturing Orders'),
            'type': 'ir.actions.act_window',
            'res_model': 'mrp.production',
            'context': self.env.context,
        }
        if len(productions) == 1:
            action.update({'view_mode': 'form', 'res_id': productions.id})
        else:
            action.update({'view_mode': 'list,form', 'domain': [('id', 'in', productions.ids)]})
        return action

    def action_open_cutlist_sum(self):
        return self._open_cutlist_sum_for_material('aluminum')

    def action_open_glass_cutlist_sum(self):
        return self._open_cutlist_sum_for_material('glass')

    def action_open_acc_cutlist_sum(self):
        return self._open_cutlist_sum_for_material('accessory')

    def action_open_acp_cutlist_sum(self):
        return self._open_cutlist_sum_for_material('acp')

    def action_open_steel_cutlist_sum(self):
        return self._open_cutlist_sum_for_material('steel')

    def action_popen_label_layout(self):
        _logger.warning(' begin22 ')
        _logger.warning(self.order_line_ids.product_id.ids)
        _logger.warning(self.order_line_ids.product_tmpl_id.ids)
        view = self.env.ref('maz_alumec_ajo.product_label_layout_form')
        return {
            'name': _('Choose Labels Layout'),
            'type': 'ir.actions.act_window',
            'res_model': 'maz_alumec_ajo.product_label_layout',
            'views': [(view.id, 'form')],
            'target': 'new',
            'context': {
                'default_product_ids': self.order_line_ids.item_ref.ids,
                'default_ajo_line_ids': self.order_line_ids.ids,
                'default_print': 'parent',
                'default_quantity': 1},
        }



class Angle(models.Model):
    _name = 'angle'
    name = fields.Char('Angle', store=True, required=True)
    angle_image = fields.Image('Angle Image', store=True)

class AjoOrderLine(models.Model):
    _name = 'ajo_order_line'
    _description = 'AJO Order Line'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    # Relational field to the parent order
    _check_company_auto = True

    order_id = fields.Many2one('ajo_order', string='Order Reference', ondelete='cascade', required=True)
    
    company_id = fields.Many2one(
        related='order_id.company_id',
        store=True, index=True, precompute=True)
    item_ref = fields.Many2one(
        comodel_name='product.product',
        string="Item Ref",
        change_default=True, ondelete='restrict', index='btree_not_null',store=True,
        check_company=True)
    
    product_id = fields.Many2one(
        comodel_name='product.product',
        string="Product",
        change_default=True, ondelete='restrict', index='btree_not_null',store=True,required=True,
        check_company=True)
    product_tmpl_id = fields.Many2one(
        string="Product Template",
        comodel_name='product.template',
        compute='_compute_product_tmpl_id',
        readonly=False,
        search='_search_product_tmpl_id',
        store=True
    )
    
    material_type = fields.Selection(related='product_tmpl_id.material_type', string='Material Type', store=True)
    length = fields.Float(
        string='Length',
        related='product_tmpl_id.length',
        readonly=True,
        store=True
    )
    alum_profile = fields.Char(string='Alum. Profile',
        related='product_tmpl_id.alum_profile.name',store=True,
        readonly=True)
    color = fields.Char(
        string='Color',
        related='product_tmpl_id.color_id.name',store=True,
        readonly=True
    )
    width = fields.Float(string='Width', default=0.00,store=True, digits=(16, 2))
    height = fields.Float(string='Height', default=0.00,store=True, digits=(16, 2))
    qty = fields.Integer(string='Qty',store=True, default=1)
    product_uom_id = fields.Many2one(
        comodel_name='uom.uom',
        string="Unit",
        compute='_compute_product_uom_id',
        store=True, readonly=False, precompute=True, ondelete='restrict')
     
    angle = fields.Many2one('angle',string="Angle")
     
    @api.depends('product_id')
    def _compute_product_tmpl_id(self):
        for line in self:
            line.product_tmpl_id = line.product_id.product_tmpl_id if line.product_id else False
     
    def _search_product_tmpl_id(self, operator, value):
        return [('product_id.product_tmpl_id', operator, value)]

    @api.depends('product_id')
    def _compute_product_uom_id(self):
        for line in self:
            if not line.product_uom_id or (line.product_id.uom_id.id != line.product_uom_id.id):
                line.product_uom_id = line.product_id.uom_id
    # 🚀 THE MAGIC TRICK: Force line changes to log on the parent chatter
    def write(self, vals):
        for line in self:
            log_msg = f"<b>Line Edited ({line.item_ref or 'Unnamed Line'}):</b><ul>"
            changes = False
            
            for field, new_val in vals.items():
                # Skip internal relational fields
                if field in ['order_id', 'write_date', 'write_uid']:
                    continue
                    
                old_val = getattr(line, field)
                if old_val != new_val:
                    field_label = self._fields[field].string
                    log_msg += f"<li>{field_label}: <s>{old_val}</s> ➔ <b>{new_val}</b></li>"
                    changes = True
            
            log_msg += "</ul>"
            if changes and line.order_id:
                # Post the log note directly inside the parent order's chatter feed
                line.order_id.message_post(body=log_msg)
                
        return super(AjoOrderLine, self).write(vals)

    @api.model_create_multi
    def create(self, vals_list):
        records = super(AjoOrderLine, self).create(vals_list)
        for record in records:
            if record.order_id:
                record.order_id.message_post(
                    body=f"➕ <b>New Line Added:</b> {record.item_ref or ''} ({record.qty} {record.product_uom_id})"
                )
        return records

    def unlink(self):
        for record in self:
            if record.order_id:
                record.order_id.message_post(
                    body=f"🗑️ <b>Line Removed:</b> {record.item_ref or 'Unnamed Line'}"
                )
        return super(AjoOrderLine, self).unlink()