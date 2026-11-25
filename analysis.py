"""Проверка гипотез, классификация и интерактивные графики по данным PostgreSQL."""

from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from scipy.stats import norm, ttest_1samp
from sklearn.dummy import DummyClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, f1_score, precision_score, recall_score, roc_auc_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import OneHotEncoder

from etl import RESULTS, ROOT, postgres_connection


START_YEAR, END_YEAR = 2022, 2024
PEAK_HOURS = [7, 8, 9, 16, 17, 18]
WEEKDAYS = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
SPEED_GROUPS = ["50–70 mph", "20–30 mph"]
LIGHT_GROUPS = ["Без освещения", "Дневной свет"]


def read_postgres():
    with postgres_connection() as conn, conn.cursor() as cursor:
        cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        cursor.execute("""
            SELECT collision_year AS year, COUNT(*) AS collisions
            FROM public.collisions GROUP BY collision_year ORDER BY collision_year
        """)
        annual = pd.DataFrame(cursor.fetchall(), columns=["year", "collisions"])
        cursor.execute("""
            SELECT collision_year AS year, collision_date AS date, hour, weekday,
                   speed_limit, speed_group, light_conditions, lighting_group, police_force, severe
            FROM public.collisions_dashboard
            WHERE collision_year BETWEEN %s AND %s
        """, (START_YEAR, END_YEAR))
        data = pd.DataFrame(cursor.fetchall(), columns=[column.name for column in cursor.description])
    data["date"] = pd.to_datetime(data["date"])
    return annual, data


def group_shares(data, column, groups):
    return (
        data.groupby(column)["severe"].agg(total="count", severe="sum")
        .reindex(groups, fill_value=0)
        .assign(percent=lambda rows: 100 * rows["severe"] / rows["total"])
    )


def test_shares(name, data, column, groups):
    # Односторонний Z-тест двух долей с общей оценкой доли при H0.
    rows = group_shares(data, column, groups)
    n1, n0 = rows["total"]
    s1, s0 = rows["severe"]
    if min(s1, n1 - s1, s0, n0 - s0) < 5:
        raise ValueError(f"{name}: недостаточно наблюдений для Z-теста.")
    pooled = (s1 + s0) / (n1 + n0)
    error = np.sqrt(pooled * (1 - pooled) * (1 / n1 + 1 / n0))
    return name, *groups, 100 * s1 / n1, 100 * s0 / n0, "п. п.", norm.sf((s1 / n1 - s0 / n0) / error)


def test_peak(name, daily):
    calendar = pd.date_range(f"{START_YEAR}-01-01", f"{END_YEAR}-12-31")
    if not daily.index.sort_values().equals(calendar):
        raise ValueError(f"{name}: в данных отсутствуют дни выбранного периода.")
    daily = daily.assign(peak_rate=daily["peak"] / 6, other_rate=daily["other"] / 18)
    test = ttest_1samp(daily["peak_rate"] - daily["other_rate"], 0, alternative="greater")
    return (
        name, "Часы пик", "Остальные часы",
        daily["peak_rate"].mean(), daily["other_rate"].mean(), "ДТП/ч", test.pvalue,
    )


def test_hypotheses(data, timed):
    daily = (
        timed.assign(peak=timed["hour"].isin(PEAK_HOURS))
        .groupby(["date", "peak"]).size().unstack(fill_value=0)
        .reindex(columns=[True, False], fill_value=0)
    )
    daily.columns = ["peak", "other"]
    results = [
        test_shares("H1", data, "speed_group", SPEED_GROUPS),
        test_shares("H2", data, "lighting_group", LIGHT_GROUPS),
        test_peak("H3", daily),
    ]
    columns = ["hypothesis", "group1", "group0", "value1", "value0", "unit", "p_value"]
    hypotheses = pd.DataFrame(results, columns=columns)
    hypotheses["difference"] = hypotheses["value1"] - hypotheses["value0"]
    hypotheses["p_adjusted"] = (hypotheses["p_value"] * len(hypotheses)).clip(upper=1)
    hypotheses["decision"] = np.where(
        hypotheses["p_adjusted"] < 0.05, "Отклоняем H0", "Недостаточно оснований отклонить H0",
    )

    nyc = pd.read_csv(
        ROOT / "data/reference/nyc_crashes_daily_2022_2024.csv", index_col="date", parse_dates=["date"],
    )
    external = pd.DataFrame([test_peak("H3 / Нью-Йорк", nyc)], columns=columns)
    external["difference"] = external["value1"] - external["value0"]
    external["decision"] = np.where(
        external["p_value"] < 0.05, "Отклоняем H0", "Недостаточно оснований отклонить H0",
    )
    return hypotheses, external


def regression(data):
    sample = data[
        data["speed_group"].isin(SPEED_GROUPS) & data["lighting_group"].isin(LIGHT_GROUPS)
        & data["police_force"].gt(0) & data["severe"].notna()
    ].copy()
    sample["high_speed"] = sample["speed_group"].eq(SPEED_GROUPS[0]).astype(int)
    sample["no_lighting"] = sample["lighting_group"].eq(LIGHT_GROUPS[0]).astype(int)
    features = pd.get_dummies(
        sample[["high_speed", "no_lighting", "year", "police_force"]],
        columns=["year", "police_force"], drop_first=True, dtype=int,
    )
    model = LogisticRegression(max_iter=1000).fit(features, sample["severe"].astype(int))
    return pd.DataFrame({"feature": features.columns, "odds_ratio": np.exp(model.coef_[0]), "n": len(sample)})


