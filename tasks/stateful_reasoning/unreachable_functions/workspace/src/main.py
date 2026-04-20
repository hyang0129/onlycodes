"""Entry point for the order processing system."""

from utils import format_order, validate_order
from services import process_payment, send_confirmation


def main():
    order = {"id": 42, "items": ["widget"], "total": 19.99}
    if validate_order(order):
        formatted = format_order(order)
        process_payment(order)
        send_confirmation(order["id"], formatted)


if __name__ == "__main__":
    main()
