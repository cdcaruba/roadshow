# Mapping of transaction states to Sentoo's payment statuses.
# See https://developer.sentoo.io/mdp/statuses

PAYMENT_STATUS_MAPPING = {
    'pending': ('issued', 'pending'),
    'done': ('success',),
    'error': ('cancelled', 'failed', 'expired', 'unknown'),
}