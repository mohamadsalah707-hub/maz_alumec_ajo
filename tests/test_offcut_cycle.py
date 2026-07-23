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
            'code': 'TESTPROF-%s' % cls.env['ir.sequence'].next_by_code('mrp.production'),
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
        # Master profile products must NOT be lot-tracked: offcuts are their
        # own separate product (keyed by length), not a lot of this one.
        assert cls.profile_product.tracking == 'none'

        # Give the base profile product a Category/Sub Category so we can
        # verify offcut products inherit them (see get_or_create_offcut_product).
        cls.category = cls.env['product.category'].create({'name': 'Test Alu Category'})
        cls.sub_category = cls.env['product_sub_category'].create({
            'name': 'Test Alu Sub Category', 'category_id': cls.category.id,
        })
        cls.profile_product.write({
            'categ_id': cls.category.id, 'sub_categ_id': cls.sub_category.id,
        })

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

    def _offcut_quant(self, length, production=None):
        template = self.env['product.template'].search([
            ('alum_profile', '=', self.alum_profile.id),
            ('material_type', '=', 'aluminum'),
            ('color_id', '=', self.color.id),
            ('length', '=', length),
        ], limit=1)
        if not template:
            return template, self.env['stock.quant']
        variant = template.product_variant_id
        warehouse = production.warehouse_id if production else self.warehouse
        quant = self.env['stock.quant'].search([
            ('product_id', '=', variant.id),
            ('location_id', '=', warehouse.offcut_location_id.id),
        ])
        if not quant:
            # Diagnostic: show every quant that exists for this product,
            # wherever it landed, to see if it's just in the wrong location.
            all_quants = self.env['stock.quant'].search([('product_id', '=', variant.id)])
            assert False, 'no quant in %s (offcut_location=%s); all quants: %s' % (
                warehouse.display_name, warehouse.offcut_location_id,
                [(q.location_id.display_name, q.quantity) for q in all_quants],
            )
        return template, quant

    def test_offcut_at_or_above_threshold_creates_product_in_offcut_location(self):
        production = self._create_and_confirm_production()
        raw_move = production.move_raw_ids.filtered(
            lambda m: m.product_id == self.profile_variant)
        self.assertTrue(raw_move, 'Raw material move for the profile should exist on the MO')
        raw_move.remaining_length = 2500.0

        self._finalize_moves(production)
        production.button_mark_done()

        self.assertEqual(production.state, 'done')

        template, quant = self._offcut_quant(2500.0, production=production)
        self.assertTrue(template, 'An offcut product with length 2500mm should have been created')
        self.assertEqual(template.alum_profile, self.alum_profile)
        self.assertEqual(template.color_id, self.color)
        # Name keeps the length as a bare number - no "L:" prefix or "mm" suffix.
        self.assertEqual(template.name, '%s - 2500' % self.profile_product.name)
        self.assertIn('2500', template.name)
        self.assertNotIn('mm', template.name)
        self.assertNotIn('L:', template.name)
        # Category/Sub Category are inserted from the base profile product.
        self.assertEqual(template.categ_id, self.category)
        self.assertEqual(template.sub_categ_id, self.sub_category)
        self.assertEqual(sum(quant.mapped('quantity')), 1.0)

    def test_offcut_below_threshold_is_ignored(self):
        production = self._create_and_confirm_production()
        raw_move = production.move_raw_ids.filtered(
            lambda m: m.product_id == self.profile_variant)
        raw_move.remaining_length = 500.0

        self._finalize_moves(production)
        production.button_mark_done()

        self.assertEqual(production.state, 'done')

        template, quant = self._offcut_quant(500.0)
        self.assertFalse(template, 'No offcut product should be created below the scrap threshold')

    def test_offcut_processing_is_idempotent(self):
        production = self._create_and_confirm_production()
        raw_move = production.move_raw_ids.filtered(
            lambda m: m.product_id == self.profile_variant)
        raw_move.remaining_length = 3000.0

        self._finalize_moves(production)
        production._ajo_process_offcuts()
        production._ajo_process_offcuts()  # calling twice must not double-create

        template, quant = self._offcut_quant(3000.0, production=production)
        self.assertTrue(template)
        self.assertEqual(sum(quant.mapped('quantity')), 1.0)
