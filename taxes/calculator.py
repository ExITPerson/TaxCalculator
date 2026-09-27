class Taxes:
    TAX_RATE = 0.06
    FIXED_FEE = 57390.0
    DUE_RATE = 0.01
    DUE_THRESHOLD = 300_000.0

    def _get_tax(self, revenue: float) -> float:
        """ Подсчет общего налога """
        tax = round(float(revenue * self.TAX_RATE), 2)
        return tax

    def get_fee(self, revenue: float) -> float:
        """ Подсчет страховых и пенсионных взносов """
        if revenue < self.DUE_THRESHOLD:
            return self.FIXED_FEE

        return round(float((revenue - self.DUE_THRESHOLD) * self.DUE_RATE + self.FIXED_FEE), 2)

    def get_full_tax(self, revenue):
        tax = self._get_tax(revenue)
        fee = self._get_fee(revenue)
        half_tax = tax * 0.5
        result = tax - fee

        return round(max(half_tax, result), 2)

    #-----------Отчетность------------

