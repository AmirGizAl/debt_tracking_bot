from enum import StrEnum


class OperationType(StrEnum):
    LEND = "lend"  # Выдал в долг
    REPAY_IN = "repay_in"  # Мне вернули
    BORROW = "borrow"  # Взял в долг
    REPAY_OUT = "repay_out"  # Я вернул
