from odoo import fields, models


class AjoGlassType(models.Model):
    _name = 'ajo_glass_type'
    _description = 'AJO Glass Type'
    _order = 'name'

    name = fields.Char(string='Glass Type', required=True, help="e.g. G1, G2")


class AjoGlassThickness(models.Model):
    _name = 'ajo_glass_thickness'
    _description = 'AJO Glass Thickness'
    _order = 'name'

    name = fields.Char(string='Glass Thickness', required=True, help="e.g. 32 mm")
