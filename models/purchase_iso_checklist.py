from odoo import fields, api, models


class PurchaseOrderLineChecklist(models.Model):
    """ISO Checklist for Purchase Order Lines"""
    _name = 'purchase.order.line.checklist'
    _description = 'ISO Checklist for Purchase Order Lines'
    _check_company_auto = True

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
    company_id = fields.Many2one(
        comodel_name='res.company',
        required=True, index=True,
        default=lambda self: self.env.company)

    partner_id = fields.Many2one(
        'res.partner',
        string='Supplier',
        related='purchase_order_id.partner_id',
        readonly=True
    )

    # Checklist items - yes/no fields
    fax_check = fields.Boolean(string='Check fax #/ Page(s)/ Date/ Supplier')
    fax_check_comments = fields.Text(string='comments')
    ral_color_check = fields.Boolean(string='RAL / color mentioned')
    ral_color_check_comments = fields.Text(string='comments')
    quantity_verified = fields.Boolean(string='Quantity checked')
    quantity_verified_comments = fields.Text(string='comments')
    price_approved = fields.Boolean(string='Prices checked and approved')
    price_approved_comments = fields.Text(string='comments')
    glass_type_check = fields.Boolean(string='Glass type mentioned/ Airspace')
    glass_type_check_comments = fields.Text(string='comments')
    polished_glass_edge = fields.Boolean(string='Polished glass edge')
    polished_glass_edge_comments = fields.Text(string='comments')
    structural_sealant = fields.Boolean(string='Structural sealant (or polyurethane)')
    structural_sealant_comments = fields.Text(string='comments')
    dimensions_checked = fields.Boolean(string='Double check dimensions / glass dimensions checked (glass cutting size sheet)')
    dimensions_checked_comments = fields.Text(string='comments')
    stock_quantity_checked = fields.Boolean(string='Stock quantity checked')
    stock_quantity_checked_comments = fields.Text(string='comments')
    project_manager_approval = fields.Boolean(string='Project manager approval')
    project_manager_approval_comments = fields.Text(string='comments')
    general_manager_approval = fields.Boolean(string='General manager approval')
    general_manager_approval_comments = fields.Text(string='comments')

    # Score calculation
    score_total = fields.Integer(string='Total Score', compute='_compute_score_total', store=True)
    max_score = fields.Integer(string='Max Score', default=11)
    score_percentage = fields.Float(string='Score %', compute='_compute_score_percentage', store=True)

    # comments
    comments = fields.Text(string='comments')
    
    # Status
    state = fields.Selection(
        [('draft', 'Draft'), ('completed', 'Completed')],
        string='Status',
        default='draft'
    )

    @api.depends('fax_check', 'ral_color_check', 'quantity_verified', 'price_approved',
                 'glass_type_check', 'polished_glass_edge', 'structural_sealant', 'dimensions_checked',
                 'stock_quantity_checked', 'project_manager_approval', 'general_manager_approval')
    def _compute_score_total(self):
        """Calculate total score based on yes/no checks"""
        for record in self:
            score = 0
            if record.fax_check:
                score += 1
            if record.ral_color_check:
                score += 1
            if record.quantity_verified:
                score += 1
            if record.price_approved:
                score += 1
            if record.glass_type_check:
                score += 1
            if record.polished_glass_edge:
                score += 1
            if record.structural_sealant:
                score += 1
            if record.dimensions_checked:
                score += 1
            if record.stock_quantity_checked:
                score += 1
            if record.project_manager_approval:
                score += 1
            if record.general_manager_approval:
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
