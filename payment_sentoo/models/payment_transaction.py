import logging

from werkzeug import urls
import requests

from odoo import _, api, models
from odoo.exceptions import ValidationError

from odoo.addons.payment import utils as payment_utils
from odoo.addons.payment_sentoo.const import PAYMENT_STATUS_MAPPING
from odoo.addons.payment_sentoo.controllers.main import SentooController

_logger = logging.getLogger(__name__)


class PaymentTransaction(models.Model):
    _inherit = 'payment.transaction'

    def _get_sentoo_payload(self):
        """
            Prepares all values needed to create a payment request at Sentoo
            Args: None
            Returns:
                payload (dictionary): dictionary with all values to do a POST call to the Sentoo API
        """
        converted_amount = payment_utils.to_minor_currency_units(self.amount, self.currency_id)
        base_url = self.provider_id.get_base_url()
        return_url = urls.url_join(base_url, SentooController._return_url)
        # Create args with SO reference to identify transaction
        query_args = '?order_ref=%s&sentoo_status=' % self.reference
        # Create payload https://developer.sentoo.io/mdp/create-new-transaction
        payload = {
            'sentoo_merchant': self.provider_id.sentoo_merchant,
            'sentoo_description': (self.sale_order_ids and self.sale_order_ids[0].name) or (self.invoice_ids and self.invoice_ids[0].name),
            'sentoo_amount': str(converted_amount),
            'sentoo_currency': self.currency_id.name,
            'sentoo_return_url': urls.url_join(return_url, query_args),
        }
        return payload

    def _get_sentoo_payment_data(self):
        """
            Creates a new transaction at Sentoo through an API POST call.
        """
        headers = {
            "content-type": "application/x-www-form-urlencoded",
            "accept": "application/json",
            "X-SENTOO-SECRET": self.provider_id.sentoo_secret,
        }
        response = requests.post(
            url=self.provider_id._sentoo_get_api_url(),
            data=self._get_sentoo_payload(),
            headers=headers)
        return response.json()

    def _get_specific_rendering_values(self, processing_values):
        """
        Override of `payment` to return Sentoo-specific processing values.

        Note: self.ensure_one() from `_get_processing_values`
        Args:
            processing_values (dictionary): the generic processing values of the transaction.
        Returns:
            rendering_values (dictionary): the dictionary of provider-specific processing values
        """
        res = super()._get_specific_rendering_values(processing_values)
        if self.provider_code != 'sentoo':
            return res
        sentoo_payment_data = self._get_sentoo_payment_data()
        if sentoo_payment_data.get("error"):
            raise ValidationError(
                _("Received data with error: %(error)s.", error=sentoo_payment_data.get("error").get("message")))
        self.provider_reference = sentoo_payment_data.get("success").get("message")
        rendering_values = {
            'api_url': sentoo_payment_data.get("success").get("data").get("url"),
        }
        return rendering_values

    def _get_tx_from_notification_data(self, provider_code, notification_data):
        """
            Override of `payment` to find the transaction based on Sentoo data.
            Args:
                provider_code (string): The code of the provider that handled the transaction
                notification_data (dictionary): The notification data sent by the provider
            Returns:
            tx (record): payment.transaction representing the current record
        """
        tx = super()._get_tx_from_notification_data(provider_code, notification_data)
        if provider_code != 'sentoo' or len(tx) == 1:
            return tx
        # Get order_ref (SO reference) from return JSON data
        reference = notification_data.get('order_ref')
        if not reference:
            raise ValidationError(
                "Sentoo: " + _("Received data with missing reference %(ref)s.", ref=reference)
            )

        tx = self.search([('reference', '=', reference), ('provider_code', '=', 'sentoo')], limit=1)
        if not tx:
            raise ValidationError(
                "Sentoo: " + _("No transaction found matching reference %s.", reference)
            )

        return tx

    def _process_notification_data(self, notification_data):
        """
            Override of `payment' to process the transaction based on Sentoo data.
            Args:
                notification_data (dictionary): The notification data sent by the provider
            Returns: none
        """
        super()._process_notification_data(notification_data)
        if self.provider_code != 'sentoo':
            return
        status = self.provider_id._get_sentoo_transaction_status(self.provider_reference)
        if not status:
            raise ValidationError("Sentoo: " + _("Received data with missing payment state."))
        if status in PAYMENT_STATUS_MAPPING['pending']:
            self._set_pending()
        elif status in PAYMENT_STATUS_MAPPING['done']:
            self._set_done()
        else:  # Classify unsupported payment state as `error` tx state.
            _logger.info(
                "Received data with invalid payment status (%(status)s)' "
                "for transaction with reference %(ref)s",
                {'status': status, 'ref': self.reference},
            )
            self._set_error("Sentoo: " + _(
                "Received invalid transaction status %(status)s.",
                status=status,
            ))
