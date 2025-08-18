# app.py
import streamlit as st
import pandas as pd
import plotly.express as px

# Настройка страницы
st.set_page_config(page_title="📊 Дашборд Продаж", layout="wide")
st.title("📊 Дашборд отдела продаж")

# Загрузка данных
@st.cache_data
def load_data():
    df = pd.read_excel("sales_data.xlsx")
    df['Дата сделки'] = pd.to_datetime(df['Дата сделки'])
    df['Сумма продажи факт'] = df['Сумма продажи факт'].fillna(0)
    df['Сумма продажи план'] = df['Сумма продажи план'].fillna(0)
    return df

df = load_data()

# --- Боковая панель: фильтры ---
st.sidebar.header("🔍 Фильтры")

# Фильтр по менеджерам
managers = st.sidebar.multiselect(
    "Менеджеры",
    options=df["Менеджер"].unique(),
    default=df["Менеджер"].unique()
)

# Фильтр по стадиям
stages = st.sidebar.multiselect(
    "Стадия сделки",
    options=df["Стадия сделки"].unique(),
    default=df["Стадия сделки"].unique()
)

# Фильтр по датам
min_date = df['Дата сделки'].min().date()
max_date = df['Дата сделки'].max().date()

start_date = st.sidebar.date_input("Начальная дата", min_date)
end_date = st.sidebar.date_input("Конечная дата", max_date)

# Применение фильтров
df_filtered = df[
    (df["Менеджер"].isin(managers)) &
    (df["Стадия сделки"].isin(stages)) &
    (df["Дата сделки"].dt.date >= start_date) &
    (df["Дата сделки"].dt.date <= end_date)
]

# --- Основные метрики ---
st.header("📌 Основные показатели")

# Только закрытые сделки
closed_deals = df_filtered[df_filtered["Стадия сделки"] == "Сделка"]

total_plan = int(df_filtered["Сумма продажи план"].sum())
total_fact = int(closed_deals["Сумма продажи факт"].sum())

avg_check = int(closed_deals["Сумма продажи факт"].mean()) if len(closed_deals) > 0 else 0

total_leads = len(df_filtered)
won_count = len(closed_deals)
conversion_rate = (won_count / total_leads * 100) if total_leads > 0 else 0

col1, col2, col3, col4 = st.columns(4)
col1.metric("План (сумма)", f"{total_plan:,} ₽")
col2.metric("Факт (сделки)", f"{total_fact:,} ₽")
col3.metric("Средний чек", f"{avg_check:,} ₽")
col4.metric("Конверсия", f"{conversion_rate:.1f}%")

# --- Графики ---
st.header("📈 Анализ продаж")

# 1. План vs Факт по менеджерам
fact_by_manager = closed_deals.groupby("Менеджер")["Сумма продажи факт"].sum().reset_index()
plan_by_manager = df_filtered.groupby("Менеджер")["Сумма продажи план"].sum().reset_index()
merged = plan_by_manager.merge(fact_by_manager, on="Менеджер", how="left").fillna(0)

fig1 = px.bar(
    merged,
    x="Менеджер",
    y=["Сумма продажи план", "Сумма продажи факт"],
    title="План vs Факт по менеджерам",
    labels={"value": "Сумма, ₽", "variable": "Тип"},
    barmode="group",
    color_discrete_map={"Сумма продажи план": "lightblue", "Сумма продажи факт": "green"}
)
st.plotly_chart(fig1, use_container_width=True)

# 2. Топ-5 клиентов по выручке
top_clients = closed_deals.groupby("ФИО Клиента")["Сумма продажи факт"].sum().nlargest(5).reset_index()
fig2 = px.pie(
    top_clients,
    values="Сумма продажи факт",
    names="ФИО Клиента",
    title="Топ-5 клиентов по выручке"
)
st.plotly_chart(fig2, use_container_width=True)

# 3. Топ-5 продуктов
top_products = closed_deals.groupby("Продукт")["Сумма продажи факт"].sum().nlargest(5).reset_index()
fig3 = px.bar(
    top_products,
    x="Продукт",
    y="Сумма продажи факт",
    title="Топ-5 продуктов",
    labels={"Сумма продажи факт": "Выручка, ₽"}
)
st.plotly_chart(fig3, use_container_width=True)

# 4. Динамика продаж по дням
daily_fact = closed_deals.groupby(pd.Grouper(key='Дата сделки', freq='D'))["Сумма продажи факт"].sum().reset_index()
fig4 = px.line(
    daily_fact,
    x="Дата сделки",
    y="Сумма продажи факт",
    title="Динамика выручки по дням",
    labels={"Сумма продажи факт": "Выручка, ₽"}
)
st.plotly_chart(fig4, use_container_width=True)

# --- Прогноз KPI ---
st.header("🔮 Прогноз выполнения KPI")

if len(df_filtered) > 0:
    days_passed = (pd.Timestamp(end_date) - pd.Timestamp(start_date)).days + 1
    if days_passed > 0:
        daily_avg = total_fact / days_passed
        predicted_monthly = daily_avg * 30  # упрощённый прогноз на 30 дней
        st.write(f"**Средний доход в день:** {int(daily_avg):,} ₽")
        st.write(f"**Прогноз на месяц:** {int(predicted_monthly):,} ₽")
        st.progress(min(predicted_monthly / total_plan, 1.0) if total_plan > 0 else 0)
else:
    st.write("Нет данных для прогноза.")

# --- Информация ---
st.sidebar.markdown("---")
st.sidebar.info("📊 Дашборд продаж | Разработан на Python + Streamlit")