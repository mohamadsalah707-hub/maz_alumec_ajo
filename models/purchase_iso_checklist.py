from odoo import fields, api, models


class PurchaseOrderLineChecklist(models.Model):
    """ISO Checklist for Purchase Order Lines"""
    _name = 'purchase.order.line.checklist'
    _description = 'ISO Checklist for Purchase Order Lines'

    purchase_line_id = fields.Many2one(
        'purchase.order.line',
        string='Purchase Order Line',
        required=True,
        ondelete='cascade'
    )
    
    purchase_order_id = fields.Many2one(
        'purchase.order',
        string='Purchase Order',
        related='purchase_line_id.order_id',
        readonly=True,
        store=True
    )

    # Checklist items - yes/no fields
    quality_check = fields.Boolean(string='Quality Check')
    quantity_check = fields.Boolean(string='Quantity Check')
    packaging_check = fields.Boolean(string='Packaging Check')
    documentation_check = fields.Boolean(string='Documentation Check')
    expiry_date_check = fields.Boolean(string='Expiry Date Check')
    price_verification = fields.Boolean(string='Price Verification')

    # Score calculation
    score_total = fields.Integer(string='Total Score', compute='_compute_score_total', store=True)
    max_score = fields.Integer(string='Max Score', default=6)
    score_percentage = fields.Float(string='Score %', compute='_compute_score_percentage', store=True)

    # Notes
    notes = fields.Text(string='Notes')
    
    # Status
    state = fields.Selection(
        [('draft', 'Draft'), ('completed', 'Completed')],
        string='Status',
        default='draft'
    )

    @api.depends('quality_check', 'quantity_check', 'packaging_check', 'documentation_check', 'expiry_date_check', 'price_verification')
    def _compute_score_total(self):
        """Calculate total score based on yes/no checks"""
        for record in self:
            score = 0
            if record.quality_check:
                score += 1
            if record.quantity_check:
                score += 1
            if record.packaging_check:
                score += 1
            if record.documentation_check:
                score += 1
            if record.expiry_date_check:
                score += 1
            if record.price_verification:
                score += 1
            record.score_total = score

    @api.depends('score_total', 'max_score')
    def _compute_score_percentage(self):
        """Calculate score percentage"""
        for record in self:
            if record.max_score > 0:
                record.score_percentage = (record.score_total / record.max_score) * 100
            else:
                record.score_percentage = 0

    def action_complete_checklist(self):
        """Mark checklist as completed"""
        self.ensure_one()
        self.write({'state': 'completed'})
