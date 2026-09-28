from config.settings import INGURE_RATE, RATE_CB


class Taxes:
    TAX_RATE = 0.06
    FIXED_FEE = 57390.0
    DUE_RATE = 0.01
    DUE_THRESHOLD = 300_000.0
    NDFL = 0.13
    EMPLOYEE_CONTRIBUTIONS = 0.3
    MAX_DEDUCTION_SHARE = 0.5

    def _get_tax(self, revenue: float) -> float:
        """ Налог """
        return round(float(revenue * self.TAX_RATE), 2)

    def get_fee(self, revenue: float) -> float:
        """ Страховые взносы """
        if revenue < self.DUE_THRESHOLD:
            return self.FIXED_FEE

        return round(float((revenue - self.DUE_THRESHOLD) * self.DUE_RATE + self.FIXED_FEE), 2)

    def get_tax_and_fee_on_salary(self, salary: float) -> dict:
        """ Налог и взносы с ЗП """
        full_salary = salary * (1 + self.NDFL)
        return {
            'Налог ЗП': round(full_salary * self.NDFL, 2),
            'Страховые взносы за сотрудников': round(full_salary * self.EMPLOYEE_CONTRIBUTIONS, 2),
            'Взносы за травматизм': round(full_salary * INGURE_RATE, 2),
        }

    def get_ndfl_overnight(self, revenue: float) -> float:
        """ Налог с овернайта """
        limit = 1_000_000 * RATE_CB

        if revenue < limit:
            return 0.0

        return round(float((revenue - limit) * self.NDFL), 2)

    def get_full_report(
        self,
        revenue: float = 0.0,
        salary: float = 0.0,
        revenue_overnight: float = 0.0,
    ) -> dict:
        """ Полный отчет по взносам """
        tax = self._get_tax(revenue)
        fee = self.get_fee(revenue)
        for_employers = self.get_tax_and_fee_on_salary(salary)

        salary_contributions = for_employers['Страховые взносы за сотрудников']
        accident_contributions = for_employers['Взносы за травматизм']

        tax_after_deduction = tax - fee - salary_contributions - accident_contributions
        min_tax = tax * self.MAX_DEDUCTION_SHARE
        full_tax = round(max(min_tax, tax_after_deduction), 2)

        return {
            'Общий налог': tax,
            'Страховые и пенсионные к оплате': fee,
            'Налог к оплате': full_tax,
            'Налог ЗП за сотрудников': for_employers['Налог ЗП'],
            'Страховые взносы за сотрудников': salary_contributions,
            'Взносы за травматизм': accident_contributions,
            'Налог с овернайта': self.get_ndfl_overnight(revenue_overnight),
        }
