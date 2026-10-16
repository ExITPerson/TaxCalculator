from decimal import Decimal

from database.crud import InvestCrud


class PortfolioAnalytics:
    """Аналитика инвестиционного портфеля. Работает через InvestCrud."""

    def __init__(self, crud: InvestCrud, account_id: str | None = None):
        self._crud = crud
        self._account_id = account_id

    # ---------- Денежные потоки ----------

    def total_deposits(self) -> float:
        return self._crud.total_deposits(self._account_id)

    def total_withdrawals(self) -> float:
        return self._crud.total_withdrawals(self._account_id)

    def net_invested(self) -> float:
        return self.total_deposits() - self.total_withdrawals()

    # ---------- Доходы и расходы ----------

    def total_income(self) -> float:
        return sum(self._crud.total_income_by_type(self._account_id).values())

    def income_by_type(self) -> dict[str, float]:
        return self._crud.total_income_by_type(self._account_id)

    def total_fees(self) -> float:
        return self._crud.total_fees(self._account_id)

    # ---------- Позиции ----------

    def positions(self) -> list[dict]:
        """Список позиций: figi, кол-во, средняя цена покупки."""
        result = []
        for figi in self._crud.get_instruments(self._account_id):
            trades = self._crud.get_trades_for_instrument(figi, self._account_id)
            buys = [t for t in trades if t.kind == 'buy']
            sells = [t for t in trades if t.kind == 'sell']

            total_buy_qty = sum((Decimal(str(t.quantity or 0)) for t in buys), Decimal("0"))
            total_buy_cost = sum(
                (abs(Decimal(str(t.payment_amount or 0))) for t in buys), Decimal("0")
            )
            avg_buy_price = (
                total_buy_cost / total_buy_qty if total_buy_qty else Decimal("0")
            )

            position = self._crud.get_position(figi, self._account_id)

            result.append({
                'figi': figi,
                'instrument_type': trades[0].instrument_type if trades else None,
                'quantity': float(position),
                'avg_buy_price': float(avg_buy_price),
                'buy_count': len(buys),
                'sell_count': len(sells),
                'realized_pnl': float(self.realized_pnl_fifo(figi)),
            })

        return result

    # ---------- FIFO P&L ----------

    def realized_pnl_fifo(self, figi: str) -> Decimal:
        """Реализованный P&L методом FIFO по инструменту."""
        trades = self._crud.get_trades_for_instrument(figi, self._account_id)

        lots: list[list[Decimal]] = []   # [кол-во, цена_за_единицу]
        realized = Decimal("0")

        for t in trades:
            qty = Decimal(str(t.quantity or 0))
            price = Decimal(str(t.price_per_unit or 0))

            if t.kind == 'buy':
                lots.append([qty, price])
            elif t.kind == 'sell':
                remaining = qty
                while remaining > 0 and lots:
                    lot_qty, lot_price = lots[0]
                    take = min(lot_qty, remaining)
                    realized += (price - lot_price) * take
                    lot_qty -= take
                    remaining -= take
                    if lot_qty == 0:
                        lots.pop(0)
                    else:
                        lots[0][0] = lot_qty

        return realized

    # ---------- Сводка ----------

    def summary(self) -> dict:
        return {
            'deposits': self.total_deposits(),
            'withdrawals': self.total_withdrawals(),
            'net_invested': self.net_invested(),
            'fees': self.total_fees(),
            'income': self.total_income(),
            'income_by_type': self.income_by_type(),
            'positions': self.positions(),
        }