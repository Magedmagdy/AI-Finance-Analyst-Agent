from pathlib import Path

import pyarrow.parquet as pq


PARQUET_FILE = Path(
    r"C:\Users\maged.magdy\.cache\huggingface\hub"
    r"\datasets--ziadatalabs--FreeFinancialTransactions50M"
    r"\snapshots\98cf38f9b2f1a9994930f52a4d490cb2b5777acc"
    r"\transactions_50M.parquet"
)


def main() -> None:
    if not PARQUET_FILE.exists():
        raise FileNotFoundError(
            f"Parquet file not found:\n{PARQUET_FILE}"
        )

    parquet = pq.ParquetFile(PARQUET_FILE)

    print("=" * 70)
    print("FREE FINANCIAL TRANSACTIONS 50M")
    print("=" * 70)

    print(f"File      : {PARQUET_FILE}")
    print(f"File size : {PARQUET_FILE.stat().st_size / (1024**3):.2f} GB")
    print(f"Rows      : {parquet.metadata.num_rows:,}")
    print(f"Row groups: {parquet.num_row_groups}")
    print()

    print("SCHEMA")
    print("-" * 70)
    print(parquet.schema_arrow)

    print()
    print("COLUMNS")
    print("-" * 70)

    for field in parquet.schema_arrow:
        print(
            f"{field.name:25} "
            f"{str(field.type):25} "
            f"nullable={field.nullable}"
        )

    print()
    print("FIRST 5 ROWS")
    print("-" * 70)

    table = parquet.read_row_group(
        0
    ).slice(
        0,
        5
    )

    print(
        table.to_pandas()
        .to_string(index=False)
    )


if __name__ == "__main__":
    main()