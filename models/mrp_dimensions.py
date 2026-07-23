from odoo import fields, models


class MrpBomLine(models.Model):
    _inherit = 'mrp.bom.line'

    width = fields.Float(string='Width', digits=(16, 2), default=0.0)
    height = fields.Float(string='Height', digits=(16, 2), default=0.0)


class StockMove(models.Model):
    _inherit = 'stock.move'

    # A raw material move created from a BOM keeps a link back to the BOM
    # line it originated from (bom_line_id), so its own Width/Height on the
    # Manufacturing Order can just mirror the BOM line's.
    width = fields.Float(
        string='Width', related='bom_line_id.width', store=True, readonly=True,
    )
    height = fields.Float(
        string='Height', related='bom_line_id.height', store=True, readonly=True,
    )

    # Aluminum cutting waste tracking (see models/mrp_offcut.py for the
    # processing logic triggered when the Manufacturing Order is closed).
    remaining_length = fields.Float(
        string='Remaining Balance (mm)', digits=(16, 2),
        help='For a raw aluminum profile component: the exact leftover length '
             'measured on the bar after cutting for this order. Leave empty if '
             'the whole bar was fully used. Logged by the operator before '
             'closing the Manufacturing Order.',
    )
    offcut_processed = fields.Boolean(
        string='Offcut Processed', default=False, copy=False,
        help='Set once this move\'s Remaining Balance has been turned into an '
             'offcut byproduct (or discarded as scrap), so closing the '
             'Manufacturing Order again never double-processes it.',
    )
