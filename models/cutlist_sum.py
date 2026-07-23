from odoo import _, models, fields, api, Command
from odoo.tools import float_compare
from datetime import datetime
from math import ceil
import logging
_logger = logging.getLogger("MAZ")



class CutlistSum(models.Model):
    _name = 'cutlist_sum'
    _description = 'Cut List Summary'
    _order = 'date desc, id desc'
    # 1. Inherit the mail mixins here
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _check_company_auto = True

    ajo_order_id = fields.Many2one(
        'ajo_order',
        string='AJO Order',
        required=True,
        ondelete='cascade',
    )
    company_id = fields.Many2one(
        comodel_name='res.company',
        required=True, index=True,
        default=lambda self: self.env.company)
    name = fields.Char(
        string='AJO No.',
        related='ajo_order_id.name',
        store=True,
        readonly=True,
    )
    project_code = fields.Char(
        string='Project Code',
        related='ajo_order_id.project_code',
        store=True,
        readonly=True,
    )
    warehouse_id = fields.Many2one(
        'stock.warehouse',
        string='Warehouse',
        related='ajo_order_id.warehouse_id',
        store=True,
        readonly=True,
    )
    vendor_id = fields.Many2one(
        'res.partner',
        string='Vendor',
        required=False,
        domain=[('supplier_rank', '>', 0)],
    )
    material_type = fields.Selection([
        ('aluminum', 'Aluminum'),
        ('glass', 'Glass'),
        ('steel', 'Steel'),
        ('acp', 'Aluminum Composite Panel (ACP)'),
        ('accessory', 'Accessory'),
        ('other', 'Other'),
    ], string='Material Type', required=False)
    date = fields.Date(
        string='Date',
        related='ajo_order_id.date',
        store=True,
        readonly=True,
    )
    currency_id = fields.Many2one(
        'res.currency',
        string='Currency',
        default=lambda self: self.env.company.currency_id,
    )
    line_ids = fields.One2many(
        'cutlist_sum_lines',
        'cutlist_id',
        string='Lines',
    )
    totqtytoorder = fields.Float(
        string='Total Qty to Order',
        compute='_compute_totals',
        store=True,
    )
    totmaxqtyneeded = fields.Float(
        string='Total Max Qty Needed',
        compute='_compute_totals',
        store=True,
    )
    tot_total_height = fields.Float(
        string='Total Height',
        compute='_compute_totals',
        store=True,
    )
    cutlist_stage_id = fields.Many2one(
        'cutliststage',
        string='Stage',
        default=lambda self: self.env['cutliststage'].search([], order='x_sequence asc', limit=1),
    )

    @api.depends('line_ids.qtytoorder', 'line_ids.max_qty_needed', 'line_ids.total_length')
    def _compute_totals(self):
        for record in self:
            record.totqtytoorder = sum(record.line_ids.mapped('qtytoorder'))
            record.totmaxqtyneeded = sum(record.line_ids.mapped('max_qty_needed'))
            record.tot_total_height = sum(record.line_ids.mapped('total_length'))
    @api.onchange('ajo_order_id', 'material_type')
    def _generate_lines(self):
        self.ensure_one()
        order = self.ajo_order_id
        if not order:
            self.line_ids = [(5, 0, 0)]
            return

        lines = order.order_line_ids
        if self.material_type:
            lines = lines.filtered(lambda l: l.material_type == self.material_type)
        sumlines = {}
        alu_type_map = {}
        for line in lines:
            tmpl_id = line.product_tmpl_id
            alu_type = line.material_type in ['aluminum']
            alu_type_map[tmpl_id.id] = alu_type
            product = self.env['product.product'].search([('product_tmpl_id', '=', tmpl_id.id)], limit=1)
            available_qty = 0.0
            if product and order.warehouse_id:
                available_qty = product.with_context(
                    warehouse=order.warehouse_id.id
                ).free_qty
            if sumlines.get(tmpl_id.id):
                sumlines[tmpl_id.id]['qty'] += line.qty
                sumlines[tmpl_id.id]['total_length'] += line.height * line.qty if alu_type else line.qty
                sumlines[tmpl_id.id]['width'] = max(sumlines[tmpl_id.id]['width'], line.width)
            else:
                sumlines[tmpl_id.id] = {
                    'total_length': line.height * line.qty if alu_type else line.qty,
                    'product_tmpl_id': tmpl_id.id,
                    'warehouse_id': order.warehouse_id.id,
                    'warehouse_code': order.warehouse_id.code or '',
                    'product_profile': tmpl_id.name or '',
                    'profile_length': tmpl_id.length if alu_type else line.height,
                    'color': tmpl_id.color_id.name or '',
                    'width': line.width,
                    'qty': line.qty,
                    'available_qty': available_qty,
                    'increase_percent': 0,
                }
        commands = [Command.clear()]
        missing_length_profiles = []
        for tmpl_id, entry in sumlines.items():
            # Each entry keeps the material type of the line(s) it was built
            # from (not the last line seen across the whole loop above).
            alu_type = alu_type_map.get(tmpl_id, False)
            profile_length = entry['profile_length']

            if alu_type and not profile_length:
                # Profile Length (the stock bar length) isn't set on this
                # product yet - qty-to-order can't be computed without it.
                missing_length_profiles.append(entry['product_profile'])
                max_qty = 0
                min_qty = 0
            else:
                max_qty = ceil(entry['total_length'] * 1.25 / profile_length if alu_type else entry['qty']) - entry['available_qty']
                min_qty = ceil(entry['total_length'] / profile_length if alu_type else entry['qty']) - entry['available_qty']

            # Map values safely back into dictionary values
            entry['max_qty_needed'] = max_qty
            entry['min_qty_needed'] = min_qty
            entry['qtytoorder'] = min_qty

            commands.append(Command.create(entry))

        # Fixed: Direct field assignment instead of self.write()
        self.line_ids = commands
        _logger.info(f"Generated {self.line_ids} ")

        if missing_length_profiles:
            return {'warning': {
                'title': _('Profile Length not set'),
                'message': _(
                    'These products have no Profile Length (stock bar length) set, '
                    'so their Qty to Order could not be computed and was left at 0: %s'
                ) % ', '.join(sorted(set(missing_length_profiles))),
            }}


