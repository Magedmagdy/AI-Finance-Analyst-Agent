from __future__ import annotations

import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq
import pyodbc


# ============================================================
# CONFIGURATION
# ============================================================

PARQUET_FILE = Path(
    r"C:\Users\maged.magdy\.cache\huggingface\hub"
    r"\datasets--ziadatalabs--FreeFinancialTransactions50M"
    r"\snapshots\98cf38f9b2f1a9994930f52a4d490cb2b5777acc"
    r"\transactions_50M.parquet"
)

DB_SERVER = "localhost"
DB_NAME = "AI_Finance"
TARGET_TABLE = "stg.transactions"

SOURCE_ID = "FreeFinancialTransactions50M_FIRST_20M"

BATCH_SIZE = 100_000

# ============================================================
# IMPORTANT:
# We intentionally load ONLY the first 20 million rows.
# ============================================================

MAX_ROWS = 20_000_000

ODBC_DRIVER = "ODBC Driver 18 for SQL Server"


# ============================================================
# DATABASE CONNECTION
# ============================================================

def get_connection() -> pyodbc.Connection:
    connection_string = (
        f"DRIVER={{{ODBC_DRIVER}}};"
        f"SERVER={DB_SERVER};"
        f"DATABASE={DB_NAME};"
        "Trusted_Connection=yes;"
        "TrustServerCertificate=yes;"
    )

    return pyodbc.connect(
        connection_string,
        timeout=30,
    )


# ============================================================
# SOURCE VALIDATION
# ============================================================

def validate_source() -> None:

    if not PARQUET_FILE.exists():
        raise FileNotFoundError(
            f"Parquet file does not exist:\n{PARQUET_FILE}"
        )


# ============================================================
# LOAD RUN
# ============================================================

def get_or_create_load_run(
    connection: pyodbc.Connection,
) -> str:

    cursor = connection.cursor()

    cursor.execute(
        """
        SELECT TOP (1)
            load_batch_id,
            status,
            rows_loaded
        FROM stg.etl_load_runs
        WHERE source_id = ?
        ORDER BY started_at DESC;
        """,
        SOURCE_ID,
    )

    row = cursor.fetchone()

    # --------------------------------------------------------
    # Existing run
    # --------------------------------------------------------

    if row is not None:

        existing_batch_id = str(row[0])
        status = row[1]
        rows_loaded = int(row[2] or 0)

        if status == "COMPLETED":

            print("20M dataset load is already completed.")
            print(f"load_batch_id: {existing_batch_id}")
            print(f"rows_loaded: {rows_loaded:,}")

            return existing_batch_id

        print("Resuming existing load run.")
        print(f"load_batch_id: {existing_batch_id}")
        print(f"previous status: {status}")
        print(f"rows_loaded: {rows_loaded:,}")

        cursor.execute(
            """
            UPDATE stg.etl_load_runs
            SET status = 'RUNNING',
                error_message = NULL
            WHERE load_batch_id = ?;
            """,
            existing_batch_id,
        )

        connection.commit()

        return existing_batch_id

    # --------------------------------------------------------
    # New run
    # --------------------------------------------------------

    load_batch_id = str(uuid.uuid4())

    cursor.execute(
        """
        INSERT INTO stg.etl_load_runs
        (
            load_batch_id,
            source_id,
            source_file,
            target_table,
            status,
            total_rows_expected,
            rows_loaded
        )
        VALUES
        (
            ?,
            ?,
            ?,
            ?,
            'RUNNING',
            ?,
            0
        );
        """,
        load_batch_id,
        SOURCE_ID,
        str(PARQUET_FILE),
        TARGET_TABLE,
        MAX_ROWS,
    )

    connection.commit()

    print("Created new load run:")
    print(f"load_batch_id: {load_batch_id}")
    print(f"target rows: {MAX_ROWS:,}")

    return load_batch_id


# ============================================================
# CHECKPOINT
# ============================================================

def is_batch_completed(
    connection: pyodbc.Connection,
    row_group_id: int,
    batch_number: int,
) -> bool:

    cursor = connection.cursor()

    cursor.execute(
        """
        SELECT 1
        FROM stg.etl_load_progress
        WHERE source_id = ?
          AND row_group_id = ?
          AND batch_number = ?;
        """,
        SOURCE_ID,
        row_group_id,
        batch_number,
    )

    return cursor.fetchone() is not None


# ============================================================
# INSERT BATCH
# ============================================================

