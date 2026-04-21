"""Notification helpers."""


def build_email_body(order_id, summary):
    return f"Dear customer,\nYour order #{order_id} has been confirmed.\n{summary}"


def build_sms_body(order_id):
    """Build an SMS notification. Not called from main."""
    return f"Order #{order_id} confirmed."


def format_address(street, city, zip_code):
    """Format a shipping address. Not called from main."""
    return f"{street}, {city} {zip_code}"
