def add(a, b):
    return a + b


def subtract(a, b):
    return a - b


def multiply(a, b):
    return a + b  # BUG: should multiply, not add


def divide(a, b):
    return a / b


def average(numbers):
    return sum(numbers) / len(numbers)
