import logging

import requests
import base64
from werkzeug import urls


from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

from odoo.addons.payment import utils as payment_utils
from odoo.addons.payment_sentoo.const import PAYMENT_STATUS_MAPPING
from odoo.tools.image import image_data_uri

_logger = logging.getLogger(__name__)


class AccountMove(models.Model):
    _inherit = 'account.move'

    sentoo_transaction_reference = fields.Char(
        string="Sentoo transaction reference",
        copy=False,
        readonly=True
    )

    sentoo_payment_url = fields.Char(
        string="Sentoo payment url",
        copy=False,
        readonly=True
    )

    sentoo_payment_id = fields.Many2one(
        "account.payment",
        string="Sentoo Payment",
        copy=False,
        readonly=True,
    )

    def button_draft(self):
        """
            Remove Sentoo.io transaction details and reset payment when we set the invoice back to draft
        """
        res = super().button_draft()
        for move in self:
            if move.sentoo_payment_id:
                if move.sentoo_payment_id.state == "posted":
                    move.sentoo_payment_id.action_draft()
                move.sentoo_payment_id.action_cancel()
            move.write({
                "sentoo_transaction_reference": False,
                "sentoo_payment_url": False,
                "sentoo_payment_id": False
            })
        return res

    def _get_sentoo_payment_data(self, provider_id):
        """
            Creates a new transaction at Sentoo.io
            Args:
                provider_id (record): payment.provider record referencing the payment provider Sentoo.io
            Returns:
                response (json): JSON dictionary with the response we get back from posting to Sentoo.io
        """
        converted_amount = payment_utils.to_minor_currency_units(self.amount_residual, self.currency_id)
        base_url = provider_id.get_base_url()
        return_url = urls.url_join(base_url, "/sentoo/qr_process_payment")
        self._portal_ensure_token()
        query_args = '?access_token=%s&sentoo_status=' % self.access_token
        # Create args with access_token to identify invoice in controller
        # Create payload https://developer.sentoo.io/mdp/create-new-transaction
        payload = {
            'sentoo_merchant': provider_id.sentoo_merchant,
            'sentoo_description': self.name,
            'sentoo_amount': str(converted_amount),
            'sentoo_currency': self.currency_id.name,
            'sentoo_return_url': urls.url_join(return_url, query_args),
        }
        headers = {
            "content-type": "application/x-www-form-urlencoded",
            "accept": "application/json",
            "X-SENTOO-SECRET": provider_id.sentoo_secret,
        }
        response = requests.post(
            url=provider_id._sentoo_get_api_url(),
            data=payload,
            headers=headers)
        return response.json()

    def create_sentoo_transaction(self):
        """
            Creates a payment request at Sentoo and stores the details on the Odoo invoice.
        """
        provider_id = self.env.ref('payment_sentoo.payment_provider_sentoo')
        for move in self:
            sentoo_payment_data = move._get_sentoo_payment_data(provider_id)
            if sentoo_payment_data.get("error"):
                raise ValidationError(
                    _("Received data with error: %(error)s.", error=sentoo_payment_data.get("error").get("message")))
            # update data on invoice from response
            move.write({
                "sentoo_transaction_reference": sentoo_payment_data.get("success").get("message"),
                "sentoo_payment_url": sentoo_payment_data.get("success").get("data").get("url"),
                "sentoo_payment_id": move.create_sentoo_payment(provider_id).id
            })
            # Make sure we commit every transaction so we never get a ghost transaction if something fails in the loop
            self.env.cr.commit()

    def create_sentoo_payment(self, provider_id):
        """
            Create a new account.payment in draft
            Args:
                provider_id (record): payment.provider record referencing the payment provider Sentoo.io
            Returns:
                account.payment (record): new payment record that was just created
        """
        return self.env['account.payment'].create(self._prepare_new_payment_values(provider_id))

    def _prepare_new_payment_values(self, provider_id):
        """
            Prepares all values needed to create a new account.payment (this function acts as a hook for easy overrides)
            Args:
                provider_id (record): payment.provider record referencing the payment provider Sentoo.io
            Returns:
                {} (dictionary): dictionary holding all values to create a minimal account.payment record in Odoo

        """
        return {
            'partner_id': self.partner_id.id,
            'payment_type': 'inbound',
            'partner_type': 'customer',
            'journal_id': provider_id.journal_id.id,
            'ref': self.name,
            'amount': self.amount_residual,
            'currency_id': self.currency_id.id,
        }

    def _process_sentoo_payment(self):
        """
            Calls the Sentoo.io API to fetch the status and update payments in Odoo accordingly.
        """
        provider_id = self.env.ref('payment_sentoo.payment_provider_sentoo')
        for move in self:
            if move.sentoo_transaction_reference and move.sentoo_payment_id.state == "draft":
                status = provider_id._get_sentoo_transaction_status(move.sentoo_transaction_reference)
                if status in PAYMENT_STATUS_MAPPING['done']:
                    move.sentoo_payment_id.action_post()
                    move_lines = move.sentoo_payment_id.line_ids.filtered(
                        lambda line: line.account_type in ('asset_receivable', 'liability_payable') and not line.reconciled
                    )
                    for line in move_lines:
                        move.js_assign_outstanding_line(line.id)
                elif status in PAYMENT_STATUS_MAPPING['error']:
                    move.sentoo_payment_id.action_cancel()

    def _generate_qr_code(self):
        """
            Generates the QR code for Sentoo.io based on the URL we got back from the Sentoo.io API earlier
        """
        self.ensure_one()
        if self.sentoo_payment_url:
            barcode = self.env['ir.actions.report'].barcode(
                barcode_type="QR", value=self.sentoo_payment_url, width=120, height=120
            )
            return image_data_uri(base64.b64encode(barcode))
        return super()._generate_qr_code()
