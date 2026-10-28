from __future__ import annotations

import contextlib
import inspect
import io
import logging
import threading
import time
import traceback
import uuid
from datetime import date
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

# -----------------------------------------------------------------------------
# Project paths
# -----------------------------------------------------------------------------

CURRENT_DIR = Path(__file__).resolve().parent
PHASE_DIR = CURRENT_DIR.parent
PROJECT_ROOT = PHASE_DIR.parent

if str(PHASE_DIR) not in __import__("sys").path:
    __import__("sys").path.insert(0, str(PHASE_DIR))

from agent.finance_agent import FinanceAgent, make_json_safe  # noqa: E402
from tools.financial_tools import (  # noqa: E402
    ALLOWED_CURRENCIES,
    analyze_cash_flow_drivers,
    analyze_financial_ratios,
    analyze_financial_trend,
    compare_financial_periods,
    detect_financial_anomalies,
    forecast_financial_kpi,
    get_financial_data_coverage,
    get_financial_kpis,
)

logger = logging.getLogger(__name__)


def _log_chat_failure(request_id: str, exc: Exception) -> None:
    """Log exception type and traceback frames without exception text or locals."""
    safe_traceback = "".join(
        f'  File "{frame.filename}", line {frame.lineno}, in {frame.name}\n'
        for frame in traceback.extract_tb(exc.__traceback__)
    )
    logger.error(
        "Copilot request failed request_id=%s exception_type=%s\n%s",
        request_id,
        type(exc).__name__,
        safe_traceback,
    )


def _chat_error_message(lang: str) -> str:
    return (
        "حدث خطأ أثناء تحليل السؤال. تم تسجيل التفاصيل في سجل التنفيذ. "
        "يمكنك إعادة المحاولة أو صياغة السؤال مع ذكر العملة والفترة."
        if lang == "ar"
        else
        "The analysis failed. Technical details were captured in the execution log. "
        "Please retry or specify the currency and period explicitly."
    )


# -----------------------------------------------------------------------------
# App setup
# -----------------------------------------------------------------------------

app = FastAPI(
    title="AI Finance Analyst",
    version="2.2.0",
    description="Professional executive dashboard and AI copilot for the verified financial analytics engine.",
)

app.mount(
    "/static",
    StaticFiles(directory=str(CURRENT_DIR / "static")),
    name="static",
)

templates = Jinja2Templates(directory=str(CURRENT_DIR / "templates"))


@app.middleware("http")
async def chat_request_diagnostics(request: Request, call_next):
    if request.url.path != "/api/chat":
        return await call_next(request)

    request_id = uuid.uuid4().hex
    request.state.chat_request_id = request_id
    try:
        result = await call_next(request)
    except Exception as exc:
        _log_chat_failure(request_id, exc)
        lang = getattr(request.state, "chat_lang", "en")
        result = JSONResponse(
            {
                "ok": False,
                "error": _chat_error_message(lang),
                "technical_error": type(exc).__name__,
                "request_id": request_id,
            },
            status_code=500,
            headers={"X-Request-ID": request_id},
        )

    result.headers["X-Request-ID"] = request_id
    return result


# -----------------------------------------------------------------------------
# Session store
# -----------------------------------------------------------------------------

_SESSION_TTL_SECONDS = 8 * 60 * 60
_sessions: dict[str, dict[str, Any]] = {}
_sessions_lock = threading.RLock()


class SessionState:
    def __init__(self) -> None:
        self.agent = FinanceAgent()
        self.created_at = time.time()
        self.last_seen = time.time()
        self.ui_messages: list[dict[str, Any]] = []
        self.lock = threading.RLock()
        self.dashboard_filter = {
            "currency": "USD",
            "month": None,
            "trend_months": 6,
        }
        self.dashboard_payload: dict[str, Any] = {}
        self.execution_log: str = ""
        self.lang: str = "en"

    def touch(self) -> None:
        self.last_seen = time.time()


def _cleanup_sessions() -> None:
    now = time.time()
    expired: list[str] = []
    for session_id, item in list(_sessions.items()):
        state: SessionState = item["state"]
        if now - state.last_seen > _SESSION_TTL_SECONDS:
            expired.append(session_id)
    for session_id in expired:
        _sessions.pop(session_id, None)


