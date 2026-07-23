from odoo import fields, models


class StockWarehouse(models.Model):
    _inherit = 'stock.warehouse'

    ajo_project_ref = fields.Char(string='AJO Project Ref', index=True)
    ajo_project_code = fields.Char(string='AJO Project Code', index=True)

    offcut_location_id = fields.Many2one(
        'stock.location', string='Offcuts Location',
        help='Dedicated internal location where reusable aluminum profile '
             'offcuts (leftover pieces >= the scrap threshold) are received '
             'back into stock, so they can be picked for future smaller cuts '
             'before a brand new bar is opened.',
    )

    def _get_or_create_offcut_location(self):
        """Find or create this warehouse's dedicated 'Offcuts' internal
        stock location, used to receive reusable aluminum leftover pieces
        back into inventory (kept separate from ordinary stock so operators
        can be directed to use them up first)."""
        self.ensure_one()
        if self.offcut_location_id:
            return self.offcut_location_id

        location = self.env['stock.location'].search([
            ('name', '=', 'Offcuts'),
            ('location_id', '=', self.view_location_id.id),
        ], limit=1)
        if not location:
            location = self.env['stock.location'].create({
                'name': 'Offcuts',
                'usage': 'internal',
                'location_id': self.view_location_id.id,
                'company_id': self.company_id.id,
            })
        self.offcut_location_id = location.id
        return location
