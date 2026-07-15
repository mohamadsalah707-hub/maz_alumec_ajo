# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.


from odoo import _, api, fields, models
from odoo.exceptions import UserError
from collections import defaultdict


class ProductLabelLayout(models.TransientModel):
    _name = 'maz_alumec_ajo.product_label_layout'
    _description = 'Choose the sheet layout to print the labels'

    print = fields.Selection([('parent', 'Parent'),('child', 'Child')], string="Format", required=True)
    ajo_quantity = fields.Selection([
        ('ajo', 'AJO Quantities'),
        ('custom', 'Custom')], string="Quantity to print", required=True, default='ajo')
    quantity = fields.Integer('Copies', default=1, required=True)
    product_ids = fields.Many2many('product.product')
    ajo_line_ids = fields.Many2many('ajo_order_line')

    def _prepare_report_data(self):
        # Get layout grid
        xml_id = 'maz_alumec_ajo.report_product_template_label_dymo'

        # Build data to pass to the report
        data = {
            'layout_wizard': self.id,
            'print': self.print,
            'ajo_quantity': self.ajo_quantity,
            'quantity': self.quantity
        }        
        if self.ajo_line_ids:
            data['ajo_line_ids'] = self.ajo_line_ids.ids
        else:
            raise UserError(_('No data available.'))        
        return xml_id, data

    def process(self):
        self.ensure_one()
        xml_id, data = self._prepare_report_data()
        if not xml_id:
            raise UserError(_('Unable to find report template for %s format', self.print_format))
        report_action = self.env.ref(xml_id).report_action(None, data=data, config=False)
        report_action.update({'close_on_report_download': True})
        return report_action