def _get_state(request: Request, response: Response) -> tuple[str, SessionState]:
    with _sessions_lock:
        _cleanup_sessions()
        session_id = request.cookies.get("ai_finance_session")
        if not session_id or session_id not in _sessions:
            session_id = uuid.uuid4().hex
            _sessions[session_id] = {"state": SessionState()}
            response.set_cookie(
                key="ai_finance_session",
                value=session_id,
                httponly=True,
                samesite="lax",
                max_age=_SESSION_TTL_SECONDS,
            )
        state: SessionState = _sessions[session_id]["state"]
        state.touch()
        return session_id, state


# -----------------------------------------------------------------------------
# Date helpers
# -----------------------------------------------------------------------------


def _month_bounds(month_text: str) -> tuple[str, str]:
    year, month = map(int, month_text.split("-"))
    first = date(year, month, 1)
    if month == 12:
        next_month = date(year + 1, 1, 1)
    else:
        next_month = date(year, month + 1, 1)
    last = next_month.fromordinal(next_month.toordinal() - 1)
    return first.isoformat(), last.isoformat()


def _add_months(month_text: str, offset: int) -> str:
    year, month = map(int, month_text.split("-"))
    index = year * 12 + (month - 1) + offset
    new_year, month0 = divmod(index, 12)
    return f"{new_year:04d}-{month0 + 1:02d}"


def _latest_actual_month(coverage: dict[str, Any]) -> str | None:
    latest = coverage.get("available_data", {}).get("date_to")
    if not latest:
        return None
    return latest[:7]


def _normalize_dashboard_month(requested: str | None, coverage: dict[str, Any]) -> str:
    latest = _latest_actual_month(coverage)
    if latest is None:
        raise ValueError("No actual financial data is available.")
    if requested:
        candidate = requested.strip()
        year, month = map(int, candidate.split("-"))
        if month < 1 or month > 12 or year < 2000:
            raise ValueError("month must use YYYY-MM format.")
        if candidate > latest:
            raise ValueError(
                f"Selected month {candidate} is beyond the latest actual month {latest}."
            )
        return candidate
    return latest


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


# -----------------------------------------------------------------------------
# Language handling (UI language -> Copilot answer language)
# -----------------------------------------------------------------------------

SUPPORTED_LANGS = {"en", "ar"}

_LANG_DIRECTIVES = {
    "en": "",
    "ar": (
        "\n\n[Response language: Arabic. Write the entire answer in clear, professional Arabic "
        "(Modern Standard Arabic, easy to read). Keep every number, currency code, date and metric "
        "value exactly as computed by the tools. Do not translate, round or alter figures.]"
    ),
}


def _normalize_lang(value: Any) -> str:
    lang = str(value or "en").strip().lower()[:2]
    return lang if lang in SUPPORTED_LANGS else "en"


def _agent_accepts(agent: Any, names: tuple[str, ...]) -> str | None:
    """Return the first keyword name FinanceAgent.ask() natively supports, if any."""
    try:
        params = inspect.signature(agent.ask).parameters
    except (TypeError, ValueError):
        return None
    for name in names:
        if name in params:
            return name
    return None


def _ask_agent(agent: Any, question: str, lang: str) -> Any:
    """Ask the FinanceAgent with an explicit response language.

    Newer FinanceAgent builds accept ``language`` directly. Older builds still
    receive a bilingual response directive as a safe fallback.
    """
    kwarg = _agent_accepts(agent, ("language", "lang", "response_language"))
    if kwarg:
        return agent.ask(question, **{kwarg: lang})
    return agent.ask(question + _LANG_DIRECTIVES.get(lang, ""))


# -----------------------------------------------------------------------------
# Dashboard builder
# -----------------------------------------------------------------------------


