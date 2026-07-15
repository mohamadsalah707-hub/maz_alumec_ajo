# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

from collections import defaultdict

from odoo import _, models
from odoo.exceptions import UserError
import logging
_logger = logging.getLogger("MAZ")

def _prepare_data(env, docids, data):
    # change product ids by actual product object to get access to fields in xml template
    # we needed to pass ids because reports only accepts native python types (int, float, strings, ...)

    layout_wizard = env['maz_alumec_ajo.product_label_layout'].browse(data.get('layout_wizard'))
    _logger.warning(' begin ')
    
    total = 0
    
    # Check if we're using ajo_line_ids
    ajo_line_ids = data.get('ajo_line_ids')    
    
    lines = env['ajo_order_line'].browse(ajo_line_ids)
    ajo_quantity = data.get('ajo_quantity')
    quantity = data.get('quantity')
    print = data.get('print')
    quantity_by_product = defaultdict(list)
    
    for line in lines:
        # Create line data with all relevant fields
        if print == 'child':
            line_data = {
                'product': line.product_id,
                'barcode': line.product_id.barcode,
                'item_ref': line.item_ref.name,
                'length': line.length,
                'color': line.color,
                'alum_profile': line.alum_profile,
                'qty': int(line.qty) if ajo_quantity == 'ajo' else quantity,  # Ensure qty is integer for range() function
            }
            # Use product object as key for consistency with template
            quantity_by_product[line.product_id.id].append(line_data)
        else:
            if quantity_by_product.get(line.item_ref.id) is None:
                line_data = {
                    'product': line.item_ref,
                    'barcode': line.item_ref.barcode,
                    'item_ref': '',
                    'length': '',
                    'color': line.item_ref.color,
                    'alum_profile': '',
                    'qty': 1 if ajo_quantity == 'ajo' else quantity,  # Ensure qty is integer for range() function
                }
                # Use product object as key for consistency with template
                quantity_by_product[line.item_ref.id].append(line_data)
        _logger.warning(line_data['product'].name)
        total += line_data['qty']
    
    return {
        'quantity': quantity_by_product,
        'ajo_lines': True,
        'page_numbers': (total - 1) // 1 ,
    }



class ReportProductReport_Producttemplatelabel_Dymo(models.AbstractModel):
    _name = 'report.maz_alumec_ajo.report_producttemplatelabel_dymo'
    _description = 'Product Label Report'

    def _get_report_values(self, docids, data):
        return _prepare_data(self.env, docids, data)
