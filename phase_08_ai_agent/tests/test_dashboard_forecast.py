import asyncio
import json
import sys
import threading
import unittest
import types
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

PHASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PHASE_DIR))

# The local test environment does not install the web server dependencies.
# Minimal interfaces allow importing the route module without starting a server.
try:
    import fastapi  # noqa: F401
except ModuleNotFoundError:
    fastapi_stub = types.ModuleType("fastapi")

    class _FastAPI:
        def __init__(self, **_kwargs):
            pass

        def mount(self, *_args, **_kwargs):
            pass

        def get(self, *_args, **_kwargs):
            return lambda function: function

        def post(self, *_args, **_kwargs):
            return lambda function: function

        def middleware(self, *_args, **_kwargs):
            return lambda function: function

    class _Request:
        cookies = {}

    class _Response:
        def __init__(self, content=None, status_code=200, **_kwargs):
            self.headers = {}
            self.status_code = status_code
            self.body = json.dumps(content, separators=(",", ":")).encode() if content is not None else b""

        def set_cookie(self, **_kwargs):
            pass

    fastapi_stub.FastAPI = _FastAPI
    fastapi_stub.Request = _Request
    fastapi_stub.Response = _Response
    sys.modules["fastapi"] = fastapi_stub

    responses_stub = types.ModuleType("fastapi.responses")
    responses_stub.HTMLResponse = _Response
    responses_stub.JSONResponse = _Response
    sys.modules["fastapi.responses"] = responses_stub

    staticfiles_stub = types.ModuleType("fastapi.staticfiles")
    staticfiles_stub.StaticFiles = lambda **_kwargs: object()
    sys.modules["fastapi.staticfiles"] = staticfiles_stub

    templating_stub = types.ModuleType("fastapi.templating")
    templating_stub.Jinja2Templates = lambda **_kwargs: SimpleNamespace(TemplateResponse=lambda **_kw: _Response())
    sys.modules["fastapi.templating"] = templating_stub

try:
    import yaml  # noqa: F401
except ModuleNotFoundError:
    yaml_stub = types.ModuleType("yaml")
    yaml_stub.safe_load = lambda *_args, **_kwargs: {}
    sys.modules["yaml"] = yaml_stub

try:
    from dotenv import load_dotenv  # noqa: F401
except ModuleNotFoundError:
    dotenv_stub = types.ModuleType("dotenv")
    dotenv_stub.load_dotenv = lambda *_args, **_kwargs: False
    sys.modules["dotenv"] = dotenv_stub

try:
    from google import genai  # noqa: F401
    from google.genai import types as google_types  # noqa: F401
except ModuleNotFoundError:
    google_stub = types.ModuleType("google")
    genai_stub = types.ModuleType("google.genai")
    google_types_stub = types.ModuleType("google.genai.types")

    class _FunctionDeclaration:
        def __init__(self, name, description, parameters_json_schema):
            self.name = name
            self.description = description
            self.parameters_json_schema = parameters_json_schema

    google_types_stub.FunctionDeclaration = _FunctionDeclaration
    genai_stub.Client = object
    genai_stub.types = google_types_stub
    google_stub.genai = genai_stub
    sys.modules.update({
        "google": google_stub,
        "google.genai": genai_stub,
        "google.genai.types": google_types_stub,
    })

from web_app import web_app
from agent.finance_agent import FinanceAgent