def classification(data):
    known = data.dropna(subset=["severe"])
    features = ["speed_limit", "light_conditions", "police_force", "weekday", "hour"]
    x = known[features].where(known[features].ge(0)).astype("Int64").astype("string").fillna("unknown")
    target = known["severe"].astype(int)
    train = known["year"] < END_YEAR
    models = {
        "Наиболее частый класс": DummyClassifier(strategy="most_frequent"),
        "Логистическая регрессия": make_pipeline(
            OneHotEncoder(handle_unknown="ignore"),
            LogisticRegression(max_iter=1000, class_weight="balanced"),
        ),
    }
    rows = []
    for name, model in models.items():
        model.fit(x[train], target[train])
        actual = target[~train]
        prediction = model.predict(x[~train])
        probability = model.predict_proba(x[~train])[:, 1]
        rows.append({
            "model": name,
            "train_rows": int(train.sum()),
            "test_rows": len(actual),
            "precision": precision_score(actual, prediction, zero_division=0),
            "recall": recall_score(actual, prediction, zero_division=0),
            "f1": f1_score(actual, prediction, zero_division=0),
            "roc_auc": roc_auc_score(actual, probability),
            "average_precision": average_precision_score(actual, probability),
        })
    return pd.DataFrame(rows)


def dashboard(annual, data, path):
    fig = make_subplots(
        rows=2, cols=2, vertical_spacing=0.16,
        subplot_titles=("ДТП по годам", "ДТП по дням недели и часам", "Тяжёлые ДТП и лимит скорости", "Тяжёлые ДТП и освещение"),
    )
    fig.add_trace(go.Scatter(x=annual["year"], y=annual["collisions"], mode="lines"), row=1, col=1)
    periods = ["2022–2024", *range(START_YEAR, END_YEAR + 1)]
    for period in periods:
        show = period == periods[0]
        sample = data if show else data[data["year"].eq(period)]
        heatmap = (
            sample.groupby(["weekday", "hour"]).size().unstack(fill_value=0)
            .reindex(index=range(1, 8), columns=range(24), fill_value=0)
        )
        fig.add_trace(go.Heatmap(
            x=list(range(24)), y=WEEKDAYS, z=heatmap.to_numpy(), colorscale="Blues",
            showscale=False, visible=show,
            hovertemplate="%{y}, %{x}:00<br>ДТП: %{z}<extra></extra>",
        ), row=1, col=2)
        charts = [("speed_group", SPEED_GROUPS, 1, "#176a8a"), ("lighting_group", LIGHT_GROUPS, 2, "#a4531b")]
        for column, groups, position, color in charts:
            shares = group_shares(sample, column, groups)
            fig.add_trace(go.Bar(
                x=groups, y=shares["percent"], customdata=shares[["severe", "total"]].to_numpy(),
                marker_color=color, visible=show,
                hovertemplate="%{x}<br>%{y:.2f}% (%{customdata[0]:.0f} из %{customdata[1]:.0f})<extra></extra>",
            ), row=2, col=position)

    buttons = [
        dict(label=str(period), method="update", args=[{
            "visible": [True] + [i == j for j in range(len(periods)) for _ in range(3)],
        }])
        for i, period in enumerate(periods)
    ]
    fig.update_xaxes(title_text="Год", row=1, col=1)
    fig.update_yaxes(title_text="ДТП", row=1, col=1)
    fig.update_xaxes(title_text="Час", dtick=4, row=1, col=2)
    fig.update_yaxes(autorange="reversed", row=1, col=2)
    fig.update_yaxes(title_text="Доля, %", range=[0, 100], row=2)
    fig.update_layout(
        title="Зарегистрированные ДТП с пострадавшими в Великобритании",
        showlegend=False, template="plotly_white", height=720, margin=dict(t=150),
        updatemenus=[dict(buttons=buttons, x=1, y=1.15, xanchor="right")],
    )
    fig.write_html(path, include_plotlyjs=True)


def main():
    annual, data = read_postgres()
    timed = data.dropna(subset=["date", "hour"])
    hypotheses, external = test_hypotheses(data, timed)
    coefficients = regression(data)
    metrics = classification(data)
    RESULTS.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=RESULTS) as folder:
        output = Path(folder)
        tables = {
            "annual": annual, "hypotheses": hypotheses, "external_h3": external,
            "regression": coefficients, "ml_metrics": metrics,
        }
        for name, table in tables.items():
            table.to_csv(output / f"{name}.csv", index=False)
        dashboard(annual, data, output / "dashboard.html")
        for path in output.iterdir():
            path.replace(RESULTS / path.name)

    print(f"Всего в PostgreSQL: {annual['collisions'].sum():,}. ДТП за 2022–2024: {len(data):,}.")
    print(hypotheses.to_string(index=False))
    print(external.to_string(index=False))
    print(metrics.to_string(index=False))


if __name__ == "__main__":
    main()