#create request for quotation
    def action_new_rfq(self):
        purchase_order = self.env['purchase.order'].create({
            'partner_id': self.vendor_id.id,
            'origin': self.vendor_id.name,
            #'name': self.vendor_id.name,
            'x_is_taxable': self.vendor_id.taxable,
            'x_defaultwh_id': 1 if self.vendor_id.taxable else 2,            
            'order_line': [(0, 0, {
                'product_id': rec.product_tmpl_id.product_variant_id.id,
                'date_planned': datetime.now(),
                'product_qty': rec.qtytoorder,
                'product_uom_id': rec.product_tmpl_id.uom_id.id,
                'name': rec.product_profile,
                'product_warehouse_id': 1 if self.vendor_id.taxable else 2,
                'tax_ids': [Command.set(rec.product_tmpl_id.taxes_id.ids)],
                'price_unit': rec.product_tmpl_id.standard_price,
                'color': rec.color,
                'width': rec.width,
                'profile_length': rec.profile_length,
                'total_length': rec.total_length,
            }) for  rec in self.line_ids],
        })
# 2. Return an action map to open the newly created RFQ form view immediately
        return {
            'name': 'Request for Quotation',
            'type': 'ir.actions.act_window',
            'res_model': 'purchase.order',
            'view_mode': 'form',
            'res_id': purchase_order.id, # Opens this exact specific record
            'target': 'current',         # Opens in the current window main screen ('new' would open a popup modal)
            'context': self.env.context,
        }        
    def send_to_channel(self):
        #users = self.env['res.users'].search([('login', '=', 'jad@alumec.com')])
        if self.cutlist_stage_id.name == 'Done':
            user = self.create_uid 
            body = 'This %s Cut List Summary is done' % (self.name)
        else:
            user = self.env['res.users'].sudo().search([('login', '=', 'jad@alumec.com')])
            body = 'This %s Cut List Summary is %s' % (self.name,self.cutlist_stage_id.name)
        # Send the notification  
        
        channel_odoo_bot_users = '%s, %s' % (self.env.user.name, user.name)
        try:
            channel_obj = self.env['mail.channel']
        except KeyError:
            # mail module not installed/loaded, skip sending notifications
            return

        channel_id = channel_obj.search([('name', 'like', channel_odoo_bot_users)])
        if not channel_id:
            # Ensure partners exist before creating channel
            partners = []
            if self.env.user and self.env.user.partner_id:
                partners.append((4, self.env.user.partner_id.id))
            if user and getattr(user, 'partner_id', False):
                partners.append((4, user.partner_id.id))
            channel_id = channel_obj.create({
                'name': channel_odoo_bot_users,
                'email_send': False,
                'channel_type': 'chat',
                'public': 'private',
                'channel_partner_ids': partners,
            })
        if channel_id:
            channel_id.message_post(
                body=body,
                message_type='comment',
                subtype='mail.mt_comment',
            )
    
    @api.model
    def create(self, vals):
        res = super(CutlistSum, self).create(vals)
        res.send_to_channel()
        return res
        
    
    @api.onchange('cutlist_stage_id')
    def _onchange_cutlist_stage_id(self):
        self.send_to_channel() 
