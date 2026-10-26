"""Money rules shared by the models, schemas and services.

Money is always `Decimal` in Python and `NUMERIC(18, 2)` in Postgres, never float:
binary floats cannot represent most decimal fractions exactly (0.1 + 0.2 != 0.3).
"""

from decimal import Decimal

MONEY_PRECISION = 18
MONEY_SCALE = 2

MAX_TRANSACTION_AMOUNT = Decimal("1000000000.00")

# Largest value a NUMERIC(18, 2) column can hold.
MAX_BALANCE = Decimal("9999999999999999.99")
