import io
from datetime import date, timedelta

import pandas as pd
import plotly.express as px
import streamlit as st

DATE_COL = "Дата сделки"
MANAGER_COL = "Менеджер"
STAGE_COL = "Стадия сделки"
CLIENT_COL = "ФИО Клиента"
PRODUCT_COL = "Продукт"
PLAN_COL = "Сумма продажи план"
FACT_COL = "Сумма продажи факт"

REQUIRED_COLUMNS = [
    DATE_COL,
    MANAGER_COL,
    STAGE_COL,
    CLIENT_COL,
    PRODUCT_COL,
    PLAN_COL,
    FACT_COL,
]

STATUS_LABELS = {
    "won": "Выиграна",
    "open": "В работе",
    "lost": "Проиграна",
}

WON_KEYWORDS = ("сделка", "оплата", "успеш", "won", "закрыто")
LOST_KEYWORDS = ("потеря", "отказ", "lost", "проиг", "неуспеш")

STAGE_PROBABILITY_HINTS = {
    "лид": 0.1,
    "квалифика": 0.2,
    "контакт": 0.25,
    "презента": 0.4,
    "коммерчес": 0.5,
    "переговор": 0.65,
    "счет": 0.75,
    "договор": 0.85,
    "сделка": 1.0,
    "оплата": 1.0,
    "потер": 0.0,
    "отказ": 0.0,
}


def format_money(value):
    return f"{int(round(value)):,} ₽".replace(",", " ")


def format_count(value):
    return f"{int(round(value)):,}".replace(",", " ")


def safe_div(numerator, denominator):
    return numerator / denominator if denominator else 0.0


def series_safe_div(numerator, denominator):
    denominator = denominator.where(denominator != 0, pd.NA)
    return numerator.divide(denominator).fillna(0.0)


def classify_stage(stage_value):
    text = str(stage_value).strip().lower()
    if any(keyword in text for keyword in WON_KEYWORDS):
        return "won"
    if any(keyword in text for keyword in LOST_KEYWORDS):
        return "lost"
    return "open"


def stage_probability(stage_value):
    text = str(stage_value).strip().lower()
    for hint, probability in STAGE_PROBABILITY_HINTS.items():
        if hint in text:
            return probability

    status = classify_stage(text)
    if status == "won":
        return 1.0
    if status == "lost":
        return 0.0
    return 0.35


def to_numeric(series):
    cleaned = (
        series.astype(str)
        .str.replace(r"[^\d,.-]", "", regex=True)
        .str.replace(",", ".", regex=False)
        .replace("", "0")
    )
    return pd.to_numeric(cleaned, errors="coerce").fillna(0.0)


@st.cache_data(show_spinner=False)
def load_data(file_bytes):
    source = io.BytesIO(file_bytes) if file_bytes else "sales_data.xlsx"
    return pd.read_excel(source)


@st.cache_data(show_spinner=False)
def preprocess_data(raw_df):
    df = raw_df.copy()
    df.columns = [str(column).strip() for column in df.columns]

    missing_columns = [column for column in REQUIRED_COLUMNS if column not in df.columns]
    if missing_columns:
        missing_text = ", ".join(missing_columns)
        st.error(f"В файле не хватает обязательных столбцов: {missing_text}")
        st.stop()

    df[DATE_COL] = pd.to_datetime(df[DATE_COL], errors="coerce")
    df = df.dropna(subset=[DATE_COL])

    df[PLAN_COL] = to_numeric(df[PLAN_COL])
    df[FACT_COL] = to_numeric(df[FACT_COL])

    for column in [MANAGER_COL, STAGE_COL, CLIENT_COL, PRODUCT_COL]:
        df[column] = df[column].fillna("Не указано").astype(str).str.strip()
        df.loc[df[column] == "", column] = "Не указано"

    df["Статус"] = df[STAGE_COL].apply(classify_stage)
    df["Вероятность этапа"] = df[STAGE_COL].apply(stage_probability)

    df["Потенциал сделки"] = df[PLAN_COL].where(df[PLAN_COL] > 0, df[FACT_COL]).fillna(0.0)
    df["Факт закрытия"] = df[FACT_COL].where(df["Статус"] == "won", 0.0)

    won_without_fact = (df["Статус"] == "won") & (df["Факт закрытия"] <= 0)
    df.loc[won_without_fact, "Факт закрытия"] = df.loc[won_without_fact, "Потенциал сделки"]

    df["Открытый пайплайн"] = df["Потенциал сделки"].where(df["Статус"] == "open", 0.0)
    df["Взвешенный прогноз"] = (
        df["Потенциал сделки"] * df["Вероятность этапа"]
    ).where(df["Статус"] == "open", 0.0)

    df["Выиграно"] = (df["Статус"] == "won").astype(int)
    df["Проиграно"] = (df["Статус"] == "lost").astype(int)
    df["В работе"] = (df["Статус"] == "open").astype(int)

    df["Месяц"] = df[DATE_COL].dt.to_period("M").dt.to_timestamp()
    df["День"] = df[DATE_COL].dt.date
    return df.sort_values(DATE_COL)


