from config.settings import INGURE_RATE, RATE_CB


class Taxes:
    TAX_RATE = 0.06
    FIXED_FEE = 57390.0
    DUE_RATE = 0.01
    DUE_THRESHOLD = 300_000.0
    TAX_SALARY = 0.13
    NDFL = 0.13
    EMPLOYEE_CONTRIBUTIONS = 0.3

    def _get_tax(self, revenue: float) -> float:
        """ Подсчет общего налога """
        tax = round(float(revenue * self.TAX_RATE), 2)
        return tax

    def get_fee(self, revenue: float) -> float:
        """ Подсчет страховых и пенсионных взносов """
        if revenue < self.DUE_THRESHOLD:
            return self.FIXED_FEE

        return round(float((revenue - self.DUE_THRESHOLD) * self.DUE_RATE + self.FIXED_FEE), 2)

    def get_tax_and_fee_on_salary(self, salary: float) -> dict:
        full_salary = salary * (1 + self.NDFL)

        tax_on_salary = round(full_salary * self.NDFL, 2)
        fee_on_salary = round(full_salary * self.EMPLOYEE_CONTRIBUTIONS, 2)
        ingure_rate_on_salary = round(full_salary * INGURE_RATE, 2)

        return {
            'Налог ЗП': tax_on_salary,
            'Страховые взносы за сотрудников': fee_on_salary,
            'Взносы за травматизм': ingure_rate_on_salary
        }

    def get_ndfl_overnight(self, revenue):
        limit = 1000000 * RATE_CB

        if revenue < limit:
            return 0

        result = round(float((revenue - limit) * self.NDFL), 2)
        return result


    def get_full_report(self, revenue, salary, revenue_overnight):
        tax = self._get_tax(revenue)
        fee = self.get_fee(revenue)
        for_employers = self.get_tax_and_fee_on_salary(salary)
        half_tax = tax * 0.5
        result = tax - fee - for_employers['Страховые взносы за сотрудников'] - for_employers['Взносы за травматизм']
        full_tax = round(max(half_tax, result), 2)
        ndfl_overnight = self.get_ndfl_overnight(revenue_overnight)


        return {
            'Общий налог': tax,
            'Страховые и пенсионные к оплате': fee,
            'Налог к оплате': full_tax,
            'Налог ЗП за сотрудников': for_employers.get('Налог ЗП', 0),
            'Страховые взносы за сотрудников': for_employers.get('Страховые взносы за сотрудников', 0),
            'Взносы за травматизм': for_employers.get('Взносы за травматизм', 0),
            'Налог с овернайта': ndfl_overnight,
        }

    #-----------Отчетность------------

