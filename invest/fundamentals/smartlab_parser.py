"""Парсер фундаментала со Smart-Lab через BeautifulSoup.

Ключевые особенности:
- Корректно обрабатывает colspan (в отличие от pandas.read_html).
- Поддерживает нефинансовые компании, банки, страховые.
- Помечает аномалии (ROE вне [-1, 1], отрицательный equity, убыток и т.п.).
- Устойчив к 404 (тикер не найден).
- Привилегированные акции (SNGSP, TATNP, SBERP) маппятся на обыкновенные.
- Устаревшие тикеры (YNDX, TCSG, FIVE) — на актуальные.

URL: https://smart-lab.ru/q/{ticker}/f/y/MSFO/
"""
import logging
import re
import time

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)

SMARTLAB_BASE = "https://smart-lab.ru/q/{ticker}/f/y/MSFO/"


# ============================================================
# Маппинг тикеров
# ============================================================

TICKER_ALIASES = {
    # Устаревшие / переименованные
    "YNDX": "YDEX",
    "YNDX_ME": "YDEX",
    "TCSG": "T",
    "FIVE": "X5",
    "FIVEP": "X5",

    # Привилегированные акции → обыкновенные (общий фундаментал)
    "SNGSP": "SNGS",
    "TATNP": "TATN",
    "SBERP": "SBER",
    "MTLRP": "MTLR",
    "TRNFP": "TRNF",
    "RTKMP": "RTKM",
    "BSPBP": "BSPB",
    "KZOSP": "KZOS",
    "NKNCP": "NKNC",
    "LSNGP": "LSNG",
    "RSTIP": "RSTI",
    "PRMBP": "PRMB",
}


# ============================================================
# Соответствие: название строки Smart-Lab → поле в БД
# ============================================================
# Точное совпадение (после lower + схлопывания пробелов).
# Никаких startswith — иначе «Чистая прибыль, %» перезапишет «Чистая прибыль».
# ============================================================

METRIC_MAP = {
    # --- Нефинансовые: абсолютные показатели ---
    "выручка , млрд руб": "revenue",
    "выручка , млн руб": "revenue",
    "операционная прибыль , млрд руб": "operating_profit",
    "ebitda , млрд руб": "ebitda",
    "чистая прибыль , млрд руб": "net_profit",
    "чистая прибыль н/с , млрд руб": "net_profit_adjusted",
    "опер.денежный поток , млрд руб": "operating_cash_flow",
    "capex , млрд руб": "capex",
    "fcf , млрд руб": "fcf",

    # --- Дивиденды ---
    "дивиденд , руб/акцию": "dividend_per_share",
    "дивиденд, руб/акцию": "dividend_per_share",
    "дивиденды/прибыль , %": "payout_ratio",
    "див.выплата , млрд руб": "dividend_payout",

    # --- Относительные показатели ---
    "рентаб ebitda , %": "ebitda_margin",
    "маржа чистой прибыли , %": "net_margin",
    "рентабельность по чистой прибыли , %": "net_margin",
    "долг/ebitda": "debt_to_ebitda",
    "чистый долг/ebitda": "net_debt_to_ebitda",
    "roe , %": "roe",
    "roic , %": "roic",
    "roa , %": "roa",

    # --- Операционные (нефтянка) ---
    "добыча нефти , млн т": "oil_production",
    "переработка нефти , млн т": "oil_refining",
    "добыча газа , млрд м3": "gas_production",

    # --- Банковские метрики ---
    "чистый операц доход , млрд руб": "net_operating_income",
    "чист. проц. доходы , млрд руб": "net_interest_income",
    "чист. комисс. доход , млрд руб": "net_fee_income",
    "доходы по цб , млрд руб": "securities_income",
    "число клиентов , млн": "clients_millions",
    "див доход, ао , %": "dividend_yield",
    "расх на персонал , млрд руб": "personnel_expenses",
    "создание резервов , млрд руб": "provisions",
    "активы банка , млрд руб": "bank_assets",
    "кредитный портфель , млрд руб": "loan_portfolio",
    "кредиты юрлицам , млрд руб": "loans_corporate",
    "кредиты физлицам , млрд руб": "loans_retail",
    "депозиты , млрд руб": "deposits",
    "депозиты юрлиц , млрд руб": "deposits_corporate",
    "депозиты физлиц , млрд руб": "deposits_retail",
    "резервы под обесценивание , млрд руб": "provisions_total",

    # --- Общие балансовые ---
    "активы , млрд руб": "assets",
    "капитал , млрд руб": "equity",
    "собственный капитал , млрд руб": "equity",
    "чистые активы , млрд руб": "net_assets",
    "процентные расходы , млрд руб": "interest_expense",
    "опер. расходы , млрд руб": "operating_expenses",
    "амортизация , млрд руб": "depreciation",
    "долг , млрд руб": "debt",
    "наличность , млрд руб": "cash",
    "чистый долг , млрд руб": "net_debt",
    # --- Балансовые (equity) ---
    "баланс стоимость , млрд руб": "equity",
    "балансовая стоимость , млрд руб": "equity",

    # --- Страховые ---
    "страховые премии , млрд руб": "insurance_premiums",
    "страховые выплаты , млрд руб": "insurance_claims",

    # --- Рыночные метрики (для мультипликаторов) ---
    "цена акции ао , руб": "share_price",
    "цена акции ап , руб": "share_price_pref",
    "число акций ао , млн": "shares_outstanding",
    "число акций ап , млн": "shares_pref",
    "капитализация , млрд руб": "market_cap",
    "p/e": "pe",
    "p/b": "pb",
    "ev/ebitda": "ev_ebitda",
    "p/fcf": "p_fcf",
    "p/s": "ps",

    # --- Per-share метрики ---
    "eps , руб": "eps",
    "fcf/акцию , руб": "fcf_per_share",
    "bv/акцию , руб": "bv_per_share",
}