def parse_date_range(selected_value, min_date, max_date):
    if isinstance(selected_value, tuple) and len(selected_value) == 2:
        start_date, end_date = selected_value
        return min(start_date, end_date), max(start_date, end_date)

    if isinstance(selected_value, list) and len(selected_value) == 2:
        start_date, end_date = selected_value
        return min(start_date, end_date), max(start_date, end_date)

    return min_date, max_date


def get_previous_period(start_date, end_date):
    days_count = (end_date - start_date).days + 1
    previous_end = start_date - timedelta(days=1)
    previous_start = previous_end - timedelta(days=days_count - 1)
    return previous_start, previous_end


def filter_data(
    df,
    start_date,
    end_date,
    managers,
    products,
    stages,
    statuses,
    min_amount,
    client_query,
):
    filtered = df[
        (df[DATE_COL].dt.date >= start_date) &
        (df[DATE_COL].dt.date <= end_date)
    ]

    if managers:
        filtered = filtered[filtered[MANAGER_COL].isin(managers)]
    if products:
        filtered = filtered[filtered[PRODUCT_COL].isin(products)]
    if stages:
        filtered = filtered[filtered[STAGE_COL].isin(stages)]
    if statuses:
        filtered = filtered[filtered["Статус"].isin(statuses)]
    if min_amount > 0:
        filtered = filtered[filtered["Потенциал сделки"] >= min_amount]
    if client_query:
        filtered = filtered[
            filtered[CLIENT_COL].str.contains(client_query, case=False, na=False)
        ]

    return filtered.copy()


def calculate_kpis(df):
    won = int(df["Выиграно"].sum())
    lost = int(df["Проиграно"].sum())
    in_progress = int(df["В работе"].sum())
    total_deals = int(len(df))

    plan = float(df[PLAN_COL].sum())
    fact = float(df["Факт закрытия"].sum())
    open_pipeline = float(df["Открытый пайплайн"].sum())
    weighted_pipeline = float(df["Взвешенный прогноз"].sum())
    forecast = fact + weighted_pipeline

    return {
        "plan": plan,
        "fact": fact,
        "open_pipeline": open_pipeline,
        "weighted_pipeline": weighted_pipeline,
        "forecast": forecast,
        "total_deals": total_deals,
        "won": won,
        "lost": lost,
        "in_progress": in_progress,
        "plan_attainment_pct": safe_div(fact, plan) * 100,
        "forecast_attainment_pct": safe_div(forecast, plan) * 100,
        "conversion_pct": safe_div(won, total_deals) * 100,
        "win_rate_pct": safe_div(won, won + lost) * 100,
        "avg_check": safe_div(fact, won),
    }


def calculate_delta(current_value, previous_value):
    if previous_value is None or previous_value == 0:
        return None
    change = (current_value - previous_value) / abs(previous_value) * 100
    return f"{change:+.1f}%"


