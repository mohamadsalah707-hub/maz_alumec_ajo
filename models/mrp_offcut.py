from odoo import _, fields, models
from odoo.exceptions import UserError

# Default "real scrap vs reusable offcut" threshold, in millimeters. Can be
# overridden per-database via the System Parameter
# 'maz_alumec_ajo.offcut_min_length' (Settings > Technical > System
# Parameters) without touching code.
DEFAULT_OFFCUT_MIN_LENGTH = 2000.0


class StockLot(models.Model):
    _inherit = 'stock.lot'

    offcut_length = fields.Float(
        string='Offcut Length (mm)', digits=(16, 2),
        help='Exact usable length of this specific aluminum profile leftover '
             'piece. Set automatically when a Manufacturing Order generates '
             'this lot as a reusable offcut.',
    )


class MrpProduction(models.Model):
    _inherit = 'mrp.production'

    def _ajo_get_offcut_threshold(self):
        return float(
            self.env['ir.config_parameter'].sudo().get_param(
                'maz_alumec_ajo.offcut_min_length', default=DEFAULT_OFFCUT_MIN_LENGTH,
            )
        )

    def button_mark_done(self):
        self._ajo_process_offcuts()
        return super().button_mark_done()

    def _ajo_process_offcuts(self):
        """For every raw aluminum profile component whose operator-logged
        Remaining Balance is:
          - below the scrap threshold: real scrap. The bar was already fully
            deducted by ordinary component consumption, so nothing further is
            done - it is simply not returned to stock as a usable profile.
          - at or above the scrap threshold: a reusable offcut. The matching
            Byproduct line's stock.move on this Manufacturing Order is given
            one move line per qualifying offcut, each carrying its own
            freshly-created lot (with the exact leftover length stored on
            it), and routed into the warehouse's dedicated Offcuts location.
        """
        threshold = self._ajo_get_offcut_threshold()
        Lot = self.env['stock.lot']

        for production in self:
            offcut_location = False
            if production.warehouse_id:
                offcut_location = production.warehouse_id._get_or_create_offcut_location()

            aluminum_byproduct_moves = production.move_byproduct_ids.filtered(
                lambda m: m.product_id.material_type == 'aluminum'
            )
            # Default every aluminum byproduct line to "nothing produced" -
            # it only gets a real quantity/lot below if at least one
            # qualifying offcut was actually logged for that product.
            unprocessed_byproducts = aluminum_byproduct_moves.filtered(lambda m: not m.offcut_processed)
            unprocessed_byproducts.write({'product_uom_qty': 0.0, 'quantity': 0.0})

            byproduct_move_by_product = {m.product_id.id: m for m in aluminum_byproduct_moves}

            qualifying_raw_moves = production.move_raw_ids.filtered(
                lambda m: (
                    m.remaining_length
                    and not m.offcut_processed
                    and m.product_id.material_type == 'aluminum'
                    and m.remaining_length >= threshold
                )
            )
            offcuts_by_product = {}
            for raw_move in qualifying_raw_moves:
                offcuts_by_product.setdefault(raw_move.product_id.id, []).append(raw_move)

            for product_id, raw_moves in offcuts_by_product.items():
                byproduct_move = byproduct_move_by_product.get(product_id)
                if not byproduct_move:
                    raise UserError(_(
                        'No matching Byproduct line was found on this Manufacturing '
                        'Order\'s Bill of Materials for "%s". Add a Byproduct line for '
                        'this same product before closing the order, so its reusable '
                        'offcuts have somewhere to go.'
                    ) % raw_moves[0].product_id.display_name)

                lots = Lot
                for raw_move in raw_moves:
                    lots |= Lot.create({
                        'product_id': product_id,
                        'company_id': production.company_id.id,
                        'name': self.env['ir.sequence'].next_by_code('ajo.offcut.lot') or _('New'),
                        'offcut_length': raw_move.remaining_length,
                    })

                dest_location = offcut_location or byproduct_move.location_dest_id
                byproduct_move.write({
                    'product_uom_qty': len(lots),
                    'quantity': len(lots),
                    'picked': True,
                    'location_dest_id': dest_location.id,
                    'move_line_ids': [(0, 0, {
                        'product_id': product_id,
                        'company_id': production.company_id.id,
                        'lot_id': lot.id,
                        'quantity': 1,
                        'location_id': byproduct_move.location_id.id,
                        'location_dest_id': dest_location.id,
                    }) for lot in lots],
                })

            # Mark every considered raw move as processed so re-running (e.g.
            # if button_mark_done shows a backorder wizard and is invoked
            # again) never double-creates lots/offcuts.
            production.move_raw_ids.filtered(
                lambda m: m.remaining_length and m.product_id.material_type == 'aluminum'
            ).write({'offcut_processed': True})

    def _ajo_suggest_offcut_lot(self, product_id, required_length):
        """Best-fit helper: given a raw material product and the length
        needed for a new cut, return the smallest available offcut lot (in
        this product's warehouse Offcuts location) that is long enough to
        supply it - so operators are pointed at using up leftovers before
        opening a brand new 6000mm bar. Returns an empty recordset if no
        offcut is currently long enough."""
        self.ensure_one()
        if not self.warehouse_id or not self.warehouse_id.offcut_location_id:
            return self.env['stock.lot']

        quants = self.env['stock.quant'].search([
            ('product_id', '=', product_id),
            ('location_id', '=', self.warehouse_id.offcut_location_id.id),
            ('quantity', '>', 0),
            ('lot_id.offcut_length', '>=', required_length),
        ], order='lot_id')
        best = quants.sorted(lambda q: q.lot_id.offcut_length)
        return best[:1].lot_id
