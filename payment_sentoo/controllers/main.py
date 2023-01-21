import logging
import pprint

from odoo import http
from odoo.http import request


_logger = logging.getLogger(__name__)


class SentooController(http.Controller):
    _return_url = '/payment/sentoo/return'

    @http.route(
        _return_url, type='http', auth='public', methods=['GET'], csrf=False, save_session=False
    )
    def sentoo_return_from_checkout(self, **data):

        """ Process the notification data sent by Sentoo after redirection.

        The route is flagged with `save_session=False` to prevent Odoo from assigning a new session
        to the user if they are redirected to this route with a POST request. Indeed, as the session
        cookie is created without a `SameSite` attribute, some browsers that don't implement the
        recommended default `SameSite=Lax` behavior will not include the cookie in the redirection
        request from the payment provider to Odoo. As the redirection to the '/payment/status' page
        will satisfy any specification of the `SameSite` attribute, the session of the user will be
        retrieved and with it the transaction which will be immediately post-processed.

        :param dict data: The notification data.
        """
        _logger.info("Handling redirection from Sentoo with data:\n%s", pprint.pformat(data))

        # Check the integrity of the notification.
        tx_sudo = request.env['payment.transaction'].sudo()._get_tx_from_notification_data(
            'sentoo', data
        )

        # Handle the notification data.
        tx_sudo._handle_notification_data('sentoo', data)
        return request.redirect('/payment/status')


    @http.route(
        "/sentoo/qr_process_payment", type='http', auth='public', methods=['GET'], csrf=False, save_session=False
    )
    def sentoo_return_from_qr_url(self, **data):
        """
        Search Invoice based on access_token and redirect to invoice
        :param data: access tokn
        :return: Invoice URL
        """
        access_token = data.get("access_token")
        move = request.env["account.move"].sudo().search([("access_token", "=", access_token)], limit=1)
        move.sudo()._process_sentoo_payment()
        return_odoo_url = move.sudo()._get_share_url(redirect=True)
        return request.redirect(return_odoo_url)