class CutlistSumLines(models.Model):
    _name = 'cutlist_sum_lines'
    _description = 'Cut List Summary Lines'
    _check_company_auto = True

    cutlist_id = fields.Many2one(
        'cutlist_sum',
        string='Cutlist Summary',
        required=True,
        ondelete='cascade',
    )
    
    company_id = fields.Many2one(
        related='cutlist_id.company_id',
        store=True, index=True, precompute=True)
    product_tmpl_id = fields.Many2one(
        'product.template',
        string='Product Template',
        required=True,
        store=True,
    )
    warehouse_id = fields.Many2one(
        'stock.warehouse',
        string='Warehouse',
    )
    warehouse_code = fields.Char(
        string='Warehouse Code',
    )
    product_profile = fields.Char(
        string='Product Profile',
    )
    color = fields.Char(
        string='Color',
    )
    total_length = fields.Float(
        string='Total Length',
        digits=(16, 2),
    )
    profile_length = fields.Float(
        string='Profile Length',
        store=True,
        digits=(16, 2),
        readonly=True,
    )
    width = fields.Float(
        string='Width',
        digits=(16, 2),
    )
    available_qty = fields.Float(
        string='Available Qty',
        digits=(16, 2),
    )
    max_qty_needed = fields.Float(
        string='Max Qty Needed',
        digits=(16, 2),
    )
    min_qty_needed = fields.Float(
        string='Min Qty Needed',
        digits=(16, 2),
    )
    increase_percent = fields.Float(
        string='Increase %',
        digits=(16, 2),
    )
    qtytoorder = fields.Float(
        string='Qty to Order',
        digits=(16, 2),
    )
    qty = fields.Float(
        string='Qty',
        digits=(16, 2),
    )
   
    # 🚀 THE MAGIC TRICK: Force line changes to log on the parent chatter
    def write(self, vals):
        for line in self:
            log_msg = f"<b>Line Edited ({line.item_ref or 'Unnamed Line'}):</b><ul>"
            changes = False
            
            for field, new_val in vals.items():
                # Skip internal relational fields
                if field in ['order_id', 'write_date', 'write_uid']:
                    continue
                    
                old_val = getattr(line, field)
                if old_val != new_val:
                    field_label = self._fields[field].string
                    log_msg += f"<li>{field_label}: <s>{old_val}</s> ➔ <b>{new_val}</b></li>"
                    changes = True
            
            log_msg += "</ul>"
            if changes and line.order_id:
                # Post the log note directly inside the parent order's chatter feed
                line.order_id.message_post(body=log_msg)
                
        return super(CutlistSumLines, self).write(vals)

class CutlistStage(models.Model):
    _name = "cutliststage"
    _description = "Cut List Stages"

    @api.model
    def default_get(self, fields):
        ctx = dict(self.env.context)
        return super(CutlistStage, self.with_context(ctx)).default_get(fields)

    name = fields.Char('Stage Name', required=True, translate=True)
    x_sequence = fields.Integer('Sequence', default=1, help="Used to order stages. Lower is better.")
    x_is_won = fields.Boolean('Is Done?')
    #requirements = fields.Text('Requirements', help="Enter here the internal requirements for this stage (ex: Offer sent to customer). It will appear as a tooltip over the stage's name.")

    x_fold = fields.Boolean('Folded in Pipeline',
        help='This stage is folded in the kanban view when there are no records in that stage to display.')
