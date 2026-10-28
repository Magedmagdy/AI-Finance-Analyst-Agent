import inspect
import json
import sys
import types as python_types
import unittest
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch


PHASE_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = PHASE_DIR.parent
sys.path.insert(0, str(PHASE_DIR))

# These modules are only needed to construct a production FinanceAgent, not to
# exercise its deterministic tool normalization/dispatch methods. Keep the unit
# tests runnable in a minimal environment without loading .env or calling a model.
try:
    import yaml  # noqa: F401
except ModuleNotFoundError:
    yaml_stub = python_types.ModuleType("yaml")
    yaml_stub.safe_load = lambda *_args, **_kwargs: {}
    sys.modules["yaml"] = yaml_stub

try:
    from dotenv import load_dotenv  # noqa: F401
except ModuleNotFoundError:
    dotenv_stub = python_types.ModuleType("dotenv")
    dotenv_stub.load_dotenv = lambda *_args, **_kwargs: False
    sys.modules["dotenv"] = dotenv_stub

try:
    from google import genai  # noqa: F401
    from google.genai import types  # noqa: F401
except ModuleNotFoundError:
    google_stub = python_types.ModuleType("google")
    genai_stub = python_types.ModuleType("google.genai")
    types_stub = python_types.ModuleType("google.genai.types")

    class FunctionDeclarationStub:
        def __init__(self, name, description, parameters_json_schema):
            self.name = name
            self.description = description
            self.parameters_json_schema = parameters_json_schema

    types_stub.FunctionDeclaration = FunctionDeclarationStub
    genai_stub.Client = object
    genai_stub.types = types_stub
    google_stub.genai = genai_stub
    sys.modules.update({
        "google": google_stub,
        "google.genai": genai_stub,
        "google.genai.types": types_stub,
    })

from agent.finance_agent import FinanceAgent, TOOL_FUNCTIONS  # noqa: E402
from tools import financial_tools  # noqa: E402


def monthly_rows(start: str, end: str, values: dict[str, float]) -> list[dict]:
    start_month = start[:7]
    end_month = end[:7]
    months = sorted(month for month in values if start_month <= month <= end_month)
    return [
        {
            "period": month,
            "currency": "USD",
            "metric": "net_cash_flow",
            "value": values[month],
        }
        for month in months
    ]


