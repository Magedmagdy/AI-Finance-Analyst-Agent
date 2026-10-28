# AI Finance Analyst Agent

An AI-powered Finance Analyst system that combines:

- SQL Server
- Python
- Machine Learning
- FastAPI
- n8n
- LLM
- RAG

The system is designed to analyze financial transactions, calculate KPIs,
detect anomalies, perform forecasting, and answer finance-related questions.

---

## Architecture

```text
User
  |
  v
n8n AI Agent
  |
  +-------------------+-------------------+-------------------+
  |                   |                   |
  v                   v                   v
SQL Tool         Prediction Tool    Anomaly Tool
  |                   |                   |
  v                   v                   v
SQL Server        FastAPI / ML      FastAPI / ML
  |                   |                   |
  +-------------------+-------------------+
                      |
                      v
              Financial Results
                      |
                      v
                 LLM Analysis
                      |
                      v
               Finance Response