from odoo import _, api, fields, models
from odoo.exceptions import UserError

UOM_XMLID_MAP = {
    'mm': 'uom.product_uom_millimeter',
    'cm': 'uom.product_uom_cm',
    'm': 'uom.product_uom_meter',
    'pcs': 'uom.product_uom_unit',
    'pc': 'uom.product_uom_unit',
    'unit': 'uom.product_uom_unit',
    'units': 'uom.product_uom_unit',
}


class AjoOrderWindow(models.Model):
    _name = 'ajo_order_window'
    _description = 'AJO Order Window / Door (parametric)'
    _order = 'sequence, id'

    order_ref = fields.Char(
        string='AJO Nb.', required=True,
        help='Type the AJO Order number. If it does not exist yet it is created '
             'automatically; if it already exists, this window is linked to it.',
    )
    order_id = fields.Many2one(
        'ajo_order', string='AJO Order', ondelete='cascade', readonly=True, store=True,
    )
    project_ref = fields.Char(
        string='Project Name',
        help='Used when the AJO Order is created for the first time. If the AJO '
             'Nb. above already exists, this just mirrors that order\'s Project '
             'Name and editing it here has no effect.',
    )
    project_code = fields.Char(
        string='Project Code',
        help='Used when the AJO Order is created for the first time. If the AJO '
             'Nb. above already exists, this just mirrors that order\'s Project '
             'Code and editing it here has no effect.',
    )
    block = fields.Char(
        string='Block',
        help='Used when the AJO Order is created for the first time.',
    )
    floor = fields.Char(
        string='Floor',
        help='Used when the AJO Order is created for the first time.',
    )
    company_id = fields.Many2one(related='order_id.company_id', store=True, index=True)
    sequence = fields.Integer(default=10)
    name = fields.Char(string='Window No.', required=True, help="e.g. A1-W2")
    template_id = fields.Many2one('ajo_window_template', string='Template', required=True)
    color_id = fields.Many2one('product_color', string='Color', required=True)
    glass_type_id = fields.Many2one('ajo_glass_type', string='Glass Type', help="e.g. G1")
    glass_thickness_id = fields.Many2one('ajo_glass_thickness', string='Glass Thickness', help="e.g. 32 mm")
    length = fields.Float(string='L (Width, mm)', required=True)
    height = fields.Float(string='H (Height, mm)', required=True)
    qty = fields.Integer(string='Qty', default=1, required=True)
    handle_height = fields.Float(string='Handle Height (mm)')
    flag_value_ids = fields.One2many('ajo_order_window_flag_value', 'window_id', string='Options')
    generated_line_ids = fields.One2many('ajo_order_line', 'window_id', string='Generated Lines')
    generated_line_count = fields.Integer(compute='_compute_generated_line_count')

    @api.depends('generated_line_ids')
    def _compute_generated_line_count(self):
        for window in self:
            window.generated_line_count = len(window.generated_line_ids)

    @api.onchange('order_ref')
    def _onchange_order_ref(self):
        if not self.order_ref:
            self.order_id = False
            return
        existing = self.env['ajo_order'].search([('name', '=', self.order_ref)], limit=1)
        if existing:
            self.order_id = existing
            # Mirror the existing order's info for reference; since order_id
            # is already set, create()/write() below won't use these to
            # create a second order.
            self.project_ref = existing.project_ref
            self.project_code = existing.project_code
            self.block = existing.block
            self.floor = existing.floor
            return {'warning': {
                'title': _('AJO Order already exists'),
                'message': _(
                    'An AJO Order named "%s" already exists. This window will be linked to it.'
                ) % self.order_ref,
            }}
        self.order_id = False

    @api.model
    def _get_or_create_order(self, order_ref, project_ref=None, project_code=None,
                              block=None, floor=None):
        order = self.env['ajo_order'].search([('name', '=', order_ref)], limit=1)
        if not order:
            order = self.env['ajo_order'].create({
                'name': order_ref,
                'project_ref': project_ref or order_ref,
                'project_code': project_code or order_ref,
                'block': block or '',
                'floor': floor or '',
            })
        return order

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('order_id') and vals.get('order_ref'):
                vals['order_id'] = self._get_or_create_order(
                    vals['order_ref'], vals.get('project_ref'), vals.get('project_code'),
                    vals.get('block'), vals.get('floor'),
                ).id
        return super().create(vals_list)

    def write(self, vals):
        if vals.get('order_ref') and not vals.get('order_id'):
            vals = dict(vals, order_id=self._get_or_create_order(
                vals['order_ref'], vals.get('project_ref'), vals.get('project_code'),
                vals.get('block'), vals.get('floor'),
            ).id)
        return super().write(vals)

    @api.onchange('template_id')
    def _onchange_template_id(self):
        for window in self:
            if window.template_id:
                window.handle_height = window.template_id.handle_height_default
                window.flag_value_ids = [(5, 0, 0)] + [
                    (0, 0, {'flag_id': flag.id, 'value': flag.default_value})
                    for flag in window.template_id.flag_ids
                ]

    def _get_or_create_finished_product(self):
        self.ensure_one()
        code = self.name
        product = self.env['product.product'].search([('default_code', '=', code)], limit=1)
        if product:
            return product
        template = self.env['product.template'].create({
            'name': '%s - %s' % (code, self.order_id.project_ref or ''),
            'default_code': code,
            'type': 'consu',
            'sale_ok': False,
            'purchase_ok': False,
        })
        return template.product_variant_id

    def _get_or_create_angle(self, angle_label):
        if not angle_label:
            return self.env['angle']
        angle = self.env['angle'].search([('name', '=', angle_label)], limit=1)
        if not angle:
            angle = self.env['angle'].create({'name': angle_label})
        return angle

    def _get_uom(self, unit_label):
        key = (unit_label or '').strip().lower()
        xmlid = UOM_XMLID_MAP.get(key, 'uom.product_uom_unit')
        return (
            self.env.ref(xmlid, raise_if_not_found=False)
            or self.env.ref('uom.product_uom_unit')
        )

    def action_generate_lines(self):
        for window in self:
            window._generate_lines()
        return True

    def _generate_lines(self):
        self.ensure_one()
        if not self.template_id.line_ids:
            raise UserError(_('This template has no cut list lines defined.'))

        # Clear previously generated lines so the button can be safely re-run
        # after editing L/H/Qty/options.
        self.generated_line_ids.unlink()

        item_product = self._get_or_create_finished_product()
        flag_values = {fv.flag_id.id: fv.value for fv in self.flag_value_ids}

        ProductTemplate = self.env['product.template']
        Line = self.env['ajo_order_line']
        manual_notes = []

        for tline in self.template_id.line_ids.sorted('sequence'):
            if tline.condition_flag_id:
                actual = flag_values.get(tline.condition_flag_id.id, tline.condition_flag_id.default_value)
                if bool(actual) != bool(tline.condition_value):
                    continue

            length = tline.length_coef_l * self.length + tline.length_coef_h * self.height + tline.length_const
            width = tline.width_coef_l * self.length + tline.width_coef_h * self.height + tline.width_const

            profile_code = tline.profile_code
            if not profile_code and tline.material_type == 'glass':
                profile_code = self.glass_type_id.name if self.glass_type_id else False
            if not profile_code:
                raise UserError(_(
                    'Line %s (%s) has no Profile/Item Code and no Glass Type to fall back on.'
                ) % (tline.sequence, tline.material_type))

            if tline.qty_mode == 'multiplier':
                qty = tline.qty_multiplier * self.qty
            elif tline.qty_mode == 'perimeter':
                qty = tline.qty_perimeter_factor * (2 * self.length + 2 * self.height) * self.qty
            else:
                qty = 0.0
                manual_notes.append(profile_code)

            profile_brand = tline.profile_brand_override or tline.template_id.profile_brand
            color_code = tline.color_override or self.color_id.code
            profile_length = tline.profile_length_override or tline.template_id.profile_length
            product = ProductTemplate.get_or_create_material_product(
                tline.material_type, profile_code, color_code, profile_brand,
                length=profile_length,
            )
            angle = self._get_or_create_angle(tline.angle)
            uom = self._get_uom(tline.unit)

            Line.create({
                'order_id': self.order_id.id,
                'window_id': self.id,
                'item_ref': item_product.id,
                'product_id': product.id,
                'width': width,
                'height': length,
                'qty': qty,
                'angle': angle.id if angle else False,
                'product_uom_id': uom.id,
            })

        if manual_notes:
            self.order_id.message_post(body=_(
                'Window %s: %s line(s) need a manual quantity (formula depends on '
                'other lines\' totals, not just L/H/Qty): %s'
            ) % (self.name, len(manual_notes), ', '.join(manual_notes)))


class AjoOrderWindowFlagValue(models.Model):
    _name = 'ajo_order_window_flag_value'
    _description = 'AJO Order Window Option Value'

    window_id = fields.Many2one('ajo_order_window', required=True, ondelete='cascade')
    flag_id = fields.Many2one('ajo_window_template_flag', required=True, ondelete='cascade')
    name = fields.Char(related='flag_id.name', readonly=True)
    value = fields.Boolean(string='Enabled')

    @api.model_create_multi
    def create(self, vals_list):
        # Options rows only ever make sense tied to a flag; silently drop any
        # blank row instead of failing the whole form save (e.g. a stray line
        # left over from before the "Options" list was locked to no-create).
        vals_list = [vals for vals in vals_list if vals.get('flag_id')]
        if not vals_list:
            return self.browse()
        return super().create(vals_list)
