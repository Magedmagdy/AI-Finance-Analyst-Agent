from __future__ import annotations

import calendar
import json
import math
import os
import re
import sys
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv
from google import genai
from google.genai import types


# ============================================================
# PATHS
# ============================================================

CURRENT_DIR = Path(__file__).resolve().parent
PHASE_DIR = CURRENT_DIR.parent
PROJECT_ROOT = PHASE_DIR.parent

if str(PHASE_DIR) not in sys.path:
    sys.path.insert(0, str(PHASE_DIR))


# ============================================================
# IMPORT FINANCIAL TOOLS
# ============================================================

from tools.financial_tools import (  # noqa: E402
    TOOL_SCHEMAS,
    analyze_cash_flow_drivers,
    analyze_financial_ratios,
    analyze_financial_trend,
    compare_financial_periods,
    detect_financial_anomalies,
    forecast_financial_kpi,
    get_financial_data_coverage,
    get_financial_kpis,
)


# ============================================================
# ENVIRONMENT
# ============================================================

load_dotenv(PROJECT_ROOT / ".env")


# ============================================================
# TOOL REGISTRY
# ============================================================

TOOL_FUNCTIONS = {
    "get_financial_kpis": get_financial_kpis,
    "compare_financial_periods": compare_financial_periods,
    "analyze_financial_trend": analyze_financial_trend,
    "detect_financial_anomalies": detect_financial_anomalies,
    "analyze_cash_flow_drivers": analyze_cash_flow_drivers,
    "forecast_financial_kpi": forecast_financial_kpi,
    "analyze_financial_ratios": analyze_financial_ratios,
}


# ============================================================
# SUPPORTED CURRENCIES
# ============================================================

ALLOWED_CURRENCIES = {
    "USD",
    "EUR",
    "GBP",
    "CAD",
    "JPY",
    "AUD",
}


# ============================================================
# SAFE JSON CONVERSION
# ============================================================

def make_json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): make_json_safe(item) for key, item in value.items()}

    if isinstance(value, (list, tuple)):
        return [make_json_safe(item) for item in value]

    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            pass

    return value


# ============================================================
# FINANCE AGENT
# ============================================================

