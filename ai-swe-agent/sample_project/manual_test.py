from calculator import add, subtract, multiply, divide, average

print("Testing add(2, 3):", add(2, 3), "Expected: 5")
print("Testing subtract(5, 3):", subtract(5, 3), "Expected: 2")
print("Testing multiply(4, 3):", multiply(4, 3), "Expected: 12")
print("Testing divide(10, 2):", divide(10, 2), "Expected: 5")
print("Testing average([1, 2, 3, 4]):", average([1, 2, 3, 4]), "Expected: 2.5")

# Additional test for divide with non-integer result
print("Testing divide(5, 2):", divide(5, 2), "Expected: 2.5")
