from odoo import fields, models


class AjoWindowTemplate(models.Model):
    _name = 'ajo_window_template'
    _description = 'AJO Window/Door Template (parametric cut list)'
    _order = 'name'

    name = fields.Char(string='Template Name', required=True)
    profile_brand = fields.Char(
        string='Default Profile Brand',
        help="Used on lines that don't set their own Profile Brand override (e.g. 'TECHNAL FXI').",
    )
    handle_height_default = fields.Float(string='Default Handle Height (mm)', default=0.0)
    profile_length = fields.Float(
        string='Default Profile Length (mm)', default=0.0,
        help="Standard stock bar length for this system's aluminum profiles "
             "(e.g. 6500). Used to set new aluminum products' own Profile Length "
             "when they're first auto-created by Generate Cut List Lines, so the "
             "Cut List Summary can compute how many bars are needed. Lines can "
             "override this individually if their profile comes in a different "
             "stock length.",
    )
    active = fields.Boolean(default=True)
    line_ids = fields.One2many('ajo_window_template_line', 'template_id', string='Cut List Lines')
    flag_ids = fields.One2many('ajo_window_template_flag', 'template_id', string='Options / Flags')


class AjoWindowTemplateFlag(models.Model):
    _name = 'ajo_window_template_flag'
    _description = 'AJO Window Template Option Flag'
    _order = 'sequence, id'

    template_id = fields.Many2one('ajo_window_template', required=True, ondelete='cascade')
    sequence = fields.Integer(default=10)
    name = fields.Char(
        string='Option Label', required=True,
        help='e.g. "Align 8402/8400 at Right", "Architrave without clip".',
    )
    default_value = fields.Boolean(string='Default')


class AjoWindowTemplateLine(models.Model):
    _name = 'ajo_window_template_line'
    _description = 'AJO Window Template Cut List Line'
    _order = 'sequence, id'

    template_id = fields.Many2one('ajo_window_template', required=True, ondelete='cascade')
    sequence = fields.Integer(default=10)
    material_type = fields.Selection([
        ('aluminum', 'Aluminum'),
        ('glass', 'Glass'),
        ('steel', 'Steel'),
        ('acp', 'Aluminum Composite Panel (ACP)'),
        ('accessory', 'Accessory'),
        ('other', 'Other'),
    ], string='Material Type', required=True, default='aluminum')
    profile_brand_override = fields.Char(string='Profile Brand (override)')
    profile_length_override = fields.Float(
        string='Profile Length (override, mm)', default=0.0,
        help="Leave at 0 to use the template's Default Profile Length above. "
             "Set this only if this specific profile comes in a different stock "
             "bar length.",
    )
    profile_code = fields.Char(
        string='Profile / Item Code',
        help="Leave empty on a Glass line to use the window's own Glass Type "
             "(e.g. 'G1') instead of a fixed code.",
    )
    color_override = fields.Char(
        string='Color (override)',
        help="Literal color code used instead of the window's Color, e.g. 'NC' "
             "for a clear/uncolored glass line.",
    )
    unit = fields.Char(string='Unit', default='mm', help="Literal unit text, e.g. 'mm' or 'pcs'.")
    angle = fields.Char(string='Angle of Cut', help="e.g. '-45.0/ 45.0'")

    # Cut length -> ajo_order_line.height = length_coef_l*L + length_coef_h*H + length_const
    length_coef_l = fields.Float(string='L Coef.', default=0.0)
    length_coef_h = fields.Float(string='H Coef.', default=0.0)
    length_const = fields.Float(string='Const.', default=0.0)

    # Second dimension -> ajo_order_line.width, only needed for lines that
    # require both a width and a height (e.g. glass panes). Leave all 3 at 0
    # for ordinary single-dimension profile/accessory lines.
    width_coef_l = fields.Float(string='Width L Coef.', default=0.0)
    width_coef_h = fields.Float(string='Width H Coef.', default=0.0)
    width_const = fields.Float(string='Width Const.', default=0.0)

    qty_mode = fields.Selection([
        ('multiplier', 'Multiplier x Window Qty'),
        ('perimeter', 'Perimeter Factor x Window Qty'),
        ('manual', 'Manual (fill in after generating)'),
    ], string='Qty Mode', required=True, default='multiplier')
    qty_multiplier = fields.Float(string='Qty Multiplier', default=1.0)
    qty_perimeter_factor = fields.Float(
        string='Perimeter Factor', default=0.0,
        help='qty = factor x (2xL + 2xH) x window qty',
    )

    condition_flag_id = fields.Many2one(
        'ajo_window_template_flag', string='Only if Option',
        domain="[('template_id', '=', template_id)]",
        help='Leave empty for a line that is always generated. Set this (and the '
             'value below) for a line that only applies when an option is checked '
             'a certain way - e.g. two lines sharing the same Profile/Item Code, '
             'one active when the option is set and one when it is not, reproduce '
             'an "alternate length depending on a checkbox" formula.',
    )
    condition_value = fields.Boolean(string='Option must be', default=True)