# ============================================================
# HTTP-клиент
# ============================================================

def _make_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    })
    retry = Retry(
        total=3,
        backoff_factor=1.0,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET"]),
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    return session


# ============================================================
# Утилиты парсинга
# ============================================================

def _parse_number(value) -> float | None:
    """'1 561' → 1561.0; '69.9%' → 0.699; '—', '?', '' → None."""
    if value is None:
        return None

    s = str(value).strip()
    if s in ("", "—", "-", "–", "n/a", "N/A", "?", "nan", "None"):
        return None

    is_percent = s.endswith("%")
    s = s.replace("%", "")
    s = re.sub(r"[\s\u00a0\u202f]+", "", s)
    s = s.replace(",", ".")

    try:
        num = float(s)
    except ValueError:
        return None

    return num / 100 if is_percent else num


def _cell_text(td) -> str:
    return re.sub(r"\s+", " ", td.get_text(" ", strip=True)).strip()


def _normalize_ticker(ticker: str) -> str:
    t = ticker.strip().upper()
    return TICKER_ALIASES.get(t, t)


def _normalize_key(s: str) -> str:
    """Для устойчивого сравнения ключей метрик: нижний регистр + схлопывание пробелов."""
    return re.sub(r"\s+", " ", str(s)).strip().lower()


# ============================================================
# Разбор таблицы с учётом colspan
# ============================================================

def _table_to_grid(table) -> list[list[str | None]]:
    """Превращает <table> в матрицу с учётом colspan."""
    rows: list[list[str | None]] = []

    for tr in table.find_all("tr"):
        cells: list[str | None] = []
        for td in tr.find_all(["td", "th"], recursive=False):
            try:
                colspan = int(td.get("colspan", 1))
            except (TypeError, ValueError):
                colspan = 1

            text = _cell_text(td) or None
            cells.append(text)
            cells.extend([None] * (colspan - 1))

        if cells:
            rows.append(cells)

    max_len = max((len(r) for r in rows), default=0)
    for r in rows:
        if len(r) < max_len:
            r.extend([None] * (max_len - len(r)))

    return rows


def _looks_like_financial_table(table) -> bool:
    """Эвристика: таблица похожа на финансовую."""
    text = table.get_text(" ", strip=True).lower()

    keywords = (
        "выручка", "ebitda", "прибыль", "капитал", "активы",
        "процентные доходы", "комиссионные доходы",
        "операционные доходы", "чистый процентный доход",
        "чистый операц доход",
        "рентабельность", "roe", "roa",
        "страховые премии",
    )
    if not any(k in text for k in keywords):
        return False

    years = re.findall(r"\b(20\d{2})\b", text)
    if len(set(years)) < 3:
        return False

    # Хотя бы 5 строк с числами
    numeric_rows = 0
    for tr in table.find_all("tr"):
        cells = tr.find_all(["td", "th"])
        num_cells = sum(
            1 for td in cells
            if re.search(r"\d", td.get_text(strip=True))
        )
        if num_cells >= 3:
            numeric_rows += 1

    return numeric_rows >= 5


def _find_main_table(soup: BeautifulSoup):
    """Ищет основную таблицу с финансовыми данными."""
    for cls in ("financials", "financial", "simple-little-table"):
        for t in soup.find_all("table", class_=cls):
            if _looks_like_financial_table(t):
                return t

    for t in soup.find_all("table"):
        if _looks_like_financial_table(t):
            return t

    return None


def _extract_year_columns(grid: list[list]) -> dict[int, int]:
    """Ищет строку с годами. Возвращает {позиция: год}."""
    for row in grid[:6]:
        year_cols: dict[int, int] = {}
        for pos, value in enumerate(row):
            if value is None:
                continue
            m = re.match(r"^(\d{4})$", str(value).strip())
            if m:
                year = int(m.group(1))
                if 2000 <= year <= 2100:
                    year_cols[pos] = year
        if len(year_cols) >= 3:
            return year_cols
    return {}


# ============================================================
# Санити-чек
# ============================================================

def _sanity_check(result: dict[int, dict]) -> dict[int, dict]:
    """
    Помечает аномалии. Считает производные метрики (market_cap).
    """
    for year, metrics in result.items():
        # ---- Аномалии ----
        roe = metrics.get("roe")
        if roe is not None and not (-1.0 <= roe <= 1.0):
            metrics["roe_anomaly"] = True

        roa = metrics.get("roa")
        if roa is not None and not (-0.5 <= roa <= 0.5):
            metrics["roa_anomaly"] = True

        rev = metrics.get("revenue")
        if rev is not None and rev < 0:
            metrics["revenue_anomaly"] = True

        ebitda = metrics.get("ebitda")
        if rev and ebitda and abs(ebitda) > 10 * abs(rev):
            metrics["ebitda_anomaly"] = True

        payout = metrics.get("payout_ratio")
        if payout is not None and payout > 2.0:
            metrics["payout_anomaly"] = True

        equity = metrics.get("equity")
        if equity is not None and equity <= 0:
            metrics["negative_equity"] = True

        net_profit = metrics.get("net_profit")
        if net_profit is not None and net_profit < 0:
            metrics["loss_making"] = True

        # ---- Производные: market_cap ----
        # Если Smart-Lab не отдал market_cap, считаем: price × shares / 1000
        if "market_cap" not in metrics:
            price = metrics.get("share_price")
            shares = metrics.get("shares_outstanding")
            if price and shares and price > 0 and shares > 0:
                # shares в млн, price в руб → market_cap в млрд руб
                metrics["market_cap"] = price * shares / 1000

        # ---- Производные: D/E ----
        debt = metrics.get("debt")
        equity = metrics.get("equity")
        if debt is not None and equity and equity > 0:
            metrics["debt_to_equity"] = debt / equity

        # ---- Производные: FCF Yield ----
        fcf = metrics.get("fcf")
        market_cap = metrics.get("market_cap")
        if fcf is not None and market_cap and market_cap > 0:
            metrics["fcf_yield"] = fcf / market_cap

        # ---- Производные: P/E, P/B, EV/EBITDA (если не отдал Smart-Lab) ----
        net_profit = metrics.get("net_profit")
        if "pe" not in metrics and market_cap and net_profit and net_profit > 0:
            metrics["pe"] = market_cap / net_profit

        if "pb" not in metrics and market_cap and equity and equity > 0:
            metrics["pb"] = market_cap / equity

        if "ev_ebitda" not in metrics and market_cap and ebitda and ebitda > 0:
            net_debt = metrics.get("net_debt", 0) or 0
            ev = market_cap + net_debt
            metrics["ev_ebitda"] = ev / ebitda

    return result

# ============================================================
# Основная функция
# ============================================================

def fetch_stock_fundamentals(ticker: str) -> dict[int, dict]:
    """
    Возвращает {year: {metric: value, ...}} для одного тикера.

    Пустой dict, если:
    - тикер не найден (404),
    - таблица не найдена,
    - нет ни одного года.
    """
    ticker = _normalize_ticker(ticker)
    url = SMARTLAB_BASE.format(ticker=ticker)
    session = _make_session()

    try:
        response = session.get(url, timeout=30)
    except Exception as e:
        logger.error("Smart-Lab %s: HTTP-ошибка: %s", ticker, e)
        return {}

    if response.status_code == 404:
        logger.warning("Smart-Lab %s: тикер не найден (404)", ticker)
        return {}

    if response.status_code != 200:
        logger.warning("Smart-Lab %s: HTTP %s", ticker, response.status_code)
        return {}

    soup = BeautifulSoup(response.text, "lxml")

    table = _find_main_table(soup)
    if table is None:
        logger.warning("Smart-Lab %s: таблица фундаментала не найдена", ticker)
        return {}

    grid = _table_to_grid(table)

    year_columns = _extract_year_columns(grid)
    if not year_columns:
        logger.warning("Smart-Lab %s: не нашли строку с годами", ticker)
        return {}

    logger.info("Smart-Lab %s: годы в колонках %s", ticker, year_columns)

    result: dict[int, dict] = {year: {} for year in year_columns.values()}

    for row in grid:
        if not row or not row[0]:
            continue

        raw_name = _normalize_key(row[0])
        if not raw_name:
            continue

        # Только точное совпадение — никаких startswith.
        field = METRIC_MAP.get(raw_name)
        if field is None:
            continue

        for pos, year in year_columns.items():
            if pos >= len(row):
                continue
            value = _parse_number(row[pos])
            if value is None:
                continue
            # Первое найденное значение побеждает
            if field not in result[year]:
                result[year][field] = value

    result = {y: data for y, data in result.items() if data}
    result = _sanity_check(result)

    logger.info(
        "Smart-Lab %s: спарсено %d лет (%s)",
        ticker, len(result), ", ".join(str(y) for y in sorted(result)),
    )
    return result


# ============================================================
# Backfill
# ============================================================

def backfill_tickers(tickers: list[str], crud, force: bool = False,
                     delay: float = 1.0) -> dict:
    """
    Прогоняет список тикеров и сохраняет фундаментал в БД.
    """
    stats = {"tickers": 0, "rows": 0, "errors": 0, "skipped": 0}

    for ticker in tickers:
        if not force and not crud.is_stale(ticker):
            stats["skipped"] += 1
            continue

        data = fetch_stock_fundamentals(ticker)
        if not data:
            stats["errors"] += 1
            continue

        for year, metrics in data.items():
            crud.upsert(ticker, year, **metrics)
            stats["rows"] += 1

        stats["tickers"] += 1
        time.sleep(delay)

    return stats


# ============================================================
# Отладка
# ============================================================

def debug_grid(ticker: str, limit: int = 40) -> None:
    """Печатает первые N строк матрицы — для отладки."""
    ticker = _normalize_ticker(ticker)
    url = SMARTLAB_BASE.format(ticker=ticker)
    session = _make_session()
    resp = session.get(url, timeout=30)

    if resp.status_code == 404:
        print(f"{ticker}: 404 — тикер не найден")
        return

    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "lxml")
    table = _find_main_table(soup)
    if table is None:
        print("Таблица не найдена")
        return

    grid = _table_to_grid(table)
    for i, row in enumerate(grid[:limit]):
        print(f"[{i:2}]", row)