class DashboardForecastTests(unittest.TestCase):
    def _mock_dashboard_tools(self):
        return (
            patch.object(
                web_app,
                "get_financial_data_coverage",
                return_value={
                    "status": "success",
                    "available_data": {"date_from": "2026-01-01", "date_to": "2026-07-31"},
                },
            ),
            patch.object(
                web_app,
                "get_financial_kpis",
                return_value={"status": "success", "results": [{"metric": "net_cash_flow", "value": 10}]},
            ),
            patch.object(
                web_app,
                "analyze_financial_ratios",
                return_value={"status": "success", "inputs": {}, "ratios": {}},
            ),
            patch.object(web_app, "compare_financial_periods", return_value={}),
            patch.object(
                web_app,
                "analyze_cash_flow_drivers",
                return_value={"top_drivers_by_currency": {}, "drivers": []},
            ),
            patch.object(web_app, "analyze_financial_trend", return_value={"status": "success", "results": []}),
            patch.object(
                web_app,
                "detect_financial_anomalies",
                return_value={"anomalies": [], "anomaly_count": 0, "currency_statistics": {}},
            ),
        )

    def test_dashboard_forecast_uses_selected_month_end_as_cutoff_and_returns_source_metadata(self):
        patches = self._mock_dashboard_tools()
        started = [item.start() for item in patches]
        self.addCleanup(lambda: [item.stop() for item in started])
        forecast = patch.object(
            web_app,
            "forecast_financial_kpi",
            return_value={
                "status": "success",
                "currency": "USD",
                "metric": "net_cash_flow",
                "forecast_period": "2026-07-01",
                "historical_cutoff": "2026-06-30",
                "forecast_value": 20,
                "method": "Trailing Moving Average",
                "lookback_months": 3,
                "historical_periods": [{"period": "2026-04"}, {"period": "2026-05"}, {"period": "2026-06"}],
                "source_periods": ["2026-04", "2026-05", "2026-06"],
                "last_actual_period": "2026-06-01",
            },
        )
        forecast_mock = forecast.start()
        self.addCleanup(forecast.stop)

        payload = web_app._build_executive_dashboard("USD", "2026-06")

        forecast_mock.assert_called_once_with(
            currency="USD",
            metric="net_cash_flow",
            forecast_period="2026-07-01",
            historical_cutoff="2026-06-30",
            lookback_months=3,
        )
        self.assertEqual(payload["forecast"]["historical_cutoff"], "2026-06-30")
        self.assertEqual(payload["forecast"]["source_periods"], ["2026-04", "2026-05", "2026-06"])


class DashboardInitializationErrorTests(unittest.TestCase):
    def setUp(self):
        self.state = SimpleNamespace(
            lock=threading.RLock(),
            dashboard_payload={},
            dashboard_filter={"currency": "USD", "month": None, "trend_months": 6},
        )
        self.state_patch = patch.object(web_app, "_get_state", return_value=("test-session", self.state))
        self.state_patch.start()
        self.addCleanup(self.state_patch.stop)

    def test_dashboard_api_logs_failure_and_returns_sanitized_service_error(self):
        builder = patch.object(web_app, "_build_executive_dashboard", side_effect=RuntimeError("secret-token-123"))
        builder.start()
        self.addCleanup(builder.stop)

        with self.assertLogs(web_app.logger, level="ERROR") as captured:
            result = asyncio.run(web_app.dashboard(None))

        self.assertEqual(result.status_code, 503)
        self.assertEqual(
            result.body,
            b'{"ok":false,"error":"Dashboard request could not be completed. Check filters or retry."}',
        )
        self.assertNotIn("secret-token-123", result.body.decode())
        self.assertIn("RuntimeError", " ".join(captured.output))


    def test_session_initialization_failure_returns_sanitized_api_error(self):
        builder = patch.object(web_app, "_build_executive_dashboard", side_effect=RuntimeError("connection-string-secret"))
        builder.start()
        self.addCleanup(builder.stop)

        with self.assertLogs(web_app.logger, level="ERROR") as captured:
            result = asyncio.run(web_app.session_info(None))

        self.assertEqual(result.status_code, 503)
        self.assertIn(b"Dashboard initialization failed", result.body)
        self.assertNotIn(b"connection-string-secret", result.body)
        self.assertIn("RuntimeError", " ".join(captured.output))