def show_metric(column, label, value, value_type="money", previous_value=None):
    if value_type == "money":
        shown_value = format_money(value)
    elif value_type == "percent":
        shown_value = f"{value:.1f}%"
    else:
        shown_value = format_count(value)

    delta = calculate_delta(value, previous_value)
    column.metric(label, shown_value, delta)


def build_manager_table(df):
    if df.empty:
        return pd.DataFrame()

    manager_table = df.groupby(MANAGER_COL, as_index=False).agg(
        Лиды=("Потенциал сделки", "size"),
        Выиграно=("Выиграно", "sum"),
        Проиграно=("Проиграно", "sum"),
        В_работе=("В работе", "sum"),
        План=(PLAN_COL, "sum"),
        Факт=("Факт закрытия", "sum"),
        Открытый_пайплайн=("Открытый пайплайн", "sum"),
        Взвешенный_прогноз=("Взвешенный прогноз", "sum"),
    )

    manager_table["Конверсия, %"] = manager_table["Выиграно"] / manager_table["Лиды"] * 100
    manager_table["Win rate, %"] = (
        manager_table["Выиграно"] /
        (manager_table["Выиграно"] + manager_table["Проиграно"]).replace(0, pd.NA)
    ).fillna(0) * 100
    manager_table["Выполнение плана, %"] = (
        series_safe_div(manager_table["Факт"], manager_table["План"]) * 100
    )
    manager_table["Средний чек"] = (
        manager_table["Факт"] / manager_table["Выиграно"].replace(0, pd.NA)
    ).fillna(0)

    return manager_table.sort_values("Факт", ascending=False)


def build_client_table(df):
    if df.empty:
        return pd.DataFrame()

    client_table = df.groupby(CLIENT_COL, as_index=False).agg(
        Сделки=("Потенциал сделки", "size"),
        Выиграно=("Выиграно", "sum"),
        Выручка=("Факт закрытия", "sum"),
        Потенциал=("Открытый пайплайн", "sum"),
        Последняя_сделка=(DATE_COL, "max"),
    )
    client_table["Конверсия, %"] = (
        client_table["Выиграно"] / client_table["Сделки"] * 100
    )
    return client_table.sort_values("Выручка", ascending=False)


def build_product_table(df):
    if df.empty:
        return pd.DataFrame()

    product_table = df.groupby(PRODUCT_COL, as_index=False).agg(
        Сделки=("Потенциал сделки", "size"),
        Выиграно=("Выиграно", "sum"),
        Выручка=("Факт закрытия", "sum"),
        Потенциал=("Открытый пайплайн", "sum"),
    )
    product_table["Конверсия, %"] = (
        product_table["Выиграно"] / product_table["Сделки"] * 100
    )
    return product_table.sort_values("Выручка", ascending=False)


def generate_insights(kpis, manager_table, client_table):
    insights = []

    if kpis["plan"] > 0 and kpis["plan_attainment_pct"] < 80:
        insights.append(("warning", "Выполнение плана ниже 80%: требуется ускорение закрытия сделок."))
    if kpis["plan"] > 0 and kpis["forecast_attainment_pct"] < 100:
        gap = max(kpis["plan"] - kpis["forecast"], 0)
        insights.append(("error", f"По текущему прогнозу не хватает {format_money(gap)} до плана."))
    if kpis["win_rate_pct"] < 25:
        insights.append(("warning", "Низкий win rate: стоит проверить качество лидов и этапы переговоров."))
    if kpis["open_pipeline"] == 0 and kpis["plan"] > kpis["fact"]:
        insights.append(("warning", "Открытый пайплайн пуст, но план еще не выполнен."))

    if not manager_table.empty and kpis["fact"] > 0:
        top_manager_share = manager_table.iloc[0]["Факт"] / kpis["fact"] * 100
        if top_manager_share > 55:
            manager_name = manager_table.iloc[0][MANAGER_COL]
            insights.append(("info", f"Высокая зависимость от одного менеджера ({manager_name}: {top_manager_share:.1f}% выручки)."))

    if not client_table.empty and kpis["fact"] > 0:
        top_client_share = client_table.iloc[0]["Выручка"] / kpis["fact"] * 100
        if top_client_share > 35:
            client_name = client_table.iloc[0][CLIENT_COL]
            insights.append(("info", f"Концентрация выручки на клиенте {client_name}: {top_client_share:.1f}%."))

    if not insights:
        insights.append(("success", "Критичных отклонений не обнаружено, показатели в контролируемом диапазоне."))

    return insights