def _build_executive_dashboard(
    currency: str,
    selected_month: str | None = None,
    trend_months: int = 6,
) -> dict[str, Any]:
    currency = currency.strip().upper()
    if currency not in ALLOWED_CURRENCIES:
        raise ValueError(f"Unsupported currency: {currency}")

    coverage = get_financial_data_coverage()
    selected_month = _normalize_dashboard_month(selected_month, coverage)
    trend_months = max(3, min(int(trend_months), 12))

    selected_from, selected_to = _month_bounds(selected_month)
    previous_month = _add_months(selected_month, -1)
    previous_from, previous_to = _month_bounds(previous_month)
    trend_from = _add_months(selected_month, -(trend_months - 1))
    trend_from_date, _ = _month_bounds(trend_from)

    # Latest-month KPI snapshot.
    kpi = get_financial_kpis(
        currency=currency,
        date_from=selected_from,
        date_to=selected_to,
    )

    if kpi.get("status") != "success":
        raise ValueError(kpi.get("message", "No KPI data available."))

    kpi_map = {
        item.get("metric"): item.get("value")
        for item in kpi.get("results", [])
        if isinstance(item, dict) and item.get("metric")
    }

    ratios = analyze_financial_ratios(
        currency=currency,
        date_from=selected_from,
        date_to=selected_to,
    )
    if ratios.get("status") != "success":
        raise ValueError(ratios.get("message", "No ratio data available."))

    comparison = compare_financial_periods(
        currency=currency,
        metric="net_cash_flow",
        period_1_from=previous_from,
        period_1_to=previous_to,
        period_2_from=selected_from,
        period_2_to=selected_to,
    )

    drivers = analyze_cash_flow_drivers(
        currency=currency,
        period_1_from=previous_from,
        period_1_to=previous_to,
        period_2_from=selected_from,
        period_2_to=selected_to,
    )

    trend = analyze_financial_trend(
        currency=currency,
        metric="net_cash_flow",
        date_from=trend_from_date,
        date_to=selected_to,
    )

    anomalies = detect_financial_anomalies(
        currency=currency,
        date_from=selected_from,
        date_to=selected_to,
        threshold=3.5,
    )

    forecast_month = _add_months(selected_month, 1)
    forecast = forecast_financial_kpi(
        currency=currency,
        metric="net_cash_flow",
        forecast_period=f"{forecast_month}-01",
        historical_cutoff=selected_to,
        lookback_months=3,
    )

    return make_json_safe(
        {
            "status": "success",
            "dashboard_version": "2.2.0",
            "filters": {
                "currency": currency,
                "month": selected_month,
                "trend_months": trend_months,
            },
            "available_data": coverage.get("available_data", {}),
            "kpis": kpi_map,
            "ratio_inputs": ratios.get("inputs", {}),
            "ratios": ratios.get("ratios", {}),
            "flow_reconciliation": ratios.get("flow_reconciliation"),
            "comparison": {
                "metric": comparison.get("comparison_metric"),
                "period_1": comparison.get("period_1"),
                "period_2": comparison.get("period_2"),
                "absolute_change": comparison.get("absolute_change"),
                "percentage_change": comparison.get("percentage_change"),
                "direction": comparison.get("direction"),
            },
            "drivers": drivers.get("top_drivers_by_currency", {}).get(
                currency,
                drivers.get("drivers", [])[:8],
            ),
            "driver_reconciliation": drivers.get("reconciliation"),
            "trend": trend.get("results", []),
            "anomalies": anomalies.get("anomalies", []),
            "anomaly_count": anomalies.get("anomaly_count", 0),
            "anomaly_threshold": anomalies.get("threshold", 3.5),
            "anomaly_observation_count": anomalies.get("currency_statistics", {}).get(
                currency,
                {}
            ).get("observation_count", 0),
            "forecast": {
                "metric": forecast.get("metric"),
                "currency": forecast.get("currency"),
                "forecast_period": forecast.get("forecast_period"),
                "historical_cutoff": forecast.get("historical_cutoff"),
                "forecast_value": forecast.get("forecast_value"),
                "method": forecast.get("method"),
                "lookback_months": forecast.get("lookback_months"),
                "historical_periods": forecast.get("historical_periods", []),
                "source_periods": forecast.get(
                    "source_periods",
                    [
                        item.get("period")
                        for item in forecast.get("historical_periods", [])
                        if isinstance(item, dict) and item.get("period")
                    ],
                ),
                "last_actual_period": forecast.get("last_actual_period"),
                "status": forecast.get("status"),
            },
        }
    )


# -----------------------------------------------------------------------------
# Existing conversational snapshot helpers
# -----------------------------------------------------------------------------


