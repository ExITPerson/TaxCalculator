from config.settings import INGURE_RATE, RATE_CB, USN_LIMIT


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

    def get_detailed_report(
            self,
            revenue,
            salary,
            revenue_overnight,
            actual_income,
            actual_expenses,
            paid_taxes,
            paid_insurance,
            paid_salary,
            internal_income,
    ):
        # --- 1. Базовые расчёты ---
        tax_total = self._get_tax(revenue)
        fee_ip = self.get_fee(revenue)
        salary_block = self.get_tax_and_fee_on_salary(salary)

        ndfl_salary = salary_block['Налог ЗП']
        contributions_salary = salary_block['Страховые взносы за сотрудников']
        accident_salary = salary_block['Взносы за травматизм']

        full_report = self.get_full_report(revenue, salary, revenue_overnight)
        tax_to_pay = full_report['Налог к оплате']

        # --- 2. К доплате ---
        tax_to_pay_net = max(0.0, tax_to_pay - paid_taxes)
        insurance_total = fee_ip + contributions_salary + accident_salary
        insurance_total_net = max(0.0, insurance_total - paid_insurance)

        # --- 3. Овернайт ---
        overnight_tax = self.get_ndfl_overnight(revenue_overnight)

        # --- 4. Остатки ---
        balance_real = actual_income - actual_expenses

        # FIX: добавлен НДФЛ с ЗП — отдельное обязательство перед бюджетом,
        # он не входит ни в tax_to_pay (там только УСН), ни в actual_expenses
        balance_free = (
                balance_real
                - tax_to_pay_net  # УСН к доплате
                - insurance_total_net  # взносы к доплате
                - ndfl_salary  # НДФЛ с ЗП
        )

        # --- 5. Лимит УСН ---
        limit_left = max(0.0, USN_LIMIT - revenue)

        total_tax_expenses = tax_to_pay_net + insurance_total_net + ndfl_salary

        return {
            'Реальный остаток на счету': round(balance_real, 2),
            'Свободный остаток (после налогов и взносов)': round(balance_free, 2),

            'Поступления (выручка)': round(revenue, 2),
            'Выплаченная ЗП': round(paid_salary, 2),
            'Расходы': round(actual_expenses, 2),

            'Лимит УСН': round(USN_LIMIT, 2),
            'Остаток до лимита УСН': round(limit_left, 2),

            'Налог за поступления': round(tax_total, 2),
            'Налог за сотрудников': round(ndfl_salary, 2),
            'Налог к оплате (общий)': round(tax_to_pay, 2),
            'Налог к оплате (с вычетом оплаченных)': round(tax_to_pay_net, 2),
            'Сумма оплаченных налогов': round(paid_taxes, 2),
            'Сумма оплаченных страховых взносов': round(paid_insurance, 2),
            'Сумма оплаченных налогов и взносов (итого)': round(paid_taxes + paid_insurance, 2),

            'Страховые и пенсионные за ИП': round(fee_ip, 2),
            'Страховые и пенсионные за сотрудников': round(contributions_salary, 2),
            'Взносы за травматизм': round(accident_salary, 2),
            'Взносы всего (с вычетом оплаченных)': round(insurance_total_net, 2),

            'Сумма всех расходов на налоги и взносы': round(total_tax_expenses, 2),
            'Сумма расходов общая': round(actual_expenses, 2),
            'Сумма выплаченной ЗП': round(paid_salary, 2),

            'Сумма заработанная с овернайта': round(internal_income, 2),
            'Налог на овернайт': round(overnight_tax, 2),
        }