def insert_batch(
    connection: pyodbc.Connection,
    rows: list[tuple[Any, ...]],
) -> None:

    if not rows:
        return

    sql = f"""
        INSERT INTO {TARGET_TABLE}
        (
            transaction_id,
            account_id,
            transaction_type,
            amount,
            currency,
            merchant_category,
            balance_after,
            transaction_timestamp,
            status,
            load_batch_id
        )
        VALUES
        (
            ?,
            ?,
            ?,
            ?,
            ?,
            ?,
            ?,
            ?,
            ?,
            ?
        );
    """

    cursor = connection.cursor()

    cursor.fast_executemany = True

    cursor.executemany(
        sql,
        rows,
    )


# ============================================================
# PROGRESS UPDATE
# ============================================================

def mark_batch_completed(
    cursor: pyodbc.Cursor,
    row_group_id: int,
    batch_number: int,
    rows_loaded: int,
) -> None:

    cursor.execute(
        """
        INSERT INTO stg.etl_load_progress
        (
            source_id,
            row_group_id,
            batch_number,
            rows_loaded
        )
        VALUES
        (
            ?,
            ?,
            ?,
            ?
        );
        """,
        SOURCE_ID,
        row_group_id,
        batch_number,
        rows_loaded,
    )


def update_run_rows(
    cursor: pyodbc.Cursor,
    load_batch_id: str,
    rows_loaded: int,
) -> None:

    cursor.execute(
        """
        UPDATE stg.etl_load_runs
        SET rows_loaded = rows_loaded + ?
        WHERE load_batch_id = ?;
        """,
        rows_loaded,
        load_batch_id,
    )


# ============================================================
# MARK COMPLETED
# ============================================================

def mark_run_completed(
    connection: pyodbc.Connection,
    load_batch_id: str,
) -> None:

    cursor = connection.cursor()

    cursor.execute(
        """
        UPDATE stg.etl_load_runs
        SET status = 'COMPLETED',
            completed_at = SYSUTCDATETIME(),
            error_message = NULL,
            rows_loaded = ?
        WHERE load_batch_id = ?;
        """,
        MAX_ROWS,
        load_batch_id,
    )

    connection.commit()


# ============================================================
# MARK FAILED
# ============================================================

def mark_run_failed(
    connection: pyodbc.Connection,
    load_batch_id: str,
    error_message: str,
) -> None:

    try:

        cursor = connection.cursor()

        cursor.execute(
            """
            UPDATE stg.etl_load_runs
            SET status = 'FAILED',
                error_message = ?
            WHERE load_batch_id = ?;
            """,
            error_message[:4000],
            load_batch_id,
        )

        connection.commit()

    except Exception:

        connection.rollback()


# ============================================================
# CONVERT ARROW BATCH
# ============================================================

def convert_batch(
    batch,
    load_batch_id: str,
) -> list[tuple[Any, ...]]:

    data = batch.to_pydict()

    result = []

    transaction_ids = data["transaction_id"]
    account_ids = data["account_id"]
    transaction_types = data["transaction_type"]
    amounts = data["amount"]
    currencies = data["currency"]
    merchant_categories = data["merchant_category"]
    balances = data["balance_after"]
    timestamps = data["transaction_timestamp"]
    statuses = data["status"]

    for i in range(batch.num_rows):

        timestamp_value = timestamps[i]

        parsed_timestamp = (
            datetime.fromisoformat(timestamp_value)
            if timestamp_value is not None
            else None
        )

        result.append(
            (
                transaction_ids[i],
                account_ids[i],
                transaction_types[i],
                amounts[i],
                currencies[i],
                merchant_categories[i],
                balances[i],
                parsed_timestamp,
                statuses[i],
                load_batch_id,
            )
        )

    return result


# ============================================================
# MAIN LOADER
# ============================================================

