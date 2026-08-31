from models import Product


def calculate_total(products: list[Product]) -> float:
    """Calculate the total value of all inventory."""
    total = 0
    for p in products:
        total += p.price * p.quantity  # BUG: Product has no 'price' attribute
    return total


def most_valuable(products: list[Product]) -> Product:
    """Return the product with the highest total value (price * quantity)."""
    return max(products, key=lambda p: p.unit_price * p.quantity)
