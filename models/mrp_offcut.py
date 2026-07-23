from odoo import _, fields, models
from odoo.exceptions import UserError

# Default "real scrap vs reusable offcut" threshold, in millimeters. Can be
# overridden per-database via the System Parameter
# 'maz_alumec_ajo.offcut_min_length' (Settings > Technical > System
# Parameters) without touching code.
DEFAULT_OFFCUT_MIN_LENGTH = 2000.0


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
          - at or above the scrap threshold: a reusable offcut. A distinct
            product is found or created for that exact profile/color/length
            (see product.template.get_or_create_offcut_product), and a
            standard stock.move receives one unit of it into the warehouse's
            dedicated Offcuts location - entirely independent of the
            Manufacturing Order's own component/finished moves, so it never
            needs the consumed profile itself to be lot-tracked.
        """
        threshold = self._ajo_get_offcut_threshold()

        for production in self:
            raw_moves = production.move_raw_ids.filtered(
                lambda m: not m.offcut_processed and m.product_id.material_type == 'aluminum'
            )
            for raw_move in raw_moves:
                if raw_move.remaining_length and raw_move.remaining_length >= threshold:
                    production._ajo_create_offcut_move(raw_move, threshold)
            raw_moves.write({'offcut_processed': True})

    def _ajo_create_offcut_move(self, raw_move, threshold):
        self.ensure_one()
        base_tmpl = raw_move.product_id.product_tmpl_id
        if not base_tmpl.alum_profile:
            raise UserError(_(
                'Cannot generate an offcut for "%s": it has no Alum. Profile '
                'master set, so a matching offcut product cannot be found or '
                'created.'
            ) % raw_move.product_id.display_name)

        offcut_product = self.env['product.template'].get_or_create_offcut_product(
            base_tmpl.alum_profile, base_tmpl.color_id, raw_move.remaining_length,
        )

        source_location = self.env['stock.location'].search([
            ('usage', '=', 'production'),
            ('company_id', 'in', [self.company_id.id, False]),
        ], limit=1)
        dest_location = raw_move.location_dest_id
        if self.warehouse_id:
            dest_location = self.warehouse_id._get_or_create_offcut_location()

        move = self.env['stock.move'].create({
            'product_id': offcut_product.id,
            'product_uom_qty': 1.0,
            'product_uom': offcut_product.uom_id.id,
            'location_id': (source_location or raw_move.location_dest_id).id,
            'location_dest_id': dest_location.id,
            'company_id': self.company_id.id,
            'origin': self.name,
        })
        move._action_confirm()
        move._action_assign()
        move.picked = True
        # Explicitly (re)create the move line rather than relying on the
        # quantity inverse to generate one: _action_assign() on a move
        # sourced from a virtual location does not always produce a move
        # line here, and without one _action_done() silently completes the
        # move with nothing actually received into stock.
        move.move_line_ids = [(5, 0, 0)] + [(0, 0, {
            'product_id': offcut_product.id,
            'company_id': self.company_id.id,
            'quantity': 1.0,
            'location_id': move.location_id.id,
            'location_dest_id': move.location_dest_id.id,
        })]
        move.quantity = 1.0
        move._action_done()
        return move

    def _ajo_suggest_offcut_product(self, alum_profile_id, color_id, required_length):
        """Best-fit helper: given a profile/color and the length needed for a
        new cut, return the smallest existing offcut product (already in the
        warehouse's Offcuts location, with stock on hand) that is long
        enough to supply it - so operators are pointed at using up leftovers
        before opening a brand new bar. Returns an empty recordset if no
        offcut is currently long enough."""
        self.ensure_one()
        if not self.warehouse_id or not self.warehouse_id.offcut_location_id:
            return self.env['product.product']

        templates = self.env['product.template'].search([
            ('alum_profile', '=', alum_profile_id),
            ('material_type', '=', 'aluminum'),
            ('color_id', '=', color_id),
            ('length', '>=', required_length),
        ], order='length asc')
        for template in templates:
            variant = template.product_variant_id
            quant = self.env['stock.quant'].search([
                ('product_id', '=', variant.id),
                ('location_id', '=', self.warehouse_id.offcut_location_id.id),
                ('quantity', '>', 0),
            ], limit=1)
            if quant:
                return variant
        return self.env['product.product']
