# code-steward: begin orders.validation


def validate_customer(customer_id: str) -> bool:
    """Check that an order has a customer identifier."""
    return bool(customer_id.strip())


def validate_inventory(quantity: int) -> bool:
    """Check that requested inventory is positive."""
    return quantity > 0


def validate_shipping(destination: str) -> bool:
    """Check that a shipping destination is present."""
    return bool(destination.strip())


# code-steward: end orders.validation
