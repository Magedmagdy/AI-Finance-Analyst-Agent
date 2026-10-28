from __future__ import annotations

import math
import json
import os
import uuid
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Sequence

import pyodbc


# ============================================================
# Configuration
# ============================================================

DB_SERVER = os.getenv("AI_FINANCE_SQL_SERVER", os.getenv("SQL_SERVER", "localhost"))
DB_DATABASE = os.getenv("AI_FINANCE_SQL_DATABASE", "AI_Finance")
DB_DRIVER = os.getenv("AI_FINANCE_SQL_DRIVER", "ODBC Driver 18 for SQL Server")
DB_TRUSTED = os.getenv("AI_FINANCE_SQL_TRUSTED_CONNECTION", "yes")
DB_ENCRYPT = os.getenv("AI_FINANCE_SQL_ENCRYPT", "no")
DB_TRUST_SERVER_CERT = os.getenv("AI_FINANCE_SQL_TRUST_SERVER_CERTIFICATE", "yes")

ALLOWED_CURRENCIES = {"USD", "EUR", "GBP", "CAD", "JPY", "AUD"}

ALLOWED_METRICS = {
    "total_inflows",
    "total_outflows",
    "net_cash_flow",
    "fees",
    "refunds",
    "transfers",
    "transactions",
    "completed_transactions",
    "pending_transactions",
    "failed_transactions",
    "reversed_transactions",
    "active_accounts",
    "average_transaction_amount",
}

MONETARY_METRICS = {
    "total_inflows", "total_outflows", "net_cash_flow", "fees", "refunds", "transfers",
}
COUNT_METRICS = {
    "transactions", "completed_transactions", "pending_transactions",
    "failed_transactions", "reversed_transactions", "active_accounts",
}
METRIC_DEFINITION_VERSION = "ai_finance_metrics_v1"
FORECAST_MODEL_VERSION = "trailing_moving_average_v1"
FORECAST_TABLE = "mart.financial_forecasts"


class DuplicateForecastError(Exception):
    """Raised when a generated forecast identifier already exists."""

CURRENCY_ALIASES = {
    "$": "USD",
    "usd": "USD",
    "us dollar": "USD",
    "us dollars": "USD",
    "€": "EUR",
    "eur": "EUR",
    "euro": "EUR",
    "£": "GBP",
    "gbp": "GBP",
    "pound": "GBP",
    "jpy": "JPY",
    "yen": "JPY",
    "cad": "CAD",
    "canadian dollar": "CAD",
    "aud": "AUD",
    "australian dollar": "AUD",
}

TRANSACTION_TYPE_ROLES = {
    "credit": "INFLOW",
    "deposit": "INFLOW",
    "interest": "INFLOW",
    "refund": "INFLOW",
    "debit": "OUTFLOW",
    "withdrawal": "OUTFLOW",
    "fee": "OUTFLOW",
    "transfer": "TRANSFER",
}

INFLOW_TYPES = {"credit", "deposit", "interest", "refund"}
OUTFLOW_TYPES = {"debit", "withdrawal", "fee"}

# Built-in metadata keeps the agent working even when financial_tools.json
# is not updated immediately. The JSON file can still override these values.
TOOL_SCHEMAS: Dict[str, Dict[str, Any]] = {
    "get_financial_kpis": {
        "name": "get_financial_kpis",
        "description": "Retrieve verified financial KPIs for a currency and date range.",
        "parameters": {
            "type": "object",
            "properties": {
                "currency": {"type": "string", "description": "Currency code such as USD or EUR."},
                "date_from": {"type": "string", "description": "Start date YYYY-MM-DD."},
                "date_to": {"type": "string", "description": "Inclusive end date YYYY-MM-DD."},
                "metric": {"type": "string", "description": "Optional KPI metric."},
            },
            "required": ["currency", "date_from", "date_to"],
        },
    },
    "compare_financial_periods": {
        "name": "compare_financial_periods",
        "description": "Compare one verified financial metric across two periods.",
        "parameters": {
            "type": "object",
            "properties": {
                "currency": {"type": "string", "description": "Currency code."},
                "metric": {"type": "string", "description": "Metric to compare."},
                "period_1_from": {"type": "string", "description": "First period start YYYY-MM-DD."},
                "period_1_to": {"type": "string", "description": "First period end YYYY-MM-DD."},
                "period_2_from": {"type": "string", "description": "Second period start YYYY-MM-DD."},
                "period_2_to": {"type": "string", "description": "Second period end YYYY-MM-DD."},
            },
            "required": ["currency", "metric", "period_1_from", "period_1_to", "period_2_from", "period_2_to"],
        },
    },
    "analyze_financial_trend": {
        "name": "analyze_financial_trend",
        "description": "Analyze a monthly financial trend for a verified metric and currency.",
        "parameters": {
            "type": "object",
            "properties": {
                "currency": {"type": "string", "description": "Currency code."},
                "metric": {"type": "string", "description": "Metric to trend."},
                "date_from": {"type": "string", "description": "Start date YYYY-MM-DD."},
                "date_to": {"type": "string", "description": "Inclusive end date YYYY-MM-DD."},
            },
            "required": ["currency", "metric", "date_from", "date_to"],
        },
    },
    "detect_financial_anomalies": {
        "name": "detect_financial_anomalies",
        "description": "Detect daily net cash flow anomalies using the modified Z-score method.",
        "parameters": {
            "type": "object",
            "properties": {
                "date_from": {"type": "string", "description": "Start date YYYY-MM-DD."},
                "date_to": {"type": "string", "description": "Inclusive end date YYYY-MM-DD."},
                "currency": {"type": "string", "description": "Optional currency filter."},
                "threshold": {"type": "number", "description": "Modified Z-score threshold; default 3.5."},
            },
            "required": ["date_from", "date_to"],
        },
    },
    "analyze_cash_flow_drivers": {
        "name": "analyze_cash_flow_drivers",
        "description": "Explain changes in net cash flow by transaction type across two periods.",
        "parameters": {
            "type": "object",
            "properties": {
                "currency": {"type": "string", "description": "Currency code."},
                "period_1_from": {"type": "string", "description": "First period start YYYY-MM-DD."},
                "period_1_to": {"type": "string", "description": "First period end YYYY-MM-DD."},
                "period_2_from": {"type": "string", "description": "Second period start YYYY-MM-DD."},
                "period_2_to": {"type": "string", "description": "Second period end YYYY-MM-DD."},
            },
            "required": ["currency", "period_1_from", "period_1_to", "period_2_from", "period_2_to"],
        },
    },
    "forecast_financial_kpi": {
        "name": "forecast_financial_kpi",
        "description": "Calculate a non-persisted monthly KPI forecast using completed observations ending on or before an inclusive historical cutoff.",
        "parameters": {
            "type": "object",
            "properties": {
                "currency": {"type": "string", "description": "Currency code."},
                "metric": {"type": "string", "description": "Metric to forecast."},
                "forecast_period": {"type": "string", "description": "Target month start in YYYY-MM-01 format."},
                "lookback_months": {"type": "integer", "description": "Number of trailing completed months, default 3."},
                "historical_cutoff": {"type": "string", "description": "Inclusive as-of date YYYY-MM-DD. Only complete months ending on or before this date may be used."},
            },
            "required": ["currency", "metric", "forecast_period", "historical_cutoff"],
        },
    },
    "save_financial_forecast": {
        "name": "save_financial_forecast",
        "description": "Calculate a cutoff-safe monthly forecast and persist it. Returns persisted=true only after the database commit succeeds.",
        "parameters": {
            "type": "object",
            "properties": {
                "currency": {"type": "string", "description": "Currency code."},
                "metric": {"type": "string", "description": "Metric to forecast."},
                "forecast_period": {"type": "string", "description": "Target month start YYYY-MM-01."},
                "historical_cutoff": {"type": "string", "description": "Inclusive historical cutoff YYYY-MM-DD."},
                "lookback_months": {"type": "integer", "description": "Number of completed monthly observations; default 3."},
            },
            "required": ["currency", "metric", "forecast_period", "historical_cutoff"],
        },
    },
    "get_saved_financial_forecast": {
        "name": "get_saved_financial_forecast",
        "description": "Retrieve one persisted forecast by its unique forecast ID.",
        "parameters": {
            "type": "object",
            "properties": {"forecast_id": {"type": "string", "description": "Unique forecast identifier returned when saving."}},
            "required": ["forecast_id"],
        },
    },
    "compare_saved_forecast_to_actual": {
        "name": "compare_saved_forecast_to_actual",
        "description": "Compare a saved monthly forecast with its actual value for the same metric, currency, unit definition, grain, and target month.",
        "parameters": {
            "type": "object",
            "properties": {"forecast_id": {"type": "string", "description": "Unique forecast identifier returned when saving."}},
            "required": ["forecast_id"],
        },
    },
    "analyze_financial_ratios": {
        "name": "analyze_financial_ratios",
        "description": "Calculate derived financial ratios from verified transaction data.",
        "parameters": {
            "type": "object",
            "properties": {
                "currency": {"type": "string", "description": "Currency code."},
                "date_from": {"type": "string", "description": "Start date YYYY-MM-DD."},
                "date_to": {"type": "string", "description": "Inclusive end date YYYY-MM-DD."},
            },
            "required": ["currency", "date_from", "date_to"],
        },
    },
}


