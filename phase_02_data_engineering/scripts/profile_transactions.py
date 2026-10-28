from __future__ import annotations

from collections import Counter
from pathlib import Path

import pyarrow.parquet as pq


PARQUET_FILE = Path(
    r"C:\Users\maged.magdy\.cache\huggingface\hub"
    r"\datasets--ziadatalabs--FreeFinancialTransactions50M"
    r"\snapshots\98cf38f9b2f1a9994930f52a4d490cb2b5777acc"
    r"\transactions_50M.parquet"
)

BATCH_SIZE = 250_000


def main() -> None:
    if not PARQUET_FILE.exists():
        raise FileNotFoundError(
            f"File not found:\n{PARQUET_FILE}"
        )

    parquet = pq.ParquetFile(PARQUET_FILE)

    columns = [
        "transaction_id",
        "account_id",
        "transaction_type",
        "amount",
        "currency",
        "merchant_category",
        "balance_after",
        "transaction_timestamp",
        "status",
    ]

    null_counts = Counter()

    transaction_types = Counter()
    currencies = Counter()
    statuses = Counter()

    min_timestamp = None
    max_timestamp = None

    min_amount = None
    max_amount = None

    total_rows = 0

    print("=" * 70)
    print("TRANSACTIONS DATA QUALITY PROFILE")
    print("=" * 70)

    for batch_number, batch in enumerate(
        parquet.iter_batches(
            batch_size=BATCH_SIZE,
            columns=columns,
        ),
        start=1,
    ):
        rows = batch.num_rows
        total_rows += rows

        data = batch.to_pydict()

        # -----------------------------
        # Null counts
        # -----------------------------

        for column in columns:
            values = data[column]

            null_counts[column] += sum(
                value is None
                for value in values
            )

        # -----------------------------
        # Categories
        # -----------------------------

        transaction_types.update(
            value
            for value in data["transaction_type"]
            if value is not None
        )

        currencies.update(
            value
            for value in data["currency"]
            if value is not None
        )

        statuses.update(
            value
            for value in data["status"]
            if value is not None
        )

        # -----------------------------
        # Timestamp range
        # -----------------------------

        timestamps = [
            value
            for value in data["transaction_timestamp"]
            if value is not None
        ]

        if timestamps:
            batch_min = min(timestamps)
            batch_max = max(timestamps)

            if min_timestamp is None or batch_min < min_timestamp:
                min_timestamp = batch_min

            if max_timestamp is None or batch_max > max_timestamp:
                max_timestamp = batch_max

        # -----------------------------
        # Amount range
        # -----------------------------

        amounts = [
            float(value)
            for value in data["amount"]
            if value is not None
        ]

        if amounts:
            batch_min = min(amounts)
            batch_max = max(amounts)

            if min_amount is None or batch_min < min_amount:
                min_amount = batch_min

            if max_amount is None or batch_max > max_amount:
                max_amount = batch_max

        if batch_number % 10 == 0:
            print(
                f"Processed rows: {total_rows:,}"
            )

    print()
    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)

    print(
        f"Rows: {total_rows:,}"
    )

    print(
        f"Min timestamp: {min_timestamp}"
    )

    print(
        f"Max timestamp: {max_timestamp}"
    )

    print(
        f"Min amount: {min_amount}"
    )

    print(
        f"Max amount: {max_amount}"
    )

    print()
    print("NULL COUNTS")
    print("-" * 70)

    for column in columns:
        count = null_counts[column]

        percentage = (
            count / total_rows * 100
            if total_rows
            else 0
        )

        print(
            f"{column:25} "
            f"{count:12,} "
            f"({percentage:.4f}%)"
        )

    print()
    print("TRANSACTION TYPES")
    print("-" * 70)

    for value, count in transaction_types.most_common():
        print(
            f"{str(value):25} {count:12,}"
        )

    print()
    print("CURRENCIES")
    print("-" * 70)

    for value, count in currencies.most_common():
        print(
            f"{str(value):25} {count:12,}"
        )

    print()
    print("STATUSES")
    print("-" * 70)

    for value, count in statuses.most_common():
        print(
            f"{str(value):25} {count:12,}"
        )


if __name__ == "__main__":
    main()