class FinanceAgent:

    def __init__(self):

        # ----------------------------------------------------
        # Paths
        # ----------------------------------------------------

        self.phase_dir = PHASE_DIR
        self.root_dir = PROJECT_ROOT

        self.agent_config_path = self.phase_dir / "agent_config" / "agent_config.yaml"
        self.model_config_path = self.phase_dir / "agent_config" / "model_config.yaml"
        self.system_prompt_path = self.phase_dir / "prompts" / "system_prompt.txt"
        self.tools_json_path = self.phase_dir / "tools" / "financial_tools.json"

        # ----------------------------------------------------
        # Load configuration
        # ----------------------------------------------------

        self.agent_config = self._load_yaml(self.agent_config_path)
        self.model_config = self._load_yaml(self.model_config_path)
        self.system_prompt = self.system_prompt_path.read_text(encoding="utf-8")
        self.tools_definition = self._load_json(self.tools_json_path)

        # ----------------------------------------------------
        # Load enabled tools
        # ----------------------------------------------------

        self._load_enabled_tools()

        # ----------------------------------------------------
        # Limits
        # ----------------------------------------------------

        agent_section = self.agent_config.get("agent", {})
        limits_config = self.agent_config.get("limits", {})

        if isinstance(agent_section, dict):
            nested_limits = agent_section.get("limits", {})
            if isinstance(nested_limits, dict):
                merged_limits = dict(nested_limits)
                merged_limits.update(limits_config if isinstance(limits_config, dict) else {})
                limits_config = merged_limits

        if not isinstance(limits_config, dict):
            limits_config = {}

        self.max_tool_rounds = int(
            limits_config.get(
                "max_tool_rounds",
                limits_config.get("max_tool_calls_per_request", 10),
            )
        )

        self.max_tool_rounds = max(1, min(self.max_tool_rounds, 20))

        # ----------------------------------------------------
        # Conversation state
        # ----------------------------------------------------

        self.last_question: str | None = None
        self.last_tool_names: list[str] = []
        self.last_verified_results: list[dict[str, Any]] = []
        self.data_boundary: dict[str, Any] = {}
        self.last_analysis_mode: str = "single_tool"
        self.current_health_findings: dict[str, Any] = {}
        self.last_health_findings: dict[str, Any] = {}

        # Smart conversational interface state.
        self.session_history: list[dict[str, Any]] = []
        self.session_turn_id: int = 0
        self.last_response_text: str | None = None
        self.last_suggested_questions: list[str] = []

        # Response / input language for the Web UI and bilingual Copilot.
        self.response_language: str = "en"

        # ----------------------------------------------------
        # Google Gemini
        # ----------------------------------------------------

        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY was not found in the project .env file.")

        provider = self.model_config.get("provider", "google")
        model_name = self.model_config.get("name", "gemini-3.5-flash-lite")

        if provider.lower() != "google":
            raise RuntimeError(f"Unsupported provider: {provider}")

        self.model_name = model_name
        self.client = genai.Client(api_key=api_key)

        # ----------------------------------------------------
        # Configuration validation
        # ----------------------------------------------------

        self._validate_configuration()

    # ========================================================
    # CONFIG SECTIONS
    # ========================================================

    def _get_agent_section(self) -> dict[str, Any]:
        agent_section = self.agent_config.get("agent", {})
        return agent_section if isinstance(agent_section, dict) else {}

    # ========================================================
    # LOAD ENABLED TOOLS
    # ========================================================

    def _load_enabled_tools(self) -> None:
        """
        Supports both the legacy top-level tool configuration and the
        canonical nested form:

        agent:
          tools:
            enabled: [...]
            disabled: [...]
        """

        agent_section = self._get_agent_section()

        tools_config = agent_section.get("tools")
        if tools_config is None:
            tools_config = self.agent_config.get("tools", {})

        configured_enabled_tools = []
        configured_disabled_tools = []

        if isinstance(tools_config, dict):
            configured_enabled_tools = (
                tools_config.get("enabled")
                or tools_config.get("enabled_tools")
                or []
            )
            configured_disabled_tools = (
                tools_config.get("disabled")
                or tools_config.get("disabled_tools")
                or []
            )

        elif isinstance(tools_config, list):
            configured_enabled_tools = tools_config

        if not configured_enabled_tools:
            configured_enabled_tools = (
                agent_section.get("enabled_tools", [])
                or self.agent_config.get("enabled_tools", [])
            )

        if not configured_disabled_tools:
            configured_disabled_tools = (
                agent_section.get("disabled_tools", [])
                or self.agent_config.get("disabled_tools", [])
            )

        if not isinstance(configured_enabled_tools, list):
            configured_enabled_tools = []
        if not isinstance(configured_disabled_tools, list):
            configured_disabled_tools = []

        self.enabled_tools = [str(name).strip() for name in configured_enabled_tools if str(name).strip()]
        self.disabled_tools = [str(name).strip() for name in configured_disabled_tools if str(name).strip()]

        self.enabled_tools = [name for name in self.enabled_tools if name not in self.disabled_tools]
        self.enabled_tools = [name for name in self.enabled_tools if name in TOOL_FUNCTIONS]

        # New ratio capability should be opt-in through config when a list exists,
        # but legacy configs that explicitly omit it are upgraded safely.
        if (
            "analyze_financial_ratios" not in self.enabled_tools
            and "analyze_financial_ratios" not in self.disabled_tools
            and configured_enabled_tools
        ):
            self.enabled_tools.append("analyze_financial_ratios")

        if not self.enabled_tools:
            self.enabled_tools = [name for name in TOOL_FUNCTIONS if name not in self.disabled_tools]
            print(
                "WARNING: No enabled tools were found in agent_config.yaml. "
                "Falling back to all registered financial tools."
            )

    # ========================================================
    # FILE LOADERS
    # ========================================================

    @staticmethod
    def _load_yaml(path: Path) -> dict[str, Any]:
        if not path.exists():
            raise FileNotFoundError(f"Configuration file not found: {path}")

        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError(f"YAML configuration must be a dictionary: {path}")
        return data

    @staticmethod
    def _load_json(path: Path) -> Any:
        if not path.exists():
            raise FileNotFoundError(f"JSON file not found: {path}")
        return json.loads(path.read_text(encoding="utf-8"))

    # ========================================================
    # EXTRACT TOOL DEFINITIONS
    # ========================================================

    def _extract_tool_definitions(self) -> list[dict[str, Any]]:
        data = self.tools_definition

        if isinstance(data, dict):
            candidates = data.get("tools") or data.get("functions") or data.get("enabled_tools") or []
        elif isinstance(data, list):
            candidates = data
        else:
            candidates = []

        definitions: list[dict[str, Any]] = []

        if isinstance(candidates, dict):
            for name, definition in candidates.items():
                if not isinstance(definition, dict):
                    continue
                item = dict(definition)
                item.setdefault("name", name)
                definitions.append(item)

        elif isinstance(candidates, list):
            definitions = [item for item in candidates if isinstance(item, dict)]

        # Built-in schemas fill gaps while JSON remains the primary source.
        by_name = {item.get("name"): item for item in definitions if item.get("name")}
        for name, schema in TOOL_SCHEMAS.items():
            if name not in by_name:
                definitions.append(dict(schema))

        return definitions

    # ========================================================
    # CONFIGURATION VALIDATION
    # ========================================================

    def _validate_configuration(self) -> None:
        if not self.enabled_tools:
            raise RuntimeError("No financial tools are enabled. Check agent_config.yaml.")

        definitions = self._extract_tool_definitions()
        definition_names = {item.get("name") for item in definitions if item.get("name")}

        missing = [name for name in self.enabled_tools if name not in definition_names]
        if missing:
            raise RuntimeError(
                "The following enabled tools are missing from financial_tools.json / built-in schemas: "
                f"{missing}"
            )

        unknown = [name for name in self.enabled_tools if name not in TOOL_FUNCTIONS]
        if unknown:
            raise RuntimeError(
                "The following configured tools do not exist in TOOL_FUNCTIONS: "
                f"{unknown}"
            )

    # ========================================================
    # DATA BOUNDARY
    # ========================================================

    def _get_data_boundary(self) -> dict[str, Any]:
        return get_financial_data_coverage()

    def _latest_actual_date(self) -> str | None:
        boundary = self.data_boundary if isinstance(self.data_boundary, dict) else {}
        latest = boundary.get("latest_actual_date") or boundary.get("max_date")
        if latest:
            return str(latest)
        available = boundary.get("available_data", {})
        if isinstance(available, dict):
            return available.get("date_to")
        return None

    # ========================================================
    # NUMERIC SAFETY
    # ========================================================

    def _validate_numeric_values(self, value: Any, path: str = "result") -> None:
        if isinstance(value, float):
            if not math.isfinite(value):
                raise ValueError(f"Non-finite numeric value detected at {path}.")
            return

        if isinstance(value, dict):
            for key, item in value.items():
                self._validate_numeric_values(item, f"{path}.{key}")
            return

        if isinstance(value, (list, tuple)):
            for index, item in enumerate(value):
                self._validate_numeric_values(item, f"{path}[{index}]")

    # ========================================================
    # NUMBER HELPERS
    # ========================================================

    @staticmethod
    def _as_number(value: Any) -> float | None:
        if value is None:
            return None
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            return None
        return numeric if math.isfinite(numeric) else None

    @staticmethod
    def _numbers_close(actual: float, expected: float, tolerance: float = 0.01) -> bool:
        difference = abs(actual - expected)
        scale = max(1.0, abs(actual), abs(expected))
        return difference <= max(tolerance, scale * 1e-8)

    # ========================================================
    # COMPARISON MATH VALIDATION
    # ========================================================

    def _validate_comparison_math(self, result: dict[str, Any]) -> tuple[bool, str | None]:
        period_1 = result.get("period_1")
        period_2 = result.get("period_2")

        value_1 = self._as_number(period_1.get("value")) if isinstance(period_1, dict) else None
        value_2 = self._as_number(period_2.get("value")) if isinstance(period_2, dict) else None

        if value_1 is None:
            value_1 = self._as_number(result.get("period_1_value"))
        if value_2 is None:
            value_2 = self._as_number(result.get("period_2_value"))

        if value_1 is None or value_2 is None:
            comparisons = result.get("comparisons")
            if isinstance(comparisons, list):
                target_currency = result.get("currency")
                selected = None
                for item in comparisons:
                    if not isinstance(item, dict):
                        continue
                    if target_currency and item.get("currency") == target_currency:
                        selected = item
                        break
                    if selected is None:
                        selected = item

                if isinstance(selected, dict):
                    if value_1 is None:
                        value_1 = self._as_number(selected.get("period_1_value"))
                    if value_2 is None:
                        value_2 = self._as_number(selected.get("period_2_value"))

        if value_1 is None or value_2 is None:
            return True, "Comparison values not available for independent recalculation."

        expected_absolute = value_2 - value_1
        actual_absolute = self._as_number(result.get("absolute_change"))
        if actual_absolute is None:
            return False, "Comparison absolute_change is missing."

        if not self._numbers_close(actual_absolute, expected_absolute, tolerance=0.01):
            return False, (
                "Comparison absolute_change mismatch. "
                f"Expected={expected_absolute:.2f}, Actual={actual_absolute:.2f}"
            )

        actual_percentage = self._as_number(result.get("percentage_change"))
        if value_1 == 0:
            if actual_percentage is not None:
                return False, "Comparison percentage_change must be null when period_1 value is zero."
        else:
            expected_percentage = expected_absolute / abs(value_1) * 100
            if actual_percentage is None:
                return False, "Comparison percentage_change is missing."
            if not self._numbers_close(actual_percentage, expected_percentage, tolerance=0.01):
                return False, (
                    "Comparison percentage_change mismatch. "
                    f"Expected={expected_percentage:.2f}, Actual={actual_percentage:.2f}"
                )

        return True, None

    # ========================================================
    # FORECAST MATH VALIDATION
    # ========================================================

    def _validate_forecast_math(self, result: dict[str, Any]) -> tuple[bool, str | None]:
        method = result.get("method") or result.get("forecast_method")
        if isinstance(method, str) and method.lower() not in {"trailing moving average", "trailing_moving_average"}:
            return True, None

        history = result.get("historical_periods")
        actual_forecast = self._as_number(result.get("forecast_value"))

        if not isinstance(history, list) or not history:
            canonical = result.get("canonical_forecast")
            if isinstance(canonical, dict):
                history = canonical.get("historical_periods")
                if actual_forecast is None:
                    actual_forecast = self._as_number(canonical.get("forecast_value"))

        if not isinstance(history, list) or not history:
            source_values = result.get("source_values")
            if isinstance(source_values, list):
                history = [{"value": item} for item in source_values]

        if not isinstance(history, list) or not history:
            return True, "Forecast historical values not available for independent recalculation."

        values: list[float] = []
        for row in history:
            if not isinstance(row, dict):
                return False, "Invalid historical forecast row."
            value = self._as_number(row.get("value"))
            if value is None:
                return False, "Invalid historical forecast value."
            values.append(value)

        if not values:
            return False, "Forecast historical values are empty."
        if actual_forecast is None:
            return False, "Forecast value is missing."

        expected_forecast = sum(values) / len(values)
        if not self._numbers_close(actual_forecast, expected_forecast, tolerance=0.01):
            return False, (
                "Forecast arithmetic mismatch. "
                f"Expected={expected_forecast:.2f}, Actual={actual_forecast:.2f}"
            )

        return True, None

    # ========================================================
    # DRIVER MATH VALIDATION
    # ========================================================

    def _validate_driver_math(self, result: dict[str, Any]) -> tuple[bool, str | None]:
        drivers = result.get("drivers")
        actual_change = self._as_number(result.get("absolute_change"))

        if not isinstance(drivers, list) or not drivers:
            return True, "Driver contribution structure not available."
        if actual_change is None:
            return False, "Driver absolute_change is missing."

        total_driver_change = 0.0
        for driver in drivers:
            if not isinstance(driver, dict):
                return False, "Invalid driver row."

            change = self._as_number(driver.get("change"))
            if change is None:
                return False, "Driver change is missing."

            total_driver_change += change
            contribution = self._as_number(driver.get("contribution_percentage"))

            if contribution is not None and actual_change != 0:
                expected_contribution = change / actual_change * 100
                if not self._numbers_close(contribution, expected_contribution, tolerance=0.02):
                    return False, (
                        "Driver contribution percentage mismatch. "
                        f"Expected={expected_contribution:.2f}, Actual={contribution:.2f}"
                    )

        if not self._numbers_close(total_driver_change, actual_change, tolerance=0.02):
            return False, (
                "Driver changes do not reconcile to total change. "
                f"Drivers={total_driver_change:.2f}, Total={actual_change:.2f}"
            )

        return True, None

    # ========================================================
    # RATIO MATH VALIDATION
    # ========================================================

    def _validate_ratio_math(self, result: dict[str, Any]) -> tuple[bool, str | None]:
        if result.get("status") != "success":
            return True, None

        inputs = result.get("inputs", {})
        ratios = result.get("ratios", {})
        if not isinstance(inputs, dict) or not isinstance(ratios, dict):
            return False, "Financial ratio result must contain inputs and ratios dictionaries."

        inflows = self._as_number(inputs.get("total_inflows"))
        outflows = self._as_number(inputs.get("total_outflows"))
        net_cash_flow = self._as_number(inputs.get("net_cash_flow"))
        fees = self._as_number(inputs.get("fees"))
        refunds = self._as_number(inputs.get("refunds"))
        total_tx = self._as_number(inputs.get("total_transactions"))
        completed = self._as_number(inputs.get("completed_transactions"))
        pending = self._as_number(inputs.get("pending_transactions"))
        failed = self._as_number(inputs.get("failed_transactions"))
        reversed_tx = self._as_number(inputs.get("reversed_transactions"))

        values = {
            "total_inflows": inflows,
            "total_outflows": outflows,
            "net_cash_flow": net_cash_flow,
            "fees": fees,
            "refunds": refunds,
            "total_transactions": total_tx,
            "completed_transactions": completed,
            "pending_transactions": pending,
            "failed_transactions": failed,
            "reversed_transactions": reversed_tx,
        }
        if any(value is None for value in values.values()):
            return False, "Financial ratio inputs contain invalid numeric values."

        assert inflows is not None
        assert outflows is not None
        assert net_cash_flow is not None
        assert fees is not None
        assert refunds is not None
        assert total_tx is not None
        assert completed is not None
        assert pending is not None
        assert failed is not None
        assert reversed_tx is not None

        reconciliation = result.get("data_quality", {}).get("flow_reconciliation", {})
        if isinstance(reconciliation, dict):
            calculated_net = self._as_number(reconciliation.get("calculated_net_from_flows"))
            reported_net = self._as_number(reconciliation.get("reported_net_cash_flow"))
            reported_gap = self._as_number(reconciliation.get("gap"))

            if calculated_net is not None and reported_net is not None and reported_gap is not None:
                expected_gap = calculated_net - reported_net
                if not self._numbers_close(reported_gap, expected_gap, tolerance=0.01):
                    return False, (
                        "Financial ratio flow reconciliation metadata is inconsistent. "
                        f"Expected gap={expected_gap:.2f}, Actual gap={reported_gap:.2f}"
                    )

        checks = [
            ("inflow_outflow_ratio", None if outflows == 0 else inflows / outflows),
            ("net_cash_flow_margin_percentage", None if inflows == 0 else (net_cash_flow / inflows) * 100),
            ("refund_rate_percentage", None if inflows == 0 else (refunds / inflows) * 100),
            ("fee_rate_percentage", None if outflows == 0 else (fees / outflows) * 100),
            ("transaction_success_rate_percentage", None if total_tx == 0 else (completed / total_tx) * 100),
            ("failed_transaction_rate_percentage", None if total_tx == 0 else (failed / total_tx) * 100),
            ("pending_transaction_rate_percentage", None if total_tx == 0 else (pending / total_tx) * 100),
            ("reversed_transaction_rate_percentage", None if total_tx == 0 else (reversed_tx / total_tx) * 100),
        ]

        for key, expected in checks:
            actual = self._as_number(ratios.get(key))
            if expected is None:
                if actual is not None:
                    return False, f"Ratio {key} should be null because its denominator is zero."
                continue
            if actual is None:
                return False, f"Ratio {key} is missing."
            if not self._numbers_close(actual, expected, tolerance=0.02):
                return False, (
                    f"Ratio {key} mismatch. "
                    f"Expected={expected:.4f}, Actual={actual:.4f}"
                )

        return True, None

    # ========================================================
    # FINANCIAL MATH VALIDATION DISPATCHER
    # ========================================================

    def _validate_financial_math(self, tool_name: str, result: dict[str, Any]) -> tuple[bool, str | None]:
        if tool_name == "compare_financial_periods":
            return self._validate_comparison_math(result)
        if tool_name == "forecast_financial_kpi":
            return self._validate_forecast_math(result)
        if tool_name == "analyze_cash_flow_drivers":
            return self._validate_driver_math(result)
        if tool_name == "analyze_financial_ratios":
            return self._validate_ratio_math(result)
        return True, None

    # ========================================================
    # TOOL RESULT VALIDATION
    # ========================================================

    def _validate_tool_result(self, tool_name: str, result: Any) -> tuple[bool, str]:
        if not isinstance(result, dict):
            raise ValueError(f"Tool {tool_name} returned a non-dictionary result.")

        self._validate_numeric_values(result)

        status = result.get("status")
        if status not in {"success", "no_data", "error", "insufficient_data"}:
            raise ValueError(f"Tool {tool_name} returned an invalid status: {status}")

        if status == "no_data":
            return True, "ACCEPTED (no_data)"

        if status == "insufficient_data":
            return True, "ACCEPTED (insufficient_data)"

        if status == "error":
            error_message = result.get("error") or result.get("message") or "Unknown tool error."
            raise RuntimeError(f"Tool {tool_name} returned error: {error_message}")

        result_currency = result.get("currency")
        if result_currency is not None:
            normalized_currency = str(result_currency).strip().upper()
            if normalized_currency not in ALLOWED_CURRENCIES:
                raise ValueError(f"Tool {tool_name} returned unsupported currency: {result_currency}")

        if tool_name == "forecast_financial_kpi":
            if result.get("is_forecast") is not True:
                raise ValueError("forecast_financial_kpi must mark is_forecast=true.")

        latest_actual = self._latest_actual_date()
        requested_period = result.get("requested_period")
        if latest_actual and isinstance(requested_period, dict):
            requested_to = requested_period.get("date_to")
            if requested_to and requested_to > latest_actual:
                result.setdefault("data_quality", {})
                if isinstance(result["data_quality"], dict):
                    result["data_quality"]["requested_period_beyond_latest_actual"] = True

        math_ok, math_message = self._validate_financial_math(tool_name, result)
        if not math_ok:
            raise ValueError(f"MATH VALIDATION FAILED: {math_message}")

        return True, "SUCCESS" if not math_message else math_message

    # ========================================================
    # CURRENCY EXTRACTION
    # ========================================================

    @staticmethod
    def _extract_currency(question: str) -> str | None:
        """Extract currency from English, symbols, or Arabic wording."""
        text = str(question or "").strip()
        question_upper = text.upper()

        # Exact ISO codes.
        for currency in sorted(ALLOWED_CURRENCIES, key=len, reverse=True):
            if re.search(rf"(?<![A-Z]){re.escape(currency)}(?![A-Z])", question_upper):
                return currency

        # English / symbol aliases.
        aliases = {
            "$": "USD",
            "DOLLARS": "USD",
            "DOLLAR": "USD",
            "US DOLLARS": "USD",
            "US DOLLAR": "USD",
            "EUROS": "EUR",
            "EURO": "EUR",
            "POUNDS": "GBP",
            "POUND": "GBP",
            "STERLING": "GBP",
            "YEN": "JPY",
            "CANADIAN DOLLAR": "CAD",
            "AUSTRALIAN DOLLAR": "AUD",
            "€": "EUR",
            "£": "GBP",
        }

        # Arabic aliases, including common Egyptian wording.
        aliases.update({
            "الدولار الأمريكي": "USD",
            "دولار أمريكي": "USD",
            "الدولار الامريكي": "USD",
            "دولار امريكي": "USD",
            "الدولار": "USD",
            "دولار": "USD",
            "اليورو": "EUR",
            "يورو": "EUR",
            "الجنيه الإسترليني": "GBP",
            "جنيه إسترليني": "GBP",
            "الجنيه الاسترليني": "GBP",
            "جنيه استرليني": "GBP",
            "الجنيه": "GBP",
            "جنيه": "GBP",
            "الين الياباني": "JPY",
            "ين ياباني": "JPY",
            "الين": "JPY",
            "ين": "JPY",
            "الدولار الكندي": "CAD",
            "دولار كندي": "CAD",
            "الدولار الأسترالي": "AUD",
            "دولار أسترالي": "AUD",
            "الدولار الاسترالي": "AUD",
            "دولار استرالي": "AUD",
        })

        for alias, code in sorted(aliases.items(), key=lambda item: len(item[0]), reverse=True):
            if alias and alias.upper() in question_upper if alias.isascii() else alias in text:
                return code

        return None

    # ========================================================
    # MONTH PERIOD EXTRACTION
    # ========================================================

    @staticmethod
    def _extract_month_periods(question: str) -> list[dict[str, str]]:
        """Extract ISO, English, and Arabic month/year expressions."""
        text = str(question or "")

        english_months = {
            "january": 1, "jan": 1,
            "february": 2, "feb": 2,
            "march": 3, "mar": 3,
            "april": 4, "apr": 4,
            "may": 5,
            "june": 6, "jun": 6,
            "july": 7, "jul": 7,
            "august": 8, "aug": 8,
            "september": 9, "sep": 9, "sept": 9,
            "october": 10, "oct": 10,
            "november": 11, "nov": 11,
            "december": 12, "dec": 12,
        }

        arabic_months = {
            "يناير": 1, "كانون الثاني": 1,
            "فبراير": 2, "شباط": 2,
            "مارس": 3, "آذار": 3,
            "أبريل": 4, "ابريل": 4, "نيسان": 4,
            "مايو": 5, "أيار": 5,
            "يونيو": 6, "يونيه": 6, "حزيران": 6,
            "يوليو": 7, "يوليه": 7, "تموز": 7,
            "أغسطس": 8, "اغسطس": 8, "آب": 8,
            "سبتمبر": 9, "أيلول": 9,
            "أكتوبر": 10, "اكتوبر": 10, "تشرين الأول": 10,
            "نوفمبر": 11, "تشرين الثاني": 11,
            "ديسمبر": 12, "كانون الأول": 12,
        }

        matches: list[tuple[int, dict[str, str]]] = []

        # ISO dates: YYYY-MM-DD.
        iso_pattern = re.compile(r"\b(20\d{2})-(\d{2})-(\d{2})\b")
        for match in iso_pattern.finditer(text):
            year, month, day = map(int, match.groups())
            try:
                last_day = calendar.monthrange(year, month)[1]
                day = min(day, last_day)
                matches.append((match.start(), {
                    "date_from": f"{year:04d}-{month:02d}-01",
                    "date_to": f"{year:04d}-{month:02d}-{day:02d}",
                }))
            except ValueError:
                continue

        # English month + year.
        month_names = "|".join(sorted(english_months, key=len, reverse=True))
        month_pattern = re.compile(rf"\b({month_names})\s+(20\d{{2}})\b", re.IGNORECASE)
        for match in month_pattern.finditer(text):
            month_number = english_months[match.group(1).lower()]
            year = int(match.group(2))
            last_day = calendar.monthrange(year, month_number)[1]
            matches.append((match.start(), {
                "date_from": f"{year:04d}-{month_number:02d}-01",
                "date_to": f"{year:04d}-{month_number:02d}-{last_day:02d}",
            }))

        # Arabic month + year. We intentionally use substring matching rather than \b
        # because Arabic word-boundary behaviour can vary across regex engines.
        arabic_months_sorted = sorted(arabic_months.items(), key=lambda item: len(item[0]), reverse=True)
        for month_name, month_number in arabic_months_sorted:
            pattern = re.compile(rf"(?<!\w){re.escape(month_name)}\s*(20\d{{2}})(?!\d)")
            for match in pattern.finditer(text):
                year = int(match.group(1))
                last_day = calendar.monthrange(year, month_number)[1]
                matches.append((match.start(), {
                    "date_from": f"{year:04d}-{month_number:02d}-01",
                    "date_to": f"{year:04d}-{month_number:02d}-{last_day:02d}",
                }))

        matches.sort(key=lambda item: item[0])

        result: list[dict[str, str]] = []
        seen: set[tuple[str, str]] = set()
        for _, period in matches:
            key = (period["date_from"], period["date_to"])
            if key in seen:
                continue
            seen.add(key)
            result.append(period)

        return result

    # ========================================================
    # METRIC INFERENCE
    # ========================================================

    @staticmethod
    def _infer_metric_from_question(question: str) -> str | None:
        text = str(question or "").strip().lower()

        if any(token in text for token in [
            "net cash flow", "net cashflow", "cash flow", "cashflow",
            "صافي التدفق النقدي", "التدفق النقدي الصافي", "التدفق النقدي",
        ]):
            return "net_cash_flow"

        if any(token in text for token in [
            "average transaction amount", "avg transaction amount",
            "average transaction", "avg transaction",
            "متوسط قيمة المعاملة", "متوسط مبلغ المعاملة", "متوسط المعاملة",
        ]):
            return "average_transaction_amount"

        if any(token in text for token in [
            "transaction count", "transaction counts",
            "number of transactions", "number of transaction",
            "عدد المعاملات", "عدد المعاملة",
        ]):
            return "transactions"

        if any(token in text for token in [
            "completed transactions", "completed transaction",
            "المعاملات المكتملة", "المعاملات الناجحة",
        ]):
            return "completed_transactions"

        if any(token in text for token in [
            "pending transactions", "pending transaction",
            "المعاملات المعلقة", "المعاملات المعلّقة",
        ]):
            return "pending_transactions"

        if any(token in text for token in [
            "failed transactions", "failed transaction",
            "المعاملات الفاشلة", "المعاملات التي فشلت",
        ]):
            return "failed_transactions"

        if any(token in text for token in [
            "reversed transactions", "reversed transaction",
            "المعاملات المعكوسة", "المعاملات المعكوسه", "المعاملات المرتجعة",
        ]):
            return "reversed_transactions"

        if any(token in text for token in [
            "active accounts", "active account", "distinct accounts",
            "الحسابات النشطة", "الحسابات النشطه", "حسابات نشطة",
        ]):
            return "active_accounts"

        if any(token in text for token in [
            "total inflows", "total inflow", "inflows", "inflow",
            "إجمالي التدفقات الداخلة", "التدفقات الداخلة", "التدفقات الواردة",
            "التدفقات الداخله", "التدفقات الوارده",
        ]):
            return "total_inflows"

        if any(token in text for token in [
            "total outflows", "total outflow", "outflows", "outflow",
            "إجمالي التدفقات الخارجة", "التدفقات الخارجة", "التدفقات الصادرة",
            "التدفقات الخارجه", "التدفقات الصادره",
        ]):
            return "total_outflows"

        if any(token in text for token in ["fees", "fee", "الرسوم", "رسوم"]):
            return "fees"

        if any(token in text for token in [
            "refunds", "refund", "المرتجعات", "مرتجعات", "المبالغ المستردة", "المبالغ المسترده",
        ]):
            return "refunds"

        if any(token in text for token in ["transfers", "transfer", "التحويلات", "تحويلات"]):
            return "transfers"

        if "transactions" in text or "المعاملات" in text:
            return "transactions"

        return None

    # ========================================================
    # LOOKBACK INFERENCE
    # ========================================================

    @staticmethod
    def _infer_lookback_months(question: str) -> int | None:
        text = question.strip().lower()
        patterns = [
            r"last\s+(\d+)\s+(?:completed\s+)?months?",
            r"past\s+(\d+)\s+months?",
            r"previous\s+(\d+)\s+months?",
            r"prior\s+(\d+)\s+months?",
            r"آخر\s+(\d+)\s+شهور",
            r"آخر\s+(\d+)\s+أشهر",
            r"خلال\s+(?:آخر|الـ)\s*(\d+)\s+(?:شهور|أشهر|شهر)",
            r"على\s+مدى\s+(\d+)\s+(?:شهور|أشهر|شهر)",
        ]

        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                try:
                    value = int(match.group(1))
                except ValueError:
                    continue
                return max(1, min(value, 24))

        return None

    # ========================================================
    # FOLLOW-UP DETECTION
    # ========================================================

    def _is_follow_up_question(self, question: str) -> bool:
        if not self.last_question:
            return False
        text = question.strip().lower()
        if not text:
            return False
        patterns = [
            "why", "and why", "what caused it", "what caused that",
            "what was the biggest driver", "what was the main driver",
            "which was the biggest driver", "which was the main driver",
            "what about", "and what about", "how about", "based on",
            "those months", "those three months", "the three months",
            "what was the average", "what were those", "same period",
            "same periods", "that result", "this result",
            "what does that mean", "what does this mean", "explain that",
            "explain this", "what happened next", "what should we expect next",
            "what about next month",
            "لماذا", "ولماذا", "ليه", "ليه؟", "ما السبب", "ما السبب؟",
            "إيه السبب", "ايه السبب", "ما سبب ذلك", "ما الذي تسبب",
            "ما أكبر محرك", "ما اكبر محرك", "المحرك الأكبر", "المحرك الاكبر",
            "المحرك الرئيسي", "أكبر سبب", "اكبر سبب",
            "ماذا عن", "ماذا تعني", "ماذا يعني ذلك", "ماذا حدث",
            "وماذا بعد", "ماذا نتوقع", "ماذا نتوقع الشهر القادم",
            "ماذا عن الشهر القادم", "بناءً على ذلك", "بناء على ذلك",
        ]
        if any(p in text for p in patterns):
            return True
        words = re.findall(r"\b\w+\b", text)
        return len(words) <= 4 and any(
            token in text
            for token in ["why", "driver", "ratio", "anomaly", "forecast", "next", "result", "mean", "difference", "change"]
        )

    def _infer_follow_up_intent(self, question: str) -> str:
        text = question.strip().lower()
        if self._has_any(text, [
            "forecast", "next month", "next period", "what should we expect", "what to expect",
            "expected", "projection", "projected", "توقع", "التوقع", "تنبؤ", "التنبؤ",
            "الشهر القادم", "الشهر المقبل", "الشهر التالي", "ماذا نتوقع"
        ]):
            return "forecast"
        if self._has_any(text, [
            "anomaly", "anomalies", "outlier", "outliers", "unusual", "abnormal", "abnormally",
            "شذوذ", "شذوذات", "قيمة شاذة", "قيم شاذة", "غير معتاد", "غير عادي", "حالات غير معتادة"
        ]):
            return "anomaly"
        if self._has_any(text, [
            "ratio", "ratios", "rate", "rates", "margin", "refund rate", "fee rate",
            "success rate", "failure rate", "inflow/outflow", "نسبة", "معدل", "هامش",
            "مؤشرات الصحة", "المؤشرات المالية", "الصحة المالية"
        ]):
            return "ratio"
        if self._has_any(text, [
            "compare", "comparison", "versus", " vs ", "difference", "changed from", "change from",
            "how did it change", "مقارنة", "قارن", "الفرق", "الفرق بين", "التغير", "التغير بين", "مقابل"
        ]):
            return "comparison"
        if self._has_any(text, [
            "trend", "monthly", "month by month", "over time", "time series", "month over month",
            "اتجاه", "اتجاه شهري", "شهري", "شهريا", "شهرياً", "على مدار الأشهر", "بمرور الوقت"
        ]):
            return "trend"
        if self._has_any(text, [
            "driver", "drivers", "why", "what caused", "reason", "what made it", "why did it", "why has it",
            "محرك", "المحركات", "سبب", "الأسباب", "السبب", "لماذا", "ليه", "ما الذي تسبب"
        ]):
            return "driver"
        if self._has_any(text, [
            "summarize", "summary", "overall", "what does that mean", "what does this mean",
            "explain that", "explain this", "give me the takeaway", "takeaway",
            "لخص", "تلخيص", "الخلاصة", "بشكل عام", "ماذا يعني ذلك", "اشرح ذلك", "وضح لي"
        ]):
            return "summary"
        return "context"

    def _select_follow_up_tools(self, question: str) -> list[str]:
        mapping = {
            "forecast": "forecast_financial_kpi",
            "anomaly": "detect_financial_anomalies",
            "ratio": "analyze_financial_ratios",
            "comparison": "compare_financial_periods",
            "trend": "analyze_financial_trend",
            "driver": "analyze_cash_flow_drivers",
        }
        tool_name = mapping.get(self._infer_follow_up_intent(question))
        return [tool_name] if tool_name in self.enabled_tools else []

    def _has_verified_tool(self, tool_name: str) -> bool:
        return any(isinstance(item, dict) and item.get("tool_name") == tool_name for item in self.last_verified_results)

    def _can_answer_follow_up_from_context(self, question: str) -> bool:
        if not self.last_question or not self.last_verified_results or not self._is_follow_up_question(question):
            return False
        intent = self._infer_follow_up_intent(question)
        if intent in {"summary", "context"}:
            return bool(self.last_health_findings) or self.last_analysis_mode == "compound_financial_analysis"
        mapping = {
            "forecast": "forecast_financial_kpi",
            "anomaly": "detect_financial_anomalies",
            "ratio": "analyze_financial_ratios",
            "comparison": "compare_financial_periods",
            "trend": "analyze_financial_trend",
            "driver": "analyze_cash_flow_drivers",
        }
        return self._has_verified_tool(mapping.get(intent, ""))

    def _previous_tool_arguments(self, tool_name: str) -> dict[str, Any]:
        for item in reversed(self.last_verified_results):
            if isinstance(item, dict) and item.get("tool_name") == tool_name and isinstance(item.get("arguments"), dict):
                return dict(item["arguments"])
        return {}

    def _context_periods_for_follow_up(self, question: str) -> list[dict[str, str]]:
        periods = self._extract_month_periods(question)
        if periods:
            return periods
        if self.last_question:
            periods = self._extract_month_periods(self.last_question)
            if periods:
                return periods
        return []

    def _record_session_turn(self, question: str, answer: str, verified_results: list[dict[str, Any]]) -> None:
        self.session_turn_id += 1
        self.last_response_text = answer
        self.session_history.append({
            "turn": self.session_turn_id,
            "question": question,
            "analysis_mode": self.last_analysis_mode,
            "tools": list(self.last_tool_names),
            "answer": answer,
            "result_count": len(verified_results),
        })
        self.session_history = self.session_history[-20:]

    def _suggest_follow_up_questions(self) -> list[str]:
        if not self.last_verified_results:
            return []
        tools = {item.get("tool_name") for item in self.last_verified_results if isinstance(item, dict)}
        currency = self._extract_currency(self.last_question or "") or self._extract_currency(self.last_question or "") or "USD"
        if self.response_language == "ar":
            suggestions: list[str] = []
            if "analyze_cash_flow_drivers" in tools:
                suggestions.append("ما أكبر محرك للتغير؟")
            if "analyze_financial_ratios" in tools:
                suggestions.append(f"ماذا تعني مؤشرات الصحة المالية للعملة {currency}؟")
            if "detect_financial_anomalies" in tools:
                suggestions.append("هل توجد أيام غير معتادة؟")
            if "forecast_financial_kpi" in tools:
                suggestions.append("كيف يقارن التوقع بالشهر الفعلي الأخير؟")
            if "analyze_financial_trend" in tools:
                suggestions.append("ما أكبر تغير خلال فترة الاتجاه؟")
            if "compare_financial_periods" in tools:
                suggestions.append("ما الذي تغير بين الفترتين؟")
            return suggestions[:4]

        suggestions = []
        if "analyze_cash_flow_drivers" in tools:
            suggestions.append("What was the biggest driver of the change?")
        if "analyze_financial_ratios" in tools:
            suggestions.append(f"What do the {currency} health indicators imply?")
        if "detect_financial_anomalies" in tools:
            suggestions.append("Were there any unusual days?")
        if "forecast_financial_kpi" in tools:
            suggestions.append("How does the forecast compare with the latest actual?")
        if "analyze_financial_trend" in tools:
            suggestions.append("What changed the most over the trend period?")
        if "compare_financial_periods" in tools:
            suggestions.append("What changed between the two periods?")
        return suggestions[:4]

    # ========================================================
    # SMART CLI HELPERS
    # ========================================================

    def print_smart_help(self) -> None:
        print()
        print("AI Finance Analyst commands")
        print("  /help      Show this help")
        print("  /status    Show current session state")
        print("  /history   Show recent questions")
        print("  /suggest   Show suggested follow-up questions")
        print("  /boundary  Show verified actual data boundary")
        print("  /tools     Show enabled tools")
        print("  /clear     Clear follow-up context")
        print("  /last      Show the previous answer")
        print("  /exit      Exit the analyst")

    def print_smart_status(self) -> None:
        available = self.data_boundary.get("available_data", {})
        print()
        print("+" + "-" * 68 + "+")
        print("| AI FINANCE ANALYST - SESSION STATUS".ljust(69) + "|")
        print("+" + "-" * 68 + "+")
        print(f"| Mode       : {self.last_analysis_mode}".ljust(69) + "|")
        print(f"| Turn       : {self.session_turn_id}".ljust(69) + "|")
        tools = ", ".join(self.last_tool_names) or "None"
        print(f"| Last tools : {tools}"[:68].ljust(69) + "|")
        print(f"| Data range : {available.get('date_from')} to {available.get('date_to')}".ljust(69) + "|")
        print(f"| Last Q     : {(self.last_question or 'None')[:55]}".ljust(69) + "|")
        print("+" + "-" * 68 + "+")

    def print_smart_history(self) -> None:
        print()
        if not self.session_history:
            print("No session history yet.")
            return
        print("Recent session questions:")
        for item in self.session_history[-8:]:
            print(f"  [{item.get('turn')}] {item.get('analysis_mode')}: {item.get('question')}")

    def print_smart_suggestions(self) -> None:
        suggestions = self._suggest_follow_up_questions()
        print()
        if not suggestions:
            print("No follow-up suggestions available yet.")
            return
        print("Suggested next questions:")
        for index, suggestion in enumerate(suggestions, start=1):
            print(f"  {index}. {suggestion}")

    def clear_conversation_context(self) -> None:
        self.last_question = None
        self.last_tool_names = []
        self.last_verified_results = []
        self.last_analysis_mode = "single_tool"
        self.current_health_findings = {}
        self.last_health_findings = {}
        self.last_response_text = None
        self.last_suggested_questions = []
        print("Conversation context cleared. Data boundary remains available from the database.")

    # ========================================================

    @staticmethod
    def _has_any(text: str, patterns: list[str]) -> bool:
        return any(pattern in text for pattern in patterns)

    def _is_compound_question(self, question: str) -> bool:
        text = question.strip().lower()

        compound_patterns = [
            "financial health",
            "health summary",
            "health analysis",
            "overall financial",
            "overall performance",
            "full financial analysis",
            "comprehensive financial",
            "executive financial analysis",
            "analyze financial performance",
            "analyse financial performance",
            "give me a complete analysis",
            "complete analysis",
            "what happened, why",
            "what happened and why",
            "main drivers, anomalies",
            "drivers, anomalies",
            "drivers and anomalies",
            "what to expect next month",
            "what should we expect next month",
            "تحليل شامل", "تحليل مالي شامل", "تحليل الأداء المالي",
            "تحليل الوضع المالي", "الأداء المالي", "الوضع المالي",
            "ماذا حدث ولماذا", "اشرح ما حدث", "اشرح ماذا حدث",
            "المحركات الرئيسية والشذوذ", "المحركات والشذوذ",
            "ما المتوقع الشهر القادم", "ماذا نتوقع الشهر القادم",
        ]

        return self._has_any(text, compound_patterns)

    def _default_primary_metric(self, question: str) -> str:
        metric = self._infer_metric_from_question(question)
        return metric or "net_cash_flow"

    # ========================================================
    # MONTH HELPERS
    # ========================================================

    @staticmethod
    def _first_day_of_previous_months(end_date_text: str, months_back: int) -> str:
        year, month, _ = map(int, end_date_text.split("-"))
        total_months = year * 12 + (month - 1) - months_back
        target_year = total_months // 12
        target_month = (total_months % 12) + 1
        return f"{target_year:04d}-{target_month:02d}-01"

    @classmethod
    def _forecast_history_start(cls, date_to_text: str, lookback_months: int) -> str:
        months_back = max(0, lookback_months - 1)
        return cls._first_day_of_previous_months(date_to_text, months_back)

    @staticmethod
    def _month_end_from_start(date_start: str) -> str:
        year, month, _ = map(int, date_start.split("-"))
        last_day = calendar.monthrange(year, month)[1]
        return f"{year:04d}-{month:02d}-{last_day:02d}"

    @staticmethod
    def _next_month_start(date_text: str) -> str:
        year, month, _ = map(int, date_text.split("-"))
        total = year * 12 + (month - 1) + 1
        next_year = total // 12
        next_month = total % 12 + 1
        return f"{next_year:04d}-{next_month:02d}-01"

    @staticmethod
    def _previous_month_period(date_start: str) -> dict[str, str]:
        year, month, _ = map(int, date_start.split("-"))
        total = year * 12 + (month - 1) - 1
        prev_year = total // 12
        prev_month = total % 12 + 1
        prev_start = f"{prev_year:04d}-{prev_month:02d}-01"
        prev_end = FinanceAgent._month_end_from_start(prev_start)
        return {"date_from": prev_start, "date_to": prev_end}

    # ========================================================
    # DETERMINISTIC ARGUMENT INFERENCE
    # ========================================================

    def _infer_tool_arguments(self, tool_name: str, question: str) -> dict[str, Any]:
        inferred: dict[str, Any] = {}

        if self._is_follow_up_question(question):
            previous_args = self._previous_tool_arguments(tool_name)
            for key, value in previous_args.items():
                if value not in (None, "", [], {}):
                    inferred[key] = value

        currency = self._extract_currency(question)
        if currency:
            inferred["currency"] = currency
        else:
            # Context fallback for short / Arabic questions that omit the currency.
            previous_currency = None
            for source_question in (question, self.last_question or ""):
                previous_currency = self._extract_currency(source_question)
                if previous_currency:
                    break
            if previous_currency:
                inferred["currency"] = previous_currency

        metric = self._infer_metric_from_question(question)
        if metric:
            inferred["metric"] = metric

        periods = self._extract_month_periods(question)
        latest_actual = self._latest_actual_date()

        # ----------------------------------------------------
        # Forecast
        # ----------------------------------------------------

        if tool_name == "forecast_financial_kpi":
            lookback = self._infer_lookback_months(question) or 3
            inferred["lookback_months"] = lookback

            if latest_actual:
                inferred["forecast_period"] = self._next_month_start(latest_actual)
                inferred["date_to"] = latest_actual

                if not inferred.get("metric"):
                    inferred["metric"] = "net_cash_flow"

            return inferred

        # ----------------------------------------------------
        # Comparison / Drivers
        # ----------------------------------------------------

        if tool_name in {"compare_financial_periods", "analyze_cash_flow_drivers"}:
            if len(periods) < 2:
                periods = self._context_periods_for_follow_up(question)

            if len(periods) >= 2:
                first = periods[0]
                second = periods[-1]
                inferred.update(
                    {
                        "period_1_from": first["date_from"],
                        "period_1_to": first["date_to"],
                        "period_2_from": second["date_from"],
                        "period_2_to": second["date_to"],
                    }
                )
            elif len(periods) == 1:
                current = periods[0]
                previous = self._previous_month_period(current["date_from"])
                inferred.update(
                    {
                        "period_1_from": previous["date_from"],
                        "period_1_to": previous["date_to"],
                        "period_2_from": current["date_from"],
                        "period_2_to": current["date_to"],
                    }
                )
            elif latest_actual:
                latest_start = latest_actual[:8] + "01"
                previous = self._previous_month_period(latest_start)
                inferred.update(
                    {
                        "period_1_from": previous["date_from"],
                        "period_1_to": previous["date_to"],
                        "period_2_from": latest_start,
                        "period_2_to": self._month_end_from_start(latest_start),
                    }
                )
            return inferred

        # ----------------------------------------------------
        # Ratio
        # ----------------------------------------------------

        if tool_name == "analyze_financial_ratios":
            if not periods:
                periods = self._context_periods_for_follow_up(question)
            if periods:
                target = periods[-1]
                inferred["date_from"] = target["date_from"]
                inferred["date_to"] = target["date_to"]
            elif latest_actual:
                latest_start = latest_actual[:8] + "01"
                inferred["date_from"] = latest_start
                inferred["date_to"] = latest_actual
            return inferred

        # ----------------------------------------------------
        # Trend
        # ----------------------------------------------------

        if tool_name == "analyze_financial_trend":
            if not periods:
                periods = self._context_periods_for_follow_up(question)
            if periods:
                inferred["date_from"] = periods[0]["date_from"]
                inferred["date_to"] = periods[-1]["date_to"]
            elif latest_actual:
                inferred["date_to"] = latest_actual
                inferred["date_from"] = self._first_day_of_previous_months(latest_actual, 5)

            if not inferred.get("metric"):
                inferred["metric"] = "net_cash_flow"

            return inferred

        # ----------------------------------------------------
        # Anomaly
        # ----------------------------------------------------

        if tool_name == "detect_financial_anomalies":
            if not periods:
                periods = self._context_periods_for_follow_up(question)
            if periods:
                target = periods[-1]
                inferred["date_from"] = target["date_from"]
                inferred["date_to"] = target["date_to"]
            elif latest_actual:
                latest_start = latest_actual[:8] + "01"
                inferred["date_from"] = latest_start
                inferred["date_to"] = latest_actual
            return inferred

        # ----------------------------------------------------
        # KPI
        # ----------------------------------------------------

        if tool_name == "get_financial_kpis":
            if not periods:
                periods = self._context_periods_for_follow_up(question)
            if periods:
                inferred["date_from"] = periods[0]["date_from"]
                inferred["date_to"] = periods[-1]["date_to"]
            elif latest_actual:
                latest_start = latest_actual[:8] + "01"
                inferred["date_from"] = latest_start
                inferred["date_to"] = latest_actual
            return inferred

        return inferred

    # ========================================================
    # NORMALIZE TOOL ARGUMENTS
    # ========================================================

    def _normalize_tool_arguments(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        question: str,
    ) -> dict[str, Any]:
        normalized = dict(arguments)
        inferred = self._infer_tool_arguments(tool_name, question)

        # Legacy aliases from an older agent version.
        alias_map = {
            "date_from_1": "period_1_from",
            "date_to_1": "period_1_to",
            "date_from_2": "period_2_from",
            "date_to_2": "period_2_to",
        }
        for old_key, new_key in alias_map.items():
            if new_key not in normalized and old_key in normalized:
                normalized[new_key] = normalized.pop(old_key)

        for key, value in inferred.items():
            if key not in normalized or normalized.get(key) in (None, "", [], {}):
                normalized[key] = value

        detected_currency = self._extract_currency(question)
        current_currency = normalized.get("currency")
        if detected_currency and not current_currency:
            normalized["currency"] = detected_currency
        elif current_currency:
            normalized["currency"] = str(current_currency).strip().upper()

        if not normalized.get("metric") and tool_name in {
            "get_financial_kpis",
            "compare_financial_periods",
            "analyze_financial_trend",
            "forecast_financial_kpi",
        }:
            normalized["metric"] = self._default_primary_metric(question)

        # ----------------------------------------------------
        # Forecast normalization
        # ----------------------------------------------------

        # ----------------------------------------------------
        # Required-argument safety net
        # ----------------------------------------------------
        # Gemini function calling can legally emit partial arguments. Never let
        # an incomplete call reach a Python tool and explode with a raw
        # "missing required positional argument" TypeError. We complete only
        # well-defined analytical arguments from context / actual boundary.
        required_by_tool = {
            "get_financial_kpis": {"currency", "date_from", "date_to"},
            "compare_financial_periods": {
                "currency", "metric", "period_1_from", "period_1_to",
                "period_2_from", "period_2_to",
            },
            "analyze_financial_trend": {"currency", "metric", "date_from", "date_to"},
            "detect_financial_anomalies": {"date_from", "date_to"},
            "analyze_cash_flow_drivers": {
                "currency", "period_1_from", "period_1_to",
                "period_2_from", "period_2_to",
            },
            "forecast_financial_kpi": {"currency", "metric", "forecast_period"},
            "analyze_financial_ratios": {"currency", "date_from", "date_to"},
        }

        required = required_by_tool.get(tool_name, set())
        latest_actual = self._latest_actual_date()

        if "currency" in required and not normalized.get("currency"):
            normalized["currency"] = self._extract_currency(question) or self._extract_currency(self.last_question or "") or "USD"

        if "metric" in required and not normalized.get("metric"):
            normalized["metric"] = self._infer_metric_from_question(question) or self._default_primary_metric(question)

        if latest_actual:
            if "date_from" in required and not normalized.get("date_from"):
                periods = self._extract_month_periods(question) or self._context_periods_for_follow_up(question)
                if periods:
                    normalized["date_from"] = periods[0]["date_from"]
                else:
                    normalized["date_from"] = latest_actual[:8] + "01"

            if "date_to" in required and not normalized.get("date_to"):
                periods = self._extract_month_periods(question) or self._context_periods_for_follow_up(question)
                if periods:
                    normalized["date_to"] = periods[-1]["date_to"]
                else:
                    normalized["date_to"] = latest_actual

            period_values = {
                "period_1_from", "period_1_to", "period_2_from", "period_2_to"
            } & required
            if period_values and not all(normalized.get(key) for key in period_values):
                periods = self._extract_month_periods(question) or self._context_periods_for_follow_up(question)
                if len(periods) >= 2:
                    p1, p2 = periods[0], periods[-1]
                elif len(periods) == 1:
                    p2 = periods[0]
                    p1 = self._previous_month_period(p2["date_from"])
                else:
                    latest_start = latest_actual[:8] + "01"
                    p2 = {"date_from": latest_start, "date_to": latest_actual}
                    p1 = self._previous_month_period(latest_start)

                normalized.setdefault("period_1_from", p1["date_from"])
                normalized.setdefault("period_1_to", p1["date_to"])
                normalized.setdefault("period_2_from", p2["date_from"])
                normalized.setdefault("period_2_to", p2["date_to"])

        missing_required = sorted(
            key for key in required if normalized.get(key) in (None, "", [], {})
        )
        if missing_required:
            raise ValueError(
                f"Unable to determine required arguments for {tool_name}: {missing_required}. "
                "Please specify the currency and period explicitly."
            )

        # ----------------------------------------------------
        # Forecast normalization
        # ----------------------------------------------------

        if tool_name == "forecast_financial_kpi":
            latest_actual = self._latest_actual_date()

            lookback = normalized.get("lookback_months") or self._infer_lookback_months(question) or 3
            try:
                lookback = int(lookback)
            except (TypeError, ValueError):
                lookback = 3
            lookback = max(1, min(lookback, 24))
            normalized["lookback_months"] = lookback

            forecast_period = normalized.get("forecast_period")
            if latest_actual:
                expected_next = self._next_month_start(latest_actual)
                if not forecast_period or forecast_period <= latest_actual:
                    forecast_period = expected_next

            if forecast_period:
                normalized["forecast_period"] = forecast_period

        return normalized

    # ========================================================
    # TOOL SELECTION
    # ========================================================

    def _select_tools_for_question(self, question: str) -> list[str]:
        text = question.strip().lower()

        # ----------------------------------------------------
        # Reuse verified context BEFORE intent-specific routing.
        # A short follow-up such as "why?" can otherwise be
        # routed directly to a single tool and lose the
        # authoritative KPI/comparison context from the prior
        # compound analysis.
        # ----------------------------------------------------
        if self._is_follow_up_question(question) and self._can_answer_follow_up_from_context(question):
            self.last_analysis_mode = "follow_up_contextual"
            return []

        selected: list[str] = []

        def add_tool(name: str) -> None:
            if name in self.enabled_tools and name not in selected:
                selected.append(name)

        compound = self._is_compound_question(question)
        periods = self._extract_month_periods(question)
        primary_metric = self._default_primary_metric(question)

        # ----------------------------------------------------
        # Compound financial-health / executive analysis
        # ----------------------------------------------------

        if compound:
            self.last_analysis_mode = "compound_financial_analysis"
            add_tool("get_financial_kpis")
            add_tool("analyze_financial_ratios")

            if len(periods) >= 2:
                add_tool("compare_financial_periods")
                add_tool("analyze_cash_flow_drivers")
                add_tool("analyze_financial_trend")
            elif len(periods) == 1:
                add_tool("compare_financial_periods")
                add_tool("analyze_cash_flow_drivers")
                add_tool("analyze_financial_trend")
            else:
                add_tool("compare_financial_periods")
                add_tool("analyze_cash_flow_drivers")
                add_tool("analyze_financial_trend")

            add_tool("detect_financial_anomalies")
            add_tool("forecast_financial_kpi")
            return selected

        self.last_analysis_mode = "single_tool"

        # ----------------------------------------------------
        # Forecast
        # ----------------------------------------------------

        forecast_patterns = [
            "forecast", "predict", "projection", "projected",
            "what could", "what would", "expected", "estimate",
            "estimated", "next month",
            "توقع", "توقعات", "تنبؤ", "التنبؤ", "الشهر القادم",
            "الشهر المقبل", "الشهر التالي", "ما المتوقع", "ماذا نتوقع",
        ]
        if self._has_any(text, forecast_patterns):
            add_tool("forecast_financial_kpi")

        # ----------------------------------------------------
        # Anomalies
        # ----------------------------------------------------

        anomaly_patterns = [
            "anomaly", "anomalies", "unusual", "outlier", "outliers",
            "abnormal", "abnormally", "unusual days",
            "شذوذ", "حالات شاذة", "قيمة شاذة", "قيم شاذة",
            "غير معتاد", "غير عادي", "أيام غير معتادة",
        ]
        if self._has_any(text, anomaly_patterns):
            add_tool("detect_financial_anomalies")

        # ----------------------------------------------------
        # Ratios / Financial health
        # ----------------------------------------------------

        ratio_patterns = [
            "ratio", "ratios", "rate", "rates", "margin", "margins",
            "success rate", "failure rate", "failed transaction rate",
            "pending rate", "reversed rate", "refund rate", "fee rate",
            "inflow outflow", "inflow/outflow", "financial health",
            "health summary", "health analysis",
            "نسبة", "نسب", "معدل", "معدلات", "هامش", "هوامش", "نجاح", "فشل",
            "مرتجع", "مرتجعات", "رسوم", "الصحة المالية", "الوضع المالي",
            "الأداء المالي", "المؤشرات المالية", "مؤشرات الصحة",
        ]
        if self._has_any(text, ratio_patterns):
            add_tool("analyze_financial_ratios")

        # ----------------------------------------------------
        # Driver analysis
        # ----------------------------------------------------

        driver_patterns = [
            "why did", "why has", "why have", "what caused",
            "what were the drivers", "main drivers", "drivers behind",
            "cash flow drivers", "reason for the change", "reasons for the change",
            "لماذا", "ليه", "ايه السبب", "إيه السبب", "ما السبب",
            "ما الذي تسبب", "ما هي الأسباب", "ما هي الاسباب",
            "المحركات الرئيسية", "أكبر محرك", "اكبر محرك",
        ]
        if self._has_any(text, driver_patterns):
            add_tool("analyze_cash_flow_drivers")

        # ----------------------------------------------------
        # Trend
        # ----------------------------------------------------

        trend_patterns = [
            "trend", "monthly trend", "month by month", "monthly",
            "monthly breakdown", "monthly performance", "monthly average",
            "over the months", "over time", "month over month", "mom",
            "time series",
            "اتجاه", "اتجاه شهري", "شهري", "شهريا", "شهرياً",
            "شهري من", "على مدار الأشهر", "بمرور الوقت",
        ]
        has_trend_intent = self._has_any(text, trend_patterns)
        if has_trend_intent:
            add_tool("analyze_financial_trend")

        # If several months are explicitly supplied, a trend is generally the
        # safest analytical primitive unless the user explicitly requests only a comparison.
        if len(periods) >= 3 and not has_trend_intent:
            add_tool("analyze_financial_trend")

        # ----------------------------------------------------
        # Comparison
        # ----------------------------------------------------

        comparison_patterns = [
            "compare", "comparison", "change from", "changed from",
            "difference between", "increase from", "decrease from",
            "versus", " vs ", "vs.",
            "قارن", "مقارنة", "مقارنة بين", "الفرق بين", "التغير بين",
            "تغير من", "تغير بين", "مقابل",
        ]
        has_explicit_comparison = self._has_any(text, comparison_patterns)
        if (
            has_explicit_comparison
            or (not has_trend_intent and self._has_any(text, ["how did", "how has", "how have"]))
        ):
            add_tool("compare_financial_periods")

        # ----------------------------------------------------
        # Follow-up
        # ----------------------------------------------------

        if not selected and self._is_follow_up_question(question):
            self.last_analysis_mode = "follow_up_contextual"
            for name in self._select_follow_up_tools(question):
                add_tool(name)
            if selected:
                return selected
            if self._can_answer_follow_up_from_context(question):
                return []

        # ----------------------------------------------------
        # Default KPI
        # ----------------------------------------------------

        if not selected:
            add_tool("get_financial_kpis")

        return selected

    # ========================================================
    # EXECUTE TOOL
    # ========================================================

    def _execute_tool(self, tool_name: str, arguments: dict[str, Any] | None) -> Any:
        if tool_name not in TOOL_FUNCTIONS:
            raise ValueError(f"Unsupported tool: {tool_name}")

        if arguments is None:
            arguments = {}
        if not isinstance(arguments, dict):
            raise ValueError(f"Tool arguments for {tool_name} must be a dictionary.")

        return TOOL_FUNCTIONS[tool_name](**arguments)

    # ========================================================
    # COMPOUND TOOL ARGUMENT PLANS
    # ========================================================

    def _build_compound_arguments(
        self,
        tool_name: str,
        question: str,
    ) -> dict[str, Any]:
        """
        Build complete arguments for compound analysis without relying on Gemini
        to choose only one tool. This makes multi-tool analysis deterministic.
        """
        inferred = self._infer_tool_arguments(tool_name, question)
        periods = self._extract_month_periods(question)
        latest_actual = self._latest_actual_date()
        metric = self._default_primary_metric(question)

        if tool_name == "get_financial_kpis":
            if periods:
                target = periods[-1]
            elif latest_actual:
                target_start = latest_actual[:8] + "01"
                target = {"date_from": target_start, "date_to": latest_actual}
            else:
                return {"currency": self._extract_currency(question) or "USD", "date_from": "1900-01-01", "date_to": "1900-01-01", "metric": metric}
            return {
                "currency": inferred.get("currency") or self._extract_currency(question) or "USD",
                "date_from": target["date_from"],
                "date_to": target["date_to"],
                "metric": metric,
            }

        if tool_name == "analyze_financial_ratios":
            if periods:
                target = periods[-1]
            elif latest_actual:
                target_start = latest_actual[:8] + "01"
                target = {"date_from": target_start, "date_to": latest_actual}
            else:
                target = {"date_from": "1900-01-01", "date_to": "1900-01-01"}
            return {
                "currency": inferred.get("currency") or self._extract_currency(question) or "USD",
                "date_from": target["date_from"],
                "date_to": target["date_to"],
            }

        if tool_name in {"compare_financial_periods", "analyze_cash_flow_drivers"}:
            if len(periods) >= 2:
                p1, p2 = periods[0], periods[-1]
            elif len(periods) == 1:
                p2 = periods[0]
                p1 = self._previous_month_period(p2["date_from"])
            elif latest_actual:
                latest_start = latest_actual[:8] + "01"
                p2 = {"date_from": latest_start, "date_to": latest_actual}
                p1 = self._previous_month_period(latest_start)
            else:
                return {}

            return {
                "currency": inferred.get("currency") or self._extract_currency(question) or "USD",
                "metric": metric,
                "period_1_from": p1["date_from"],
                "period_1_to": p1["date_to"],
                "period_2_from": p2["date_from"],
                "period_2_to": p2["date_to"],
            } if tool_name == "compare_financial_periods" else {
                "currency": inferred.get("currency") or self._extract_currency(question) or "USD",
                "period_1_from": p1["date_from"],
                "period_1_to": p1["date_to"],
                "period_2_from": p2["date_from"],
                "period_2_to": p2["date_to"],
            }

        if tool_name == "analyze_financial_trend":
            if len(periods) >= 2:
                start = periods[0]["date_from"]
                end = periods[-1]["date_to"]
            elif len(periods) == 1:
                end = periods[0]["date_to"]
                start = self._first_day_of_previous_months(end, 5)
            elif latest_actual:
                end = latest_actual
                start = self._first_day_of_previous_months(end, 5)
            else:
                return {}

            return {
                "currency": inferred.get("currency") or self._extract_currency(question) or "USD",
                "metric": metric,
                "date_from": start,
                "date_to": end,
            }

        if tool_name == "detect_financial_anomalies":
            if periods:
                target = periods[-1]
            elif latest_actual:
                target = {"date_from": latest_actual[:8] + "01", "date_to": latest_actual}
            else:
                return {}

            return {
                "currency": inferred.get("currency") or self._extract_currency(question) or "USD",
                "date_from": target["date_from"],
                "date_to": target["date_to"],
                "threshold": 3.5,
            }

        if tool_name == "forecast_financial_kpi":
            args = {
                "currency": inferred.get("currency") or self._extract_currency(question) or "USD",
                "metric": metric,
                "forecast_period": inferred.get("forecast_period") or (
                    self._next_month_start(latest_actual) if latest_actual else None
                ),
                "lookback_months": inferred.get("lookback_months") or self._infer_lookback_months(question) or 3,
            }
            return {key: value for key, value in args.items() if value is not None}

        return inferred

    # ========================================================
    # DETERMINISTIC FINANCIAL HEALTH FINDINGS
    # ========================================================

    def _build_financial_health_findings(
        self,
        verified_results: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """
        Build deterministic, evidence-backed financial health findings
        from already verified tool results.

        This is intentionally NOT a numeric health score. It produces
        structured observations from direct facts, derived ratios,
        period changes, drivers, anomalies, and forecast output.
        """

        findings: dict[str, Any] = {
            "status": "success",
            "analysis_type": "financial_health_findings",
            "version": "1.0",
            "based_on_tools": [],
            "observations": [],
            "comparison_observations": [],
            "driver_observations": [],
            "anomaly_observations": [],
            "forecast_observations": [],
            "limitations": [],
        }

        tool_map: dict[str, list[dict[str, Any]]] = {}

        for item in verified_results:
            if not isinstance(item, dict):
                continue
            tool_name = item.get("tool_name")
            result = item.get("result")
            if not tool_name or not isinstance(result, dict):
                continue

            findings["based_on_tools"].append(tool_name)
            tool_map.setdefault(tool_name, []).append(result)

            status = result.get("status")
            if status in {"no_data", "insufficient_data"}:
                message = result.get("message") or result.get("error") or status
                findings["limitations"].append({
                    "tool": tool_name,
                    "type": status,
                    "message": message,
                })

        # Keep tool order stable and unique.
        findings["based_on_tools"] = list(dict.fromkeys(findings["based_on_tools"]))

        # ----------------------------------------------------
        # KPI observations
        # ----------------------------------------------------
        for result in tool_map.get("get_financial_kpis", []):
            if result.get("status") != "success":
                continue

            values: dict[str, Any] = {}
            for row in result.get("results", []):
                if isinstance(row, dict) and row.get("metric"):
                    values[str(row["metric"])] = row.get("value")

            currency = result.get("currency")
            period = result.get("requested_period") or {}

            net_cash_flow = self._as_number(values.get("net_cash_flow"))
            total_inflows = self._as_number(values.get("total_inflows"))
            total_outflows = self._as_number(values.get("total_outflows"))

            if net_cash_flow is not None:
                findings["observations"].append({
                    "signal": "negative_net_cash_flow" if net_cash_flow < 0 else ("positive_net_cash_flow" if net_cash_flow > 0 else "zero_net_cash_flow"),
                    "currency": currency,
                    "period": period,
                    "value": net_cash_flow,
                    "evidence": "net_cash_flow",
                })

            if total_inflows is not None and total_outflows is not None:
                findings["observations"].append({
                    "signal": "outflows_exceeded_inflows" if total_outflows > total_inflows else ("inflows_exceeded_outflows" if total_inflows > total_outflows else "inflows_equal_outflows"),
                    "currency": currency,
                    "period": period,
                    "total_inflows": total_inflows,
                    "total_outflows": total_outflows,
                })

        # ----------------------------------------------------
        # KPI / ratio flow reconciliation
        # ----------------------------------------------------
        for source_name in ("get_financial_kpis", "analyze_financial_ratios"):
            for result in tool_map.get(source_name, []):
                quality = result.get("data_quality", {})
                if not isinstance(quality, dict):
                    continue
                reconciliation = quality.get("flow_reconciliation", {})
                if not isinstance(reconciliation, dict):
                    continue
                if reconciliation.get("status") == "not_reconciled":
                    findings["limitations"].append({
                        "tool": source_name,
                        "type": "flow_reconciliation",
                        "message": (
                            "Reported net cash flow does not exactly reconcile to "
                            "total inflows minus total outflows in the authoritative mart. "
                            "The reported net cash flow is retained as the authoritative KPI."
                        ),
                        "gap": reconciliation.get("gap"),
                    })

        # ----------------------------------------------------
        # Ratio observations
        # ----------------------------------------------------
        for result in tool_map.get("analyze_financial_ratios", []):
            if result.get("status") != "success":
                continue

            ratios = result.get("ratios", {})
            inputs = result.get("inputs", {})
            if not isinstance(ratios, dict):
                ratios = {}
            if not isinstance(inputs, dict):
                inputs = {}

            currency = result.get("currency")
            period = result.get("period", {})

            mapping = [
                ("transaction_success_rate_percentage", "transaction_success_rate"),
                ("failed_transaction_rate_percentage", "failed_transaction_rate"),
                ("pending_transaction_rate_percentage", "pending_transaction_rate"),
                ("reversed_transaction_rate_percentage", "reversed_transaction_rate"),
                ("refund_rate_percentage", "refund_rate"),
                ("fee_rate_percentage", "fee_rate"),
                ("inflow_outflow_ratio", "inflow_outflow_ratio"),
                ("net_cash_flow_margin_percentage", "net_cash_flow_margin"),
            ]

            for key, signal in mapping:
                value = self._as_number(ratios.get(key))
                if value is None:
                    continue
                findings["observations"].append({
                    "signal": signal,
                    "currency": currency,
                    "period": period,
                    "value": value,
                    "unit": "ratio" if key == "inflow_outflow_ratio" else "percent",
                    "evidence": key,
                })

            success = self._as_number(ratios.get("transaction_success_rate_percentage"))
            failed = self._as_number(ratios.get("failed_transaction_rate_percentage"))
            pending = self._as_number(ratios.get("pending_transaction_rate_percentage"))
            reversed_rate = self._as_number(ratios.get("reversed_transaction_rate_percentage"))

            if success is not None:
                findings["observations"].append({
                    "signal": "completed_share_of_transactions",
                    "currency": currency,
                    "period": period,
                    "value": success,
                    "unit": "percent",
                })

            if failed is not None and failed > 0:
                findings["observations"].append({
                    "signal": "failed_transactions_present",
                    "currency": currency,
                    "period": period,
                    "value": failed,
                    "unit": "percent",
                })

            if pending is not None and pending > 0:
                findings["observations"].append({
                    "signal": "pending_transactions_present",
                    "currency": currency,
                    "period": period,
                    "value": pending,
                    "unit": "percent",
                })

            if reversed_rate is not None and reversed_rate > 0:
                findings["observations"].append({
                    "signal": "reversed_transactions_present",
                    "currency": currency,
                    "period": period,
                    "value": reversed_rate,
                    "unit": "percent",
                })

        # ----------------------------------------------------
        # Comparison observations
        # ----------------------------------------------------
        for result in tool_map.get("compare_financial_periods", []):
            if result.get("status") != "success":
                continue

            p1 = result.get("period_1", {})
            p2 = result.get("period_2", {})
            v1 = self._as_number(p1.get("value")) if isinstance(p1, dict) else None
            v2 = self._as_number(p2.get("value")) if isinstance(p2, dict) else None
            absolute_change = self._as_number(result.get("absolute_change"))
            percentage_change = self._as_number(result.get("percentage_change"))

            findings["comparison_observations"].append({
                "metric": result.get("comparison_metric"),
                "currency": result.get("currency"),
                "period_1": p1,
                "period_2": p2,
                "absolute_change": absolute_change,
                "percentage_change": percentage_change,
                "direction": result.get("direction"),
            })

            if v1 is not None and v2 is not None:
                if v1 < 0 and v2 < v1:
                    signal = "negative_metric_became_more_negative"
                elif v1 < 0 and v2 > v1:
                    signal = "negative_metric_became_less_negative"
                elif v1 >= 0 and v2 > v1:
                    signal = "positive_direction_increase"
                elif v1 >= 0 and v2 < v1:
                    signal = "positive_direction_decrease"
                else:
                    signal = "no_material_directional_change"

                findings["comparison_observations"].append({
                    "signal": signal,
                    "metric": result.get("comparison_metric"),
                    "currency": result.get("currency"),
                    "period_1_value": v1,
                    "period_2_value": v2,
                    "absolute_change": absolute_change,
                    "percentage_change": percentage_change,
                })

        # ----------------------------------------------------
        # Driver observations
        # ----------------------------------------------------
        for result in tool_map.get("analyze_cash_flow_drivers", []):
            if result.get("status") != "success":
                continue

            drivers = result.get("drivers", [])
            if not isinstance(drivers, list) or not drivers:
                continue

            valid_drivers = [
                d for d in drivers
                if (
                    isinstance(d, dict)
                    and self._as_number(d.get("change")) is not None
                    and str(d.get("flow_role", "")).upper() != "RECONCILIATION"
                    and str(d.get("transaction_type", "")) != "__reconciliation__"
                )
            ]
            if not valid_drivers:
                continue

            largest_magnitude = max(valid_drivers, key=lambda d: abs(self._as_number(d.get("change")) or 0.0))
            positive_drivers = [d for d in valid_drivers if (self._as_number(d.get("change")) or 0.0) > 0]
            negative_drivers = [d for d in valid_drivers if (self._as_number(d.get("change")) or 0.0) < 0]

            for label, candidates in (("largest_positive_driver", positive_drivers), ("largest_negative_driver", negative_drivers)):
                if not candidates:
                    continue
                chosen = max(candidates, key=lambda d: abs(self._as_number(d.get("change")) or 0.0))
                findings["driver_observations"].append({
                    "signal": label,
                    "transaction_type": chosen.get("transaction_type"),
                    "change": self._as_number(chosen.get("change")),
                    "contribution_percentage": self._as_number(chosen.get("contribution_percentage")),
                    "currency": result.get("currency"),
                })

            findings["driver_observations"].append({
                "signal": "largest_absolute_driver",
                "transaction_type": largest_magnitude.get("transaction_type"),
                "change": self._as_number(largest_magnitude.get("change")),
                "contribution_percentage": self._as_number(largest_magnitude.get("contribution_percentage")),
                "currency": result.get("currency"),
            })

        # ----------------------------------------------------
        # Anomaly observations
        # ----------------------------------------------------
        for result in tool_map.get("detect_financial_anomalies", []):
            count = _count = result.get("anomaly_count")
            try:
                count_int = int(count or 0)
            except (TypeError, ValueError):
                count_int = 0

            if result.get("status") == "success":
                findings["anomaly_observations"].append({
                    "signal": "anomalies_detected" if count_int > 0 else "no_anomalies_detected",
                    "currency": result.get("currency"),
                    "date_from": result.get("date_from"),
                    "date_to": result.get("date_to"),
                    "anomaly_count": count_int,
                    "threshold": result.get("threshold"),
                })

            anomalies = result.get("anomalies", [])
            if isinstance(anomalies, list):
                for anomaly in anomalies[:5]:
                    if isinstance(anomaly, dict):
                        findings["anomaly_observations"].append({
                            "signal": "observed_anomaly",
                            "business_date": anomaly.get("business_date"),
                            "currency": anomaly.get("currency"),
                            "observed_value": anomaly.get("observed_value"),
                            "modified_z_score": anomaly.get("modified_z_score"),
                            "direction": anomaly.get("direction"),
                        })

        # ----------------------------------------------------
        # Forecast observations
        # ----------------------------------------------------
        for result in tool_map.get("forecast_financial_kpi", []):
            if result.get("status") != "success":
                continue

            forecast_value = self._as_number(result.get("forecast_value"))
            history = result.get("historical_periods", [])
            last_actual_value = None
            last_actual_period = result.get("last_actual_period")

            if isinstance(history, list) and history:
                last_row = history[-1]
                if isinstance(last_row, dict):
                    last_actual_value = self._as_number(last_row.get("value"))

            item = {
                "signal": "forecast_available",
                "metric": result.get("metric"),
                "currency": result.get("currency"),
                "forecast_period": result.get("forecast_period"),
                "forecast_value": forecast_value,
                "last_actual_period": last_actual_period,
                "last_actual_value": last_actual_value,
                "method": result.get("method"),
            }

            if forecast_value is not None and last_actual_value is not None:
                if forecast_value > last_actual_value:
                    item["direction_vs_last_actual"] = "increase"
                elif forecast_value < last_actual_value:
                    item["direction_vs_last_actual"] = "decrease"
                else:
                    item["direction_vs_last_actual"] = "unchanged"

            findings["forecast_observations"].append(item)

        # ----------------------------------------------------
        # Data boundary limitation
        # ----------------------------------------------------
        latest_actual = self.data_boundary.get("available_data", {}).get("date_to")
        if latest_actual:
            findings["limitations"].append({
                "type": "actual_data_boundary",
                "latest_actual_date": latest_actual,
            })

        # Deduplicate exact limitations / tools while preserving order.
        unique_limits: list[dict[str, Any]] = []
        seen_limits: set[str] = set()
        for item in findings["limitations"]:
            key = json.dumps(make_json_safe(item), sort_keys=True, ensure_ascii=False)
            if key in seen_limits:
                continue
            seen_limits.add(key)
            unique_limits.append(item)
        findings["limitations"] = unique_limits

        return make_json_safe(findings)

    # ========================================================
    # GEMINI TOOL DECLARATIONS
    # ========================================================

    def _build_tool_declarations(self, allowed_tools: list[str]) -> list[types.FunctionDeclaration]:
        if not allowed_tools:
            raise RuntimeError("No allowed tools available.")

        definitions = self._extract_tool_definitions()
        declaration_map = {item.get("name"): item for item in definitions if item.get("name")}
        declarations = []

        for tool_name in allowed_tools:
            definition = declaration_map.get(tool_name)
            if not definition:
                raise RuntimeError(f"No tool definition found for {tool_name}")

            parameters = (
                definition.get("parameters")
                or definition.get("parameters_json_schema")
                or {"type": "object", "properties": {}}
            )

            declarations.append(
                types.FunctionDeclaration(
                    name=tool_name,
                    description=definition.get("description", ""),
                    parameters_json_schema=parameters,
                )
            )

        return declarations

    # ========================================================
    # LANGUAGE HELPERS
    # ========================================================

    @staticmethod
    def _normalize_language(value: str | None, question: str = "") -> str:
        if value:
            normalized = str(value).strip().lower()[:2]
            if normalized in {"ar", "en"}:
                return normalized

        arabic_chars = len(re.findall(r"[\u0600-\u06FF]", question or ""))
        latin_chars = len(re.findall(r"[A-Za-z]", question or ""))
        return "ar" if arabic_chars > max(2, latin_chars) else "en"

    # ========================================================
    # RUNTIME SYSTEM PROMPT
    # ========================================================

    def _build_runtime_system_prompt(self) -> str:
        language_rules = (
            "\n\nLANGUAGE RULES:\n"
            "- If the user writes in Arabic, answer entirely in clear professional Arabic.\n"
            "- If the user writes in English, answer in English.\n"
            "- Keep metric names, dates, currency codes, and numeric values exact.\n"
            "- Arabic questions must still map to canonical tool arguments in English/ISO form.\n"
            "- Do not claim that Arabic is unsupported.\n"
            if self.response_language == "ar"
            else (
                "\n\nLANGUAGE RULES:\n"
                "- Answer in English unless the user explicitly writes in Arabic.\n"
                "- Keep metric names, dates, currency codes, and numeric values exact.\n"
            )
        )

        runtime_rules = """
IMPORTANT FINANCIAL ANALYST RULES:

1. Use only verified tool results for factual financial values.
2. Never invent missing financial data.
3. Clearly distinguish actual, forecast, anomaly, comparison, trend, ratio, and compound analysis.
4. Monetary metrics must include their currency.
5. Count metrics are NOT monetary: transactions, completed_transactions, pending_transactions,
   failed_transactions, reversed_transactions, active_accounts. Never attach a currency symbol to counts.
6. average_transaction_amount is monetary and must include the currency.
7. Percentage change formula: (period_2 - period_1) / abs(period_1) * 100
8. Do not silently convert a negative percentage change into a positive percentage.
9. For driver analysis, if only Top 5 drivers are shown, do not claim they represent 100% of the change.
10. Actual financial data does not exist beyond the verified actual data boundary.
11. Forecasts must be explicitly labeled as forecasts.
12. Ratios are derived indicators from verified transaction data. Do not invent statutory accounting ratios.
13. Inflow/outflow ratio is a pure ratio (x), not a percentage unless explicitly converted.
14. Financial health language must describe observed indicators and trends. Do not invent a numeric health score unless one is explicitly defined by a verified tool.
15. For compound analysis, use the complete verified tool set supplied in the prompt and distinguish:
    - observed facts
    - derived ratios
    - period changes
    - drivers
    - anomalies
    - forecast view
    - limitations / data coverage
16. Be concise, factual, and explicit about data boundaries.
"""

        return self.system_prompt + language_rules + "\n\n" + runtime_rules

    # ========================================================
    # TOOL CONFIG
    # ========================================================

    def _build_tool_config(self, allowed_tools: list[str]) -> types.GenerateContentConfig:
        declarations = self._build_tool_declarations(allowed_tools)
        return types.GenerateContentConfig(
            system_instruction=self._build_runtime_system_prompt(),
            tools=[types.Tool(function_declarations=declarations)],
            tool_config=types.ToolConfig(
                function_calling_config=types.FunctionCallingConfig(mode="ANY")
            ),
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )

    # ========================================================
    # FINAL CONFIG
    # ========================================================

    def _build_final_config(self) -> types.GenerateContentConfig:
        return types.GenerateContentConfig(
            system_instruction=(
                self._build_runtime_system_prompt()
                +
                """

FINAL ANSWER RULES:

- Answer the user's question directly.
- Use ONLY the verified tool results supplied.
- Do not make another tool call.
- Do not invent missing values.
- Monetary values must include currency.
- Count metrics must not have currency symbols.
- Do not describe transaction counts as monetary amounts.
- Forecasts must be clearly labeled.
- If actual data is unavailable, say so explicitly.
- For compound financial analysis, organize the answer as:
  1) Key observed performance
  2) Ratios / health indicators
  3) Comparison or trend
  4) Main drivers
  5) Anomalies
  6) Forecast / outlook
  7) Data limitations when relevant
- Treat DETERMINISTIC FINANCIAL HEALTH FINDINGS as structured evidence, not as a numeric score.
- When flow_reconciliation.status is not_reconciled, do not say that total inflows minus total outflows "resulted in" the reported net cash flow. State the reported net cash flow as the authoritative KPI and mention the reconciliation limitation only when relevant.
- Do not invent a health score, risk score, or accounting classification.
- Preserve the exact sign of monetary changes and percentages.
- State the evidence behind important conclusions.
- Do not convert descriptive transaction-model indicators into statutory accounting conclusions.
- Do not rank political or otherwise unrelated choices.
"""
            ),
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )

    # ========================================================
    # USER PROMPT
    # ========================================================

    def _build_user_prompt(
        self,
        question: str,
        boundary: dict[str, Any],
        verified_results: list[dict[str, Any]],
    ) -> str:
        boundary_text = json.dumps(make_json_safe(boundary), indent=2, ensure_ascii=False)
        results_text = json.dumps(make_json_safe(verified_results), indent=2, ensure_ascii=False)

        health_findings_text = ""
        if self.current_health_findings:
            health_findings_text = (
                "\n\nDETERMINISTIC FINANCIAL HEALTH FINDINGS:\n"
                + json.dumps(
                    make_json_safe(self.current_health_findings),
                    indent=2,
                    ensure_ascii=False,
                )
            )

        follow_up_context = ""
        if self.last_question:
            follow_up_context = "\n\nPREVIOUS USER QUESTION:\n" + self.last_question

        # Bilingual normalization hints are supplied to Gemini so Arabic input
        # is understood consistently even when the model emits partial tool args.
        question_metadata = {
            "language": self.response_language,
            "detected_currency": self._extract_currency(question),
            "detected_periods": self._extract_month_periods(question),
            "inferred_metric": self._infer_metric_from_question(question),
            "follow_up": self._is_follow_up_question(question),
            "canonical_note": "Use ISO dates and ISO currency codes for tool arguments.",
        }
        metadata_text = json.dumps(
            make_json_safe(question_metadata),
            indent=2,
            ensure_ascii=False,
        )

        return (
            f"USER QUESTION:\n{question}\n\n"
            f"BILINGUAL QUESTION NORMALIZATION:\n{metadata_text}\n\n"
            f"ANALYSIS MODE:\n{self.last_analysis_mode}\n\n"
            f"DATA BOUNDARY:\n{boundary_text}\n\n"
            f"VERIFIED TOOL RESULTS:\n{results_text}"
            f"{health_findings_text}"
            f"{follow_up_context}"
        )

    # ========================================================
    # FUNCTION CALL EXTRACTION
    # ========================================================

    @staticmethod
    def _extract_function_calls(response: Any) -> list[Any]:
        calls = getattr(response, "function_calls", None)
        if calls:
            return list(calls)

        extracted = []
        candidates = getattr(response, "candidates", None)
        if not candidates:
            return extracted

        for candidate in candidates:
            content = getattr(candidate, "content", None)
            if not content:
                continue
            parts = getattr(content, "parts", None)
            if not parts:
                continue
            for part in parts:
                function_call = getattr(part, "function_call", None)
                if function_call:
                    extracted.append(function_call)

        return extracted

    # ========================================================
    # COMPOUND EXECUTION
    # ========================================================

    def _execute_compound_analysis(
        self,
        question: str,
        selected_tools: list[str],
        verified_results: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        for tool_name in selected_tools:
            arguments = self._build_compound_arguments(tool_name, question)

            if not arguments:
                print(f"SKIPPED COMPOUND TOOL: {tool_name} (arguments unavailable)")
                continue

            print()
            print("=" * 70)
            print("COMPOUND TOOL EXECUTION")
            print("=" * 70)
            print(f"TOOL REQUEST: {tool_name}")
            print(f"DETERMINISTIC ARGUMENTS: {arguments}")

            result = self._execute_tool(tool_name, arguments)
            validation_ok, validation_message = self._validate_tool_result(tool_name, result)

            print(f"MATH VALIDATION: {validation_message}")
            print(f"RESULT VALIDATION: {'SUCCESS' if validation_ok else 'FAILED'} ({tool_name})")
            print(f"TOOL RESULT STATUS: {result.get('status')}")

            verified_results.append(
                {
                    "tool_name": tool_name,
                    "arguments": arguments,
                    "result": result,
                }
            )

        return verified_results

    # ========================================================
    # ASK
    # ========================================================

    def ask(self, question: str, language: str | None = None) -> str:
        question = question.strip()
        self.response_language = self._normalize_language(language, question)
        if not question:
            return "من فضلك اكتب سؤالًا ماليًا." if self.response_language == "ar" else "Please provide a financial question."

        self.current_health_findings = {}
        self.data_boundary = self._get_data_boundary()

        print()
        print("=" * 70)
        print("DATA BOUNDARY:")

        if self.data_boundary.get("status") == "success":
            available = self.data_boundary.get("available_data", {})
            print(f"Actual Range: {available.get('date_from')} to {available.get('date_to')}")
        else:
            print(self.data_boundary)

        selected_tools = self._select_tools_for_question(question)

        # ----------------------------------------------------
        # Context-only follow-up
        # ----------------------------------------------------

        if not selected_tools and self._can_answer_follow_up_from_context(question):
            self.last_analysis_mode = "follow_up_contextual"
            verified_results = list(self.last_verified_results)
            self.current_health_findings = dict(self.last_health_findings)
            self.last_tool_names = list(dict.fromkeys(
                item.get("tool_name")
                for item in verified_results
                if isinstance(item, dict) and item.get("tool_name")
            ))
            print()
            print("ROUTED TOOLS:")
            print("(reuse previous verified context)")
            print(f"ANALYSIS MODE: {self.last_analysis_mode}")
            print("FOLLOW-UP CONTEXT: REUSED")

            follow_up_intent = self._infer_follow_up_intent(question)

            final_prompt = (
                self._build_user_prompt(question, self.data_boundary, verified_results)
                +
                f"""

FOLLOW-UP ANSWER TASK:
Follow-up intent: {follow_up_intent}

Use ONLY the previous verified tool results and deterministic financial health findings.
Do not make another tool call.
Answer the follow-up directly and concisely.
Do not repeat the entire previous analysis unless requested.
Preserve the authoritative KPI scope used in the previous compound analysis.
Do not substitute transaction-level flow totals for the authoritative net_cash_flow KPI.
For a driver question, explain the drivers of the authoritative KPI change using the
verified comparison plus driver results. Driver components are explanatory evidence;
the authoritative net cash flow value comes from the KPI/comparison result.
If a reconciliation residual exists, identify it as a residual rather than inventing
a business driver for it.
If the answer is not supported by the previous verified results, say so.
"""
            )
            final_response = self.client.models.generate_content(
                model=self.model_name,
                contents=final_prompt,
                config=self._build_final_config(),
            )
            final_text = getattr(final_response, "text", None)
            if final_text:
                self.last_question = question
                self.last_verified_results = verified_results
                self.last_suggested_questions = self._suggest_follow_up_questions()
                self._record_session_turn(question, final_text, verified_results)
                return final_text

        if not selected_tools:
            raise RuntimeError("Tool routing returned zero tools.")

        print()
        print("ROUTED TOOLS:")
        print(", ".join(selected_tools))
        print(f"ANALYSIS MODE: {self.last_analysis_mode}")

        self.last_tool_names = list(selected_tools)
        verified_results: list[dict[str, Any]] = []

        # ----------------------------------------------------
        # Deterministic compound path
        # ----------------------------------------------------

        if self.last_analysis_mode == "compound_financial_analysis":
            verified_results = self._execute_compound_analysis(
                question,
                selected_tools,
                verified_results,
            )

            if verified_results:
                self.current_health_findings = self._build_financial_health_findings(verified_results)
                self.last_health_findings = dict(self.current_health_findings)

                print()
                print("DETERMINISTIC FINANCIAL HEALTH FINDINGS: READY")
                print("Sending complete verified compound result + deterministic findings to Gemini...")

                final_prompt = (
                    self._build_user_prompt(
                        question,
                        self.data_boundary,
                        verified_results,
                    )
                    +
                    """

FINAL ANSWER TASK:

Produce a complete financial analysis using ONLY the verified results above.
Do not call tools again.
Do not invent values, scores, or unsupported accounting measures.
Clearly separate facts from derived indicators.
If a tool returned no_data or insufficient_data, state that limitation.
"""
                )

                final_response = self.client.models.generate_content(
                    model=self.model_name,
                    contents=final_prompt,
                    config=self._build_final_config(),
                )

                final_text = getattr(final_response, "text", None)
                if final_text:
                    self.last_question = question
                    self.last_verified_results = verified_results
                    self.last_suggested_questions = self._suggest_follow_up_questions()
                    self._record_session_turn(question, final_text, verified_results)
                    return final_text

        # ----------------------------------------------------
        # Gemini tool loop for single / targeted questions
        # ----------------------------------------------------

        for round_number in range(1, self.max_tool_rounds + 1):
            print()
            print(f"Gemini generation round {round_number}...")

            tool_config = self._build_tool_config(selected_tools)
            prompt = self._build_user_prompt(question, self.data_boundary, verified_results)

            response = self.client.models.generate_content(
                model=self.model_name,
                contents=prompt,
                config=tool_config,
            )

            function_calls = self._extract_function_calls(response)

            if not function_calls:
                text = getattr(response, "text", None)
                if text:
                    if verified_results:
                        self.last_question = question
                        self.last_verified_results = verified_results
                        return text
                    return "No verified financial tool result was returned for this question."
                break

            new_tools_executed = False

            for function_call in function_calls:
                tool_name = getattr(function_call, "name", None)
                raw_arguments = getattr(function_call, "args", None)

                if not tool_name:
                    continue
                if tool_name not in selected_tools:
                    raise ValueError(f"Gemini attempted to call an unapproved tool: {tool_name}")

                if raw_arguments is None:
                    raw_arguments = {}
                raw_arguments = dict(raw_arguments)

                print()
                print("=" * 70)
                print(f"FUNCTION CALL ROUND {round_number}")
                print("=" * 70)
                print(f"TOOL REQUEST: {tool_name}")
                print(f"RAW ARGUMENTS: {raw_arguments}")

                inferred_arguments = self._infer_tool_arguments(tool_name, question)
                if inferred_arguments:
                    print(f"INFERRED ARGUMENTS: {inferred_arguments}")

                normalized_arguments = self._normalize_tool_arguments(
                    tool_name,
                    raw_arguments,
                    question,
                )

                print(f"NORMALIZED ARGUMENTS: {normalized_arguments}")

                result = self._execute_tool(tool_name, normalized_arguments)
                validation_ok, validation_message = self._validate_tool_result(tool_name, result)

                print(f"MATH VALIDATION: {validation_message}")
                print(f"RESULT VALIDATION: {'SUCCESS' if validation_ok else 'FAILED'} ({tool_name})")
                print(f"TOOL RESULT STATUS: {result.get('status')}")

                if tool_name == "forecast_financial_kpi":
                    forecasts = result.get("forecasts", [])
                    print(f"Forecasts returned: {len(forecasts)}")

                verified_results.append(
                    {
                        "tool_name": tool_name,
                        "arguments": normalized_arguments,
                        "result": result,
                    }
                )
                new_tools_executed = True

            if new_tools_executed:
                print()
                print("Sending verified SQL result to Gemini for final answer...")

                final_prompt = (
                    self._build_user_prompt(
                        question,
                        self.data_boundary,
                        verified_results,
                    )
                    +
                    """

FINAL ANSWER TASK:

Answer the original user question now using ONLY the verified tool results above.
Do not make another tool call.
Do not invent missing values.
For monetary metrics include currency.
For count metrics do not include currency symbols.
Clearly distinguish actuals from forecasts.
"""
                )

                final_response = self.client.models.generate_content(
                    model=self.model_name,
                    contents=final_prompt,
                    config=self._build_final_config(),
                )

                final_text = getattr(final_response, "text", None)
                if final_text:
                    self.last_question = question
                    self.last_verified_results = verified_results
                    self.last_suggested_questions = self._suggest_follow_up_questions()
                    self._record_session_turn(question, final_text, verified_results)
                    return final_text

        self.last_question = question
        self.last_verified_results = verified_results

        if verified_results:
            return "Verified financial data was retrieved, but the final narrative response could not be generated."

        return "I could not generate a verified financial answer for this question."

    # ========================================================
    # STARTUP INFORMATION
    # ========================================================

    def print_startup_info(self) -> None:
        agent_section = self._get_agent_section()

        agent_name = agent_section.get("name", "AI Finance Analyst")
        version = agent_section.get("version", "1.0.0")

        print()
        print("=" * 70)
        print(f"Name    : {agent_name}")
        print(f"Version : {version}")
        print("Provider: google")
        print(f"Model   : {self.model_name}")
        print("Tools   : " + ", ".join(self.enabled_tools))
        print("Interface: Smart CLI / Context-Aware Follow-ups")
        print("Configuration validation: SUCCESS")
        print("=" * 70)
        print("Type /help for commands. Ask a question directly to begin.")


# ============================================================
# CLI
# ============================================================

def main() -> None:
    agent = FinanceAgent()
    agent.print_startup_info()

    while True:
        try:
            question = input("\nYou: ")
        except (EOFError, KeyboardInterrupt):
            print()
            print("Exiting AI Finance Analyst.")
            break

        question = question.strip()
        if not question:
            continue

        command = question.lower()
        if command in {"/exit", "/quit", "/q", "exit", "quit", "q"}:
            print("Exiting AI Finance Analyst.")
            break
        if command == "/help":
            agent.print_smart_help(); continue
        if command == "/status":
            agent.print_smart_status(); continue
        if command == "/history":
            agent.print_smart_history(); continue
        if command == "/suggest":
            agent.print_smart_suggestions(); continue
        if command == "/boundary":
            available = agent.data_boundary.get("available_data", {})
            print()
            if available:
                print(f"Verified actual data: {available.get('date_from')} to {available.get('date_to')}")
            else:
                print("Data boundary has not been loaded yet. Ask a question first.")
            continue
        if command == "/tools":
            print("\nEnabled tools:")
            for tool in agent.enabled_tools:
                print(f"  - {tool}")
            continue
        if command == "/clear":
            agent.clear_conversation_context(); continue
        if command == "/last":
            print()
            print(agent.last_response_text or "No previous answer in this session.")
            continue

        try:
            answer = agent.ask(question)
            print()
            print("AI Finance Analyst:")
            print(answer)

            suggestions = agent._suggest_follow_up_questions()
            if suggestions:
                print("\nSuggested next questions:")
                for index, suggestion in enumerate(suggestions, start=1):
                    print(f"  {index}. {suggestion}")
        except Exception as exc:
            print()
            print("ERROR:")
            print(f"{type(exc).__name__}: {exc}")
            print("Tip: type /status or /help to inspect the current session.")


if __name__ == "__main__":
    main()