def get_sql_connection() -> pyodbc.Connection:
    conn_str = (
        f"DRIVER={{{DB_DRIVER}}};"
        f"SERVER={DB_SERVER};"
        f"DATABASE={DB_DATABASE};"
        f"Trusted_Connection={DB_TRUSTED};"
        f"Encrypt={DB_ENCRYPT};"
        f"TrustServerCertificate={DB_TRUST_SERVER_CERT};"
    )
    return pyodbc.connect(conn_str, timeout=30)


def _rows_to_dicts(cursor: pyodbc.Cursor) -> List[Dict[str, Any]]:
    columns = [c[0] for c in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def _query_one(sql: str, params: Sequence[Any] = ()) -> Optional[Dict[str, Any]]:
    conn = get_sql_connection()
    try:
        cur = conn.cursor()
        cur.execute(sql, tuple(params))
        row = cur.fetchone()
        if row is None:
            return None
        columns = [c[0] for c in cur.description]
        return dict(zip(columns, row))
    finally:
        conn.close()


def _query_all(sql: str, params: Sequence[Any] = ()) -> List[Dict[str, Any]]:
    conn = get_sql_connection()
    try:
        cur = conn.cursor()
        cur.execute(sql, tuple(params))
        return _rows_to_dicts(cur)
    finally:
        conn.close()


def _safe_float(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_ratio(numerator: float, denominator: float) -> Optional[float]:
    if denominator == 0:
        return None
    return numerator / denominator


def _round_or_none(value: Optional[float], digits: int = 4) -> Optional[float]:
    return round(value, digits) if value is not None else None


def _validate_currency(currency: str) -> str:
    currency = (currency or "").strip().upper()
    if currency not in ALLOWED_CURRENCIES:
        raise ValueError(f"Unsupported currency: {currency}. Allowed: {sorted(ALLOWED_CURRENCIES)}")
    return currency


def _validate_metric(metric: str) -> str:
    metric = (metric or "").strip().lower()
    if metric not in ALLOWED_METRICS:
        raise ValueError(f"Unsupported metric: {metric}. Allowed: {sorted(ALLOWED_METRICS)}")
    return metric


def _parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def _month_start(value: date) -> date:
    return value.replace(day=1)


def _add_months(value: date, months: int) -> date:
    index = value.year * 12 + (value.month - 1) + months
    year, month0 = divmod(index, 12)
    return date(year, month0 + 1, 1)


def _month_end(value: date) -> date:
    next_month = _add_months(_month_start(value), 1)
    return next_month - timedelta(days=1)


def _canonical_period(date_from: str, date_to: str) -> Dict[str, str]:
    _parse_date(date_from)
    _parse_date(date_to)
    if date_from > date_to:
        raise ValueError("date_from must be <= date_to")
    return {"date_from": date_from, "date_to": date_to}


# ============================================================
# Data coverage
# ============================================================


def get_financial_data_coverage() -> Dict[str, Any]:
    row = _query_one(
        """
        SELECT
            MIN(CAST(transaction_timestamp AS date)) AS min_date,
            MAX(CAST(transaction_timestamp AS date)) AS max_date,
            COUNT_BIG(*) AS row_count
        FROM core.vw_transactions;
        """
    )

    if not row or row.get("min_date") is None:
        return {
            "status": "no_data",
            "available_data": {"date_from": None, "date_to": None},
            "min_date": None,
            "max_date": None,
            "latest_actual_date": None,
            "row_count": 0,
        }

    min_date = row["min_date"].isoformat()
    max_date = row["max_date"].isoformat()

    return {
        "status": "success",
        "available_data": {
            "date_from": min_date,
            "date_to": max_date,
        },
        "min_date": min_date,
        "max_date": max_date,
        "latest_actual_date": max_date,
        "row_count": _safe_int(row["row_count"]),
    }


def _resolve_actual_period(
    date_from: str,
    date_to: str,
) -> Tuple[str, str, Dict[str, Any], bool]:
    """Resolve requested period against the verified actual boundary."""
    _parse_date(date_from)
    _parse_date(date_to)
    if date_from > date_to:
        raise ValueError("date_from must be <= date_to")

    coverage = get_financial_data_coverage()
    available = coverage.get("available_data", {}) if isinstance(coverage, dict) else {}
    min_date = available.get("date_from")
    max_date = available.get("date_to")

    if not min_date or not max_date:
        return date_from, date_to, coverage, False

    if date_to < min_date or date_from > max_date:
        return date_from, date_to, coverage, False

    resolved_from = max(date_from, min_date)
    resolved_to = min(date_to, max_date)
    return resolved_from, resolved_to, coverage, True


# ============================================================
# Tool 1: KPI
# ============================================================


def get_financial_kpis(
    currency: str,
    date_from: str,
    date_to: str,
    metric: Optional[str] = None,
) -> Dict[str, Any]:
    currency = _validate_currency(currency)
    _parse_date(date_from)
    _parse_date(date_to)
    if date_from > date_to:
        raise ValueError("date_from must be <= date_to")
    if metric:
        metric = _validate_metric(metric)

    coverage = get_financial_data_coverage()
    latest_actual = coverage.get("available_data", {}).get("date_to")
    requested_period = _canonical_period(date_from, date_to)

    if latest_actual and date_from > latest_actual:
        return {
            "status": "no_data",
            "requested_period": requested_period,
            "available_data": coverage.get("available_data"),
            "currency": currency,
            "message": "The requested period is outside the available actual data range.",
        }

    resolved_date_to = date_to
    partial_period = False
    if latest_actual and date_to > latest_actual:
        resolved_date_to = latest_actual
        partial_period = True

    if date_from > resolved_date_to:
        return {
            "status": "no_data",
            "requested_period": requested_period,
            "available_data": coverage.get("available_data"),
            "currency": currency,
            "message": "The requested period is outside the available actual data range.",
        }

    mart_rows = _query_one(
        """
        SELECT
            COALESCE(SUM(total_inflows), 0) AS total_inflows,
            COALESCE(SUM(total_outflows), 0) AS total_outflows,
            COALESCE(SUM(net_cash_flow), 0) AS net_cash_flow,
            COALESCE(SUM(fees), 0) AS fees,
            COALESCE(SUM(refunds), 0) AS refunds,
            COALESCE(SUM(transfers), 0) AS transfers,
            COALESCE(SUM(completed_transactions), 0) AS completed_transactions,
            COALESCE(SUM(pending_transactions), 0) AS pending_transactions,
            COALESCE(SUM(failed_transactions), 0) AS failed_transactions,
            COALESCE(SUM(reversed_transactions), 0) AS reversed_transactions
        FROM mart.daily_financial_kpis
        WHERE currency = ?
          AND business_date >= ?
          AND business_date <= ?;
        """,
        (currency, date_from, resolved_date_to),
    )

    tx_row = _query_one(
        """
        SELECT
            COUNT_BIG(*) AS transactions,
            COUNT(DISTINCT account_id) AS active_accounts,
            AVG(CAST(amount AS decimal(38, 10))) AS average_transaction_amount
        FROM core.vw_transactions
        WHERE currency = ?
          AND transaction_timestamp >= ?
          AND transaction_timestamp < DATEADD(day, 1, ?);
        """,
        (currency, date_from, resolved_date_to),
    )

    if not tx_row or _safe_int(tx_row.get("transactions")) == 0:
        return {
            "status": "no_data",
            "requested_period": requested_period,
            "available_data": coverage.get("available_data"),
            "currency": currency,
            "message": "No financial records were found for the requested period and currency.",
        }

    values = {
        "total_inflows": _safe_float(mart_rows.get("total_inflows")) if mart_rows else 0.0,
        "total_outflows": _safe_float(mart_rows.get("total_outflows")) if mart_rows else 0.0,
        "net_cash_flow": _safe_float(mart_rows.get("net_cash_flow")) if mart_rows else 0.0,
        "fees": _safe_float(mart_rows.get("fees")) if mart_rows else 0.0,
        "refunds": _safe_float(mart_rows.get("refunds")) if mart_rows else 0.0,
        "transfers": _safe_float(mart_rows.get("transfers")) if mart_rows else 0.0,
        "transactions": _safe_int(tx_row.get("transactions")),
        "completed_transactions": _safe_int(mart_rows.get("completed_transactions")) if mart_rows else 0,
        "pending_transactions": _safe_int(mart_rows.get("pending_transactions")) if mart_rows else 0,
        "failed_transactions": _safe_int(mart_rows.get("failed_transactions")) if mart_rows else 0,
        "reversed_transactions": _safe_int(mart_rows.get("reversed_transactions")) if mart_rows else 0,
        "active_accounts": _safe_int(tx_row.get("active_accounts")),
        "average_transaction_amount": _safe_float(tx_row.get("average_transaction_amount")),
    }

    return {
        "status": "success",
        "currency": currency,
        "requested_period": requested_period,
        "resolved_period": {"date_from": date_from, "date_to": resolved_date_to},
        "available_data": coverage.get("available_data"),
        "filters": {"currency": currency, "date_from": date_from, "date_to": resolved_date_to},
        "results": [
            {
                "period": {"date_from": date_from, "date_to": resolved_date_to},
                "currency": currency,
                "metric": m,
                "value": values[m],
            }
            for m in ([metric] if metric else list(ALLOWED_METRICS))
        ],
        "data_quality": {
            "actual_data": True,
            "source": "AI_Finance.mart.daily_financial_kpis + AI_Finance.core.vw_transactions",
            "latest_actual_date": latest_actual,
            "partial_period": partial_period,
            "flow_reconciliation": {
                "calculated_net_from_flows": values["total_inflows"] - values["total_outflows"],
                "reported_net_cash_flow": values["net_cash_flow"],
                "gap": (values["total_inflows"] - values["total_outflows"]) - values["net_cash_flow"],
                "status": (
                    "reconciled"
                    if math.isclose(
                        values["total_inflows"] - values["total_outflows"],
                        values["net_cash_flow"],
                        abs_tol=0.01,
                        rel_tol=1e-9,
                    )
                    else "not_reconciled"
                ),
            },
        },
    }


# ============================================================
# Shared metric extraction
# ============================================================


def _metric_value(currency: str, metric: str, date_from: str, date_to: str) -> Optional[float]:
    metric = _validate_metric(metric)
    currency = _validate_currency(currency)
    _canonical_period(date_from, date_to)

    if metric in {
        "total_inflows",
        "total_outflows",
        "net_cash_flow",
        "fees",
        "refunds",
        "transfers",
        "completed_transactions",
        "pending_transactions",
        "failed_transactions",
        "reversed_transactions",
    }:
        row = _query_one(
            f"""
            SELECT COALESCE(SUM({metric}), 0) AS value
            FROM mart.daily_financial_kpis
            WHERE currency = ?
              AND business_date >= ?
              AND business_date <= ?;
            """,
            (currency, date_from, date_to),
        )
        return _safe_float(row.get("value")) if row else None

    if metric == "transactions":
        row = _query_one(
            """
            SELECT COUNT_BIG(*) AS value
            FROM core.vw_transactions
            WHERE currency = ?
              AND transaction_timestamp >= ?
              AND transaction_timestamp < DATEADD(day, 1, ?);
            """,
            (currency, date_from, date_to),
        )
        return _safe_float(row.get("value")) if row else None

    if metric == "active_accounts":
        row = _query_one(
            """
            SELECT COUNT(DISTINCT account_id) AS value
            FROM core.vw_transactions
            WHERE currency = ?
              AND transaction_timestamp >= ?
              AND transaction_timestamp < DATEADD(day, 1, ?);
            """,
            (currency, date_from, date_to),
        )
        return _safe_float(row.get("value")) if row else None

    if metric == "average_transaction_amount":
        row = _query_one(
            """
            SELECT AVG(CAST(amount AS decimal(38, 10))) AS value
            FROM core.vw_transactions
            WHERE currency = ?
              AND transaction_timestamp >= ?
              AND transaction_timestamp < DATEADD(day, 1, ?);
            """,
            (currency, date_from, date_to),
        )
        return _safe_float(row.get("value")) if row else None

    return None


# ============================================================
# Tool 2: Compare
# ============================================================


def compare_financial_periods(
    currency: str,
    metric: str,
    period_1_from: str,
    period_1_to: str,
    period_2_from: str,
    period_2_to: str,
) -> Dict[str, Any]:
    currency = _validate_currency(currency)
    metric = _validate_metric(metric)
    for value in [period_1_from, period_1_to, period_2_from, period_2_to]:
        _parse_date(value)
    _canonical_period(period_1_from, period_1_to)
    _canonical_period(period_2_from, period_2_to)

    v1 = _metric_value(currency, metric, period_1_from, period_1_to)
    v2 = _metric_value(currency, metric, period_2_from, period_2_to)

    if v1 is None or v2 is None:
        return {
            "status": "no_data",
            "comparison_metric": metric,
            "currency": currency,
            "period_1": {"date_from": period_1_from, "date_to": period_1_to, "value": v1, "status": "no_data" if v1 is None else "success"},
            "period_2": {"date_from": period_2_from, "date_to": period_2_to, "value": v2, "status": "no_data" if v2 is None else "success"},
        }

    absolute_change = v2 - v1
    percentage_change = None if v1 == 0 else (absolute_change / abs(v1)) * 100

    if math.isclose(absolute_change, 0.0, abs_tol=1e-12):
        direction = "unchanged"
    elif absolute_change > 0:
        direction = "increase"
    else:
        direction = "decrease"

    return {
        "status": "success",
        "comparison_metric": metric,
        "currency": currency,
        "period_1": {"date_from": period_1_from, "date_to": period_1_to, "value": v1, "status": "success"},
        "period_2": {"date_from": period_2_from, "date_to": period_2_to, "value": v2, "status": "success"},
        "absolute_change": absolute_change,
        "percentage_change": percentage_change,
        "direction": direction,
        "comparisons": [
            {"period": "period_1", "value": v1},
            {"period": "period_2", "value": v2},
        ],
        "calculation": {
            "absolute_change": "period_2 - period_1",
            "percentage_change": "(period_2 - period_1) / abs(period_1) * 100",
        },
        "data_quality": {"actual_data": True, "read_only": True},
    }


# ============================================================
# Tool 3: Monthly trend
# ============================================================


def analyze_financial_trend(
    currency: str,
    metric: str,
    date_from: str,
    date_to: str,
) -> Dict[str, Any]:
    currency = _validate_currency(currency)
    metric = _validate_metric(metric)
    start = _parse_date(date_from)
    end = _parse_date(date_to)

    if start > end:
        raise ValueError("date_from must be <= date_to")

    if metric in {
        "total_inflows",
        "total_outflows",
        "net_cash_flow",
        "fees",
        "refunds",
        "transfers",
        "completed_transactions",
        "pending_transactions",
        "failed_transactions",
        "reversed_transactions",
    }:
        rows = _query_all(
            f"""
            SELECT
                DATEFROMPARTS(YEAR(business_date), MONTH(business_date), 1) AS month_start,
                COALESCE(SUM({metric}), 0) AS value
            FROM mart.daily_financial_kpis
            WHERE currency = ?
              AND business_date >= ?
              AND business_date <= ?
            GROUP BY DATEFROMPARTS(YEAR(business_date), MONTH(business_date), 1)
            ORDER BY month_start;
            """,
            (currency, date_from, date_to),
        )
    elif metric == "transactions":
        rows = _query_all(
            """
            SELECT
                DATEFROMPARTS(YEAR(transaction_timestamp), MONTH(transaction_timestamp), 1) AS month_start,
                COUNT_BIG(*) AS value
            FROM core.vw_transactions
            WHERE currency = ?
              AND transaction_timestamp >= ?
              AND transaction_timestamp < DATEADD(day, 1, ?)
            GROUP BY DATEFROMPARTS(YEAR(transaction_timestamp), MONTH(transaction_timestamp), 1)
            ORDER BY month_start;
            """,
            (currency, date_from, date_to),
        )
    elif metric == "active_accounts":
        rows = _query_all(
            """
            SELECT
                DATEFROMPARTS(YEAR(transaction_timestamp), MONTH(transaction_timestamp), 1) AS month_start,
                COUNT(DISTINCT account_id) AS value
            FROM core.vw_transactions
            WHERE currency = ?
              AND transaction_timestamp >= ?
              AND transaction_timestamp < DATEADD(day, 1, ?)
            GROUP BY DATEFROMPARTS(YEAR(transaction_timestamp), MONTH(transaction_timestamp), 1)
            ORDER BY month_start;
            """,
            (currency, date_from, date_to),
        )
    elif metric == "average_transaction_amount":
        rows = _query_all(
            """
            SELECT
                DATEFROMPARTS(YEAR(transaction_timestamp), MONTH(transaction_timestamp), 1) AS month_start,
                AVG(CAST(amount AS decimal(38, 10))) AS value
            FROM core.vw_transactions
            WHERE currency = ?
              AND transaction_timestamp >= ?
              AND transaction_timestamp < DATEADD(day, 1, ?)
            GROUP BY DATEFROMPARTS(YEAR(transaction_timestamp), MONTH(transaction_timestamp), 1)
            ORDER BY month_start;
            """,
            (currency, date_from, date_to),
        )
    else:
        raise ValueError(f"Unsupported trend metric: {metric}")

    results: List[Dict[str, Any]] = []
    previous_value: Optional[float] = None

    for row in rows:
        current = _safe_float(row.get("value"))
        month_value = row["month_start"]
        period_label = month_value.strftime("%Y-%m")

        abs_change = None
        pct_change = None
        direction = "initial"

        if previous_value is not None:
            abs_change = current - previous_value
            pct_change = None if previous_value == 0 else (abs_change / abs(previous_value)) * 100
            if math.isclose(abs_change, 0.0, abs_tol=1e-12):
                direction = "unchanged"
            elif abs_change > 0:
                direction = "increase"
            else:
                direction = "decrease"

        results.append(
            {
                "period": period_label,
                "currency": currency,
                "metric": metric,
                "value": current,
                "previous_value": previous_value,
                "absolute_change": abs_change,
                "percentage_change": pct_change,
                "direction": direction,
            }
        )
        previous_value = current

    if not results:
        return {
            "status": "no_data",
            "currency": currency,
            "metric": metric,
            "requested_period": {"date_from": date_from, "date_to": date_to},
            "results": [],
        }

    return {
        "status": "success",
        "currency": currency,
        "metric": metric,
        "granularity": "monthly",
        "requested_period": {"date_from": date_from, "date_to": date_to},
        "results": results,
        "data_quality": {"actual_data": True, "read_only": True},
    }


# ============================================================
# Tool 4: Anomalies
# ============================================================


def _median(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    n = len(ordered)
    mid = n // 2
    if n % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def detect_financial_anomalies(
    date_from: str,
    date_to: str,
    currency: Optional[str] = None,
    threshold: float = 3.5,
) -> Dict[str, Any]:
    start = _parse_date(date_from)
    end = _parse_date(date_to)
    if start > end:
        raise ValueError("date_from must be <= date_to")

    if threshold <= 0:
        raise ValueError("threshold must be > 0")

    if currency:
        currency = _validate_currency(currency)

    sql = """
        SELECT
            CAST(transaction_timestamp AS date) AS business_date,
            currency,
            SUM(
                CASE
                    WHEN LOWER(LTRIM(RTRIM(transaction_type))) IN ('credit','deposit','interest','refund')
                        THEN ABS(CAST(amount AS decimal(38, 10)))
                    WHEN LOWER(LTRIM(RTRIM(transaction_type))) IN ('debit','withdrawal','fee')
                        THEN -ABS(CAST(amount AS decimal(38, 10)))
                    ELSE 0
                END
            ) AS net_cash_flow
        FROM core.vw_transactions
        WHERE transaction_timestamp >= ?
          AND transaction_timestamp < DATEADD(day, 1, ?)
    """
    params: List[Any] = [date_from, date_to]
    if currency:
        sql += " AND currency = ? "
        params.append(currency)

    sql += """
        GROUP BY CAST(transaction_timestamp AS date), currency
        ORDER BY business_date, currency;
    """

    rows = _query_all(sql, params)
    by_currency: Dict[str, List[Dict[str, Any]]] = {}
    for row in rows:
        by_currency.setdefault(str(row["currency"]), []).append(row)

    anomalies: List[Dict[str, Any]] = []
    stats: Dict[str, Any] = {}

    for curr, curr_rows in by_currency.items():
        values = [_safe_float(r["net_cash_flow"]) for r in curr_rows]
        med = _median(values)
        abs_deviations = [abs(v - med) for v in values]
        mad = _median(abs_deviations)

        curr_anomalies: List[Dict[str, Any]] = []
        for row in curr_rows:
            observed = _safe_float(row["net_cash_flow"])
            if mad == 0:
                modified_z = 0.0
            else:
                modified_z = 0.6745 * (observed - med) / mad

            if abs(modified_z) >= threshold:
                item = {
                    "business_date": row["business_date"].isoformat(),
                    "currency": curr,
                    "observed_value": observed,
                    "median": med,
                    "mad": mad,
                    "modified_z_score": modified_z,
                    "direction": "high" if modified_z > 0 else "low",
                    "threshold": threshold,
                }
                curr_anomalies.append(item)
                anomalies.append(item)

        stats[curr] = {
            "observation_count": len(values),
            "median": med,
            "mad": mad,
            "threshold": threshold,
            "anomaly_count": len(curr_anomalies),
        }

    return {
        "status": "success" if rows else "no_data",
        "analysis": "modified_z_score",
        "date_from": date_from,
        "date_to": date_to,
        "currency": currency,
        "threshold": threshold,
        "currency_statistics": stats,
        "anomalies": anomalies,
        "anomaly_count": len(anomalies),
        "data_quality": {"actual_data": True, "read_only": True},
    }


# ============================================================
# Tool 5: Cash-flow drivers
# ============================================================


def _driver_query(
    currency: str,
    period_from: str,
    period_to: str,
) -> List[Dict[str, Any]]:
    return _query_all(
        """
        SELECT
            LOWER(LTRIM(RTRIM(transaction_type))) AS transaction_type,
            SUM(
                CASE
                    WHEN LOWER(LTRIM(RTRIM(transaction_type))) IN ('credit','deposit','interest','refund')
                        THEN ABS(CAST(amount AS decimal(38, 10)))
                    WHEN LOWER(LTRIM(RTRIM(transaction_type))) IN ('debit','withdrawal','fee')
                        THEN -ABS(CAST(amount AS decimal(38, 10)))
                    ELSE 0
                END
            ) AS value
        FROM core.vw_transactions
        WHERE currency = ?
          AND transaction_timestamp >= ?
          AND transaction_timestamp < DATEADD(day, 1, ?)
        GROUP BY LOWER(LTRIM(RTRIM(transaction_type)));
        """,
        (currency, period_from, period_to),
    )


def _authoritative_net_cash_flow(
    currency: str,
    period_from: str,
    period_to: str,
) -> Optional[float]:
    row = _query_one(
        """
        SELECT COALESCE(SUM(net_cash_flow), 0) AS value
        FROM mart.daily_financial_kpis
        WHERE currency = ?
          AND business_date >= ?
          AND business_date <= ?;
        """,
        (currency, period_from, period_to),
    )
    return _safe_float(row.get("value")) if row else None


def _authoritative_cash_flow_metrics(
    currency: str,
    period_from: str,
    period_to: str,
) -> Dict[str, Optional[float]]:
    """Read the authoritative monthly cash-flow measures for one currency/period."""
    row = _query_one(
        """
        SELECT
            COUNT_BIG(*) AS observation_count,
            SUM(total_inflows) AS total_inflows,
            SUM(total_outflows) AS total_outflows,
            SUM(net_cash_flow) AS net_cash_flow,
            SUM(fees) AS fees,
            SUM(refunds) AS refunds
        FROM mart.daily_financial_kpis
        WHERE currency = ?
          AND business_date >= ?
          AND business_date <= ?;
        """,
        (currency, period_from, period_to),
    )
    metric_names = ("total_inflows", "total_outflows", "net_cash_flow", "fees", "refunds")
    if not row or _safe_int(row.get("observation_count")) == 0:
        return {metric: None for metric in metric_names}
    return {
        metric: _safe_float(row.get(metric)) if row.get(metric) is not None else None
        for metric in metric_names
    }


def analyze_cash_flow_drivers(
    currency: str,
    period_1_from: str,
    period_1_to: str,
    period_2_from: str,
    period_2_to: str,
) -> Dict[str, Any]:
    """
    Explain the authoritative net cash flow change using transaction-type
    component movements.

    Important scope rule:
      * Period net cash flow values come from mart.daily_financial_kpis.
      * Driver components come from core.vw_transactions.
      * Any difference between component change and authoritative KPI change
        is surfaced explicitly as a reconciliation residual.

    This prevents follow-up analysis from reporting a transaction-level
    flow total as if it were the authoritative KPI.
    """

    currency = _validate_currency(currency)
    for value in [period_1_from, period_1_to, period_2_from, period_2_to]:
        _parse_date(value)
    _canonical_period(period_1_from, period_1_to)
    _canonical_period(period_2_from, period_2_to)

    rows1 = _driver_query(currency, period_1_from, period_1_to)
    rows2 = _driver_query(currency, period_2_from, period_2_to)

    kpis_1 = _authoritative_cash_flow_metrics(currency, period_1_from, period_1_to)
    kpis_2 = _authoritative_cash_flow_metrics(currency, period_2_from, period_2_to)
    authoritative_1 = kpis_1.get("net_cash_flow")
    authoritative_2 = kpis_2.get("net_cash_flow")

    if authoritative_1 is None or authoritative_2 is None:
        return {
            "status": "no_data",
            "currency": currency,
            "period_1": {"date_from": period_1_from, "date_to": period_1_to, "value": authoritative_1},
            "period_2": {"date_from": period_2_from, "date_to": period_2_to, "value": authoritative_2},
            "message": "Authoritative net cash flow is unavailable for one or both requested periods.",
        }

    p1 = {str(r["transaction_type"]): _safe_float(r["value"]) for r in rows1}
    p2 = {str(r["transaction_type"]): _safe_float(r["value"]) for r in rows2}
    all_types = sorted(set(p1) | set(p2))

    component_period_1_value = sum(p1.values())
    component_period_2_value = sum(p2.values())
    component_absolute_change = component_period_2_value - component_period_1_value

    period_1_value = authoritative_1
    period_2_value = authoritative_2
    absolute_change = period_2_value - period_1_value
    percentage_change = None if period_1_value == 0 else (absolute_change / abs(period_1_value)) * 100

    component_comparisons = []
    for metric in ("net_cash_flow", "total_inflows", "total_outflows", "fees", "refunds"):
        value_1 = kpis_1.get(metric)
        value_2 = kpis_2.get(metric)
        available = value_1 is not None and value_2 is not None
        change = value_2 - value_1 if available else None
        component_comparisons.append(
            {
                "metric": metric,
                "currency": currency,
                "source": "AI_Finance.mart.daily_financial_kpis",
                "period_1": {
                    "date_from": period_1_from,
                    "date_to": period_1_to,
                    "value": value_1,
                },
                "period_2": {
                    "date_from": period_2_from,
                    "date_to": period_2_to,
                    "value": value_2,
                },
                "period_1_value": value_1,
                "period_2_value": value_2,
                "absolute_change": change,
                "percentage_change": (
                    None if not available or value_1 == 0 else (change / abs(value_1)) * 100
                ),
                "status": "success" if available else "no_data",
            }
        )

    flow_reconciliation = {}
    for label, values in (("period_1", kpis_1), ("period_2", kpis_2)):
        inflows = values.get("total_inflows")
        outflows = values.get("total_outflows")
        net = values.get("net_cash_flow")
        if inflows is None or outflows is None or net is None:
            flow_reconciliation[label] = {"status": "unavailable"}
            continue
        calculated_net = inflows - outflows
        gap = calculated_net - net
        flow_reconciliation[label] = {
            "calculated_net_from_flows": calculated_net,
            "reported_net_cash_flow": net,
            "gap": gap,
            "status": "reconciled" if math.isclose(calculated_net, net, abs_tol=0.01, rel_tol=1e-9) else "not_reconciled",
        }

    drivers: List[Dict[str, Any]] = []
    for tx_type in all_types:
        v1 = p1.get(tx_type, 0.0)
        v2 = p2.get(tx_type, 0.0)
        change = v2 - v1
        contribution = None if absolute_change == 0 else (change / absolute_change) * 100
        drivers.append(
            {
                "transaction_type": tx_type,
                "flow_role": TRANSACTION_TYPE_ROLES.get(tx_type, "OTHER"),
                "period_1_value": v1,
                "period_2_value": v2,
                "change": change,
                "contribution_percentage": contribution,
                "is_reconciliation_item": False,
            }
        )

    reconciliation_residual = absolute_change - component_absolute_change
    if not math.isclose(reconciliation_residual, 0.0, abs_tol=0.01, rel_tol=1e-9):
        residual_contribution = None if absolute_change == 0 else (reconciliation_residual / absolute_change) * 100
        drivers.append(
            {
                "transaction_type": "__reconciliation__",
                "flow_role": "RECONCILIATION",
                "period_1_value": 0.0,
                "period_2_value": 0.0,
                "change": reconciliation_residual,
                "contribution_percentage": residual_contribution,
                "is_reconciliation_item": True,
                "explanation": (
                    "Residual required to reconcile transaction-level driver components "
                    "to the authoritative mart net cash flow change."
                ),
            }
        )

    drivers.sort(key=lambda x: abs(x["change"]), reverse=True)
    top_drivers = [d for d in drivers if not d.get("is_reconciliation_item")][:5]

    return {
        "status": "success",
        "currency": currency,
        "period_1": {"date_from": period_1_from, "date_to": period_1_to, "value": period_1_value},
        "period_2": {"date_from": period_2_from, "date_to": period_2_to, "value": period_2_value},
        "absolute_change": absolute_change,
        "percentage_change": percentage_change,
        "cash_flow_metric_comparisons": component_comparisons,
        "flow_reconciliation": flow_reconciliation,
        "metric_relationships": {
            "fees": "Reported separately; analyzed as fees / total_outflows. Do not add fees to total_outflows.",
            "refunds": "Reported separately; analyzed as refunds / total_inflows. Do not add refunds to total_inflows.",
        },
        "drivers": drivers,
        "drivers_by_currency": {currency: drivers},
        "top_drivers_by_currency": {currency: top_drivers},
        "calculation": {
            "authoritative_period_value": "mart.daily_financial_kpis.net_cash_flow",
            "component_period_value": "sum of signed transaction-type contributions from core.vw_transactions",
            "absolute_change": "authoritative_period_2_net_cash_flow - authoritative_period_1_net_cash_flow",
            "percentage_change": "(period_2 - period_1) / abs(period_1) * 100",
            "driver_contribution": "driver_change / authoritative_absolute_change * 100",
            "reconciliation_residual": "authoritative_change - component_change",
        },
        "driver_reconciliation": {
            "authoritative_period_1_value": period_1_value,
            "authoritative_period_2_value": period_2_value,
            "authoritative_absolute_change": absolute_change,
            "component_period_1_value": component_period_1_value,
            "component_period_2_value": component_period_2_value,
            "component_absolute_change": component_absolute_change,
            "residual": reconciliation_residual,
            "status": (
                "reconciled"
                if math.isclose(component_absolute_change, absolute_change, abs_tol=0.01, rel_tol=1e-9)
                else "reconciled_with_residual"
            ),
        },
        "data_quality": {
            "actual_data": True,
            "read_only": True,
            "authoritative_net_cash_flow_source": "AI_Finance.mart.daily_financial_kpis",
            "driver_component_source": "AI_Finance.core.vw_transactions",
            "cash_flow_metric_source": "AI_Finance.mart.daily_financial_kpis",
            "mixed_scope_is_explicit": True,
        },
    }


# ============================================================
# Tool 6: Forecast
# ============================================================


def _forecast_monthly_values(
    currency: str,
    metric: str,
    end_month: date,
    lookback_months: int,
) -> List[Dict[str, Any]]:
    start_month = _add_months(_month_start(end_month), -(lookback_months - 1))
    end_month_end = _month_end(end_month)
    trend = analyze_financial_trend(
        currency=currency,
        metric=metric,
        date_from=start_month.isoformat(),
        date_to=end_month_end.isoformat(),
    )
    if trend.get("status") != "success":
        return []
    return trend.get("results", [])


def forecast_financial_kpi(
    currency: str,
    metric: str,
    forecast_period: str,
    historical_cutoff: str,
    lookback_months: int = 3,
) -> Dict[str, Any]:
    currency = _validate_currency(currency)
    metric = _validate_metric(metric)
    forecast_date = _parse_date(forecast_period)
    cutoff_date = _parse_date(historical_cutoff)
    if forecast_date.day != 1:
        raise ValueError("forecast_period must be the first day of the target month (YYYY-MM-01).")
    forecast_month = _month_start(forecast_date)
    if cutoff_date >= forecast_month:
        raise ValueError("historical_cutoff must be before the target forecast month.")

    if lookback_months < 1 or lookback_months > 24:
        raise ValueError("lookback_months must be between 1 and 24")

    coverage = get_financial_data_coverage()
    latest_actual_text = coverage.get("available_data", {}).get("date_to")
    if not latest_actual_text:
        return {
            "status": "no_data", "currency": currency, "metric": metric,
            "forecast_period": forecast_month.isoformat(),
            "historical_cutoff": cutoff_date.isoformat(),
            "lookback_months": lookback_months, "grain": "monthly",
            "is_forecast": True, "persisted": False,
            "message": "No actual data is available for the requested forecast.",
        }

    latest_actual = _parse_date(latest_actual_text)
    eligible_through = min(cutoff_date, latest_actual)
    last_complete_month = _month_start(eligible_through)
    if eligible_through < _month_end(last_complete_month):
        if last_complete_month == date.min.replace(day=1):
            last_complete_month = None
        else:
            last_complete_month = _add_months(last_complete_month, -1)

    history = (
        _forecast_monthly_values(
            currency=currency,
            metric=metric,
            end_month=last_complete_month,
            lookback_months=lookback_months,
        )
        if last_complete_month is not None
        else []
    )
    history = [
        item for item in history
        if str(item.get("period", "")) <= last_complete_month.strftime("%Y-%m")
    ]

    if len(history) < lookback_months:
        return {
            "status": "insufficient_data",
            "currency": currency,
            "metric": metric,
            "forecast_period": forecast_month.isoformat(),
            "historical_cutoff": cutoff_date.isoformat(),
            "lookback_months": lookback_months,
            "historical_periods": history,
            "grain": "monthly",
            "is_forecast": True,
            "persisted": False,
            "available_data": coverage.get("available_data"),
            "message": "Not enough completed monthly observations are available on or before the historical cutoff.",
        }

    values = [_safe_float(item.get("value")) for item in history[-lookback_months:]]
    forecast_value = sum(values) / len(values)

    return {
        "status": "success",
        "currency": currency,
        "metric": metric,
        "forecast_period": forecast_month.isoformat(),
        "historical_cutoff": cutoff_date.isoformat(),
        "forecast_value": forecast_value,
        "method": "Trailing Moving Average",
        "grain": "monthly",
        "lookback_months": lookback_months,
        "lookback_window": {
            "from": history[-lookback_months]["period"],
            "through": history[-1]["period"],
            "observation_count": len(history[-lookback_months:]),
        },
        "is_forecast": True,
        "persisted": False,
        "message": "Forecast calculated from completed historical monthly observations; it has not been saved.",
        "historical_periods": history[-lookback_months:],
        "source_periods": [x["period"] for x in history[-lookback_months:]],
        "source_values": values,
        "last_actual_period": last_complete_month.isoformat(),
        "calculation": {
            "formula": f"sum(last_{lookback_months}_completed_months) / {lookback_months}"
        },
        "data_quality": {
            "actual_history": True,
            "forecast_is_not_actual": True,
            "latest_actual_date": latest_actual_text,
            "no_data_after_historical_cutoff_used": True,
        },
    }


def _metric_unit(metric: str, currency: str) -> str:
    if metric in MONETARY_METRICS:
        return currency
    if metric == "average_transaction_amount":
        return f"{currency}/transaction"
    if metric in COUNT_METRICS:
        return "count"
    raise ValueError(f"No unit definition is available for metric: {metric}")


def _insert_forecast_record(record: Dict[str, Any]) -> Dict[str, Any]:
    """Insert a forecast record and return DB-confirmed metadata after commit."""
    conn = get_sql_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            f"""
            INSERT INTO {FORECAST_TABLE} (
                forecast_id, metric, currency, target_period, time_grain, unit,
                forecast_value, forecast_method, lookback_months, historical_cutoff,
                source_periods_json, source_values_json, model_version,
                metric_definition_version, status, provenance_json
            )
            OUTPUT INSERTED.forecast_id, INSERTED.created_at
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (
                record["forecast_id"], record["metric"], record["currency"],
                record["target_period"], record["time_grain"], record["unit"],
                record["forecast_value"], record["forecast_method"], record["lookback_months"],
                record["historical_cutoff"], record["source_periods_json"],
                record["source_values_json"], record["model_version"],
                record["metric_definition_version"], record["status"], record["provenance_json"],
            ),
        )
        inserted = cursor.fetchone()
        if inserted is None:
            raise RuntimeError("The database did not confirm the forecast insert.")
        conn.commit()
        return {"forecast_id": str(inserted[0]), "created_at": inserted[1]}
    except Exception as exc:
        conn.rollback()
        message = str(exc).lower()
        if "2627" in message or "2601" in message or "duplicate key" in message:
            raise DuplicateForecastError("Forecast identifier already exists.") from None
        raise
    finally:
        conn.close()


def _select_forecast_record(forecast_id: str) -> Optional[Dict[str, Any]]:
    return _query_one(
        f"""
        SELECT forecast_id, metric, currency, target_period, time_grain, unit,
               forecast_value, forecast_method, lookback_months, historical_cutoff,
               source_periods_json, source_values_json, model_version,
               metric_definition_version, status, provenance_json, created_at
        FROM {FORECAST_TABLE}
        WHERE forecast_id = ?;
        """,
        (forecast_id,),
    )


def save_financial_forecast(
    currency: str,
    metric: str,
    forecast_period: str,
    historical_cutoff: str,
    lookback_months: int = 3,
) -> Dict[str, Any]:
    """Calculate and persist a forecast; never reports saved before commit."""
    calculated = forecast_financial_kpi(
        currency=currency,
        metric=metric,
        forecast_period=forecast_period,
        historical_cutoff=historical_cutoff,
        lookback_months=lookback_months,
    )
    if calculated.get("status") != "success":
        return {**calculated, "persisted": False, "message": calculated.get("message", "Forecast could not be calculated.")}

    currency = _validate_currency(calculated["currency"])
    metric = _validate_metric(calculated["metric"])
    forecast_value = float(calculated["forecast_value"])
    if not math.isfinite(forecast_value):
        return {
            **calculated,
            "status": "save_failed",
            "persisted": False,
            "message": "Forecast value is not a finite number and cannot be saved.",
        }
    lookback_months = int(calculated["lookback_months"])
    if not 1 <= lookback_months <= 24:
        return {
            **calculated,
            "status": "save_failed",
            "persisted": False,
            "message": "Forecast lookback configuration is invalid and cannot be saved.",
        }
    record = {
        "forecast_id": str(uuid.uuid4()),
        "metric": metric,
        "currency": currency,
        "target_period": calculated["forecast_period"],
        "time_grain": calculated["grain"],
        "unit": _metric_unit(metric, currency),
        "forecast_value": forecast_value,
        "forecast_method": calculated["method"],
        "lookback_months": lookback_months,
        "historical_cutoff": calculated["historical_cutoff"],
        "source_periods_json": json.dumps(calculated["source_periods"]),
        "source_values_json": json.dumps(calculated["source_values"]),
        "model_version": FORECAST_MODEL_VERSION,
        "metric_definition_version": METRIC_DEFINITION_VERSION,
        "status": "saved",
        "provenance_json": json.dumps({
            "source": "verified_actuals",
            "calculation": calculated["calculation"],
            "forecast_is_not_actual": True,
        }),
    }

    try:
        confirmation = _insert_forecast_record(record)
    except DuplicateForecastError:
        return {
            **calculated,
            "status": "duplicate_id",
            "persisted": False,
            "message": "The forecast identifier already exists; no existing record was overwritten.",
        }
    except Exception:
        return {
            **calculated,
            "status": "save_failed",
            "persisted": False,
            "message": "Forecast calculation succeeded, but persistent storage is unavailable or the forecast schema is not installed.",
        }

    return {
        **calculated,
        "status": "saved",
        "forecast_id": confirmation["forecast_id"],
        "created_at": confirmation["created_at"].isoformat()
        if hasattr(confirmation["created_at"], "isoformat")
        else str(confirmation["created_at"]),
        "model_version": FORECAST_MODEL_VERSION,
        "metric_definition_version": METRIC_DEFINITION_VERSION,
        "unit": record["unit"],
        "persisted": True,
        "message": "Forecast calculated and saved successfully.",
    }


def get_saved_financial_forecast(forecast_id: str) -> Dict[str, Any]:
    try:
        normalized_id = str(uuid.UUID(str(forecast_id)))
    except (ValueError, TypeError, AttributeError):
        return {"status": "invalid_forecast_id", "message": "A valid forecast ID is required."}
    try:
        row = _select_forecast_record(normalized_id)
    except Exception:
        return {"status": "retrieval_failed", "message": "Forecast storage is unavailable or the forecast schema is not installed."}
    if row is None:
        return {"status": "forecast_not_found", "forecast_id": normalized_id, "message": "No saved forecast was found for this ID."}

    result = dict(row)
    result["forecast_id"] = str(result["forecast_id"])
    for field in ("target_period", "historical_cutoff", "created_at"):
        if hasattr(result.get(field), "isoformat"):
            result[field] = result[field].isoformat()
    for field, destination in (("source_periods_json", "source_periods"), ("source_values_json", "source_values"), ("provenance_json", "provenance")):
        try:
            result[destination] = json.loads(result.pop(field))
        except (TypeError, json.JSONDecodeError):
            return {"status": "retrieval_failed", "forecast_id": normalized_id, "message": "Saved forecast metadata is invalid."}
    result["status"] = "success"
    result["persisted"] = True
    result["forecast_value"] = _safe_float(result["forecast_value"])
    return result


def _has_actual_observations(metric: str, currency: str, date_from: str, date_to: str) -> bool:
    """Distinguish a recorded zero from an absent source period."""
    if metric in {"transactions", "active_accounts", "average_transaction_amount"}:
        row = _query_one(
            """
            SELECT COUNT_BIG(*) AS observation_count
            FROM core.vw_transactions
            WHERE currency = ?
              AND transaction_timestamp >= ?
              AND transaction_timestamp < DATEADD(day, 1, ?);
            """,
            (currency, date_from, date_to),
        )
    else:
        row = _query_one(
            """
            SELECT COUNT_BIG(*) AS observation_count
            FROM mart.daily_financial_kpis
            WHERE currency = ?
              AND business_date >= ?
              AND business_date <= ?;
            """,
            (currency, date_from, date_to),
        )
    return bool(row and _safe_int(row.get("observation_count")) > 0)


def compare_saved_forecast_to_actual(forecast_id: str) -> Dict[str, Any]:
    saved = get_saved_financial_forecast(forecast_id)
    if saved.get("status") != "success":
        return {
            "status": saved.get("status", "retrieval_failed"),
            "forecast_id": saved.get("forecast_id"),
            "message": saved.get("message", "Saved forecast could not be retrieved."),
        }

    metric = _validate_metric(saved["metric"])
    currency = _validate_currency(saved["currency"])
    period = _parse_date(saved["target_period"])
    if saved.get("time_grain") != "monthly" or period.day != 1:
        return {"status": "comparison_rejected", "forecast_id": saved["forecast_id"], "message": "Only first-of-month monthly forecasts can be compared."}
    expected_unit = _metric_unit(metric, currency)
    if saved.get("unit") != expected_unit or saved.get("metric_definition_version") != METRIC_DEFINITION_VERSION:
        return {"status": "comparison_rejected", "forecast_id": saved["forecast_id"], "message": "Forecast metric definition or unit does not match the current actual metric."}

    period_start = period.isoformat()
    period_end = _month_end(period).isoformat()
    coverage = get_financial_data_coverage()
    latest_actual = coverage.get("available_data", {}).get("date_to")
    if not latest_actual or latest_actual < period_end:
        return {
            "status": "actual_not_found", "forecast_id": saved["forecast_id"],
            "metric": metric, "currency": currency, "time_grain": saved["time_grain"],
            "target_period": period_start,
            "message": "A complete actual value for the forecast target month is not available.",
        }

    try:
        source_has_observations = _has_actual_observations(metric, currency, period_start, period_end)
    except Exception:
        return {
            "status": "actual_not_found", "forecast_id": saved["forecast_id"],
            "metric": metric, "currency": currency, "time_grain": saved["time_grain"],
            "target_period": period_start,
            "message": "Actual source availability could not be verified for the forecast target month.",
        }
    if not source_has_observations:
        return {
            "status": "actual_not_found", "forecast_id": saved["forecast_id"],
            "metric": metric, "currency": currency, "time_grain": saved["time_grain"],
            "target_period": period_start,
            "message": "No source observations are available for this metric, currency, and target month.",
        }

    actual_result = get_financial_kpis(
        currency=currency, date_from=period_start, date_to=period_end, metric=metric,
    )
    if actual_result.get("status") != "success":
        return {
            "status": "actual_not_found", "forecast_id": saved["forecast_id"],
            "metric": metric, "currency": currency, "time_grain": saved["time_grain"],
            "target_period": period_start,
            "message": "No matching actual value is available for the forecast target month and currency.",
        }
    expected_period = {"date_from": period_start, "date_to": period_end}
    resolved_period = actual_result.get("resolved_period")
    result_filters = actual_result.get("filters", {})
    if resolved_period != expected_period or result_filters.get("currency") != currency:
        return {
            "status": "comparison_rejected", "forecast_id": saved["forecast_id"],
            "message": "Actual currency or resolved period did not exactly match the saved forecast metadata.",
        }
    actual_rows = actual_result.get("results", [])
    matching = [
        row for row in actual_rows
        if row.get("metric") == metric
        and row.get("currency") == currency
        and row.get("period") == expected_period
    ]
    if len(matching) != 1:
        return {"status": "comparison_rejected", "forecast_id": saved["forecast_id"], "message": "Actual metric, currency, or period did not match the saved forecast."}

    actual_value = _safe_float(matching[0]["value"])
    forecast_value = _safe_float(saved["forecast_value"])
    signed_difference = actual_value - forecast_value
    absolute_error = abs(signed_difference)
    percentage_error = None if actual_value == 0 else absolute_error / abs(actual_value) * 100
    return {
        "status": "comparison_success",
        "forecast_id": saved["forecast_id"],
        "metric": metric,
        "currency": currency,
        "unit": expected_unit,
        "time_grain": saved["time_grain"],
        "target_period": period_start,
        "historical_cutoff": saved["historical_cutoff"],
        "forecast_value": forecast_value,
        "actual_value": actual_value,
        "signed_difference": signed_difference,
        "absolute_error": absolute_error,
        "percentage_error": percentage_error,
        "percentage_error_status": "unavailable_actual_is_zero" if actual_value == 0 else "available",
        "message": "Percentage error is unavailable because actual is zero." if actual_value == 0 else "Forecast compared with the matching actual period.",
    }


# ============================================================
# Tool 7: Financial ratios
# ============================================================


def analyze_financial_ratios(
    currency: str,
    date_from: str,
    date_to: str,
) -> Dict[str, Any]:
    """
    Calculate derived financial ratios using the same authoritative
    monetary KPI source as get_financial_kpis.

    Monetary flows and status counts come from mart.daily_financial_kpis
    so compound analysis cannot silently mix transaction-level and mart
    accounting scopes. Transaction count / active account count remain
    sourced from core.vw_transactions where required.
    """

    currency = _validate_currency(currency)
    _parse_date(date_from)
    _parse_date(date_to)
    if date_from > date_to:
        raise ValueError("date_from must be <= date_to")

    resolved_from, resolved_to, coverage, has_data_boundary = _resolve_actual_period(
        date_from, date_to
    )
    requested_period = {"date_from": date_from, "date_to": date_to}

    if not has_data_boundary or resolved_from > resolved_to:
        return {
            "status": "no_data",
            "analysis_type": "financial_ratios",
            "currency": currency,
            "requested_period": requested_period,
            "period": requested_period,
            "available_data": coverage.get("available_data"),
            "message": "The requested period is outside the available actual data range.",
        }

    mart_row = _query_one(
        """
        SELECT
            COALESCE(SUM(total_inflows), 0) AS total_inflows,
            COALESCE(SUM(total_outflows), 0) AS total_outflows,
            COALESCE(SUM(net_cash_flow), 0) AS net_cash_flow,
            COALESCE(SUM(fees), 0) AS fees,
            COALESCE(SUM(refunds), 0) AS refunds,
            COALESCE(SUM(completed_transactions), 0) AS completed_transactions,
            COALESCE(SUM(pending_transactions), 0) AS pending_transactions,
            COALESCE(SUM(failed_transactions), 0) AS failed_transactions,
            COALESCE(SUM(reversed_transactions), 0) AS reversed_transactions
        FROM mart.daily_financial_kpis
        WHERE currency = ?
          AND business_date >= ?
          AND business_date <= ?;
        """,
        (currency, resolved_from, resolved_to),
    )

    tx_row = _query_one(
        """
        SELECT
            COUNT_BIG(*) AS total_transactions
        FROM core.vw_transactions
        WHERE currency = ?
          AND transaction_timestamp >= ?
          AND transaction_timestamp < DATEADD(day, 1, ?);
        """,
        (currency, resolved_from, resolved_to),
    )

    total_transactions = _safe_int(tx_row.get("total_transactions")) if tx_row else 0

    if not mart_row or total_transactions == 0:
        return {
            "status": "no_data",
            "analysis_type": "financial_ratios",
            "currency": currency,
            "requested_period": requested_period,
            "period": {"date_from": resolved_from, "date_to": resolved_to},
            "available_data": coverage.get("available_data"),
            "message": "No financial records were found for the requested period and currency.",
        }

    total_inflows = _safe_float(mart_row.get("total_inflows"))
    total_outflows = _safe_float(mart_row.get("total_outflows"))
    net_cash_flow = _safe_float(mart_row.get("net_cash_flow"))
    fees = _safe_float(mart_row.get("fees"))
    refunds = _safe_float(mart_row.get("refunds"))
    completed_transactions = _safe_int(mart_row.get("completed_transactions"))
    pending_transactions = _safe_int(mart_row.get("pending_transactions"))
    failed_transactions = _safe_int(mart_row.get("failed_transactions"))
    reversed_transactions = _safe_int(mart_row.get("reversed_transactions"))

    calculated_net_from_flows = total_inflows - total_outflows
    reconciliation_gap = calculated_net_from_flows - net_cash_flow
    reconciliation_status = (
        "reconciled"
        if math.isclose(
            calculated_net_from_flows,
            net_cash_flow,
            abs_tol=0.01,
            rel_tol=1e-9,
        )
        else "not_reconciled"
    )

    return {
        "status": "success",
        "analysis_type": "financial_ratios",
        "currency": currency,
        "requested_period": requested_period,
        "period": {"date_from": resolved_from, "date_to": resolved_to},
        "available_data": coverage.get("available_data"),
        "inputs": {
            "total_inflows": total_inflows,
            "total_outflows": total_outflows,
            "net_cash_flow": net_cash_flow,
            "fees": fees,
            "refunds": refunds,
            "total_transactions": total_transactions,
            "completed_transactions": completed_transactions,
            "pending_transactions": pending_transactions,
            "failed_transactions": failed_transactions,
            "reversed_transactions": reversed_transactions,
        },
        "ratios": {
            "inflow_outflow_ratio": _round_or_none(
                _safe_ratio(total_inflows, total_outflows), 6
            ),
            "net_cash_flow_margin_percentage": _round_or_none(
                _safe_ratio(net_cash_flow, total_inflows) * 100
                if total_inflows else None,
                4,
            ),
            "refund_rate_percentage": _round_or_none(
                _safe_ratio(refunds, total_inflows) * 100
                if total_inflows else None,
                4,
            ),
            "fee_rate_percentage": _round_or_none(
                _safe_ratio(fees, total_outflows) * 100
                if total_outflows else None,
                4,
            ),
            "transaction_success_rate_percentage": _round_or_none(
                _safe_ratio(completed_transactions, total_transactions) * 100
                if total_transactions else None,
                4,
            ),
            "failed_transaction_rate_percentage": _round_or_none(
                _safe_ratio(failed_transactions, total_transactions) * 100
                if total_transactions else None,
                4,
            ),
            "pending_transaction_rate_percentage": _round_or_none(
                _safe_ratio(pending_transactions, total_transactions) * 100
                if total_transactions else None,
                4,
            ),
            "reversed_transaction_rate_percentage": _round_or_none(
                _safe_ratio(reversed_transactions, total_transactions) * 100
                if total_transactions else None,
                4,
            ),
        },
        "definitions": {
            "inflow_outflow_ratio": "Total inflows / Total outflows",
            "net_cash_flow_margin_percentage": "Authoritative net cash flow / Total inflows × 100",
            "refund_rate_percentage": "Refunds / Total inflows × 100",
            "fee_rate_percentage": "Fees / Total outflows × 100",
            "transaction_success_rate_percentage": "Completed transactions / Total transactions × 100",
            "failed_transaction_rate_percentage": "Failed transactions / Total transactions × 100",
            "pending_transaction_rate_percentage": "Pending transactions / Total transactions × 100",
            "reversed_transaction_rate_percentage": "Reversed transactions / Total transactions × 100",
        },
        "data_quality": {
            "actual_data": True,
            "read_only": True,
            "latest_actual_date": coverage.get("latest_actual_date"),
            "partial_period": resolved_to != date_to or resolved_from != date_from,
            "data_scope": {
                "monetary_metrics_source": "AI_Finance.mart.daily_financial_kpis",
                "status_counts_source": "AI_Finance.mart.daily_financial_kpis",
                "transaction_count_source": "AI_Finance.core.vw_transactions",
            },
            "flow_reconciliation": {
                "calculated_net_from_flows": calculated_net_from_flows,
                "reported_net_cash_flow": net_cash_flow,
                "gap": reconciliation_gap,
                "status": reconciliation_status,
            },
        },
        "limitations": [
            "These are transaction-model ratios, not full accounting ratios.",
            "Balance-sheet ratios such as Current Ratio or Debt-to-Equity require additional financial statement data.",
            "Margin-like metrics are descriptive indicators of the supplied transaction flows and should not be treated as statutory accounting margins.",
        ],
    }


# ============================================================
# Registry
# ============================================================

TOOL_FUNCTIONS = {
    "get_financial_kpis": get_financial_kpis,
    "compare_financial_periods": compare_financial_periods,
    "analyze_financial_trend": analyze_financial_trend,
    "detect_financial_anomalies": detect_financial_anomalies,
    "analyze_cash_flow_drivers": analyze_cash_flow_drivers,
    "forecast_financial_kpi": forecast_financial_kpi,
    "save_financial_forecast": save_financial_forecast,
    "get_saved_financial_forecast": get_saved_financial_forecast,
    "compare_saved_forecast_to_actual": compare_saved_forecast_to_actual,
    "analyze_financial_ratios": analyze_financial_ratios,
}


def list_enabled_tool_names() -> List[str]:
    return list(TOOL_FUNCTIONS.keys())
