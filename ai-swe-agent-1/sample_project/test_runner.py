from calculator import add, subtract, multiply, divide, average
from models import Product
from inventory import calculate_total, most_valuable

print("Testing calculator...")
print(f"add(2, 3) = {add(2, 3)} (expected: 5)")
print(f"subtract(5, 3) = {subtract(5, 3)} (expected: 2)")
print(f"multiply(4, 3) = {multiply(4, 3)} (expected: 12)")
print(f"divide(10, 2) = {divide(10, 2)} (expected: 5)")
print(f"average([1, 2, 3, 4]) = {average([1, 2, 3, 4])} (expected: 2.5)")

print("\nTesting inventory...")
products = [
    Product("Widget", unit_price=2.5, quantity=10),
    Product("Gadget", unit_price=5.0, quantity=4),
]
print(f"calculate_total(products) = {calculate_total(products)} (expected: 45.0)")
print(f"most_valuable(products).name = {most_valuable(products).name} (expected: Widget)")
