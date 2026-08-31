from models import Product
from inventory import calculate_total, most_valuable


def make_products():
    return [
        Product("Widget", unit_price=2.5, quantity=10),
        Product("Gadget", unit_price=5.0, quantity=4),
    ]


def test_calculate_total():
    products = make_products()
    assert calculate_total(products) == 45.0  # (2.5*10) + (5.0*4)


def test_most_valuable():
    products = make_products()
    assert most_valuable(products).name == "Widget"  # 25.0 > 20.0
