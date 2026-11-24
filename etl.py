import json
import os
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path

import pandas as pd
import psycopg
from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parent
SOURCE = (
    ROOT / "data" / "raw"
    / "dft-road-casualty-statistics-collision-1979-latest-published-year.csv"
)
RESULTS = ROOT / "results"
CHUNK_SIZE = 100_000

COLUMNS = [
    "collision_index",
    "collision_year",
    "collision_severity",
    "speed_limit",
    "light_conditions",
    "date",
    "time",
    "police_force",
]

NUMERIC_COLUMNS = [
    "collision_year",
    "collision_severity",
    "speed_limit",
    "light_conditions",
    "police_force",
]


def prepare(raw):
    """Преобразовать блок и выделить записи с неверным ключом или годом."""
    data = raw[COLUMNS].copy()

    for column in COLUMNS:
        data[column] = data[column].str.strip()

    for column in NUMERIC_COLUMNS:
        numbers = pd.to_numeric(data[column], errors="coerce")
        valid = (
            numbers.between(-32768, 32767)
            & numbers.mod(1).eq(0)
        )
        data[column] = numbers.where(valid).astype("Int64")

    valid_id = (
        data["collision_index"].ne("")
        & ~data["collision_index"].str.contains("\x00", regex=False)
    )
    current_year = datetime.now(timezone.utc).year
    valid_year = data["collision_year"].between(1979, current_year).fillna(False)
    accepted = valid_id & valid_year

    rejected = raw.loc[~accepted, COLUMNS].copy()
    rejected["reason"] = "Пустой/некорректный идентификатор или год"

    dates = pd.to_datetime(
        data["date"], format="%d/%m/%Y", errors="coerce"
    )
    dates = dates.where(
        dates.dt.year.eq(data["collision_year"]).fillna(False)
    )
    data["date"] = dates.dt.strftime("%Y-%m-%d")

    valid_time = data["time"].str.fullmatch(
        r"(?:[01]\d|2[0-3]):[0-5]\d"
    )
    data["time"] = data["time"].where(valid_time, pd.NA)

    return data.loc[accepted, COLUMNS], rejected


def main():
    load_dotenv(ROOT / ".env")

    if not SOURCE.is_file():
        raise FileNotFoundError(f"Не найден датасет: {SOURCE}")

    RESULTS.mkdir(exist_ok=True)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    reject_path = RESULTS / f"etl_rejects_{run_id}.csv"
    report_path = RESULTS / f"etl_report_{run_id}.json"

    report = {
        "source": SOURCE.name,
        "source_bytes": SOURCE.stat().st_size,
        "status": "running",
        "rows_read": 0,
        "rows_rejected": 0,
        "rows_inserted": 0,
        "rows_duplicate": 0,
        "missing_values": {column: 0 for column in COLUMNS},
    }

    try:
        with psycopg.connect(
            host="127.0.0.1",
            port=os.getenv("POSTGRES_PORT", "5432"),
            dbname=os.environ["POSTGRES_DB"],
            user=os.environ["POSTGRES_USER"],
            password=os.environ["POSTGRES_PASSWORD"],
            autocommit=True,
        ) as conn:
            with conn.cursor() as cur:
                # Запрет одновременного запуска двух копий этого ETL.
                cur.execute("SELECT pg_try_advisory_lock(240117)")
                if not cur.fetchone()[0]:
                    raise RuntimeError("Другой процесс ETL уже работает.")

                cur.execute("""
                    CREATE TEMP TABLE staging_collisions
                    (LIKE public.collisions)
                    ON COMMIT DELETE ROWS
                """)

                reader = pd.read_csv(
                    SOURCE,
                    usecols=COLUMNS,
                    dtype="string",
                    keep_default_na=False,
                    chunksize=CHUNK_SIZE,
                    encoding="utf-8-sig",
                )

                for number, raw in enumerate(reader, start=1):
                    report["rows_read"] += len(raw)
                    clean, rejected = prepare(raw)

                    if not rejected.empty:
                        rejected.to_csv(
                            reject_path,
                            mode="a",
                            header=not reject_path.exists(),
                            index=False,
                            encoding="utf-8",
                        )
                    report["rows_rejected"] += len(rejected)

                    missing = clean.isna().sum()
                    for column in COLUMNS:
                        report["missing_values"][column] += int(missing[column])

                    if not clean.empty:
                        with conn.transaction():
                            # CSV-буфер содержит только один обработанный блок.
                            buffer = StringIO()
                            clean.to_csv(
                                buffer,
                                index=False,
                                header=False,
                                na_rep="",
                                lineterminator="\n",
                            )

                            with cur.copy("""
                                COPY staging_collisions
                                FROM STDIN WITH (FORMAT CSV)
                            """) as copy:
                                copy.write(buffer.getvalue())

                            # Одинаковый ID с разными данными требует разбора.
                            cur.execute("""
                                SELECT collision_index
                                FROM staging_collisions AS s
                                GROUP BY collision_index
                                HAVING COUNT(DISTINCT ROW(s.*)) > 1
                                LIMIT 1
                            """)
                            conflict = cur.fetchone()

                            if conflict:
                                raise ValueError(
                                    f"Разные записи с одним ID: {conflict[0]}"
                                )

                            cur.execute("""
                                SELECT s.collision_index
                                FROM staging_collisions AS s
                                JOIN public.collisions AS c
                                  USING (collision_index)
                                WHERE ROW(c.*) IS DISTINCT FROM ROW(s.*)
                                LIMIT 1
                            """)
                            conflict = cur.fetchone()

                            if conflict:
                                raise ValueError(
                                    "Запись отличается от уже загруженной: "
                                    f"{conflict[0]}"
                                )

                            cur.execute("""
                                INSERT INTO public.collisions
                                SELECT DISTINCT *
                                FROM staging_collisions
                                ON CONFLICT (collision_index) DO NOTHING
                            """)
                            inserted = cur.rowcount

                        report["rows_inserted"] += inserted
                        report["rows_duplicate"] += len(clean) - inserted

                    print(
                        f"Блок {number}: "
                        f"прочитано {report['rows_read']:,}; "
                        f"добавлено {report['rows_inserted']:,}; "
                        f"повторов {report['rows_duplicate']:,}; "
                        f"отклонено {report['rows_rejected']:,}",
                        flush=True,
                    )

                cur.execute("ANALYZE public.collisions")
                cur.execute("SELECT COUNT(*) FROM public.collisions")
                report["rows_in_database"] = cur.fetchone()[0]

        report["status"] = "completed"

    except Exception as exc:
        report["status"] = "failed"
        report["error"] = str(exc)
        raise

    finally:
        report_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"Отчёт: {report_path}", flush=True)

    print("Загрузка завершена.")
    print(f"Строк в БД: {report['rows_in_database']:,}")


if __name__ == "__main__":
    main()