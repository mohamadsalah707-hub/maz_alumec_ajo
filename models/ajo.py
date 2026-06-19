from odoo import models, fields, api

class AjoOrder(models.Model):
    _name = 'ajo_order'
    _description = 'AJO Order'
    _order = 'date desc, id desc'
    # 1. Inherit the mail mixins here
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(
        string='AJO Nb.', 
        required=True, 
        copy=False, 
        readonly=True, 
        default=lambda self: self.env['ir.sequence'].next_by_code('ajo.order') or '/'
    )
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
        string='Accesories',
        domain=[('material_type', '=', 'accesory')]
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
    


class Angle(models.Model):
    _name = 'angle'
    name = fields.Char('Angle', store=True, required=True)
    angle_image = fields.Image('Angle Image', store=True)

class AjoOrderLine(models.Model):
    _name = 'ajo_order_line'
    _description = 'AJO Order Line'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    # Relational field to the parent order

    order_id = fields.Many2one('ajo_order', string='Order Reference', ondelete='cascade', required=True)
    item_ref = fields.Many2one(
        comodel_name='product.product',
        string="Item Ref",
        change_default=True, ondelete='restrict', index='btree_not_null',store=True,
        check_company=True)
    
    product_id = fields.Many2one(
        comodel_name='product.product',
        string="Product",
        change_default=True, ondelete='restrict', index='btree_not_null',store=True,
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