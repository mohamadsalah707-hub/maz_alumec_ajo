from odoo import fields, api, models
from odoo.tools import float_compare



class ProductTemplate(models.Model):
    _inherit = 'product.template'

    #item_ref = fields.Char(string='Item Ref')
    alum_profile = fields.Many2one('alum_profile', string='Alum. Profile')
    warehouse = fields.Many2one('stock.warehouse', "Warehouse")
    length = fields.Float(string='Profile Length', default=0.00, digits=(16, 2),
        store=True)
    material_type = fields.Selection([
        ('aluminum', 'Aluminum'),
        ('glass', 'Glass'),
        ('steel', 'Steel'),
        ('acp', 'Aluminum Composite Panel (ACP)'),
        ('accessory', 'Accessory'),
        ('other', 'Other'),
    ], string='Material Type')
    color_id = fields.Many2one(
            'product_color', 
            string="color",
            readonly=False, # Optional: make it read-only on product.product
            store=True,   # Optional: if you don't need to store it in the DB
        )
        
    @api.depends('alum_profile', 'color_id', 'length')
    def _compute_name(self):
        """Generate cutting list name"""
        for record in self:
            parts = []
            if record.alum_profile:
                parts.append(record.alum_profile.name)
            if record.color_id:
                parts.append(record.color_id.name)
            parts.append(f"L: {record.length}")
            record.name = " - ".join(parts) if parts else ""
    
class ProductColor(models.Model):
    _name = 'product_color'
    name = fields.Char('Description', store=True, required=True)
    code = fields.Char('Code', store=True, required=True)
    
class AlumProfile(models.Model):
    _name = 'alum_profile'
    name = fields.Char('Description', store=True, required=True)
    code = fields.Char('Code', store=True, required=True)
    brand = fields.Char('Profile Brand', store=True, required=True)
    
 
class ProductProduct(models.Model):
    _inherit = 'product.product'
    warehouse = fields.Many2one(
            string="WareHouse",
            related='product_tmpl_id.warehouse',
            readonly=True, # Optional: make it read-only on product.product
            store=False,   # Optional: if you don't need to store it in the DB
        )
