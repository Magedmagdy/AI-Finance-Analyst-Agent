import os
from pathlib import Path

from dotenv import load_dotenv


# ---------------------------------------------------------
# Project Root
# ---------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------
# Load Environment Variables
# ---------------------------------------------------------
ENV_FILE = BASE_DIR / ".env"

load_dotenv(ENV_FILE)


# ---------------------------------------------------------
# Hugging Face
# ---------------------------------------------------------
HF_DATASET_REPO = os.getenv(
    "HF_DATASET_REPO",
    "ziadatalabs/FreeFinancialTransactions50M"
)

HF_DATASET_FILE = os.getenv(
    "HF_DATASET_FILE",
    "transactions_50M.parquet"
)


# ---------------------------------------------------------
# SQL Server
# ---------------------------------------------------------
SQL_SERVER = os.getenv("SQL_SERVER", "localhost")
SQL_PORT = os.getenv("SQL_PORT", "1433")
SQL_DATABASE = os.getenv("SQL_DATABASE", "AI_Finance")

SQL_USERNAME = os.getenv("SQL_USERNAME", "")
SQL_PASSWORD = os.getenv("SQL_PASSWORD", "")


# ---------------------------------------------------------
# API
# ---------------------------------------------------------
API_HOST = os.getenv("API_HOST", "127.0.0.1")
API_PORT = int(os.getenv("API_PORT", "8000"))


# ---------------------------------------------------------
# LLM
# ---------------------------------------------------------
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "")
LLM_MODEL = os.getenv("LLM_MODEL", "")
LLM_API_KEY = os.getenv("LLM_API_KEY", "")


# ---------------------------------------------------------
# Application
# ---------------------------------------------------------
APP_ENV = os.getenv("APP_ENV", "development")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")