from decimal import Decimal
def total(amounts):
    return Decimal(sum(float(value) for value in amounts))
