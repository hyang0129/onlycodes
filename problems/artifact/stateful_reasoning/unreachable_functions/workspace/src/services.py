"""Service layer for payments and notifications."""

from notifications import build_email_body


def process_payment(order):
    charge_card(order["total"])


def charge_card(amount):
    pass  # stub


def send_confirmation(order_id, summary):
    body = build_email_body(order_id, summary)
    _dispatch_email(body)


def _dispatch_email(body):
    pass  # stub


def cancel_order(order_id):
    """Cancel an existing order. Not called from main."""
    _log_cancellation(order_id)
    refund_payment(order_id)


def _log_cancellation(order_id):
    """Log order cancellation. Not called from main."""
    pass


def refund_payment(order_id):
    """Issue a refund. Not called from main."""
    pass