st.set_page_config(page_title="Панель руководителя продаж", layout="wide")
st.title("Панель руководителя отдела продаж")
st.caption("Управленческий дашборд: KPI, воронка, эффективность менеджеров, клиентская и продуктовая аналитика.")

with st.sidebar:
    st.header("Источник данных")
    uploaded_file = st.file_uploader(
        "Excel с продажами (.xlsx)",
        type=["xlsx"],
        help="Если файл не выбран, используется sales_data.xlsx из проекта.",
    )

file_bytes = uploaded_file.getvalue() if uploaded_file else None
raw_data = load_data(file_bytes)
df = preprocess_data(raw_data)

if df.empty:
    st.warning("После подготовки не осталось валидных строк (проверьте даты и обязательные поля).")
    st.stop()

min_date = df[DATE_COL].min().date()
max_date = df[DATE_COL].max().date()

with st.sidebar:
    st.header("Фильтры")
    selected_period = st.date_input(
        "Период сделки",
        value=(min_date, max_date),
        min_value=min_date,
        max_value=max_date,
    )
    start_date, end_date = parse_date_range(selected_period, min_date, max_date)

    manager_options = sorted(df[MANAGER_COL].unique().tolist())
    selected_managers = st.multiselect(
        "Менеджеры",
        options=manager_options,
        default=manager_options,
    )

    product_options = sorted(df[PRODUCT_COL].unique().tolist())
    selected_products = st.multiselect(
        "Продукты",
        options=product_options,
        default=product_options,
    )

    stage_options = sorted(df[STAGE_COL].unique().tolist())
    selected_stages = st.multiselect(
        "Стадии сделки",
        options=stage_options,
        default=stage_options,
    )

    status_options = list(STATUS_LABELS.values())
    selected_status_labels = st.multiselect(
        "Статусы",
        options=status_options,
        default=status_options,
    )
    selected_statuses = [
        status for status, label in STATUS_LABELS.items() if label in selected_status_labels
    ]

    max_amount = int(df["Потенциал сделки"].max()) if len(df) else 0
    step = max(10000, max_amount // 50) if max_amount else 10000
    min_amount = st.number_input(
        "Минимальная сумма сделки, ₽",
        min_value=0,
        value=0,
        step=step,
    )

    client_query = st.text_input("Поиск по клиенту", value="")
    compare_previous = st.checkbox("Сравнить с предыдущим периодом", value=True)

filtered_df = filter_data(
    df=df,
    start_date=start_date,
    end_date=end_date,
    managers=selected_managers,
    products=selected_products,
    stages=selected_stages,
    statuses=selected_statuses,
    min_amount=min_amount,
    client_query=client_query.strip(),
)

if filtered_df.empty:
    st.warning("По текущим фильтрам данных нет. Измени период или ослабь фильтрацию.")
    st.stop()

kpis = calculate_kpis(filtered_df)
manager_table = build_manager_table(filtered_df)
client_table = build_client_table(filtered_df)
product_table = build_product_table(filtered_df)

previous_kpis = None
previous_start = None
previous_end = None

if compare_previous:
    previous_start, previous_end = get_previous_period(start_date, end_date)
    previous_df = filter_data(
        df=df,
        start_date=previous_start,
        end_date=previous_end,
        managers=selected_managers,
        products=selected_products,
        stages=selected_stages,
        statuses=selected_statuses,
        min_amount=min_amount,
        client_query=client_query.strip(),
    )
    if not previous_df.empty:
        previous_kpis = calculate_kpis(previous_df)

with st.sidebar:
    st.markdown("---")
    st.caption(f"Сделок в выборке: {format_count(len(filtered_df))}")
    st.caption(f"Выиграно: {format_count(kpis['won'])} | Проиграно: {format_count(kpis['lost'])}")
    if previous_start and previous_end:
        st.caption(f"Период сравнения: {previous_start} - {previous_end}")

tab_summary, tab_funnel, tab_managers, tab_clients, tab_registry = st.tabs(
    ["Сводка", "Воронка", "Менеджеры", "Клиенты и продукты", "Реестр сделок"]
)

with tab_summary:
    st.subheader("Ключевые KPI")
    metric_row_1 = st.columns(4)
    show_metric(
        metric_row_1[0],
        "План",
        kpis["plan"],
        value_type="money",
        previous_value=previous_kpis["plan"] if previous_kpis else None,
    )
    show_metric(
        metric_row_1[1],
        "Факт",
        kpis["fact"],
        value_type="money",
        previous_value=previous_kpis["fact"] if previous_kpis else None,
    )
    show_metric(
        metric_row_1[2],
        "Выполнение плана",
        kpis["plan_attainment_pct"],
        value_type="percent",
        previous_value=previous_kpis["plan_attainment_pct"] if previous_kpis else None,
    )
    show_metric(
        metric_row_1[3],
        "Конверсия",
        kpis["conversion_pct"],
        value_type="percent",
        previous_value=previous_kpis["conversion_pct"] if previous_kpis else None,
    )

    metric_row_2 = st.columns(4)
    show_metric(
        metric_row_2[0],
        "Win rate",
        kpis["win_rate_pct"],
        value_type="percent",
        previous_value=previous_kpis["win_rate_pct"] if previous_kpis else None,
    )
    show_metric(
        metric_row_2[1],
        "Средний чек",
        kpis["avg_check"],
        value_type="money",
        previous_value=previous_kpis["avg_check"] if previous_kpis else None,
    )
    show_metric(
        metric_row_2[2],
        "Открытый пайплайн",
        kpis["open_pipeline"],
        value_type="money",
        previous_value=previous_kpis["open_pipeline"] if previous_kpis else None,
    )
    show_metric(
        metric_row_2[3],
        "Прогноз (факт + взвеш.)",
        kpis["forecast"],
        value_type="money",
        previous_value=previous_kpis["forecast"] if previous_kpis else None,
    )

    st.subheader("Управленческие инсайты")
    for level, message in generate_insights(kpis, manager_table, client_table):
        if level == "error":
            st.error(message)
        elif level == "warning":
            st.warning(message)
        elif level == "info":
            st.info(message)
        else:
            st.success(message)

    trend_col_1, trend_col_2 = st.columns(2)

    with trend_col_1:
        monthly = filtered_df.groupby("Месяц", as_index=False).agg(
            План=(PLAN_COL, "sum"),
            Факт=("Факт закрытия", "sum"),
            Взвешенный=("Взвешенный прогноз", "sum"),
        )
        monthly["Прогноз"] = monthly["Факт"] + monthly["Взвешенный"]
        monthly_long = monthly.melt(
            id_vars="Месяц",
            value_vars=["План", "Факт", "Прогноз"],
            var_name="Показатель",
            value_name="Сумма",
        )
        fig_monthly = px.line(
            monthly_long,
            x="Месяц",
            y="Сумма",
            color="Показатель",
            markers=True,
            title="План / факт / прогноз по месяцам",
        )
        st.plotly_chart(fig_monthly, use_container_width=True)

    with trend_col_2:
        daily_fact = filtered_df.groupby("День", as_index=False).agg(
            Факт=("Факт закрытия", "sum"),
            Сделки=("Потенциал сделки", "size"),
        )
        fig_daily = px.bar(
            daily_fact,
            x="День",
            y="Факт",
            title="Дневная динамика выручки",
            labels={"Факт": "Выручка, ₽", "День": "Дата"},
        )
        st.plotly_chart(fig_daily, use_container_width=True)

    st.subheader("Прогноз темпа выполнения в текущем периоде")
    today = date.today()
    if start_date <= today <= end_date:
        elapsed_days = (today - start_date).days + 1
        total_days = (end_date - start_date).days + 1
        days_left = max((end_date - today).days, 0)

        fact_to_date = filtered_df[filtered_df[DATE_COL].dt.date <= today]["Факт закрытия"].sum()
        run_rate_forecast = fact_to_date / elapsed_days * total_days if elapsed_days else 0
        plan_gap = max(kpis["plan"] - fact_to_date, 0)
        needed_daily = plan_gap / days_left if days_left > 0 else plan_gap

        pace_col_1, pace_col_2, pace_col_3 = st.columns(3)
        pace_col_1.metric("Факт на сегодня", format_money(fact_to_date))
        pace_col_2.metric("Прогноз по текущему темпу", format_money(run_rate_forecast))
        pace_col_3.metric("Нужный средний день до конца", format_money(needed_daily))
    elif today < start_date:
        st.info("Выбран будущий период. Прогноз темпа появится после начала периода.")
    else:
        st.info("Период уже завершён. Темп рассчитывается только в активном интервале.")

with tab_funnel:
    st.subheader("Воронка продаж")
    stage_table = filtered_df.groupby([STAGE_COL, "Вероятность этапа"], as_index=False).agg(
        Сделки=("Потенциал сделки", "size"),
        Потенциал=("Потенциал сделки", "sum"),
        Факт=("Факт закрытия", "sum"),
    )
    stage_table = stage_table.sort_values(
        by=["Вероятность этапа", "Сделки"],
        ascending=[True, False],
    )

    funnel_col_1, funnel_col_2 = st.columns(2)
    with funnel_col_1:
        fig_funnel_count = px.funnel(
            stage_table,
            y=STAGE_COL,
            x="Сделки",
            title="Количество сделок по стадиям",
        )
        st.plotly_chart(fig_funnel_count, use_container_width=True)

    with funnel_col_2:
        fig_funnel_amount = px.funnel(
            stage_table,
            y=STAGE_COL,
            x="Потенциал",
            title="Сумма потенциала по стадиям",
        )
        st.plotly_chart(fig_funnel_amount, use_container_width=True)

    stage_detail = stage_table.copy()
    stage_detail["Конверсия к предыдущей стадии, %"] = (
        stage_detail["Сделки"] / stage_detail["Сделки"].shift(1).replace(0, pd.NA) * 100
    ).fillna(100)
    stage_detail["Конверсия к предыдущей стадии, %"] = (
        stage_detail["Конверсия к предыдущей стадии, %"].round(1)
    )
    st.dataframe(
        stage_detail[[STAGE_COL, "Сделки", "Потенциал", "Факт", "Конверсия к предыдущей стадии, %"]],
        use_container_width=True,
        hide_index=True,
    )

with tab_managers:
    st.subheader("Эффективность менеджеров")

    if manager_table.empty:
        st.info("Недостаточно данных для анализа менеджеров.")
    else:
        chart_col_1, chart_col_2 = st.columns(2)

        with chart_col_1:
            manager_plan_fact = manager_table.melt(
                id_vars=MANAGER_COL,
                value_vars=["План", "Факт"],
                var_name="Показатель",
                value_name="Сумма",
            )
            fig_plan_fact = px.bar(
                manager_plan_fact,
                x=MANAGER_COL,
                y="Сумма",
                color="Показатель",
                barmode="group",
                title="План vs факт по менеджерам",
            )
            st.plotly_chart(fig_plan_fact, use_container_width=True)

        with chart_col_2:
            fig_performance = px.scatter(
                manager_table,
                x="Win rate, %",
                y="Выполнение плана, %",
                size="Открытый_пайплайн",
                color=MANAGER_COL,
                hover_data=["Лиды", "Выиграно", "Факт"],
                title="Карта эффективности менеджеров",
            )
            st.plotly_chart(fig_performance, use_container_width=True)

        manager_display = manager_table.rename(
            columns={
                "В_работе": "В работе",
                "Открытый_пайплайн": "Открытый пайплайн",
                "Взвешенный_прогноз": "Взвешенный прогноз",
            }
        )
        st.dataframe(manager_display, use_container_width=True, hide_index=True)

        selected_manager = st.selectbox(
            "Детализация по менеджеру",
            options=manager_table[MANAGER_COL].tolist(),
        )
        manager_filtered = filtered_df[filtered_df[MANAGER_COL] == selected_manager]
        manager_monthly = manager_filtered.groupby("Месяц", as_index=False).agg(
            Факт=("Факт закрытия", "sum"),
            Потенциал=("Открытый пайплайн", "sum"),
        )
        manager_monthly_long = manager_monthly.melt(
            id_vars="Месяц",
            value_vars=["Факт", "Потенциал"],
            var_name="Показатель",
            value_name="Сумма",
        )
        fig_manager_month = px.line(
            manager_monthly_long,
            x="Месяц",
            y="Сумма",
            color="Показатель",
            markers=True,
            title=f"Динамика менеджера: {selected_manager}",
        )
        st.plotly_chart(fig_manager_month, use_container_width=True)

with tab_clients:
    st.subheader("Клиентская и продуктовая аналитика")

    analytics_col_1, analytics_col_2 = st.columns(2)

    with analytics_col_1:
        st.markdown("**Топ клиентов по выручке**")
        if client_table.empty:
            st.info("Нет данных по клиентам.")
        else:
            top_clients = client_table.head(10).sort_values("Выручка", ascending=True)
            fig_clients = px.bar(
                top_clients,
                x="Выручка",
                y=CLIENT_COL,
                orientation="h",
                title="Топ-10 клиентов",
                labels={"Выручка": "Выручка, ₽"},
            )
            st.plotly_chart(fig_clients, use_container_width=True)
            st.dataframe(client_table.head(20), use_container_width=True, hide_index=True)

    with analytics_col_2:
        st.markdown("**Продукты: выручка и конверсия**")
        if product_table.empty:
            st.info("Нет данных по продуктам.")
        else:
            top_products = product_table.head(10).sort_values("Выручка", ascending=True)
            fig_products = px.bar(
                top_products,
                x="Выручка",
                y=PRODUCT_COL,
                orientation="h",
                title="Топ-10 продуктов",
                labels={"Выручка": "Выручка, ₽"},
            )
            st.plotly_chart(fig_products, use_container_width=True)
            st.dataframe(product_table, use_container_width=True, hide_index=True)

with tab_registry:
    st.subheader("Реестр сделок")

    search_query = st.text_input("Поиск в реестре (клиент, продукт, менеджер)", value="")
    sort_options = {
        "Дата сделки": DATE_COL,
        "Потенциал сделки": "Потенциал сделки",
        "Факт закрытия": "Факт закрытия",
    }
    sort_label = st.selectbox("Сортировка", options=list(sort_options.keys()))
    descending = st.toggle("По убыванию", value=True)

    registry_df = filtered_df.copy()
    if search_query.strip():
        mask = (
            registry_df[CLIENT_COL].str.contains(search_query, case=False, na=False) |
            registry_df[PRODUCT_COL].str.contains(search_query, case=False, na=False) |
            registry_df[MANAGER_COL].str.contains(search_query, case=False, na=False)
        )
        registry_df = registry_df[mask]

    registry_df = registry_df.sort_values(sort_options[sort_label], ascending=not descending)

    display_columns = [
        DATE_COL,
        MANAGER_COL,
        CLIENT_COL,
        PRODUCT_COL,
        STAGE_COL,
        "Статус",
        PLAN_COL,
        FACT_COL,
        "Потенциал сделки",
        "Открытый пайплайн",
        "Взвешенный прогноз",
    ]
    existing_columns = [column for column in display_columns if column in registry_df.columns]

    st.dataframe(
        registry_df[existing_columns],
        use_container_width=True,
        hide_index=True,
    )

    csv_data = registry_df[existing_columns].to_csv(index=False).encode("utf-8-sig")
    st.download_button(
        "Скачать текущую выборку в CSV",
        data=csv_data,
        file_name=f"sales_registry_{start_date}_{end_date}.csv",
        mime="text/csv",
    )
