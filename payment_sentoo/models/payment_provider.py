import requests
from odoo import fields, models
from odoo.addons.payment_sentoo.const import PAYMENT_STATUS_MAPPING


class PaymentProvider(models.Model):
    _inherit = 'payment.provider'

    code = fields.Selection(
        selection_add=[('sentoo', "Sentoo")],
        ondelete={'sentoo': 'set default'}
    )

    sentoo_merchant = fields.Char(
        string="Sentoo Merchant Identifier",
        help="The code of the merchant account to use with this provider.",
        required_if_provider='sentoo',
    )

    sentoo_secret = fields.Char(
        string="Sentoo Merchant Secret",
        help="The secret code of the merchant account to use with this provider.",
        required_if_provider='sentoo',
    )

    def _sentoo_get_api_url(self):
        """
            Return the API URL according to the state of the payment provider (disabled, enabled, test mode)
            Args: None
            Returns:
                string: string with the API endpoint URL for production or testing
        """
        self.ensure_one()
        if self.state == 'enabled':
            return 'https://api.sentoo.io/v1/payment/new'
        else:
            return 'https://api.sandbox.sentoo.io/v1/payment/new'

    def _sentoo_get_status_url(self):
        """
            Returns the fetch transaction status URL according according to the state of the payment
            provider (disabled, enabled, test mode)

        """
        self.ensure_one()
        if self.state == 'enabled':
            return 'https://api.sentoo.io/v1/payment/status'
        else:
            return 'https://api.sandbox.sentoo.io/v1/payment/status'

    def _get_sentoo_transaction_status(self, sentoo_transaction_reference):
        """
            Calls the Sentoo.io API to get the latest transaction status
        """
        headers = {
            "content-type": "application/x-www-form-urlencoded",
            "accept": "application/json",
            "X-SENTOO-SECRET": self.sentoo_secret,
        }

        response = requests.get(
            url="%s/%s/%s" % (self._sentoo_get_status_url(), self.sentoo_merchant, sentoo_transaction_reference),
            headers=headers
        )
        transaction_response = response.json()
        return transaction_response.get('success').get('message')

    def _cron_sentoo_payment_status(self):
        """
        Call Sentoo API to get updated transaction status and update related payment in Odoo.
        """
        provider_id = self.env.ref('payment_sentoo.payment_provider_sentoo')
        # Process customer invoices
        for move in self.env["account.move"].search([
            ("sentoo_transaction_reference", "!=", False), ("sentoo_payment_id.state", "=", "draft")]):
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
        # Process payment transactions
        for transaction in self.env["payment.transaction"].search([
            ("provider_code", "=", 'sentoo'), ("state", "in", ['draft', 'pending'])]):
            status = provider_id._get_sentoo_transaction_status(transaction.provider_reference)
            if status in PAYMENT_STATUS_MAPPING['done']:
                transaction._set_done()
