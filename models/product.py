from odoo import fields, api, models
from odoo.tools import float_compare



class ProductTemplate(models.Model):
    _inherit = 'product.template'

    #item_ref = fields.Char(string='Item Ref')
    alum_profile = fields.Many2one('alum_profile', string='Alum. Profile')
    warehouse = fields.Many2one('stock.warehouse', "Warehouse")
    length = fields.Float(string='Profile Length', default=0.00, digits=(16, 2),
        store=True)
    width = fields.Float(string='Width', default=0.00, digits=(16, 2),
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
    sub_categ_id = fields.Many2one(
        'product_sub_category',
        string='Sub Category',
        domain="[('category_id', '=', categ_id)]",
        help="Must belong to the selected Category.",
    )
    name = fields.Char(
        compute='_compute_name', store=True, readonly=False, precompute=True,
    )

    @api.depends('alum_profile', 'color_id', 'length')
    def _compute_name(self):
        """Generate cutting list name: Profile - Color - Length"""
        for record in self:
            if not (record.alum_profile or record.color_id):
                # Not an aluminum/cutlist product: leave any manually entered name as-is.
                record.name = record.name
                continue
            parts = []
            if record.alum_profile:
                parts.append(record.alum_profile.name)
            if record.color_id:
                parts.append(record.color_id.name)
            if record.length:
                unit = 'mm' if record.material_type == 'aluminum' else ''
                parts.append('L:%.0f%s' % (record.length, unit) if unit else 'L:%s' % record.length)
            record.name = ' - '.join(parts)

    @api.model_create_multi
    def create(self, vals_list):
        mm_uom = self.env.ref('uom.product_uom_millimeter', raise_if_not_found=False)
        if mm_uom:
            for vals in vals_list:
                if vals.get('material_type') == 'aluminum' and not vals.get('uom_id'):
                    vals['uom_id'] = mm_uom.id
        return super().create(vals_list)

    def write(self, vals):
        if vals.get('material_type') == 'aluminum' and not vals.get('uom_id'):
            mm_uom = self.env.ref('uom.product_uom_millimeter', raise_if_not_found=False)
            if mm_uom:
                vals = dict(vals, uom_id=mm_uom.id)
        return super().write(vals)

    @api.onchange('material_type')
    def _onchange_material_type_uom(self):
        if self.material_type == 'aluminum':
            mm_uom = self.env.ref('uom.product_uom_millimeter', raise_if_not_found=False)
            if mm_uom:
                self.uom_id = mm_uom

    @api.model
    def get_or_create_material_product(self, material_type, profile_code, color_code,
                                        profile_brand=None, length=None):
        """Find or create the product.product for an (material_type, profile/item
        code, color) combination. Shared by the AJO cutlist import wizard and the
        parametric window-template cut list generator so both resolve products
        the same way. `length`, when given and the product is newly created, sets
        that new aluminum product's own Profile Length (stock bar length)."""
        profile_code = str(profile_code)
        color_code = str(color_code) if color_code else ''

        AlumProfile = self.env['alum_profile']
        alum_profile = AlumProfile.search([('code', '=', profile_code)], limit=1)
        if not alum_profile:
            alum_profile = AlumProfile.create({
                'name': profile_code,
                'code': profile_code,
                'brand': profile_brand or '',
            })

        Color = self.env['product_color']
        color = Color
        if color_code:
            color = Color.search([('code', '=', color_code)], limit=1)
            if not color:
                color = Color.create({'name': color_code, 'code': color_code})

        domain = [
            ('alum_profile', '=', alum_profile.id),
            ('material_type', '=', material_type),
            ('color_id', '=', color.id if color else False),
        ]
        template = self.search(domain, limit=1)
        if not template:
            vals = {
                # 'name' is left unset: _compute_name derives it from
                # alum_profile + color_id (+ length, in mm, for aluminum).
                'alum_profile': alum_profile.id,
                'color_id': color.id if color else False,
                'material_type': material_type,
                'type': 'consu',
            }
            if material_type == 'aluminum':
                # Lot tracking is required for the offcut/waste workflow:
                # each reusable leftover piece is stored as its own lot
                # carrying its exact length (see models/mrp_offcut.py).
                vals['tracking'] = 'lot'
                if length:
                    vals['length'] = length
            template = self.create(vals)
        return template.product_variant_id

class ProductSubCategory(models.Model):
    _name = 'product_sub_category'
    _description = 'Product Sub Category'

    name = fields.Char('Sub Category', store=True, required=True)
    category_id = fields.Many2one(
        'product.category', string='Category', store=True, required=True,
    )

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
