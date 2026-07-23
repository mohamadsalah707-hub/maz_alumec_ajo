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
            'weight_per_meter': 1.25,
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

    def test_weight_per_meter_auto_fetched_via_onchange(self):
        line = self.env['purchase.order.line'].new({
            'order_id': self.order.id,
            'product_id': self.product.id,
        })
        line._onchange_product_id_alu_weight_per_meter()
        self.assertEqual(line.alu_weight_per_meter, 1.25)

    def test_unit_cost_and_totals_compute(self):
        line = self._create_line(
            profile_length=6.0,
            alu_weight_per_meter=1.25,
            alu_price_per_kg=3.0,
        )
        # Unit Cost = weight/m * length/pc * price/kg = 1.25 * 6.0/1000.0 * 3.0
        self.assertAlmostEqual(line.alu_unit_cost, 0.0225)
        # qty_pieces mirrors product_qty (4.0 -> 4)
        self.assertEqual(line.alu_qty_pieces, 4)
        # Total Length = qty_pieces * length/pc = 4 * 6.0
        self.assertAlmostEqual(line.alu_total_length, 24.0)
        # Total Weight = total_length * weight/m = 24.0 * 1.25
        self.assertAlmostEqual(line.alu_total_weight, 30.0)
        # Total = qty_pieces * unit_cost = 4 * 0.0225
        self.assertAlmostEqual(line.alu_total, 0.09)

    def test_qty_pieces_syncs_both_ways(self):
        line = self._create_line(product_qty=5.0)
        self.assertEqual(line.alu_qty_pieces, 5)

        line.alu_qty_pieces = 8
        self.assertAlmostEqual(line.product_qty, 8.0)

        line.product_qty = 10.0
        self.assertEqual(line.alu_qty_pieces, 10)

    def test_price_by_weight_syncs_price_unit(self):
        line = self._create_line(
            profile_length=6.0,
            alu_weight_per_meter=1.25,
            alu_price_per_kg=3.0,
            alu_price_by_weight=True,
        )
        self.assertAlmostEqual(line.price_unit, 22.5)
        self.assertAlmostEqual(line.price_subtotal, 4 * 22.5)

        # Server-side path (write(), not the form onchange): changing the
        # rate afterwards must keep price_unit in sync too.
        line.write({'alu_price_per_kg': 4.0})
        self.assertAlmostEqual(line.alu_unit_cost, 1.25 * 6.0 * 4.0)
        self.assertAlmostEqual(line.price_unit, 1.25 * 6.0 * 4.0)

    def test_price_by_weight_disabled_leaves_price_unit_alone(self):
        line = self._create_line(
            profile_length=6.0,
            alu_weight_per_meter=1.25,
            alu_price_per_kg=3.0,
            price_unit=99.0,
            alu_price_by_weight=False,
        )
        self.assertAlmostEqual(line.alu_unit_cost, 22.5)
        self.assertAlmostEqual(line.price_unit, 99.0)
