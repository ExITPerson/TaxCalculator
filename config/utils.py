def _fmt(value: float) -> str:
    """Форматирует число: 1234567.89 -> '1 234 567.89 ₽'."""
    return f"{value:,.2f} ₽".replace(",", " ")