def _session_snapshot(state: SessionState) -> dict[str, Any]:
    agent = state.agent
    available = (
        agent.data_boundary.get("available_data", {})
        if isinstance(agent.data_boundary, dict)
        else {}
    )
    return make_json_safe(
        {
            "analysis_mode": getattr(agent, "last_analysis_mode", "single_tool"),
            "turn": getattr(agent, "session_turn_id", 0),
            "model": getattr(agent, "model_name", "unknown"),
            "provider": "google",
            "enabled_tools": getattr(agent, "enabled_tools", []),
            "last_question": getattr(agent, "last_question", None),
            "data_boundary": available,
            "health_findings": getattr(agent, "last_health_findings", {}),
            "suggestions": getattr(agent, "last_suggested_questions", []),
            "dashboard": state.dashboard_payload,
            "history": getattr(agent, "session_history", []),
            "dashboard_filter": state.dashboard_filter,
            "lang": getattr(state, "lang", "en"),
            "response_language": getattr(agent, "response_language", getattr(state, "lang", "en")),
            "bilingual_engine": True,
        }
    )


def _rendered_history(state: SessionState) -> list[dict[str, Any]]:
    return make_json_safe(state.ui_messages)


# -----------------------------------------------------------------------------
# Routes
# -----------------------------------------------------------------------------


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    response = Response()
    session_id, state = _get_state(request, response)
    if not state.dashboard_payload:
        try:
            state.dashboard_payload = _build_executive_dashboard("USD")
            state.dashboard_filter = state.dashboard_payload["filters"]
        except Exception as exc:
            logger.error("Dashboard initialization failed: %s", type(exc).__name__)
            state.dashboard_payload = {}
    page = templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"session_id": session_id},
    )
    cookie = response.headers.get("set-cookie")
    if cookie:
        page.headers["set-cookie"] = cookie
    return page


@app.get("/api/session")
async def session_info(request: Request) -> JSONResponse:
    response = Response()
    session_id, state = _get_state(request, response)
    if not state.dashboard_payload:
        try:
            state.dashboard_payload = _build_executive_dashboard(
                state.dashboard_filter.get("currency", "USD"),
                state.dashboard_filter.get("month"),
                state.dashboard_filter.get("trend_months", 6),
            )
            state.dashboard_filter = state.dashboard_payload["filters"]
        except Exception as exc:
            logger.error("Dashboard session initialization failed: %s", type(exc).__name__)
            result = JSONResponse(
                {
                    "ok": False,
                    "error": "Dashboard initialization failed. Please retry or check server logs.",
                },
                status_code=503,
            )
            cookie = response.headers.get("set-cookie")
            if cookie:
                result.headers["set-cookie"] = cookie
            return result
    result = JSONResponse(
        {
            "session_id": session_id,
            "messages": _rendered_history(state),
            **_session_snapshot(state),
        }
    )
    cookie = response.headers.get("set-cookie")
    if cookie:
        result.headers["set-cookie"] = cookie
    return result


@app.get("/api/dashboard")
async def dashboard(
    request: Request,
    currency: str = "USD",
    month: str | None = None,
    trend_months: int = 6,
) -> JSONResponse:
    response = Response()
    _, state = _get_state(request, response)
    try:
        with state.lock:
            payload = _build_executive_dashboard(currency, month, trend_months)
            state.dashboard_payload = payload
            state.dashboard_filter = payload["filters"]
        result = JSONResponse(
            {
                "ok": True,
                "dashboard": payload,
                "session": _session_snapshot(state),
            }
        )
    except Exception as exc:
        logger.error("Dashboard API request failed: %s", type(exc).__name__)
        result = JSONResponse(
            {
                "ok": False,
                "error": "Dashboard request could not be completed. Check filters or retry.",
            },
            status_code=400 if isinstance(exc, ValueError) else 503,
        )
    cookie = response.headers.get("set-cookie")
    if cookie:
        result.headers["set-cookie"] = cookie
    return result


