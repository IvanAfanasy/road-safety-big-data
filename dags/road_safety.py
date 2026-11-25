from datetime import datetime, timezone
from pathlib import Path

from airflow import DAG
from airflow.operators.bash import BashOperator


PROJECT_ROOT = str(Path(__file__).resolve().parents[1])


with DAG(
    dag_id="road_safety",
    description="STATS19: CSV → Spark → PostgreSQL → анализ ДТП",
    start_date=datetime(2025, 1, 1, tzinfo=timezone.utc),
    schedule=None,
    catchup=False,
    max_active_runs=1,
    tags=["spark", "postgres", "stats19"],
) as dag:
    check_source = BashOperator(
        task_id="check_source",
        cwd=PROJECT_ROOT,
        bash_command="python etl.py check",
    )
    load_collisions = BashOperator(
        task_id="load_collisions",
        cwd=PROJECT_ROOT,
        bash_command="spark-submit --master 'local[2]' --driver-memory 2g etl.py",
    )
    analyze = BashOperator(
        task_id="analyze",
        cwd=PROJECT_ROOT,
        bash_command="python analysis.py",
    )

    check_source >> load_collisions >> analyze
