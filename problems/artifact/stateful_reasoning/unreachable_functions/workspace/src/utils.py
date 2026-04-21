"""Utility functions for order processing."""


def validate_order(order):
    return bool(order.get("id") and order.get("items") and order.get("total", 0) > 0)


def format_order(order):
    return f"Order #{order['id']}: {', '.join(order['items'])} — ${order['total']:.2f}"


def sanitize_input(text):
    """Remove leading/trailing whitespace. Not called from main."""
    return text.strip()


def compute_discount(total, pct):
    """Compute a percentage discount. Not called from main."""
    return total * (1 - pct / 100)
