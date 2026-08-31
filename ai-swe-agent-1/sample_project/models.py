class Product:
    """Represents an item in inventory."""

    def __init__(self, name: str, unit_price: float, quantity: int):
        self.name = name
        self.unit_price = unit_price
        self.quantity = quantity
