from typing import List
from models import Product


def calculate_total(products: List[Product]) -> float:
    """Calculate the total value of all inventory."""
    total = 0
    for p in products:
        total += p.unit_price * p.quantity
    return total


def most_valuable(products: List[Product]) -> Product:
    """Return the product with the highest total value (price * quantity)."""
    return max(products, key=lambda p: p.unit_price * p.quantity)
