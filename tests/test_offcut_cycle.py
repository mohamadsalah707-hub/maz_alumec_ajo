from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestAluminumOffcutCycle(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.warehouse = cls.env['stock.warehouse'].search(
            [('company_id', '=', cls.company.id)], limit=1)

        cls.alum_profile = cls.env['alum_profile'].create({
            'name': 'TEST-PROFILE',
            'code': 'TESTPROF-%s' % cls.env['ir.sequence'].next_by_code('ajo.offcut.lot'),
            'brand': 'TestBrand',
        })
        cls.color = cls.env['product_color'].create({
            'name': 'Test Color',
            'code': 'TC-%s' % cls.alum_profile.id,
        })

        cls.profile_variant = cls.env['product.template'].get_or_create_material_product(
            'aluminum', cls.alum_profile.code, cls.color.code, 'TestBrand',
        )
        cls.profile_product = cls.profile_variant.product_tmpl_id

        cls.finished_tmpl = cls.env['product.template'].create({
            'name': 'Test Window %s' % cls.alum_profile.id,
            'type': 'consu',
        })
        cls.finished_product = cls.finished_tmpl.product_variant_id

        cls.bom = cls.env['mrp.bom'].create({
            'product_tmpl_id': cls.finished_tmpl.id,
            'product_id': cls.finished_product.id,
            'product_qty': 1.0,
            'product_uom_id': cls.finished_product.uom_id.id,
            'company_id': cls.company.id,
            'bom_line_ids': [(0, 0, {
                'product_id': cls.profile_variant.id,
                'product_qty': 2,
                'product_uom_id': cls.profile_variant.uom_id.id,
            })],
            'byproduct_ids': [(0, 0, {
                'product_id': cls.profile_variant.id,
                'product_qty': 1,
                'product_uom_id': cls.profile_variant.uom_id.id,
            })],
        })

    def _create_and_confirm_production(self):
        production = self.env['mrp.production'].create({
            'product_id': self.finished_product.id,
            'product_qty': 1.0,
            'product_uom_id': self.finished_product.uom_id.id,
            'bom_id': self.bom.id,
            'company_id': self.company.id,
        })
        production.action_confirm()
        return production

    def _finalize_moves(self, production):
        # Force every move's done quantity so button_mark_done can complete
        # without needing real on-hand stock reservation for this test.
        for move in production.move_raw_ids:
            move.quantity = move.product_uom_qty
            move.picked = True
        production.qty_producing = production.product_qty

    def test_offcut_at_or_above_threshold_creates_lot_in_offcut_location(self):
        production = self._create_and_confirm_production()
        raw_move = production.move_raw_ids.filtered(
            lambda m: m.product_id == self.profile_variant)
        self.assertTrue(raw_move, 'Raw material move for the profile should exist on the MO')
        raw_move.remaining_length = 2500.0

        self._finalize_moves(production)
        production.button_mark_done()

        self.assertEqual(production.state, 'done')

        byproduct_move = production.move_byproduct_ids.filtered(
            lambda m: m.product_id == self.profile_variant)
        self.assertTrue(byproduct_move, 'Byproduct move for the profile should exist on the MO')
        self.assertEqual(len(byproduct_move.move_line_ids), 1)

        lot = byproduct_move.move_line_ids.lot_id
        self.assertTrue(lot, 'A lot should have been created for the offcut')
        self.assertAlmostEqual(lot.offcut_length, 2500.0)
        self.assertEqual(
            byproduct_move.location_dest_id,
            self.warehouse.offcut_location_id,
            'Offcut should be received into the warehouse Offcuts location',
        )

    def test_offcut_below_threshold_is_ignored(self):
        production = self._create_and_confirm_production()
        raw_move = production.move_raw_ids.filtered(
            lambda m: m.product_id == self.profile_variant)
        raw_move.remaining_length = 500.0

        self._finalize_moves(production)
        production.button_mark_done()

        self.assertEqual(production.state, 'done')

        byproduct_move = production.move_byproduct_ids.filtered(
            lambda m: m.product_id == self.profile_variant)
        self.assertTrue(byproduct_move)
        self.assertEqual(byproduct_move.quantity, 0.0)
        self.assertFalse(byproduct_move.move_line_ids)

    def test_offcut_processing_is_idempotent(self):
        production = self._create_and_confirm_production()
        raw_move = production.move_raw_ids.filtered(
            lambda m: m.product_id == self.profile_variant)
        raw_move.remaining_length = 3000.0

        self._finalize_moves(production)
        production._ajo_process_offcuts()
        production._ajo_process_offcuts()  # calling twice must not double-create lots

        byproduct_move = production.move_byproduct_ids.filtered(
            lambda m: m.product_id == self.profile_variant)
        self.assertEqual(len(byproduct_move.move_line_ids), 1)