class ForecastCutoffTests(unittest.TestCase):
    def setUp(self) -> None:
        self.values = {
            "2026-03": 10.0,
            "2026-04": 20.0,
            "2026-05": 30.0,
            "2026-06": 40.0,
            "2026-07": 999999.0,
        }
        self.coverage = {
            "status": "success",
            "available_data": {"date_from": "2026-01-01", "date_to": "2026-07-31"},
        }
        self.coverage_patch = patch.object(
            financial_tools, "get_financial_data_coverage", return_value=self.coverage
        )
        self.trend_patch = patch.object(
            financial_tools,
            "analyze_financial_trend",
            side_effect=lambda currency, metric, date_from, date_to: {
                "status": "success",
                "results": monthly_rows(date_from, date_to, self.values),
            },
        )
        self.coverage_patch.start()
        self.trend_patch.start()
        self.addCleanup(self.coverage_patch.stop)
        self.addCleanup(self.trend_patch.stop)

    def forecast(self, **overrides):
        args = {
            "currency": "USD",
            "metric": "net_cash_flow",
            "forecast_period": "2026-07-01",
            "historical_cutoff": "2026-06-30",
            "lookback_months": 3,
        }
        args.update(overrides)
        return financial_tools.forecast_financial_kpi(**args)

    def test_july_forecast_uses_only_completed_months_through_cutoff(self):
        result = self.forecast()
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["forecast_period"], "2026-07-01")
        self.assertEqual(result["historical_cutoff"], "2026-06-30")
        self.assertEqual(result["source_periods"], ["2026-04", "2026-05", "2026-06"])
        self.assertEqual(result["forecast_value"], 30.0)
        self.assertNotIn("2026-07", result["source_periods"])
        self.assertFalse(result["persisted"])

    def test_cutoff_in_data_path_and_partial_month_excluded(self):
        with patch.object(
            financial_tools,
            "analyze_financial_trend",
            side_effect=lambda currency, metric, date_from, date_to: {
                "status": "success",
                "results": monthly_rows(date_from, date_to, self.values),
            },
        ) as trend:
            # A cutoff partway through June makes May the latest eligible month.
            result = self.forecast(historical_cutoff="2026-06-15", lookback_months=2)
            self.assertEqual(result["source_periods"], ["2026-04", "2026-05"])
            self.assertEqual(trend.call_args.kwargs["date_to"], "2026-05-31")

    def test_insufficient_history_is_structured(self):
        result = self.forecast(lookback_months=8)
        self.assertEqual(result["status"], "insufficient_data")
        self.assertIn("historical cutoff", result["message"])
        self.assertFalse(result["persisted"])

    def test_conflicting_or_invalid_target_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "before the target forecast month"):
            self.forecast(historical_cutoff="2026-07-01")
        with self.assertRaisesRegex(ValueError, "first day"):
            self.forecast(forecast_period="2026-07-15")

    def test_currency_and_metric_validation(self):
        with self.assertRaisesRegex(ValueError, "Unsupported currency"):
            self.forecast(currency="XYZ")
        with self.assertRaisesRegex(ValueError, "Unsupported metric"):
            self.forecast(metric="made_up_metric")

    def test_json_builtin_schema_and_callable_signature_match(self):
        payload = json.loads((PHASE_DIR / "tools" / "financial_tools.json").read_text(encoding="utf-8"))
        definition = next(tool for tool in payload["tools"] if tool["name"] == "forecast_financial_kpi")
        schema = definition["input_schema"]
        self.assertEqual(
            set(schema["properties"]),
            {"currency", "metric", "forecast_period", "historical_cutoff", "lookback_months"},
        )
        signature = inspect.signature(financial_tools.forecast_financial_kpi)
        self.assertEqual(set(schema["required"]), {
            name for name, parameter in signature.parameters.items()
            if parameter.default is inspect.Parameter.empty
        })
        self.assertEqual(
            set(financial_tools.TOOL_SCHEMAS["forecast_financial_kpi"]["parameters"]["properties"]),
            set(schema["properties"]),
        )
        agent = FinanceAgent.__new__(FinanceAgent)
        agent.tools_definition = payload
        declaration = agent._build_tool_declarations(["forecast_financial_kpi"])[0]
        self.assertEqual(declaration.parameters_json_schema, schema)

    def test_aggregation_and_anomaly_schemas_match_callable_arguments(self):
        payload = json.loads((PHASE_DIR / "tools" / "financial_tools.json").read_text(encoding="utf-8"))
        definitions = {
            tool["name"]: tool.get("input_schema", tool.get("parameters", {}))
            for tool in payload["tools"]
        }
        kpis = definitions["get_financial_kpis"]
        self.assertIn("currency", kpis["required"])
        self.assertIn("metric", kpis["properties"])
        self.assertNotIn("metrics", kpis["properties"])
        anomalies = definitions["detect_financial_anomalies"]
        self.assertEqual(set(anomalies["properties"]), {"date_from", "date_to", "currency", "threshold"})
        self.assertEqual(set(anomalies["required"]), {"date_from", "date_to"})

    def test_kpi_normalization_requires_currency_without_inventing_one(self):
        agent = FinanceAgent.__new__(FinanceAgent)
        agent.last_question = None
        agent.last_verified_results = []
        agent.data_boundary = {"available_data": {"date_to": "2026-07-31"}}
        with self.assertRaisesRegex(
            ValueError,
            "Currency is unspecified or prior results conflict. Please specify a currency\\.",
        ):
            agent._normalize_tool_arguments(
                "get_financial_kpis",
                {"date_from": "2026-07-01", "date_to": "2026-07-31", "metric": "net_cash_flow"},
                "Summarize the July 2026 financial results",
            )

    def test_normalizer_rejects_arguments_not_supported_by_selected_callable(self):
        agent = FinanceAgent.__new__(FinanceAgent)
        agent.last_question = None
        agent.last_verified_results = []
        agent.data_boundary = {"available_data": {"date_to": "2026-07-31"}}
        with self.assertRaisesRegex(ValueError, r"Unsupported arguments for detect_financial_anomalies: \['metric'\]"):
            agent._normalize_tool_arguments(
                "detect_financial_anomalies",
                {"date_from": "2026-07-01", "date_to": "2026-07-31", "metric": "net_cash_flow"},
                "Find anomalies in July 2026",
            )

    def test_exact_arabic_chart_request_routes_monthly_usd_trend(self):
        question = (
            "اعرض صافي التدفق النقدي شهريًا بعملة USD من فبراير إلى يوليو 2026 "
            "في رسم بياني، واشرح اتجاه التغيّر بين الشهور."
        )
        agent = FinanceAgent.__new__(FinanceAgent)
        agent.enabled_tools = ["analyze_financial_trend"]
        agent.last_question = None
        agent.last_verified_results = []
        agent.last_analysis_mode = "single_tool"
        agent.data_boundary = {"available_data": {"date_to": "2026-07-31"}}

        self.assertTrue(agent._is_chart_request(question))
        self.assertEqual(agent._extract_currency(question), "USD")
        self.assertEqual(
            agent._extract_month_periods(question),
            [
                {"date_from": "2026-02-01", "date_to": "2026-02-28"},
                {"date_from": "2026-07-01", "date_to": "2026-07-31"},
            ],
        )
        self.assertEqual(agent._select_tools_for_question(question), ["analyze_financial_trend"])
        arguments = agent._infer_tool_arguments("analyze_financial_trend", question)
        self.assertEqual(arguments["currency"], "USD")
        self.assertEqual(arguments["metric"], "net_cash_flow")
        self.assertEqual(arguments["date_from"], "2026-02-01")
        self.assertEqual(arguments["date_to"], "2026-07-31")

    def test_chart_payload_uses_only_verified_points_and_one_matching_currency(self):
        question = "اعرض صافي التدفق النقدي شهريًا بعملة USD من فبراير إلى يوليو 2026 في رسم بياني"
        months = ["2026-02", "2026-03", "2026-04", "2026-05", "2026-06", "2026-07"]
        result_rows = [
            {
                "period": month,
                "currency": "USD",
                "metric": "net_cash_flow",
                "value": (index + 1) * 17.25,
            }
            for index, month in enumerate(months)
        ]
        agent = FinanceAgent.__new__(FinanceAgent)
        agent.response_language = "ar"
        verified = [{
            "tool_name": "analyze_financial_trend",
            "arguments": {"currency": "USD", "metric": "net_cash_flow"},
            "result": {
                "status": "success",
                "currency": "USD",
                "metric": "net_cash_flow",
                "requested_period": {"date_from": "2026-02-01", "date_to": "2026-07-31"},
                "data_quality": {"actual_data": True, "read_only": True},
                "results": result_rows,
            },
        }]
        chart = agent._build_chat_chart(question, verified)
        self.assertEqual(chart["type"], "line")
        self.assertEqual(chart["currency"], "USD")
        self.assertEqual(chart["source_tool"], "analyze_financial_trend")
        self.assertEqual(chart["points"], [
            {"period": row["period"], "value": row["value"]} for row in result_rows
        ])

        mismatched_currency = [{
            **verified[0],
            "result": {**verified[0]["result"], "currency": "EUR"},
        }]
        self.assertIsNone(agent._build_chat_chart(question, mismatched_currency))

    def test_exact_arabic_chart_request_executes_trend_tool_and_sets_chart_data(self):
        question = (
            "اعرض صافي التدفق النقدي شهريًا بعملة USD من فبراير إلى يوليو 2026 "
            "في رسم بياني، واشرح اتجاه التغيّر بين الشهور."
        )
        months = ["2026-02", "2026-03", "2026-04", "2026-05", "2026-06", "2026-07"]
        tool_result = {
            "status": "success",
            "currency": "USD",
            "metric": "net_cash_flow",
            "granularity": "monthly",
            "requested_period": {"date_from": "2026-02-01", "date_to": "2026-07-31"},
            "data_quality": {"actual_data": True, "read_only": True},
            "results": [
                {"period": month, "currency": "USD", "metric": "net_cash_flow", "value": (index + 1) * 13.5}
                for index, month in enumerate(months)
            ],
        }
        function_call = type("FunctionCall", (), {
            "name": "analyze_financial_trend",
            "args": {"currency": "USD", "metric": "net_cash_flow"},
        })()
        responses = iter([
            type("Response", (), {"function_calls": [function_call], "text": None})(),
            type("Response", (), {"function_calls": [], "text": "يوضح الرسم اتجاه صافي التدفق النقدي."})(),
        ])
        agent = FinanceAgent.__new__(FinanceAgent)
        agent.enabled_tools = ["analyze_financial_trend"]
        agent.last_question = None
        agent.last_tool_names = []
        agent.last_verified_results = []
        agent.data_boundary = {
            "status": "success",
            "latest_actual_date": "2026-07-31",
            "available_data": {"date_from": "2026-02-01", "date_to": "2026-07-31"},
        }
        agent.last_analysis_mode = "single_tool"
        agent.current_health_findings = {}
        agent.last_health_findings = {}
        agent.last_suggested_questions = []
        agent.response_language = "ar"
        agent.max_tool_rounds = 1
        agent.model_name = "test-model"
        agent.client = type("Client", (), {"models": type("Models", (), {
            "generate_content": staticmethod(lambda **_kwargs: next(responses))
        })()})()

        with patch.object(agent, "_get_data_boundary", return_value=agent.data_boundary), \
             patch.object(agent, "_build_tool_config", return_value=object()), \
             patch.object(agent, "_build_user_prompt", return_value="test prompt"), \
             patch.object(agent, "_build_final_config", return_value=object()), \
             patch.object(agent, "_execute_tool", return_value=tool_result) as execute, \
             patch.object(agent, "_validate_tool_result", return_value=(True, "SUCCESS")), \
             patch.object(agent, "_record_session_turn"), \
             patch.object(agent, "_suggest_follow_up_questions", return_value=[]):
            answer = agent.ask(question, language="ar")

        self.assertIn("يوضح الرسم", answer)
        self.assertEqual(execute.call_args.args[0], "analyze_financial_trend")
        self.assertEqual(execute.call_args.args[1]["currency"], "USD")
        self.assertEqual(execute.call_args.args[1]["metric"], "net_cash_flow")
        self.assertEqual(execute.call_args.args[1]["date_from"], "2026-02-01")
        self.assertEqual(execute.call_args.args[1]["date_to"], "2026-07-31")
        self.assertEqual(agent.last_chart_data["currency"], "USD")
        self.assertEqual(len(agent.last_chart_data["points"]), len(months))

    def test_ordinary_question_does_not_produce_chart_metadata(self):
        agent = FinanceAgent.__new__(FinanceAgent)
        agent.response_language = "en"
        self.assertFalse(agent._is_chart_request("Explain the net cash flow trend in USD"))
        self.assertIsNone(agent._build_chat_chart("Explain the net cash flow trend in USD", []))

    def test_agent_normalization_preserves_target_and_explicit_cutoff(self):
        agent = FinanceAgent.__new__(FinanceAgent)
        agent.data_boundary = {"latest_actual_date": "2026-07-31"}
        agent.last_question = None
        normalized = agent._normalize_tool_arguments(
            "forecast_financial_kpi",
            {
                "currency": "USD",
                "metric": "net_cash_flow",
                "forecast_period": "2026-07-01",
                "historical_cutoff": "2026-06-30",
                "lookback_months": 3,
            },
            "Forecast July 2026 USD net cash flow using data through June 30, 2026",
        )
        self.assertEqual(normalized["forecast_period"], "2026-07-01")
        self.assertEqual(normalized["historical_cutoff"], "2026-06-30")

    def test_agent_dispatches_corrected_arguments_to_registered_tool(self):
        agent = FinanceAgent.__new__(FinanceAgent)
        received = {}

        def spy(**kwargs):
            received.update(kwargs)
            return {"status": "success", "is_forecast": True}

        with patch.dict(TOOL_FUNCTIONS, {"forecast_financial_kpi": spy}):
            result = agent._execute_tool("forecast_financial_kpi", {
                "currency": "USD",
                "metric": "net_cash_flow",
                "forecast_period": "2026-07-01",
                "historical_cutoff": "2026-06-30",
                "lookback_months": 3,
            })
        self.assertEqual(received["historical_cutoff"], "2026-06-30")
        self.assertEqual(received["forecast_period"], "2026-07-01")
        self.assertEqual(result["status"], "success")

    def test_agent_rejects_ambiguous_legacy_date_arguments(self):
        agent = FinanceAgent.__new__(FinanceAgent)
        agent.data_boundary = {"latest_actual_date": "2026-07-31"}
        agent.last_question = None
        with self.assertRaisesRegex(ValueError, "no longer accepts date_from/date_to"):
            agent._normalize_tool_arguments(
                "forecast_financial_kpi",
                {"date_from": "2026-01-01", "date_to": "2026-06-30", "metric": "net_cash_flow"},
                "forecast net cash flow",
            )

    def saved_row(self, forecast_id=None, forecast_value=30.0):
        return {
            "forecast_id": str(forecast_id or uuid.UUID("c16f9289-a378-4f47-b2e5-fd596a4a4ab0")),
            "metric": "net_cash_flow",
            "currency": "USD",
            "target_period": "2026-07-01",
            "time_grain": "monthly",
            "unit": "USD",
            "forecast_value": forecast_value,
            "forecast_method": "Trailing Moving Average",
            "lookback_months": 3,
            "historical_cutoff": "2026-06-30",
            "source_periods_json": '["2026-04", "2026-05", "2026-06"]',
            "source_values_json": "[20.0, 30.0, 40.0]",
            "model_version": financial_tools.FORECAST_MODEL_VERSION,
            "metric_definition_version": financial_tools.METRIC_DEFINITION_VERSION,
            "status": "saved",
            "provenance_json": '{"source":"synthetic_test"}',
            "created_at": "2026-10-28T00:00:00+00:00",
        }

    def test_save_retrieve_and_compare_synthetic_forecast(self):
        forecast_id = uuid.UUID("c16f9289-a378-4f47-b2e5-fd596a4a4ab0")
        memory_store = {}

        def insert(record):
            memory_store[record["forecast_id"]] = record
            return {"forecast_id": record["forecast_id"], "created_at": datetime(2026, 10, 28, tzinfo=timezone.utc)}

        def select(_forecast_id):
            return memory_store.get(_forecast_id)

        with patch.object(financial_tools.uuid, "uuid4", return_value=forecast_id), patch.object(
            financial_tools, "_insert_forecast_record", side_effect=insert
        ), patch.object(financial_tools, "_select_forecast_record", side_effect=select):
            saved = financial_tools.save_financial_forecast(
                currency="USD", metric="net_cash_flow", forecast_period="2026-07-01",
                historical_cutoff="2026-06-30", lookback_months=3,
            )
            retrieved = financial_tools.get_saved_financial_forecast(str(forecast_id))
            with patch.object(financial_tools, "_has_actual_observations", return_value=True), patch.object(financial_tools, "get_financial_kpis", return_value={
                "status": "success",
                "resolved_period": {"date_from": "2026-07-01", "date_to": "2026-07-31"},
                "filters": {"currency": "USD"},
                "results": [{
                    "metric": "net_cash_flow", "currency": "USD", "value": 40.0,
                    "period": {"date_from": "2026-07-01", "date_to": "2026-07-31"},
                }],
            }):
                compared = financial_tools.compare_saved_forecast_to_actual(str(forecast_id))

        self.assertTrue(saved["persisted"])
        self.assertEqual(saved["forecast_id"], str(forecast_id))
        self.assertEqual(retrieved["status"], "success")
        self.assertEqual(retrieved["historical_cutoff"], "2026-06-30")
        self.assertEqual(compared["status"], "comparison_success")
        self.assertEqual(compared["signed_difference"], 10.0)
        self.assertEqual(compared["absolute_error"], 10.0)
        self.assertEqual(compared["percentage_error"], 25.0)
        self.assertEqual(len(memory_store), 1)

    def test_duplicate_and_failed_write_never_claim_persistence(self):
        with patch.object(financial_tools, "_insert_forecast_record", side_effect=financial_tools.DuplicateForecastError()):
            duplicate = financial_tools.save_financial_forecast(
                currency="USD", metric="net_cash_flow", forecast_period="2026-07-01",
                historical_cutoff="2026-06-30", lookback_months=3,
            )
        with patch.object(financial_tools, "_insert_forecast_record", side_effect=RuntimeError("db failure")):
            failed = financial_tools.save_financial_forecast(
                currency="USD", metric="net_cash_flow", forecast_period="2026-07-01",
                historical_cutoff="2026-06-30", lookback_months=3,
            )
        self.assertEqual(duplicate["status"], "duplicate_id")
        self.assertFalse(duplicate["persisted"])
        self.assertNotIn("forecast_id", duplicate)
        self.assertEqual(failed["status"], "save_failed")
        self.assertFalse(failed["persisted"])
        self.assertNotIn("forecast_id", failed)

    def test_missing_forecast_and_actual_are_truthful(self):
        with patch.object(financial_tools, "_select_forecast_record", return_value=None):
            missing = financial_tools.get_saved_financial_forecast("c16f9289-a378-4f47-b2e5-fd596a4a4ab0")
            compare_missing = financial_tools.compare_saved_forecast_to_actual("c16f9289-a378-4f47-b2e5-fd596a4a4ab0")
        self.assertEqual(missing["status"], "forecast_not_found")
        self.assertEqual(compare_missing["status"], "forecast_not_found")

        with patch.object(financial_tools, "_select_forecast_record", return_value=self.saved_row()), patch.object(
            financial_tools, "get_financial_data_coverage", return_value={"available_data": {"date_to": "2026-07-15"}}
        ):
            actual_missing = financial_tools.compare_saved_forecast_to_actual("c16f9289-a378-4f47-b2e5-fd596a4a4ab0")
        self.assertEqual(actual_missing["status"], "actual_not_found")

    def test_zero_actual_has_no_percentage_error(self):
        with patch.object(financial_tools, "_select_forecast_record", return_value=self.saved_row(forecast_value=30.0)), patch.object(
            financial_tools, "_has_actual_observations", return_value=True
        ), patch.object(
            financial_tools, "get_financial_kpis", return_value={
                "status": "success",
                "resolved_period": {"date_from": "2026-07-01", "date_to": "2026-07-31"},
                "filters": {"currency": "USD"},
                "results": [{
                    "metric": "net_cash_flow", "currency": "USD", "value": 0.0,
                    "period": {"date_from": "2026-07-01", "date_to": "2026-07-31"},
                }],
            }
        ):
            result = financial_tools.compare_saved_forecast_to_actual("c16f9289-a378-4f47-b2e5-fd596a4a4ab0")
        self.assertIsNone(result["percentage_error"])
        self.assertEqual(result["percentage_error_status"], "unavailable_actual_is_zero")

    def test_mismatched_actual_metric_currency_or_period_is_rejected(self):
        actual_cases = [
            {"metric": "total_outflows", "currency": "USD", "period": {"date_from": "2026-07-01", "date_to": "2026-07-31"}},
            {"metric": "net_cash_flow", "currency": "EUR", "period": {"date_from": "2026-07-01", "date_to": "2026-07-31"}},
            {"metric": "net_cash_flow", "currency": "USD", "period": {"date_from": "2026-06-01", "date_to": "2026-06-30"}},
        ]
        for row in actual_cases:
            with self.subTest(row=row), patch.object(
                financial_tools, "_select_forecast_record", return_value=self.saved_row()
            ), patch.object(financial_tools, "_has_actual_observations", return_value=True), patch.object(financial_tools, "get_financial_kpis", return_value={
                "status": "success",
                "resolved_period": {"date_from": "2026-07-01", "date_to": "2026-07-31"},
                "filters": {"currency": "USD"},
                "results": [{**row, "value": 40.0}],
            }):
                result = financial_tools.compare_saved_forecast_to_actual(
                    "c16f9289-a378-4f47-b2e5-fd596a4a4ab0"
                )
                self.assertEqual(result["status"], "comparison_rejected")

    def test_metadata_mismatch_is_rejected(self):
        row = self.saved_row()
        row["unit"] = "EUR"
        with patch.object(financial_tools, "_select_forecast_record", return_value=row):
            result = financial_tools.compare_saved_forecast_to_actual("c16f9289-a378-4f47-b2e5-fd596a4a4ab0")
        self.assertEqual(result["status"], "comparison_rejected")

    def test_new_tool_schemas_and_agent_registry_match_functions(self):
        payload = json.loads((PHASE_DIR / "tools" / "financial_tools.json").read_text(encoding="utf-8"))
        definitions = {item["name"]: item["input_schema"] for item in payload["tools"] if "input_schema" in item}
        for name in (
            "save_financial_forecast", "get_saved_financial_forecast", "compare_saved_forecast_to_actual",
        ):
            function = financial_tools.TOOL_FUNCTIONS[name]
            self.assertIn(name, TOOL_FUNCTIONS)
            schema = definitions[name]
            signature = inspect.signature(function)
            self.assertEqual(set(schema["properties"]), set(signature.parameters))
            required = {key for key, parameter in signature.parameters.items() if parameter.default is inspect.Parameter.empty}
            self.assertEqual(set(schema["required"]), required)

    def test_agent_routes_save_retrieval_and_comparison_tools(self):
        agent = FinanceAgent.__new__(FinanceAgent)
        agent.enabled_tools = list(TOOL_FUNCTIONS)
        agent.last_question = None
        agent.last_verified_results = []
        agent.last_analysis_mode = "single_tool"
        self.assertEqual(agent._select_tools_for_question("Save a July 2026 USD net cash flow forecast"), ["save_financial_forecast"])
        self.assertEqual(agent._select_tools_for_question("Compare the saved forecast with actual results"), ["compare_saved_forecast_to_actual"])
        self.assertEqual(agent._select_tools_for_question("Show the saved forecast"), ["get_saved_financial_forecast"])

    def test_agent_invokes_save_tool_and_rejects_unconfirmed_success(self):
        agent = FinanceAgent.__new__(FinanceAgent)
        received = {}

        def spy(**kwargs):
            received.update(kwargs)
            return {"status": "save_failed", "persisted": False, "message": "Storage unavailable."}

        with patch.dict(TOOL_FUNCTIONS, {"save_financial_forecast": spy}):
            result = agent._execute_tool("save_financial_forecast", {
                "currency": "USD", "metric": "net_cash_flow", "forecast_period": "2026-07-01",
                "historical_cutoff": "2026-06-30", "lookback_months": 3,
            })
        self.assertEqual(received["historical_cutoff"], "2026-06-30")
        self.assertEqual(result["status"], "save_failed")

        agent.data_boundary = {"latest_actual_date": "2026-07-31"}
        accepted, _ = agent._validate_tool_result("save_financial_forecast", result)
        self.assertTrue(accepted)
        with self.assertRaisesRegex(ValueError, "only after confirmed persistence"):
            agent._validate_tool_result("save_financial_forecast", {
                "status": "saved", "persisted": False, "is_forecast": True, "currency": "USD",
            })

    def test_cash_flow_comparison_routes_to_driver_tool_and_orders_months_chronologically(self):
        question = (
            "What factors explain the decline in net cash flow in July 2026 compared with June 2026? "
            "Compare Inflows, Outflows, Fees, and Refunds, showing actual values and absolute/relative changes. "
            "Do not infer unsupported causes. USD"
        )
        agent = FinanceAgent.__new__(FinanceAgent)
        agent.enabled_tools = list(TOOL_FUNCTIONS)
        agent.last_question = None
        agent.last_verified_results = []
        agent.last_analysis_mode = "single_tool"
        agent.data_boundary = {"available_data": {"date_to": "2026-07-31"}}

        selected = agent._select_tools_for_question(question)
        arguments = agent._build_compound_arguments(selected[0], question)

        self.assertEqual(selected, ["analyze_cash_flow_drivers"])
        self.assertEqual(agent.last_analysis_mode, "compound_financial_analysis")
        self.assertEqual(arguments["currency"], "USD")
        self.assertEqual(arguments["period_1_from"], "2026-06-01")
        self.assertEqual(arguments["period_1_to"], "2026-06-30")
        self.assertEqual(arguments["period_2_from"], "2026-07-01")
        self.assertEqual(arguments["period_2_to"], "2026-07-31")

    def test_model_currency_cannot_override_explicit_question_currency(self):
        agent = FinanceAgent.__new__(FinanceAgent)
        agent.last_question = None
        agent.last_verified_results = []
        agent.data_boundary = {"available_data": {"date_to": "2026-07-31"}}
        normalized = agent._normalize_tool_arguments(
            "compare_financial_periods",
            {
                "currency": "JPY",
                "metric": "net_cash_flow",
                "period_1_from": "2026-07-01",
                "period_1_to": "2026-07-31",
                "period_2_from": "2026-06-01",
                "period_2_to": "2026-06-30",
            },
            "Compare July 2026 with June 2026 in USD",
        )
        self.assertEqual(normalized["currency"], "USD")
        self.assertEqual(normalized["period_1_from"], "2026-06-01")
        self.assertEqual(normalized["period_2_from"], "2026-07-01")

    def test_arabic_summary_explicit_usd_is_extracted_and_passed_to_selected_tool(self):
        question = "لخص الأداء المالي في يوليو 2026 بعملة USD"
        agent = FinanceAgent.__new__(FinanceAgent)
        agent.last_question = None
        agent.last_verified_results = []
        agent.data_boundary = {"available_data": {"date_to": "2026-07-31"}}
        self.assertEqual(agent._extract_currency(question), "USD")
        arguments = agent._build_compound_arguments("get_financial_kpis", question)
        self.assertEqual(arguments["currency"], "USD")

    def test_management_priorities_without_currency_reaches_currency_separated_tool(self):
        agent = FinanceAgent.__new__(FinanceAgent)
        agent.response_language = "en"
        agent.last_question = None
        agent.last_verified_results = []
        agent.last_health_findings = {}
        agent.last_analysis_mode = "compound_financial_analysis"
        agent.max_tool_rounds = 1
        agent.model_name = "test-model"
        agent.enabled_tools = ["detect_financial_anomalies"]
        agent.client = python_types.SimpleNamespace(models=python_types.SimpleNamespace(
            generate_content=lambda **_kwargs: python_types.SimpleNamespace(text=None, candidates=[])
        ))
        with patch.object(agent, "_get_data_boundary", return_value={"status": "success", "available_data": {"date_to": "2026-07-31"}}), \
             patch.object(agent, "_select_tools_for_question", return_value=[
                 "get_financial_kpis", "analyze_financial_ratios", "detect_financial_anomalies"
             ]), \
             patch.object(agent, "_build_tool_config", return_value=object()), \
             patch.object(agent, "_build_user_prompt", return_value="prompt"), \
             patch.object(agent, "_extract_function_calls", return_value=[]):
            answer = agent.ask("What should management prioritize?", language="en")
        self.assertNotIn("specify a currency", answer.lower())
        self.assertEqual(agent.last_tool_names, ["detect_financial_anomalies"])

    def test_model_currency_cannot_override_single_currency_verified_context(self):
        agent = FinanceAgent.__new__(FinanceAgent)
        agent.last_question = "Compare June 2026 with July 2026 in USD"
        agent.last_verified_results = [{
            "tool_name": "compare_financial_periods",
            "arguments": {"currency": "USD"},
            "result": {"currency": "USD"},
        }]
        agent.data_boundary = {"available_data": {"date_to": "2026-07-31"}}
        normalized = agent._normalize_tool_arguments(
            "compare_financial_periods",
            {
                "currency": "JPY",
                "metric": "net_cash_flow",
                "period_1_from": "2026-06-01",
                "period_1_to": "2026-06-30",
                "period_2_from": "2026-07-01",
                "period_2_to": "2026-07-31",
            },
            "Compare July 2026 with June 2026",
        )
        self.assertEqual(normalized["currency"], "USD")

    def test_unspecified_or_conflicting_currency_is_clarified_at_currency_tool_boundary(self):
        agent = FinanceAgent.__new__(FinanceAgent)
        agent.last_question = "Compare June 2026 and July 2026 in USD"
        agent.last_verified_results = [{
            "tool_name": "compare_financial_periods",
            "arguments": {"currency": "JPY"},
            "result": {"currency": "JPY"},
        }]
        agent.data_boundary = {"available_data": {"date_to": "2026-07-31"}}
        with self.assertRaisesRegex(ValueError, "Please specify a currency"):
            agent._normalize_tool_arguments(
                "compare_financial_periods",
                {"metric": "net_cash_flow"},
                "Compare June 2026 with July 2026",
            )

    def test_cash_flow_tool_reports_monthly_values_and_changes_and_marks_missing_metric(self):
        june = {
            "net_cash_flow": 100.0,
            "total_inflows": 500.0,
            "total_outflows": 400.0,
            "fees": 20.0,
            "refunds": 10.0,
        }
        july = {
            "net_cash_flow": 50.0,
            "total_inflows": 450.0,
            "total_outflows": 400.0,
            "fees": None,
            "refunds": 5.0,
        }
        with patch.object(financial_tools, "_driver_query", return_value=[]), patch.object(
            financial_tools, "_authoritative_cash_flow_metrics", side_effect=[june, july]
        ):
            result = financial_tools.analyze_cash_flow_drivers(
                currency="USD",
                period_1_from="2026-06-01",
                period_1_to="2026-06-30",
                period_2_from="2026-07-01",
                period_2_to="2026-07-31",
            )

        by_metric = {row["metric"]: row for row in result["cash_flow_metric_comparisons"]}
        self.assertEqual(result["currency"], "USD")
        self.assertEqual(by_metric["net_cash_flow"]["absolute_change"], -50.0)
        self.assertEqual(by_metric["net_cash_flow"]["percentage_change"], -50.0)
        self.assertEqual(by_metric["total_inflows"]["period_1"]["date_from"], "2026-06-01")
        self.assertEqual(by_metric["total_outflows"]["absolute_change"], 0.0)
        self.assertEqual(by_metric["refunds"]["absolute_change"], -5.0)
        self.assertEqual(by_metric["fees"]["status"], "no_data")
        self.assertIsNone(by_metric["fees"]["absolute_change"])
        self.assertEqual(by_metric["fees"]["currency"], "USD")
        self.assertTrue(result["metric_relationships"]["fees"].startswith("Reported separately"))
        self.assertEqual(result["data_quality"]["cash_flow_metric_source"], "AI_Finance.mart.daily_financial_kpis")
        agent = FinanceAgent.__new__(FinanceAgent)
        agent.data_boundary = {"available_data": {"date_to": "2026-07-31"}}
        accepted, message = agent._validate_tool_result("analyze_cash_flow_drivers", result)
        self.assertTrue(accepted, message)

    def test_agent_prompt_limits_causes_to_verified_driver_evidence(self):
        agent = FinanceAgent.__new__(FinanceAgent)
        agent.response_language = "en"
        agent.system_prompt = ""
        prompt = agent._build_runtime_system_prompt()
        self.assertIn("observed associations, not proof of business causes", prompt)
        self.assertIn("cause is not established", prompt)
        self.assertIn("Do not add them to total_outflows or total_inflows", prompt)


if __name__ == "__main__":
    unittest.main()
