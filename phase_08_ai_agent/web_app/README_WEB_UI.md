# AI Finance Analyst — Professional Executive Dashboard v2.1 (Bilingual · Dark/Light)

This package upgrades the existing Smart CLI Web UI into a richer executive dashboard while keeping the existing `FinanceAgent` and financial tools unchanged.

## What is new in v2.1

- **Arabic / English UI** with full RTL layout (one-click switch, no reload, remembered per browser)
- **Dark / Light mode** (follows the OS preference on first visit, then remembered)
- **Copilot answers in the selected UI language** (see "Agent language" below)
- Fixed the anomaly badge plural ("anomalyies" → "anomalies")

### Agent language

The chat request now carries `lang` (`en` | `ar`). `web_app.py` handles it without touching `FinanceAgent`:

1. If `FinanceAgent.ask()` already accepts `language` / `lang` / `response_language`, that parameter is used.
2. Otherwise a short language directive is appended to the question sent to the agent. The chat bubble and the
   dashboard month/currency parsing still use the original question text.

Numbers, currency codes and dates are always kept exactly as computed by the verified tools.

## What was new in v2

- Executive KPI cards for the selected month
- Currency selector: USD, EUR, GBP, CAD, JPY, AUD
- Analysis-month selector constrained to the verified actual boundary
- 3M / 6M / 12M trend window
- Net cash flow SVG trend chart with tooltips
- Financial health signal cards without an artificial health score
- Month-over-month comparison panel
- Cash-flow driver visualization with reconciliation status
- Modified Z-score anomaly panel
- Forecast outlook with historical basis
- Context-aware AI Copilot below the dashboard
- Execution log viewer
- Session/context reset
- Responsive layout for desktop/tablet/mobile (including RTL)

## Files

```text
phase_08_ai_agent/web_app/
├── web_app.py
├── templates/
│   └── index.html
├── static/
│   ├── app.js        # rendering + chat + language/theme toggles
│   ├── i18n.js       # EN/AR dictionary, locale, theme + direction handling
│   └── style.css     # CSS variables: dark + light themes, RTL rules
├── requirements-web.txt
├── run_web.bat
└── README_WEB_UI.md
```

## Install

Run from the project root:

```bat
D:\venv311\Scripts\python.exe -m pip install -r "phase_08_ai_agent\web_app\requirements-web.txt"
```

If your corporate network causes pip SSL verification errors, use the temporary `--trusted-host` workaround only for the package install.

## Run

```bat
D:\venv311\Scripts\python.exe "phase_08_ai_agent\web_app\web_app.py"
```

Open:

```text
http://127.0.0.1:8501
```

Or run:

```text
phase_08_ai_agent\web_app\run_web.bat
```

## Architecture

```text
Professional Dashboard
        |
        +-- /api/dashboard  -> deterministic dashboard tools
        |
        +-- /api/chat       -> existing FinanceAgent
        |
        +-- /api/session    -> session + dashboard state
        |
        +-- /api/reset      -> clear conversational context
        |
        v
Existing FinanceAgent / financial_tools.py
        |
        v
SQL Server + Gemini
```

The dashboard is deliberately deterministic. It calls the verified financial tools directly for dashboard KPIs, ratios, comparison, trend, drivers, anomalies, and forecast. The Copilot remains responsible for conversational analysis and follow-up context.

## Notes

- No external chart library is required. The trend chart is rendered with inline SVG.
- The dashboard does not create a synthetic 0–100 health score.
- Monetary figures come from the verified financial tools and retain their currency.
- Counts are displayed without currency symbols.
- The forecast is always labeled as a forecast.

## Adding or editing translations

All UI text lives in `static/i18n.js` (`DICT.en` / `DICT.ar`). Static HTML uses `data-i18n="key"`,
`data-i18n-placeholder`, and `data-i18n-title`; dynamic text uses `t('key', {vars})` in `app.js`.
Arabic names for transaction types are in `TXN_AR` (unknown types are shown as returned by the data layer).
