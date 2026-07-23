from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestPurchaseAluminumWeightPricing(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.vendor = cls.env['res.partner'].create({'name': 'Test Alu Vendor'})

        cls.product_tmpl = cls.env['product.template'].create({
            'name': 'Test Alu Purchase Profile',
            'type': 'consu',
            'material_type': 'aluminum',
        })
        cls.product = cls.product_tmpl.product_variant_id

        cls.order = cls.env['purchase.order'].create({
            'partner_id': cls.vendor.id,
            'company_id': cls.company.id,
        })

    def _create_line(self, **extra_vals):
        vals = {
            'order_id': self.order.id,
            'product_id': self.product.id,
            'product_qty': 4.0,
            'product_uom_id': self.product.uom_id.id,
            'price_unit': 0.0,
        }
        vals.update(extra_vals)
        return self.env['purchase.order.line'].create(vals)

    def test_unit_cost_and_totals_compute(self):
        line = self._create_line(
            profile_length=6000.0,
            alu_weight_per_meter=1.25,
            alu_price_per_kg=3.0,
        )
        # Unit Cost = weight/m * length/pc(m) * price/kg = 1.25 * 6000.0/1000.0 * 3.0
        self.assertAlmostEqual(line.alu_unit_cost, 22.5)
        # qty_pieces mirrors product_qty (4.0 -> 4)
        self.assertEqual(line.alu_qty_pieces, 4)
        # Total Length = qty_pieces * length/pc = 4 * 6000.0
        self.assertAlmostEqual(line.alu_total_length, 24000.0)
        # Total Weight = total_length * weight/m = 24000.0 * 1.25
        self.assertAlmostEqual(line.alu_total_weight, 30000.0)
        # Total = qty_pieces * unit_cost = 4 * 22.5
        self.assertAlmostEqual(line.alu_total, 90.0)

    def test_qty_pieces_syncs_both_ways(self):
        line = self._create_line(product_qty=5.0)
        self.assertEqual(line.alu_qty_pieces, 5)

        line.alu_qty_pieces = 8
        self.assertAlmostEqual(line.product_qty, 8.0)

        line.product_qty = 10.0
        self.assertEqual(line.alu_qty_pieces, 10)

    def test_aluminum_line_syncs_price_unit(self):
        line = self._create_line(
            profile_length=6000.0,
            alu_weight_per_meter=1.25,
            alu_price_per_kg=3.0,
        )
        self.assertAlmostEqual(line.price_unit, 22.5)
        self.assertAlmostEqual(line.price_subtotal, 4 * 22.5)

        # Server-side path (write(), not the form onchange): changing the
        # rate afterwards must keep price_unit in sync too.
        line.write({'alu_price_per_kg': 4.0})
        self.assertAlmostEqual(line.alu_unit_cost, 1.25 * 6.0 * 4.0)
        self.assertAlmostEqual(line.price_unit, 1.25 * 6.0 * 4.0)

    def test_non_aluminum_line_leaves_price_unit_alone(self):
        other_tmpl = self.env['product.template'].create({
            'name': 'Test Non-Alu Product',
            'type': 'consu',
            'material_type': 'glass',
        })
        line = self._create_line(
            product_id=other_tmpl.product_variant_id.id,
            profile_length=6000.0,
            alu_weight_per_meter=1.25,
            alu_price_per_kg=3.0,
            price_unit=99.0,
        )
        self.assertAlmostEqual(line.price_unit, 99.0)

    def test_legacy_grid_fields(self):
        categ = self.env['product.category'].create({'name': 'Test Alu Category'})
        self.product_tmpl.write({
            'categ_id': categ.id,
            'default_code': 'ALU-215031',
        })
        line = self._create_line()
        self.assertEqual(line.product_code, 'ALU-215031')
        self.assertEqual(line.categ_id, categ)
        self.assertTrue(line.vat_applicable)
        # Net cost = Unit cost after the line's own Discount %
        line.write({'price_unit': 100.0, 'discount': 10.0})
        self.assertAlmostEqual(line.price_unit_discounted, 90.0)

    def test_extra_cost_line(self):
        glass_type = self.env['ajo_glass_type'].create({'name': 'G1'})
        extra_cost = self.env['purchase.order.extra.cost'].create({
            'order_id': self.order.id,
            'glass_type_id': glass_type.id,
            'description': 'Freight',
            'cost': 50.0,
        })
        self.assertIn(extra_cost, self.order.extra_cost_line_ids)

    def test_global_discount_amount_compute(self):
        self._create_line(price_unit=100.0, product_qty=2.0)
        self.order.global_discount_percent = 10.0
        self.assertAlmostEqual(
            self.order.global_discount_amount,
            self.order.amount_untaxed * 0.10,
        )
