#!/usr/bin/env python
"""Simple test runner to verify all functionality."""

import sys
from calculator import add, subtract, multiply, divide, average
from models import Product
from inventory import calculate_total, most_valuable


def test_calculator():
    """Test all calculator functions."""
    print("Testing calculator...")
    
    # Test add
    assert add(2, 3) == 5, "add(2, 3) should return 5"
    print("PASS: add(2, 3) = 5")
    
    # Test subtract
    assert subtract(5, 3) == 2, "subtract(5, 3) should return 2"
    print("PASS: subtract(5, 3) = 2")
    
    # Test multiply
    assert multiply(4, 3) == 12, "multiply(4, 3) should return 12"
    print("PASS: multiply(4, 3) = 12")
    
    # Test divide
    assert divide(10, 2) == 5, "divide(10, 2) should return 5"
    print("PASS: divide(10, 2) = 5")
    
    # Test average
    assert average([1, 2, 3, 4]) == 2.5, "average([1, 2, 3, 4]) should return 2.5"
    print("PASS: average([1, 2, 3, 4]) = 2.5")
    
    print("All calculator tests passed!\n")


def test_inventory():
    """Test all inventory functions."""
    print("Testing inventory...")
    
    # Create test products
    products = [
        Product("Widget", unit_price=2.5, quantity=10),
        Product("Gadget", unit_price=5.0, quantity=4),
    ]
    
    # Test calculate_total
    total = calculate_total(products)
    assert total == 45.0, f"calculate_total should return 45.0, got {total}"
    print("PASS: calculate_total(products) = 45.0")
    
    # Test most_valuable
    most_valuable_product = most_valuable(products)
    assert most_valuable_product.name == "Widget", "most_valuable should return Widget"
    print("PASS: most_valuable(products).name = Widget")
    
    print("All inventory tests passed!\n")


if __name__ == "__main__":
    try:
        test_calculator()
        test_inventory()
        print("=" * 50)
        print("ALL TESTS PASSED!")
        print("=" * 50)
        sys.exit(0)
    except AssertionError as e:
        print(f"\nFAIL: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\nERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
