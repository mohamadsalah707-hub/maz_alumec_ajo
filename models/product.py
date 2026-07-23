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
        """Generate cutting list name: Profile - Color - Length (bare number,
        e.g. "700 - RAL8014 - 6000" - no "L:" prefix or "mm" suffix)."""
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
                parts.append('%g' % record.length)
            record.name = ' - '.join(parts)

    @api.model_create_multi
    def create(self, vals_list):
        mm_uom = self.env.ref('uom.product_uom_millimeter', raise_if_not_found=False)
        for vals in vals_list:
            if vals.get('material_type') == 'aluminum' and mm_uom and not vals.get('uom_id'):
                vals['uom_id'] = mm_uom.id
            # Applies regardless of how the product is created - manually via
            # the product form, through the import wizard, or the parametric
            # window generator - so none of them has to remember to set it.
            if vals.get('material_type') and 'is_storable' not in vals:
                vals['is_storable'] = True
            if vals.get('alum_profile') and not (vals.get('categ_id') and vals.get('sub_categ_id')):
                base = self._ajo_find_base_material_product(vals['alum_profile'], vals.get('color_id'))
                if base:
                    if not vals.get('categ_id') and base.categ_id:
                        vals['categ_id'] = base.categ_id.id
                    if not vals.get('sub_categ_id') and base.sub_categ_id:
                        vals['sub_categ_id'] = base.sub_categ_id.id
        return super().create(vals_list)

    def write(self, vals):
        if vals.get('material_type') == 'aluminum' and not vals.get('uom_id'):
            mm_uom = self.env.ref('uom.product_uom_millimeter', raise_if_not_found=False)
            if mm_uom:
                vals = dict(vals, uom_id=mm_uom.id)
        if vals.get('material_type') and 'is_storable' not in vals:
            vals = dict(vals, is_storable=True)
        res = super().write(vals)
        if 'alum_profile' in vals or 'color_id' in vals:
            for record in self:
                if not record.alum_profile or (record.categ_id and record.sub_categ_id):
                    continue
                base = self._ajo_find_base_material_product(
                    record.alum_profile.id, record.color_id.id if record.color_id else False,
                )
                if not base or base.id == record.id:
                    continue
                update_vals = {}
                if not record.categ_id and base.categ_id:
                    update_vals['categ_id'] = base.categ_id.id
                if not record.sub_categ_id and base.sub_categ_id:
                    update_vals['sub_categ_id'] = base.sub_categ_id.id
                if update_vals:
                    # Bypass this same override on the follow-up write: it
                    # never touches alum_profile/color_id, so there's nothing
                    # more for it to do, only avoidable recursion.
                    super(ProductTemplate, record).write(update_vals)
        return res

    def _ajo_find_base_material_product(self, alum_profile_id, color_id):
        """Find an existing aluminum product (any length) for a given
        profile/color, used as the source of Category/Sub Category info for
        a sibling product - manually created, imported, or a
        parametrically-generated offcut - that doesn't have them set yet."""
        if not alum_profile_id:
            return self.browse()
        return self.search([
            ('alum_profile', '=', alum_profile_id),
            ('material_type', '=', 'aluminum'),
            ('color_id', '=', color_id or False),
        ], limit=1)

    @api.onchange('material_type')
    def _onchange_material_type_uom(self):
        if self.material_type == 'aluminum':
            mm_uom = self.env.ref('uom.product_uom_millimeter', raise_if_not_found=False)
            if mm_uom:
                self.uom_id = mm_uom
        if self.material_type:
            self.is_storable = True

    @api.onchange('alum_profile', 'color_id')
    def _onchange_alum_profile_color_category(self):
        if not self.alum_profile or (self.categ_id and self.sub_categ_id):
            return
        base = self._ajo_find_base_material_product(
            self.alum_profile.id, self.color_id.id if self.color_id else False,
        )
        if not base or base.id == self._origin.id:
            return
        if not self.categ_id and base.categ_id:
            self.categ_id = base.categ_id
        if not self.sub_categ_id and base.sub_categ_id:
            self.sub_categ_id = base.sub_categ_id

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
                # 'is_storable' and Category/Sub Category are filled in by
                # create()'s own logic above - no need to set them here.
                'alum_profile': alum_profile.id,
                'color_id': color.id if color else False,
                'material_type': material_type,
                'type': 'consu',
            }
            if material_type == 'aluminum' and length:
                vals['length'] = length
            template = self.create(vals)
        return template.product_variant_id

    @api.model
    def get_or_create_offcut_product(self, alum_profile, color, length):
        """Find or create a distinct product for a specific reusable aluminum
        offcut length: same profile/color as the master bar it was cut from,
        but its own product - keyed additionally by `length` - so an offcut
        is never confused with (and never forces lot tracking onto) the
        master profile product. Its Category/Sub Category are inserted (on
        creation, via create()'s own logic above) or backfilled here (if
        missing on an already-existing offcut product) from the base profile
        product of the same profile/color, so an offcut is never left
        uncategorized."""
        color_id = color.id if color else False
        template = self.search([
            ('alum_profile', '=', alum_profile.id),
            ('material_type', '=', 'aluminum'),
            ('color_id', '=', color_id),
            ('length', '=', length),
        ], limit=1)
        if not template:
            template = self.create({
                'alum_profile': alum_profile.id,
                'color_id': color_id,
                'material_type': 'aluminum',
                'length': length,
                'type': 'consu',
            })
        elif not (template.categ_id and template.sub_categ_id):
            base = self._ajo_find_base_material_product(alum_profile.id, color_id)
            if base and base.id != template.id:
                update_vals = {}
                if not template.categ_id and base.categ_id:
                    update_vals['categ_id'] = base.categ_id.id
                if not template.sub_categ_id and base.sub_categ_id:
                    update_vals['sub_categ_id'] = base.sub_categ_id.id
                if update_vals:
                    template.write(update_vals)
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