@app.post("/api/chat")
async def chat(request: Request) -> JSONResponse:
    response = Response()
    request_id = getattr(getattr(request, "state", None), "chat_request_id", None) or uuid.uuid4().hex
    response.headers["X-Request-ID"] = request_id
    _, state = _get_state(request, response)
    body = await request.json()
    question = str(body.get("question", "")).strip()
    lang = _normalize_lang(body.get("lang"))
    request.state.chat_lang = lang
    state.lang = lang

    if not question:
        result = JSONResponse(
            {
                "ok": False,
                "error": "الرجاء إدخال سؤال مالي." if lang == "ar" else "Please enter a financial question.",
            },
            status_code=400,
        )
        result.headers["X-Request-ID"] = request_id
        cookie = response.headers.get("set-cookie")
        if cookie:
            result.headers["set-cookie"] = cookie
        return result

    state.ui_messages.append(
        {
            "role": "user",
            "content": question,
            "ts": time.time(),
        }
    )

    stdout_buffer = io.StringIO()
    error_message = None
    answer = None

    try:
        with state.lock:
            with contextlib.redirect_stdout(stdout_buffer):
                answer = _ask_agent(state.agent, question, lang)
    except Exception as exc:  # pragma: no cover - runtime integration path
        _log_chat_failure(request_id, exc)
        error_message = type(exc).__name__

    captured_logs = stdout_buffer.getvalue()
    state.execution_log = captured_logs

    if error_message:
        user_error = _chat_error_message(lang)
        state.ui_messages.append(
            {
                "role": "error",
                "content": user_error,
                "ts": time.time(),
            }
        )
        result = JSONResponse(
            {
                "ok": False,
                "error": user_error,
                "technical_error": error_message,
                "request_id": request_id,
                "logs": captured_logs,
                "session": _session_snapshot(state),
                "messages": _rendered_history(state),
            },
            status_code=500,
        )
    else:
        # Refresh the executive dashboard to reflect the newest verified context.
        try:
            preferred_currency = state.dashboard_filter.get("currency", "USD")
            question_currency = getattr(state.agent, "_extract_currency", lambda _: None)(question)
            if question_currency:
                preferred_currency = question_currency
            preferred_month = state.dashboard_filter.get("month")
            periods = getattr(state.agent, "_extract_month_periods", lambda _: [])(question)
            if periods:
                preferred_month = periods[-1]["date_from"][:7]
            state.dashboard_payload = _build_executive_dashboard(
                preferred_currency,
                preferred_month,
                state.dashboard_filter.get("trend_months", 6),
            )
            state.dashboard_filter = state.dashboard_payload["filters"]
        except Exception as exc:
            logger.error("Dashboard refresh after Copilot request failed: %s", type(exc).__name__)

        chart_data = getattr(state.agent, "last_chart_data", None)

        state.ui_messages.append(
            {
                "role": "assistant",
                "content": answer or "",
                "ts": time.time(),
                "analysis_mode": getattr(state.agent, "last_analysis_mode", "single_tool"),
                "chart": chart_data,
            }
        )
        result = JSONResponse(
            {
                "ok": True,
                "answer": answer,
                "chart": chart_data,
                "logs": captured_logs,
                "session": _session_snapshot(state),
                "messages": _rendered_history(state),
            }
        )

    cookie = response.headers.get("set-cookie")
    if cookie:
        result.headers["set-cookie"] = cookie
    result.headers["X-Request-ID"] = request_id
    return result


@app.post("/api/reset")
async def reset(request: Request) -> JSONResponse:
    response = Response()
    session_id, state = _get_state(request, response)
    state.agent.clear_conversation_context()
    state.ui_messages.clear()
    state.execution_log = ""
    state.agent.data_boundary = state.agent._get_data_boundary()
    try:
        state.dashboard_payload = _build_executive_dashboard(
            state.dashboard_filter.get("currency", "USD"),
            state.dashboard_filter.get("month"),
            state.dashboard_filter.get("trend_months", 6),
        )
    except Exception as exc:
        logger.error("Dashboard refresh after reset failed: %s", type(exc).__name__)
        state.dashboard_payload = {}
        result = JSONResponse(
            {
                "ok": False,
                "error": "Dashboard initialization failed. Please retry or check server logs.",
            },
            status_code=503,
        )
        cookie = response.headers.get("set-cookie")
        if cookie:
            result.headers["set-cookie"] = cookie
        return result
    result = JSONResponse(
        {
            "ok": True,
            "session_id": session_id,
            "messages": [],
            "session": _session_snapshot(state),
        }
    )
    cookie = response.headers.get("set-cookie")
    if cookie:
        result.headers["set-cookie"] = cookie
    return result


@app.get("/api/health")
async def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "service": "AI Finance Analyst Professional Dashboard",
        "version": "2.1.0",
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "web_app:app",
        host="127.0.0.1",
        port=8501,
        reload=False,
    )
