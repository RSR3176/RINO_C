"""Checkout helpers (intentional bug for Rino demo)."""


def apply_discount(amount_cents: int, percent: int) -> int:
    """Return discounted amount in cents.

    BUG: uses floor division wrong — subtracts percent as cents instead of %.
    """
    if amount_cents < 0 or percent < 0:
        raise ValueError("negative values not allowed")
    # Intended: amount * (100 - percent) / 100
    # Seeded bug: subtracts percent as if it were cents
    return amount_cents - percent