def run_loader() -> None:

    validate_source()

    parquet = pq.ParquetFile(
        PARQUET_FILE
    )

    total_source_rows = parquet.metadata.num_rows

    print("=" * 70)
    print("FIRST 20M TRANSACTIONS LOADER")
    print("=" * 70)

    print(
        f"Source rows      : {total_source_rows:,}"
    )

    print(
        f"Target rows      : {MAX_ROWS:,}"
    )

    print(
        f"Batch size       : {BATCH_SIZE:,}"
    )

    print(
        f"Row groups       : {parquet.num_row_groups}"
    )

    print()

    connection = get_connection()

    load_batch_id = None

    try:

        load_batch_id = get_or_create_load_run(
            connection
        )

        # ----------------------------------------------------
        # Check current progress
        # ----------------------------------------------------

        cursor = connection.cursor()

        cursor.execute(
            """
            SELECT rows_loaded
            FROM stg.etl_load_runs
            WHERE load_batch_id = ?;
            """,
            load_batch_id,
        )

        row = cursor.fetchone()

        processed_rows = (
            int(row[0])
            if row is not None
            else 0
        )

        print(
            f"Current progress: {processed_rows:,}"
        )

        # ----------------------------------------------------
        # Already completed
        # ----------------------------------------------------

        if processed_rows >= MAX_ROWS:

            print(
                "20M rows are already loaded."
            )

            return

        overall_start = time.time()

        # ----------------------------------------------------
        # Read row groups
        # ----------------------------------------------------

        for row_group_id in range(
            parquet.num_row_groups
        ):

            if processed_rows >= MAX_ROWS:
                break

            row_group_table = (
                parquet.read_row_group(
                    row_group_id
                )
            )

            row_group_rows = (
                row_group_table.num_rows
            )

            print(
                f"Row Group {row_group_id + 1}"
                f"/{parquet.num_row_groups}"
            )

            batch_number = 0

            offset = 0

            while offset < row_group_rows:

                if processed_rows >= MAX_ROWS:
                    break

                batch_number += 1

                # --------------------------------------------
                # Remaining target rows
                # --------------------------------------------

                remaining_rows = (
                    MAX_ROWS
                    - processed_rows
                )

                batch_size = min(
                    BATCH_SIZE,
                    row_group_rows - offset,
                    remaining_rows,
                )

                # --------------------------------------------
                # Checkpoint
                # --------------------------------------------

                if is_batch_completed(
                    connection,
                    row_group_id,
                    batch_number,
                ):

                    print(
                        f"  Batch {batch_number} "
                        f"SKIP - already completed"
                    )

                    processed_rows += batch_size
                    offset += batch_size

                    continue

                print(
                    f"  Batch {batch_number} "
                    f"| Rows: {batch_size:,}"
                )

                # --------------------------------------------
                # Extract batch
                # --------------------------------------------

                arrow_batch = (
                    row_group_table.slice(
                        offset,
                        batch_size,
                    )
                )

                converted_rows = (
                    convert_batch(
                        arrow_batch,
                        load_batch_id,
                    )
                )

                batch_start = time.time()

                try:

                    insert_batch(
                        connection,
                        converted_rows,
                    )

                    cursor = connection.cursor()

                    mark_batch_completed(
                        cursor,
                        row_group_id,
                        batch_number,
                        batch_size,
                    )

                    update_run_rows(
                        cursor,
                        load_batch_id,
                        batch_size,
                    )

                    connection.commit()

                except Exception:

                    connection.rollback()

                    raise

                # --------------------------------------------
                # Statistics
                # --------------------------------------------

                processed_rows += batch_size

                offset += batch_size

                elapsed = (
                    time.time()
                    - batch_start
                )

                rows_per_second = (
                    batch_size / elapsed
                    if elapsed > 0
                    else 0
                )

                overall_elapsed = (
                    time.time()
                    - overall_start
                )

                overall_rps = (
                    processed_rows
                    / overall_elapsed
                    if overall_elapsed > 0
                    else 0
                )

                percentage = (
                    processed_rows
                    / MAX_ROWS
                    * 100
                )

                print(
                    f"  DONE | "
                    f"{batch_size:,} rows | "
                    f"{rows_per_second:,.0f} rows/sec | "
                    f"Total: {processed_rows:,} | "
                    f"{percentage:.2f}%"
                )

                if processed_rows >= MAX_ROWS:

                    print()
                    print("=" * 70)
                    print("TARGET LIMIT REACHED")
                    print("=" * 70)

                    print(
                        f"Rows loaded: "
                        f"{processed_rows:,}"
                    )

                    print(
                        f"Target rows: "
                        f"{MAX_ROWS:,}"
                    )

                    print(
                        "Marking load as COMPLETED..."
                    )

                    mark_run_completed(
                        connection,
                        load_batch_id,
                    )

                    print(
                        "20M transaction load completed successfully."
                    )

                    return

        # ----------------------------------------------------
        # Final safety
        # ----------------------------------------------------

        if processed_rows >= MAX_ROWS:

            mark_run_completed(
                connection,
                load_batch_id,
            )

    except Exception as exc:

        print()
        print("=" * 70)
        print("LOAD FAILED")
        print("=" * 70)

        print(
            f"{type(exc).__name__}: {exc}"
        )

        if load_batch_id is not None:

            mark_run_failed(
                connection,
                load_batch_id,
                str(exc),
            )

        raise

    finally:

        connection.close()


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":

    run_loader()