class ChatFailureDiagnosticsTests(unittest.TestCase):
    def _successful_chat_response(self, chart_data):
        state = SimpleNamespace(
            agent=SimpleNamespace(last_chart_data=chart_data, last_analysis_mode="single_tool"),
            ui_messages=[],
            lock=threading.RLock(),
            lang="en",
            execution_log="",
            dashboard_filter={"currency": "USD", "month": None, "trend_months": 6},
            dashboard_payload={"filters": {"currency": "USD", "month": None, "trend_months": 6}},
        )

        async def request_json():
            return {"question": "Show the trend in a chart, USD", "lang": "en"}

        request = SimpleNamespace(
            state=SimpleNamespace(chat_request_id="chart-response-contract"),
            json=request_json,
        )

        with patch.object(web_app, "_get_state", return_value=("test-session", state)), \
             patch.object(web_app, "_ask_agent", return_value="The monthly trend changes over time."), \
             patch.object(web_app, "_session_snapshot", return_value={}), \
             patch.object(web_app, "_rendered_history", side_effect=lambda current: current.ui_messages), \
             patch.object(web_app, "_build_executive_dashboard", return_value={"filters": state.dashboard_filter}):
            response = asyncio.run(web_app.chat(request))
        return response, state

    def test_chat_api_returns_chart_metadata_and_points_with_assistant_message(self):
        chart = {
            "type": "line",
            "title": "Monthly net cash flow",
            "metric": "net_cash_flow",
            "currency": "USD",
            "source_tool": "analyze_financial_trend",
            "status": "success",
            "data_quality": {"actual_data": True},
            "points": [{"period": "2026-02", "value": 21.0}, {"period": "2026-03", "value": 34.5}],
        }
        response, state = self._successful_chat_response(chart)
        body = json.loads(response.body.decode())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(body["chart"], chart)
        self.assertEqual(body["messages"][-1]["chart"], chart)
        self.assertEqual(state.ui_messages[-1]["chart"]["points"], chart["points"])

    def test_ordinary_chat_response_keeps_text_only_contract(self):
        response, state = self._successful_chat_response(None)
        body = json.loads(response.body.decode())
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(body["chart"])
        self.assertIsNone(body["messages"][-1]["chart"])
        self.assertEqual(body["answer"], "The monthly trend changes over time.")

    def test_management_priorities_chat_routes_currency_separated_analysis_without_500(self):
        function_call = SimpleNamespace(
            name="detect_financial_anomalies",
            args={"date_from": "2026-07-01", "date_to": "2026-07-31"},
        )
        responses = iter([
            SimpleNamespace(function_calls=[function_call], text=None),
            SimpleNamespace(text="Review the currency-separated anomaly findings before prioritizing actions."),
        ])
        agent = FinanceAgent.__new__(FinanceAgent)
        agent.enabled_tools = [
            "get_financial_kpis", "compare_financial_periods", "analyze_financial_trend",
            "detect_financial_anomalies", "analyze_cash_flow_drivers", "forecast_financial_kpi",
            "analyze_financial_ratios",
        ]
        agent.last_question = None
        agent.last_verified_results = []
        agent.last_analysis_mode = "single_tool"
        agent.last_health_findings = {}
        agent.last_suggested_questions = []
        agent.max_tool_rounds = 1
        agent.model_name = "test-model"
        agent.client = SimpleNamespace(models=SimpleNamespace(generate_content=lambda **_kwargs: next(responses)))

        state = SimpleNamespace(
            agent=agent,
            ui_messages=[],
            lock=threading.RLock(),
            lang="en",
            execution_log="",
            dashboard_filter={"currency": "USD", "month": None, "trend_months": 6},
            dashboard_payload={"filters": {"currency": "USD", "month": None, "trend_months": 6}},
        )

        async def request_json():
            return {"question": "What should management prioritize?", "lang": "en"}

        request = SimpleNamespace(
            state=SimpleNamespace(chat_request_id="management-priorities-request"),
            json=request_json,
        )
        request.state.chat_lang = "en"

        with patch.object(web_app, "_get_state", return_value=("test-session", state)), \
             patch.object(web_app, "_session_snapshot", return_value={}), \
             patch.object(web_app, "_rendered_history", return_value=[]), \
             patch.object(web_app, "_build_executive_dashboard", return_value={"filters": state.dashboard_filter}), \
             patch.object(agent, "_get_data_boundary", return_value={
                 "status": "success",
                 "available_data": {"date_from": "2026-01-01", "date_to": "2026-07-31"},
             }), \
             patch.object(agent, "_build_tool_config", return_value=object()), \
             patch.object(agent, "_build_user_prompt", return_value="test prompt"), \
             patch.object(agent, "_build_final_config", return_value=object()), \
             patch.object(agent, "_execute_tool", return_value={"status": "success", "currency_statistics": {}}) as execute, \
             patch.object(agent, "_validate_tool_result", return_value=(True, "SUCCESS")), \
             patch.object(agent, "_record_session_turn"), \
             patch.object(agent, "_suggest_follow_up_questions", return_value=[]):
            result = asyncio.run(web_app.chat(request))

        body = json.loads(result.body.decode())
        self.assertEqual(result.status_code, 200)
        self.assertTrue(body["ok"])
        self.assertIn("currency-separated", body["answer"])
        self.assertEqual(agent.last_tool_names, ["detect_financial_anomalies"])
        self.assertEqual(execute.call_args.args[0], "detect_financial_anomalies")
        self.assertNotIn("currency", execute.call_args.args[1])

    def test_agent_exception_is_logged_with_request_id_without_exception_text(self):
        state = SimpleNamespace(
            agent=object(),
            ui_messages=[],
            lock=threading.RLock(),
            lang="en",
            execution_log="",
        )
        request = SimpleNamespace(
            state=SimpleNamespace(chat_request_id="test-request-123"),
            json=lambda: None,
        )

        async def request_json():
            return {"question": "sensitive prompt text", "lang": "en"}

        request.json = request_json
        with patch.object(web_app, "_get_state", return_value=("test-session", state)), patch.object(
            web_app, "_ask_agent", side_effect=RuntimeError("secret connection string")
        ), patch.object(web_app, "_session_snapshot", return_value={}), patch.object(
            web_app, "_rendered_history", return_value=[]
        ), self.assertLogs(web_app.logger, level="ERROR") as captured:
            result = asyncio.run(web_app.chat(request))

        self.assertEqual(result.status_code, 500)
        self.assertEqual(result.headers["X-Request-ID"], "test-request-123")
        self.assertIn(b"The analysis failed. Technical details were captured in the execution log.", result.body)
        self.assertIn(b'"request_id":"test-request-123"', result.body)
        self.assertIn(b'"technical_error":"RuntimeError"', result.body)
        self.assertNotIn(b"secret connection string", result.body)
        log_text = "\n".join(captured.output)
        self.assertIn("request_id=test-request-123", log_text)
        self.assertIn("exception_type=RuntimeError", log_text)
        self.assertIn("web_app.py", log_text)
        self.assertNotIn("secret connection string", log_text)
        self.assertNotIn("sensitive prompt text", log_text)

    def test_uncaught_chat_pipeline_failure_gets_safe_correlated_response(self):
        request = SimpleNamespace(
            url=SimpleNamespace(path="/api/chat"),
            state=SimpleNamespace(chat_lang="ar"),
        )

        async def failed_pipeline(_request):
            raise TypeError("private prompt or credential detail")

        with self.assertLogs(web_app.logger, level="ERROR") as captured:
            result = asyncio.run(web_app.chat_request_diagnostics(request, failed_pipeline))

        body = json.loads(result.body.decode())
        self.assertEqual(result.status_code, 500)
        self.assertEqual(result.headers["X-Request-ID"], body["request_id"])
        self.assertEqual(body["error"], web_app._chat_error_message("ar"))
        self.assertEqual(body["technical_error"], "TypeError")
        self.assertNotIn("private prompt or credential detail", result.body.decode())
        log_text = "\n".join(captured.output)
        self.assertIn(f"request_id={body['request_id']}", log_text)
        self.assertIn("exception_type=TypeError", log_text)
        self.assertNotIn("private prompt or credential detail", log_text)


if __name__ == "__main__":
    unittest.main()
