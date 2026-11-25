import csv
import json
import os
import sys
from datetime import date
from gzip import open as open_gzip
from pathlib import Path
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "data/raw" / os.getenv(
    "SOURCE_CSV", "dft-road-casualty-statistics-collision-1979-latest-published-year.csv"
)
RESULTS = Path(os.getenv("RESULTS_DIR", ROOT / "results/latest"))
COLUMNS = (
    "collision_index", "collision_year", "collision_severity", "speed_limit",
    "light_conditions", "date", "time", "police_force",
)
NUMBER_COLUMNS = (
    "collision_year", "collision_severity", "speed_limit", "light_conditions", "police_force",
)


def check_source():
    if not SOURCE.is_file():
        raise FileNotFoundError(f"Положите исходный CSV в {SOURCE}")
    size = SOURCE.stat().st_size
    minimum = int(os.getenv("MIN_SOURCE_BYTES", "500000000"))
    if size <= minimum:
        raise ValueError(f"Размер CSV {size:,} байт. Требуется больше {minimum:,} байт.")
    open_csv = open_gzip if SOURCE.suffix == ".gz" else open
    with open_csv(SOURCE, "rt", encoding="utf-8-sig", newline="") as file:
        header = next(csv.reader(file), [])
    missing = set(COLUMNS) - set(header)
    if missing:
        raise ValueError(f"В CSV нет столбцов: {', '.join(sorted(missing))}")
    print(f"CSV: {SOURCE.name}, {size:,} байт")
    return size


def postgres_connection():
    import psycopg

    return psycopg.connect(
        host=os.getenv("POSTGRES_HOST", "127.0.0.1"),
        port=os.getenv("POSTGRES_PORT", "5432"),
        dbname=os.environ["POSTGRES_DB"],
        user=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"],
        connect_timeout=10,
    )


def clean_csv(spark):
    from pyspark.sql import functions as F

    raw = spark.read.csv(str(SOURCE), header=True, mode="FAILFAST")
    clean = raw.select(*(F.trim(column).alias(column) for column in COLUMNS))
    for column in NUMBER_COLUMNS:
        clean = clean.withColumn(column, F.expr(f"try_cast({column} AS SMALLINT)"))

    parsed_date = F.try_to_timestamp("date", F.lit("dd/MM/yyyy")).cast("date")
    clean = clean.withColumn("date", F.when(F.year(parsed_date) == F.col("collision_year"), parsed_date))
    clean = clean.withColumn("time", F.when(F.col("time").rlike(r"^([01][0-9]|2[0-3]):[0-5][0-9]$"), F.col("time")))

    collision_id = F.col("collision_index")
    valid_id = (F.length(collision_id) > 0) & ~collision_id.contains(chr(0))
    valid_year = F.col("collision_year").between(1979, date.today().year)
    return clean.withColumn("valid", F.coalesce(valid_id & valid_year, F.lit(False)))


def load_postgres(csv_dir):
    columns = ", ".join(COLUMNS)
    updated = ", ".join(f"{column} = EXCLUDED.{column}" for column in COLUMNS[1:])
    current = ", ".join(f"c.{column}" for column in COLUMNS[1:])
    incoming = ", ".join(f"EXCLUDED.{column}" for column in COLUMNS[1:])

    with postgres_connection() as conn, conn.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(240117)")
        cursor.execute((ROOT / "sql/schema.sql").read_text(encoding="utf-8"))
        cursor.execute(f"""
            CREATE TEMP TABLE staging_collisions ON COMMIT DROP AS
            SELECT {columns} FROM public.collisions WITH NO DATA
        """)
        for path in sorted(csv_dir.glob("part-*.csv.gz")):
            with open_gzip(path, "rb") as file, cursor.copy(
                f"COPY staging_collisions ({columns}) FROM STDIN WITH (FORMAT CSV)"
            ) as copy:
                while block := file.read(1024 * 1024):
                    copy.write(block)

        # Spark removes identical rows. A repeated key here means conflicting values.
        cursor.execute("CREATE UNIQUE INDEX ON staging_collisions (collision_index)")
        cursor.execute("SELECT COUNT(*) FROM staging_collisions")
        staged = cursor.fetchone()[0]
        if staged == 0:
            raise ValueError("После очистки не осталось строк для загрузки.")

        cursor.execute(f"""
            INSERT INTO public.collisions AS c ({columns})
            SELECT {columns} FROM staging_collisions
            ON CONFLICT (collision_index) DO UPDATE SET {updated}
            WHERE ROW({current}) IS DISTINCT FROM ROW({incoming})
        """)
        changed = cursor.rowcount
        cursor.execute((ROOT / "sql/dashboard.sql").read_text(encoding="utf-8"))
        cursor.execute("ANALYZE public.collisions")
        cursor.execute("SELECT COUNT(*) FROM public.collisions")
        return staged, changed, cursor.fetchone()[0]


def main():
    from pyspark.sql import SparkSession
    from pyspark.sql import functions as F

    source_bytes = check_source()
    spark = (
        SparkSession.builder.appName("STATS19")
        .config("spark.sql.shuffle.partitions", "8")
        .config("spark.sql.legacy.timeParserPolicy", "CORRECTED")
        .getOrCreate()
    )
    spark.sparkContext.setLogLevel("WARN")
    try:
        with TemporaryDirectory(prefix="stats19-") as folder:
            csv_dir = Path(folder) / "clean"
            data = clean_csv(spark).cache()
            counts = data.agg(
                F.count("*").alias("read"),
                F.count(F.when(~F.col("valid"), 1)).alias("rejected"),
                F.count(F.when(F.col("valid") & F.col("date").isNull(), 1)).alias("missing_date"),
                F.count(F.when(F.col("valid") & F.col("time").isNull(), 1)).alias("missing_time"),
            ).first()
            clean = data.filter("valid").select(*COLUMNS).dropDuplicates()
            clean.write.option("escape", '"').csv(str(csv_dir), compression="gzip")
            data.unpersist()

            staged, changed, total = load_postgres(csv_dir)
    finally:
        spark.stop()

    report = {
        "source": SOURCE.name,
        "source_bytes": source_bytes,
        "rows_read": counts["read"],
        "rows_rejected": counts["rejected"],
        "rows_duplicate": counts["read"] - counts["rejected"] - staged,
        "rows_staged": staged,
        "rows_changed": changed,
        "rows_in_database": total,
        "accepted_missing_date": counts["missing_date"],
        "accepted_missing_time": counts["missing_time"],
    }
    RESULTS.mkdir(parents=True, exist_ok=True)
    output = RESULTS / "load_report.json"
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(output.read_text(encoding="utf-8"))


if __name__ == "__main__":
    if sys.argv[1:] == ["check"]:
        check_source()
    else:
        main()
