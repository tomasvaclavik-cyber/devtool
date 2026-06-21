"""Streamlit dashboard pro vizualizaci spotových cen."""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import altair as alt
import pandas as pd
import streamlit as st
from streamlit_autorefresh import st_autorefresh

from ote.db import (
    get_available_dates,
    get_connection,
    get_daily_stats,
    get_data_days_count,
    get_prices_for_date,
)
from ote.spot import (
    SpotPrice,
    fetch_spot_prices,
    get_current_price,
    get_current_price_debug,
)

PRAGUE_TZ = ZoneInfo("Europe/Prague")

# Barevná škála podle cenové hladiny
PRICE_COLORS = {
    "velmi levná": "#22C55E",
    "levná": "#86EFAC",
    "normální": "#EAB308",
    "drahá": "#F97316",
    "velmi drahá": "#EF4444",
    "nedostatek dat": "#6B7280",
}

CSS = """
<style>
    /* Globální font a spacing */
    [data-testid="stAppViewContainer"] { font-family: 'Inter', sans-serif; }

    /* Nadpis stránky */
    h1 { font-size: 2rem !important; font-weight: 700 !important; letter-spacing: -0.5px; }
    h2 { font-size: 1.25rem !important; font-weight: 600 !important; color: #E5E7EB; }
    h3 { font-size: 1rem !important; font-weight: 600 !important; color: #9CA3AF; text-transform: uppercase; letter-spacing: 0.5px; }

    /* Metric karty */
    [data-testid="metric-container"] {
        background: #1F2937;
        border: 1px solid #374151;
        border-radius: 12px;
        padding: 16px 20px;
    }
    [data-testid="metric-container"] [data-testid="stMetricLabel"] {
        font-size: 0.75rem;
        text-transform: uppercase;
        letter-spacing: 0.5px;
        color: #9CA3AF;
    }
    [data-testid="metric-container"] [data-testid="stMetricValue"] {
        font-size: 1.6rem;
        font-weight: 700;
        color: #F9FAFB;
    }

    /* Divider */
    hr { border-color: #374151 !important; margin: 1.5rem 0 !important; }

    /* Sidebar */
    [data-testid="stSidebar"] { background: #111827; }
    [data-testid="stSidebar"] h2 { color: #D1D5DB; }

    /* Expander */
    [data-testid="stExpander"] { border: 1px solid #374151 !important; border-radius: 8px; }

    /* Tabs */
    [data-testid="stTabs"] [role="tab"] { font-weight: 500; }
</style>
"""


def price_color(price: float, p10: float, p30: float, p70: float, p90: float) -> str:
    if price <= p10:
        return "#22C55E"
    elif price <= p30:
        return "#86EFAC"
    elif price <= p70:
        return "#EAB308"
    elif price <= p90:
        return "#F97316"
    else:
        return "#EF4444"


def load_prices_as_df(prices: list[SpotPrice]) -> pd.DataFrame:
    return pd.DataFrame([
        {
            "Čas": p.time_from,
            "Hodina": p.time_from.strftime("%H:%M"),
            "Cena (CZK/MWh)": p.price_czk,
            "Cena (EUR/MWh)": p.price_eur,
        }
        for p in prices
    ])


def colored_bar_chart(df: pd.DataFrame, height: int = 400) -> alt.Chart:
    """Graf s barevnými sloupci podle cenové hladiny."""
    vals = df["Cena (CZK/MWh)"]
    p10, p30, p70, p90 = (
        vals.quantile(0.10), vals.quantile(0.30),
        vals.quantile(0.70), vals.quantile(0.90),
    )

    df = df.copy()
    df["Hladina"] = df["Cena (CZK/MWh)"].apply(lambda v: (
        "Velmi levná" if v <= p10 else
        "Levná" if v <= p30 else
        "Normální" if v <= p70 else
        "Drahá" if v <= p90 else
        "Velmi drahá"
    ))

    return (
        alt.Chart(df)
        .mark_bar()
        .encode(
            x=alt.X("Hodina:N", title="Čas", sort=None,
                    axis=alt.Axis(labelAngle=-45, labelFontSize=11)),
            y=alt.Y("Cena (CZK/MWh):Q", title="CZK/MWh",
                    axis=alt.Axis(format=",.0f")),
            color=alt.Color(
                "Hladina:N",
                scale=alt.Scale(
                    domain=["Velmi levná", "Levná", "Normální", "Drahá", "Velmi drahá"],
                    range=["#22C55E", "#86EFAC", "#EAB308", "#F97316", "#EF4444"],
                ),
                legend=alt.Legend(title="Cenová hladina", orient="bottom"),
            ),
            tooltip=[
                alt.Tooltip("Hodina:N", title="Čas"),
                alt.Tooltip("Cena (CZK/MWh):Q", title="CZK/MWh", format=",.0f"),
                alt.Tooltip("Cena (EUR/MWh):Q", title="EUR/MWh", format=",.2f"),
                alt.Tooltip("Hladina:N", title="Hladina"),
            ],
        )
        .properties(height=height)
        .interactive()
    )


def main() -> None:
    st.set_page_config(
        page_title="OTE Spotové ceny",
        page_icon="⚡",
        layout="wide",
    )
    st.markdown(CSS, unsafe_allow_html=True)

    st_autorefresh(interval=15 * 60 * 1000, key="price_refresh")

    now = datetime.now(PRAGUE_TZ)

    # Header
    col_title, col_time = st.columns([3, 1])
    with col_title:
        st.title("⚡ OTE Spotové ceny elektřiny")
    with col_time:
        st.markdown(
            f"<div style='text-align:right; padding-top:12px; color:#9CA3AF; font-size:0.85rem;'>"
            f"Aktualizováno<br><strong style='color:#E5E7EB'>{now.strftime('%H:%M:%S')}</strong>"
            f" (CET/CEST)</div>",
            unsafe_allow_html=True,
        )

    st.markdown("---")

    tab_prices, tab_analysis, tab_profiles, tab_forecast, tab_weather = st.tabs([
        "⚡ Aktuální ceny",
        "📊 Analýza",
        "👤 Profily & Riziko",
        "🔮 Predikce",
        "🌤️ Počasí",
    ])

    with tab_prices:
        show_prices_tab()
    with tab_analysis:
        show_analysis_tab()
    with tab_profiles:
        show_profiles_tab()
    with tab_forecast:
        show_forecast_tab()
    with tab_weather:
        show_weather_tab()


# ─── TAB: Ceny ───────────────────────────────────────────────────────────────

def show_prices_tab() -> None:
    st.sidebar.header("Nastavení")
    data_source = st.sidebar.radio(
        "Zdroj dat",
        ["Živá data (API)", "Databáze (historie)"],
        key="prices_source",
    )

    if data_source == "Živá data (API)":
        show_live_data()
    else:
        show_historical_data()


def show_live_data() -> None:
    selected_date = st.sidebar.date_input(
        "Datum",
        value=date.today(),
        max_value=date.today() + timedelta(days=1),
        key="live_date",
    )

    with st.spinner("Načítám data z OTE..."):
        try:
            prices, eur_czk_rate = fetch_spot_prices(selected_date)
        except Exception as e:
            st.error(f"Chyba při načítání dat: {e}")
            return

    if not prices:
        st.warning("Žádná data nejsou k dispozici.")
        return

    df = load_prices_as_df(prices)
    current, _ = get_current_price_debug(prices)

    # KPI řada
    col1, col2, col3, col4, col5 = st.columns(5)
    with col1:
        if current:
            st.metric("Aktuální cena", f"{current.price_czk:,.0f} CZK/MWh",
                      help=f"{current.time_from:%H:%M}–{current.time_to:%H:%M}")
        else:
            st.metric("Aktuální cena", "—")
    with col2:
        st.metric("Minimum dne", f"{df['Cena (CZK/MWh)'].min():,.0f} CZK/MWh")
    with col3:
        st.metric("Maximum dne", f"{df['Cena (CZK/MWh)'].max():,.0f} CZK/MWh")
    with col4:
        st.metric("Průměr dne", f"{df['Cena (CZK/MWh)'].mean():,.0f} CZK/MWh")
    with col5:
        spread = df["Cena (CZK/MWh)"].max() - df["Cena (CZK/MWh)"].min()
        st.metric("Rozpětí", f"{spread:,.0f} CZK/MWh",
                  help="Max − Min za den")

    st.caption(f"Kurz ČNB: 1 EUR = {eur_czk_rate:.3f} CZK")

    st.subheader(f"Průběh cen — {selected_date}")
    st.altair_chart(colored_bar_chart(df), use_container_width=True)

    with st.expander("Tabulka dat"):
        st.dataframe(
            df[["Hodina", "Cena (CZK/MWh)", "Cena (EUR/MWh)"]],
            use_container_width=True, hide_index=True,
        )


def show_historical_data() -> None:
    conn = get_connection()
    dates = get_available_dates(conn)

    if not dates:
        st.warning("Databáze je prázdná.")
        conn.close()
        return

    selected_date = st.sidebar.selectbox(
        "Datum",
        options=dates,
        format_func=lambda d: d.strftime("%d.%m.%Y"),
        key="history_date",
    )

    prices = get_prices_for_date(conn, selected_date)
    stats = get_daily_stats(conn, selected_date)

    if not prices or not stats:
        st.warning("Žádná data pro vybrané datum.")
        conn.close()
        return

    df = load_prices_as_df(prices)

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("Minimum", f"{stats['min']:,.0f} CZK/MWh")
    with col2:
        st.metric("Maximum", f"{stats['max']:,.0f} CZK/MWh")
    with col3:
        st.metric("Průměr", f"{stats['avg']:,.0f} CZK/MWh")
    with col4:
        spread = stats["max"] - stats["min"]
        st.metric("Rozpětí", f"{spread:,.0f} CZK/MWh")

    st.caption(f"Kurz ČNB: 1 EUR = {stats['eur_czk_rate']:.3f} CZK")

    st.subheader(f"Průběh cen — {selected_date.strftime('%d.%m.%Y')}")
    st.altair_chart(colored_bar_chart(df), use_container_width=True)

    # Porovnání posledních 30 dnů
    if len(dates) > 1:
        st.subheader("Vývoj průměrných cen — posledních 30 dní")

        all_data = []
        for d in dates[:30]:
            day_stats = get_daily_stats(conn, d)
            if day_stats:
                all_data.append({
                    "Datum": d,
                    "Min": day_stats["min"],
                    "Max": day_stats["max"],
                    "Průměr": day_stats["avg"],
                })

        if all_data:
            compare_df = pd.DataFrame(all_data)

            band = (
                alt.Chart(compare_df)
                .mark_area(opacity=0.15, color="#3B82F6")
                .encode(
                    x=alt.X("Datum:T", title="Datum"),
                    y=alt.Y("Min:Q", title="CZK/MWh", axis=alt.Axis(format=",.0f")),
                    y2=alt.Y2("Max:Q"),
                )
            )
            line = (
                alt.Chart(compare_df)
                .mark_line(color="#3B82F6", strokeWidth=2.5)
                .encode(
                    x=alt.X("Datum:T"),
                    y=alt.Y("Průměr:Q"),
                    tooltip=[
                        alt.Tooltip("Datum:T", title="Den", format="%d.%m.%Y"),
                        alt.Tooltip("Průměr:Q", title="Průměr", format=",.0f"),
                        alt.Tooltip("Min:Q", title="Min", format=",.0f"),
                        alt.Tooltip("Max:Q", title="Max", format=",.0f"),
                    ],
                )
            )
            points = line.mark_point(filled=True, size=40, color="#3B82F6")

            st.altair_chart(
                (band + line + points).properties(height=280).interactive(),
                use_container_width=True,
            )

    conn.close()


# ─── TAB: Analýza ────────────────────────────────────────────────────────────

def show_analysis_tab() -> None:
    conn = get_connection()
    days_count = get_data_days_count(conn)

    if days_count == 0:
        st.warning("Databáze je prázdná.")
        conn.close()
        return

    if days_count < 7:
        st.warning(f"Pro analýzu je potřeba alespoň 7 dnů dat. Aktuálně {days_count} dnů.")
        conn.close()
        return

    from ote.analysis import (
        classify_price,
        get_best_hours,
        get_hourly_patterns,
        get_moving_averages,
        get_negative_price_forecast,
        get_negative_price_hours_list,
        get_negative_price_stats,
        get_price_distribution,
        get_price_level_color,
        get_price_trend,
        get_weekday_hour_heatmap_data,
        get_worst_hours,
    )

    # ── Aktuální cenová hladina ──
    st.subheader("Aktuální cenová hladina")
    try:
        prices, _ = fetch_spot_prices(date.today())
        current = get_current_price(prices)
        if current:
            classification = classify_price(current.price_czk, conn)
            color = get_price_level_color(classification)
            col1, col2 = st.columns([1, 2])
            with col1:
                st.metric("Aktuální cena", f"{current.price_czk:,.0f} CZK/MWh")
            with col2:
                st.markdown(
                    f"<div style='margin-top:8px; padding:14px 20px; background:{color}20; "
                    f"border:1px solid {color}; border-radius:10px; text-align:center; "
                    f"color:{color}; font-weight:700; font-size:1.1rem; letter-spacing:1px;'>"
                    f"{classification.upper()}</div>",
                    unsafe_allow_html=True,
                )
        else:
            st.info("Aktuální cena není k dispozici.")
    except Exception:
        st.info("Nelze načíst aktuální cenu z API.")

    st.markdown("---")

    # ── Průměrné ceny podle hodiny ──
    st.subheader("Průměrné ceny podle hodiny (posledních 30 dní)")
    patterns = get_hourly_patterns(conn, days_back=30)

    if patterns:
        pattern_df = pd.DataFrame([
            {"Hodina": p.hour, "Průměr": p.avg_price, "Min": p.min_price, "Max": p.max_price}
            for p in patterns
        ])

        band = (
            alt.Chart(pattern_df)
            .mark_area(opacity=0.12, color="#3B82F6")
            .encode(
                x=alt.X("Hodina:O", title="Hodina"),
                y=alt.Y("Min:Q", title="CZK/MWh", axis=alt.Axis(format=",.0f")),
                y2=alt.Y2("Max:Q"),
            )
        )
        bars = (
            alt.Chart(pattern_df)
            .mark_bar(cornerRadiusTopLeft=3, cornerRadiusTopRight=3, color="#3B82F6", opacity=0.85)
            .encode(
                x=alt.X("Hodina:O"),
                y=alt.Y("Průměr:Q"),
                tooltip=[
                    alt.Tooltip("Hodina:O", title="Hodina"),
                    alt.Tooltip("Průměr:Q", title="Průměr", format=",.0f"),
                    alt.Tooltip("Min:Q", title="Min", format=",.0f"),
                    alt.Tooltip("Max:Q", title="Max", format=",.0f"),
                ],
            )
        )
        st.altair_chart((band + bars).properties(height=280).interactive(), use_container_width=True)

    # Nejlevnější / nejdražší hodiny
    col1, col2 = st.columns(2)
    with col1:
        st.markdown("### 🟢 Nejlevnější hodiny")
        best = get_best_hours(conn, top_n=5)
        for i, (hour, price) in enumerate(best):
            medal = ["🥇", "🥈", "🥉", "4.", "5."][i]
            st.markdown(
                f"<div style='display:flex;justify-content:space-between;padding:8px 12px;"
                f"background:#1F2937;border-radius:8px;margin-bottom:6px;'>"
                f"<span>{medal} <strong>{hour:02d}:00</strong></span>"
                f"<span style='color:#22C55E;font-weight:600'>{price:,.0f} CZK</span>"
                f"</div>",
                unsafe_allow_html=True,
            )
    with col2:
        st.markdown("### 🔴 Nejdražší hodiny")
        worst = get_worst_hours(conn, top_n=5)
        for i, (hour, price) in enumerate(worst):
            medal = ["🥇", "🥈", "🥉", "4.", "5."][i]
            st.markdown(
                f"<div style='display:flex;justify-content:space-between;padding:8px 12px;"
                f"background:#1F2937;border-radius:8px;margin-bottom:6px;'>"
                f"<span>{medal} <strong>{hour:02d}:00</strong></span>"
                f"<span style='color:#EF4444;font-weight:600'>{price:,.0f} CZK</span>"
                f"</div>",
                unsafe_allow_html=True,
            )

    st.markdown("---")

    # ── Týdenní heatmapa ──
    if days_count >= 14:
        st.subheader("Heatmapa: hodina × den v týdnu")
        heatmap_data = get_weekday_hour_heatmap_data(conn, days_back=60)
        if heatmap_data:
            heatmap_df = pd.DataFrame(heatmap_data)
            heatmap = (
                alt.Chart(heatmap_df)
                .mark_rect(cornerRadius=2)
                .encode(
                    x=alt.X("hour:O", title="Hodina",
                            axis=alt.Axis(labelFontSize=11)),
                    y=alt.Y("weekday_name:O", title=None,
                            sort=["Po", "Út", "St", "Čt", "Pá", "So", "Ne"],
                            axis=alt.Axis(labelFontSize=12, labelFontWeight="bold")),
                    color=alt.Color(
                        "avg_price:Q", title="CZK/MWh",
                        scale=alt.Scale(scheme="redyellowgreen", reverse=True),
                        legend=alt.Legend(gradientLength=200, orient="right"),
                    ),
                    tooltip=[
                        alt.Tooltip("weekday_name:O", title="Den"),
                        alt.Tooltip("hour:O", title="Hodina"),
                        alt.Tooltip("avg_price:Q", title="Průměr CZK/MWh", format=",.0f"),
                    ],
                )
                .properties(height=220)
            )
            st.altair_chart(heatmap, use_container_width=True)

    st.markdown("---")

    # ── Negativní ceny ──
    st.subheader("Negativní ceny")
    neg_stats_30 = get_negative_price_stats(conn, days_back=30)
    neg_stats_7 = get_negative_price_stats(conn, days_back=7)

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Negativní hodiny (30 dní)", neg_stats_30.count)
    with col2:
        st.metric("Negativní hodiny (7 dní)", neg_stats_7.count)
    with col3:
        if neg_stats_30.min_price is not None:
            st.metric("Nejnižší cena", f"{neg_stats_30.min_price:,.0f} CZK/MWh")
        else:
            st.metric("Nejnižší cena", "—")

    risky_hours = get_negative_price_forecast(conn)
    if risky_hours:
        hours_str = ", ".join(f"{h}:00" for h in risky_hours)
        st.warning(f"⚠️ Riziko negativních cen zítra kolem: {hours_str}")

    hours_dist = neg_stats_30.hours_distribution
    if hours_dist:
        dist_df = pd.DataFrame([
            {"Hodina": h, "Počet": c}
            for h, c in sorted(hours_dist.items())
        ])
        dist_chart = (
            alt.Chart(dist_df)
            .mark_bar(color="#EF4444", cornerRadiusTopLeft=3, cornerRadiusTopRight=3)
            .encode(
                x=alt.X("Hodina:O", title="Hodina"),
                y=alt.Y("Počet:Q", title="Výskytů"),
                tooltip=["Hodina", "Počet"],
            )
            .properties(height=180, title="Typické hodiny s negativními cenami")
        )
        st.altair_chart(dist_chart, use_container_width=True)

    neg_hours = get_negative_price_hours_list(conn, days_back=30)
    if neg_hours:
        with st.expander("Historie negativních cen (30 dní)"):
            neg_df = pd.DataFrame([
                {"Datum": h.date.strftime("%d.%m.%Y"), "Hodina": f"{h.hour:02d}:00",
                 "Cena (CZK/MWh)": f"{h.price_czk:,.0f}"}
                for h in neg_hours
            ])
            st.dataframe(neg_df, use_container_width=True, hide_index=True)

    st.markdown("---")

    # ── Cenové trendy ──
    st.subheader("Cenové trendy")

    distribution = get_price_distribution(conn, days_back=30)
    trend = get_price_trend(conn, days_back=30)

    col1, col2, col3 = st.columns(3)
    with col1:
        median = distribution.percentiles.get("p50")
        st.metric("Medián (30 dní)", f"{median:,.0f} CZK/MWh" if median else "—")
    with col2:
        change = trend.change_percent
        st.metric("Trend", trend.direction,
                  delta=f"{change:+.1f}%" if change is not None else None,
                  delta_color="inverse")
    with col3:
        p90 = distribution.percentiles.get("p90")
        st.metric("90. percentil", f"{p90:,.0f} CZK/MWh" if p90 else "—")

    # Histogram
    if distribution.bins and distribution.counts:
        hist_df = pd.DataFrame({"Pásmo": distribution.bins, "Počet": distribution.counts})
        hist_chart = (
            alt.Chart(hist_df)
            .mark_bar(color="#6366F1", cornerRadiusTopLeft=2, cornerRadiusTopRight=2)
            .encode(
                x=alt.X("Pásmo:N", title="Cena (CZK/MWh)", sort=None,
                        axis=alt.Axis(labelAngle=-45, labelFontSize=10)),
                y=alt.Y("Počet:Q", title="Počet 15min intervalů"),
                tooltip=["Pásmo", "Počet"],
            )
            .properties(height=220, title="Distribuce cen — histogram (30 dní)")
        )
        st.altair_chart(hist_chart, use_container_width=True)

    # Klouzavé průměry
    if days_count >= 14:
        ma_data = get_moving_averages(conn, days_back=60)
        if ma_data:
            ma_df = pd.DataFrame([
                {"Datum": d.date, "Denní průměr": d.daily_avg, "7denní MA": d.ma7, "30denní MA": d.ma30}
                for d in ma_data
            ])
            ma_long = ma_df.melt(
                id_vars=["Datum"],
                value_vars=["Denní průměr", "7denní MA", "30denní MA"],
                var_name="Typ", value_name="Cena",
            ).dropna(subset=["Cena"])

            trend_chart = (
                alt.Chart(ma_long)
                .mark_line()
                .encode(
                    x=alt.X("Datum:T", title="Datum"),
                    y=alt.Y("Cena:Q", title="CZK/MWh", axis=alt.Axis(format=",.0f")),
                    color=alt.Color("Typ:N", scale=alt.Scale(
                        domain=["Denní průměr", "7denní MA", "30denní MA"],
                        range=["#374151", "#3B82F6", "#F97316"],
                    ), legend=alt.Legend(orient="bottom")),
                    strokeWidth=alt.condition(
                        alt.datum.Typ == "Denní průměr", alt.value(1), alt.value(2.5)
                    ),
                    opacity=alt.condition(
                        alt.datum.Typ == "Denní průměr", alt.value(0.6), alt.value(1)
                    ),
                    tooltip=["Datum:T", "Typ:N", alt.Tooltip("Cena:Q", format=",.0f")],
                )
                .properties(height=280, title="Vývoj cen s klouzavými průměry")
                .interactive()
            )
            st.altair_chart(trend_chart, use_container_width=True)

    conn.close()


# ─── TAB: Profily & Riziko ───────────────────────────────────────────────────

def show_profiles_tab() -> None:
    conn = get_connection()
    days_count = get_data_days_count(conn)

    if days_count < 7:
        st.warning(f"Pro analýzu profilů je potřeba alespoň 7 dnů. Aktuálně {days_count}.")
        conn.close()
        return

    from ote.analysis import (
        get_all_profiles_comparison,
        get_current_benchmark,
        get_peak_analysis,
        get_peak_probability_by_hour,
        get_volatility_metrics,
        predict_peaks_tomorrow,
    )

    # ── Benchmark ──
    st.subheader("Aktuální cenový benchmark")
    try:
        prices, _ = fetch_spot_prices(date.today())
        current = get_current_price(prices)
        if current:
            bm = get_current_benchmark(conn, current.price_czk)
            color = PRICE_COLORS.get(bm.classification, "#6B7280")

            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.metric("Aktuální cena", f"{bm.current_price:,.0f} CZK/MWh")
            with col2:
                st.metric("Průměr 7 dní", f"{bm.avg_7d:,.0f} CZK/MWh")
            with col3:
                st.metric("Průměr 30 dní", f"{bm.avg_30d:,.0f} CZK/MWh")
            with col4:
                st.metric("Percentil", f"{bm.percentile_rank}.")

            st.markdown(
                f"<div style='padding:12px 20px; background:{color}20; border:1px solid {color}; "
                f"border-radius:10px; text-align:center; color:{color}; font-weight:700; "
                f"font-size:1.1rem; margin-top:8px;'>{bm.classification.upper()}</div>",
                unsafe_allow_html=True,
            )

            if bm.vs_yesterday_pct is not None or bm.vs_last_week_pct is not None:
                c1, c2 = st.columns(2)
                with c1:
                    if bm.vs_yesterday_pct is not None:
                        st.metric("Vs. včera", "", delta=f"{bm.vs_yesterday_pct:+.1f}%",
                                  delta_color="inverse")
                with c2:
                    if bm.vs_last_week_pct is not None:
                        st.metric("Vs. minulý týden", "", delta=f"{bm.vs_last_week_pct:+.1f}%",
                                  delta_color="inverse")
        else:
            st.info("Aktuální cena není k dispozici.")
    except Exception:
        st.info("Nelze načíst aktuální cenu z API.")

    st.markdown("---")

    # ── Spotřebitelské profily ──
    st.subheader("Spotřebitelské profily")
    profiles = get_all_profiles_comparison(conn)

    if profiles:
        profile_df = pd.DataFrame([{
            "Profil": p.name,
            "Popis": p.description,
            "Cena (CZK/MWh)": round(p.avg_price_czk),
            "Úspora (%)": round(p.savings_vs_flat_pct, 1),
            "Nejlevnější den": p.best_day,
        } for p in profiles])

        chart = (
            alt.Chart(profile_df)
            .mark_bar(cornerRadiusTopLeft=4, cornerRadiusTopRight=4)
            .encode(
                x=alt.X("Profil:N", sort=None, axis=alt.Axis(labelFontSize=12)),
                y=alt.Y("Cena (CZK/MWh):Q", title="Průměrná cena (CZK/MWh)",
                        axis=alt.Axis(format=",.0f")),
                color=alt.condition(
                    alt.datum["Úspora (%)"] > 0,
                    alt.value("#22C55E"),
                    alt.value("#EF4444"),
                ),
                tooltip=["Profil", "Popis", "Cena (CZK/MWh)", "Úspora (%)", "Nejlevnější den"],
            )
            .properties(height=280, title="Průměrná cena spotřeby podle profilu")
        )
        st.altair_chart(chart, use_container_width=True)

        best = profiles[0]
        st.success(
            f"**Doporučený profil:** {best.name} — "
            f"úspora {best.savings_vs_flat_pct:+.1f}% oproti flat tarifu"
        )
        st.dataframe(profile_df, use_container_width=True, hide_index=True)

    st.markdown("---")

    # ── Volatilita ──
    st.subheader("Volatilita a riziko")
    metrics = get_volatility_metrics(conn)

    if metrics.volatility_trend != "nedostatek dat":
        c1, c2, c3, c4, c5 = st.columns(5)
        with c1:
            st.metric("Denní volatilita", f"{metrics.daily_volatility:,.0f} CZK",
                      help="Směrodatná odchylka denních průměrů")
        with c2:
            st.metric("Intraday volatilita", f"{metrics.intraday_volatility:,.0f} CZK")
        with c3:
            st.metric("Prům. denní rozpětí", f"{metrics.avg_daily_swing:,.0f} CZK")
        with c4:
            st.metric("Max denní rozpětí", f"{metrics.max_daily_swing:,.0f} CZK")
        with c5:
            icons = {"rostoucí": "📈", "klesající": "📉", "stabilní": "➡️"}
            st.metric("Trend volatility",
                      f"{icons.get(metrics.volatility_trend, '')} {metrics.volatility_trend}")

        c1, c2 = st.columns(2)
        with c1:
            st.metric("VaR 95%", f"{metrics.var_95:,.0f} CZK/MWh",
                      help="95 % cen je pod touto hodnotou")
        with c2:
            st.metric("VaR 99%", f"{metrics.var_99:,.0f} CZK/MWh")

    st.markdown("---")

    # ── Cenové špičky ──
    st.subheader("Cenové špičky")
    peak_analysis = get_peak_analysis(conn)

    if peak_analysis.total_peaks_30d > 0:
        c1, c2, c3 = st.columns(3)
        with c1:
            st.metric("Hranice špičky (P90)", f"{peak_analysis.threshold_p90:,.0f} CZK/MWh")
        with c2:
            st.metric("Špičky za 30 dní", peak_analysis.total_peaks_30d)
        with c3:
            risky_str = ", ".join(f"{h}:00" for h in peak_analysis.most_risky_hours[:3])
            st.metric("Nejrizikovější hodiny", risky_str)

        probs = get_peak_probability_by_hour(conn)
        prob_df = pd.DataFrame([
            {"Hodina": h, "Pravděpodobnost (%)": p * 100}
            for h, p in probs.items()
        ])

        prob_chart = (
            alt.Chart(prob_df)
            .mark_bar(cornerRadiusTopLeft=3, cornerRadiusTopRight=3)
            .encode(
                x=alt.X("Hodina:O", title="Hodina"),
                y=alt.Y("Pravděpodobnost (%):Q", title="Pravděpodobnost (%)"),
                color=alt.Color("Pravděpodobnost (%):Q",
                                scale=alt.Scale(scheme="redyellowgreen", reverse=True),
                                legend=None),
                tooltip=["Hodina", alt.Tooltip("Pravděpodobnost (%):Q", format=".1f")],
            )
            .properties(height=220, title="Pravděpodobnost cenové špičky podle hodiny")
        )
        st.altair_chart(prob_chart, use_container_width=True)

        st.subheader("Predikce špiček pro zítřek")
        predictions = predict_peaks_tomorrow(conn)
        risky = [p for p in predictions if p.probability >= 0.2]

        if risky:
            pred_df = pd.DataFrame([{
                "Hodina": f"{p.hour:02d}:00",
                "Pravděpodobnost (%)": round(p.probability * 100, 1),
                "Očekávaná cena": f"{p.expected_price:,.0f} CZK/MWh",
                "Riziko": p.risk_level,
            } for p in sorted(risky, key=lambda x: x.probability, reverse=True)])
            st.dataframe(pred_df, use_container_width=True, hide_index=True)
        else:
            st.success("Zítra se neočekávají výrazné cenové špičky.")
    else:
        st.info("Žádné cenové špičky za posledních 30 dní.")

    conn.close()


# ─── TAB: Predikce ──────────────────────────────────────────────────────────

def show_forecast_tab() -> None:
    conn = get_connection()

    from ote.forecast import (
        get_data_sufficiency,
        get_forecast_for_days,
        get_tomorrow_prices,
    )

    sufficiency = get_data_sufficiency(conn)

    st.sidebar.header("Stav dat")
    st.sidebar.metric("Dnů v historii", sufficiency.total_days)
    for label, ok in [
        ("Zítřejší ceny (D+1)", sufficiency.can_show_tomorrow),
        ("Hodinové vzorce", sufficiency.can_show_hourly_patterns),
        ("Statistická predikce", sufficiency.can_show_statistical_forecast),
    ]:
        icon = "✅" if ok else "❌"
        st.sidebar.markdown(f"{icon} {label}")

    # ── Zítřejší ceny ──
    st.subheader("Zítřejší ceny (D+1)")
    st.caption("Day-ahead ceny publikované OTE — obvykle kolem 13:00 CET")

    with st.spinner("Načítám zítřejší ceny..."):
        tomorrow_prices, eur_czk_rate, available = get_tomorrow_prices()

    if available and tomorrow_prices:
        tomorrow = date.today() + timedelta(days=1)
        df = load_prices_as_df(tomorrow_prices)

        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Minimum", f"{df['Cena (CZK/MWh)'].min():,.0f} CZK/MWh")
        with col2:
            st.metric("Maximum", f"{df['Cena (CZK/MWh)'].max():,.0f} CZK/MWh")
        with col3:
            st.metric("Průměr", f"{df['Cena (CZK/MWh)'].mean():,.0f} CZK/MWh")
        with col4:
            st.metric("Kurz EUR/CZK", f"{eur_czk_rate:.2f}")

        st.altair_chart(colored_bar_chart(df, height=320), use_container_width=True)

        with st.expander("Tabulka"):
            st.dataframe(df[["Hodina", "Cena (CZK/MWh)", "Cena (EUR/MWh)"]],
                         use_container_width=True, hide_index=True)
    else:
        st.info("Zítřejší ceny zatím nejsou publikovány (OTE zveřejňuje kolem 13:00 CET).")

    st.markdown("---")

    # ── Prognóza D+2 až D+7 ──
    st.subheader("Statistická prognóza D+2 až D+7")

    if not sufficiency.can_show_hourly_patterns:
        st.warning(f"Pro prognózu je potřeba alespoň 7 dnů dat. Aktuálně {sufficiency.total_days}.")
        conn.close()
        return

    method = "Statistická predikce" if sufficiency.can_show_statistical_forecast else "Hodinové vzorce"
    st.caption(f"Metoda: {method}")

    forecasts = get_forecast_for_days(conn, days_ahead=7)
    if not forecasts:
        st.info("Nedostatek dat pro prognózu.")
        conn.close()
        return

    # Souhrnný přehled všech dní
    summary_data = []
    for target_date, day_forecasts in forecasts.items():
        day_prices = [f.price_czk for f in day_forecasts]
        summary_data.append({
            "Datum": target_date,
            "Den": target_date.strftime("%a %d.%m"),
            "Min": min(day_prices),
            "Max": max(day_prices),
            "Průměr": sum(day_prices) / len(day_prices),
        })

    summary_df = pd.DataFrame(summary_data)

    band = (
        alt.Chart(summary_df)
        .mark_area(opacity=0.15, color="#8B5CF6")
        .encode(
            x=alt.X("Datum:T"),
            y=alt.Y("Min:Q", title="CZK/MWh", axis=alt.Axis(format=",.0f")),
            y2=alt.Y2("Max:Q"),
        )
    )
    line = (
        alt.Chart(summary_df)
        .mark_line(color="#8B5CF6", strokeWidth=2.5, point=True)
        .encode(
            x=alt.X("Datum:T", title="Datum"),
            y=alt.Y("Průměr:Q"),
            tooltip=[
                alt.Tooltip("Den:N", title="Den"),
                alt.Tooltip("Průměr:Q", title="Průměr", format=",.0f"),
                alt.Tooltip("Min:Q", title="Min", format=",.0f"),
                alt.Tooltip("Max:Q", title="Max", format=",.0f"),
            ],
        )
    )
    st.altair_chart(
        (band + line).properties(height=260, title="Prognóza průměrné ceny D+2 až D+7").interactive(),
        use_container_width=True,
    )

    # Detail po dnech
    for target_date, day_forecasts in forecasts.items():
        with st.expander(target_date.strftime("%A %d.%m.%Y"), expanded=False):
            forecast_df = pd.DataFrame([{
                "Hodina": f.time_from.strftime("%H:%M"),
                "Predikce (CZK/MWh)": f.price_czk,
                "Min": f.confidence_low,
                "Max": f.confidence_high,
            } for f in day_forecasts])

            c1, c2, c3 = st.columns(3)
            pred_col = "Predikce (CZK/MWh)"
            with c1:
                st.metric("Min", f"{forecast_df[pred_col].min():,.0f} CZK/MWh")
            with c2:
                st.metric("Max", f"{forecast_df[pred_col].max():,.0f} CZK/MWh")
            with c3:
                st.metric("Průměr", f"{forecast_df[pred_col].mean():,.0f} CZK/MWh")

            fc_chart = (
                alt.Chart(forecast_df)
                .mark_bar(color="#8B5CF6", cornerRadiusTopLeft=3, cornerRadiusTopRight=3)
                .encode(
                    x=alt.X("Hodina:N", sort=None, axis=alt.Axis(labelAngle=-45)),
                    y=alt.Y("Predikce (CZK/MWh):Q", title="CZK/MWh",
                            axis=alt.Axis(format=",.0f")),
                    tooltip=["Hodina", alt.Tooltip("Predikce (CZK/MWh):Q", format=",.0f"),
                             alt.Tooltip("Min:Q", format=",.0f"),
                             alt.Tooltip("Max:Q", format=",.0f")],
                )
                .properties(height=220)
                .interactive()
            )
            st.altair_chart(fc_chart, use_container_width=True)

    conn.close()


# ─── TAB: Počasí ─────────────────────────────────────────────────────────────

def show_weather_tab() -> None:
    try:
        from ote.weather import fetch_weather_forecast, get_weather_price_correlation
    except ImportError:
        st.error("Modul počasí není dostupný.")
        return

    st.subheader("Předpověď počasí — Praha (7 dní)")

    try:
        with st.spinner("Načítám předpověď počasí..."):
            weather_forecasts = fetch_weather_forecast(days_ahead=7)

        if weather_forecasts:
            weather_df = pd.DataFrame([{
                "Datum": f.date,
                "Den": f.date.strftime("%a %d.%m"),
                "Typ": f.weather_type,
                "Teplota (°C)": f.avg_temperature,
                "Oblačnost (%)": f.avg_cloud_cover,
                "Vítr (m/s)": f.avg_wind_speed,
                "Vliv na ceny": {"sunny": "↓ nižší", "windy": "↓ nižší",
                                  "cloudy": "↑ vyšší", "mixed": "~ běžné"}.get(f.weather_type, "?"),
            } for f in weather_forecasts])

            # Ikony počasí jako karty
            cols = st.columns(len(weather_forecasts))
            type_icon = {"sunny": "☀️", "cloudy": "☁️", "windy": "💨", "mixed": "🌤️"}
            impact_color = {"sunny": "#22C55E", "windy": "#22C55E", "cloudy": "#EF4444", "mixed": "#EAB308"}
            for i, (col, f) in enumerate(zip(cols, weather_forecasts)):
                with col:
                    color = impact_color.get(f.weather_type, "#6B7280")
                    st.markdown(
                        f"<div style='background:#1F2937;border:1px solid #374151;border-radius:10px;"
                        f"padding:12px 8px;text-align:center;'>"
                        f"<div style='font-size:0.75rem;color:#9CA3AF;'>{f.date.strftime('%a %d.%m')}</div>"
                        f"<div style='font-size:1.8rem;margin:4px 0'>{type_icon.get(f.weather_type,'?')}</div>"
                        f"<div style='font-weight:700;font-size:1rem'>{f.avg_temperature:.0f}°C</div>"
                        f"<div style='font-size:0.75rem;color:{color};margin-top:4px'>"
                        f"{impact_color.get(f.weather_type,'')}"
                        f"{'↓ levnější' if f.weather_type in ('sunny','windy') else '↑ dražší' if f.weather_type == 'cloudy' else '~ běžné'}"
                        f"</div></div>",
                        unsafe_allow_html=True,
                    )

            st.markdown("")

            col1, col2 = st.columns(2)
            with col1:
                temp_chart = (
                    alt.Chart(weather_df)
                    .mark_area(color="#F97316", opacity=0.15, line={"color": "#F97316", "strokeWidth": 2})
                    .encode(
                        x=alt.X("Datum:T", title="Datum"),
                        y=alt.Y("Teplota (°C):Q", title="Teplota (°C)"),
                        tooltip=[alt.Tooltip("Den:N"), alt.Tooltip("Teplota (°C):Q", format=".1f")],
                    )
                    .properties(height=200, title="Teplota")
                )
                st.altair_chart(temp_chart, use_container_width=True)

            with col2:
                cloud_chart = (
                    alt.Chart(weather_df)
                    .mark_bar(color="#3B82F6", cornerRadiusTopLeft=3, cornerRadiusTopRight=3)
                    .encode(
                        x=alt.X("Datum:T", title="Datum"),
                        y=alt.Y("Oblačnost (%):Q", title="Oblačnost (%)"),
                        tooltip=[alt.Tooltip("Den:N"), alt.Tooltip("Oblačnost (%):Q", format=".0f")],
                    )
                    .properties(height=200, title="Oblačnost")
                )
                st.altair_chart(cloud_chart, use_container_width=True)

            wind_chart = (
                alt.Chart(weather_df)
                .mark_line(color="#22C55E", strokeWidth=2, point={"filled": True, "size": 50})
                .encode(
                    x=alt.X("Datum:T", title="Datum"),
                    y=alt.Y("Vítr (m/s):Q", title="Rychlost větru (m/s)"),
                    tooltip=[alt.Tooltip("Den:N"), alt.Tooltip("Vítr (m/s):Q", format=".1f")],
                )
                .properties(height=160, title="Rychlost větru")
                .interactive()
            )
            st.altair_chart(wind_chart, use_container_width=True)

        else:
            st.warning("Nepodařilo se načíst předpověď počasí.")

    except Exception as e:
        st.error(f"Chyba: {e}")

    st.markdown("---")

    # ── Korelace ──
    st.subheader("Korelace počasí a cen elektřiny")

    conn = get_connection()
    days_count = get_data_days_count(conn)

    if days_count >= 14:
        try:
            with st.spinner("Analyzuji korelaci..."):
                correlation = get_weather_price_correlation(conn, days_back=30)

            if correlation:
                factors = [
                    ("Teplota", correlation.temperature_correlation,
                     "Kladná = vyšší teplota → vyšší cena"),
                    ("Oblačnost", correlation.cloud_cover_correlation,
                     "Kladná = více mraků → vyšší cena"),
                    ("Sluneční záření", correlation.solar_radiation_correlation,
                     "Záporná = více slunce → nižší cena (FVE)"),
                    ("Rychlost větru", correlation.wind_speed_correlation,
                     "Záporná = více větru → nižší cena"),
                ]

                cols = st.columns(4)
                for col, (label, val, help_text) in zip(cols, factors):
                    with col:
                        icon = "🔴" if val > 0.3 else "🟢" if val < -0.3 else "🟡"
                        st.metric(f"{icon} {label}", f"{val:+.2f}", help=help_text)

                st.info(
                    f"**Nejsilnější faktor:** {correlation.strongest_factor} "
                    f"&nbsp;|&nbsp; R² = {correlation.r_squared:.3f}"
                )

                with st.expander("Interpretace korelací"):
                    st.markdown("""
                    | Faktor | Vztah | Důvod |
                    |--------|-------|-------|
                    | ☀️ Sluneční záření | Záporná korelace | Více slunce = více FVE = nižší ceny |
                    | 💨 Rychlost větru | Záporná korelace | Více větru = více větrné energie |
                    | ☁️ Oblačnost | Kladná korelace | Zataženo = méně FVE = vyšší ceny |
                    | 🌡️ Teplota | Smíšená | Extrémy = vyšší spotřeba = vyšší ceny |
                    """)
        except Exception as e:
            st.warning(f"Korelační analýza není dostupná: {e}")
    else:
        st.info(f"Pro korelační analýzu je potřeba alespoň 14 dnů dat. Aktuálně {days_count}.")

    conn.close()

    st.markdown("---")

    # ── Počasí-enhanced predikce ──
    st.subheader("Predikce cen s počasím (D+1 až D+5)")

    conn = get_connection()
    days_count = get_data_days_count(conn)

    if days_count >= 7:
        from ote.forecast import get_forecast_for_days_with_weather
        try:
            with st.spinner("Vytvářím predikci..."):
                price_forecasts = get_forecast_for_days_with_weather(conn, days_ahead=5)

            if price_forecasts:
                summary_data = []
                for dt, day_forecasts in sorted(price_forecasts.items()):
                    ps = [f.price_czk for f in day_forecasts]
                    summary_data.append({
                        "Datum": dt, "Den": dt.strftime("%a %d.%m"),
                        "Min": min(ps), "Max": max(ps), "Průměr": sum(ps) / len(ps),
                    })
                summary_df = pd.DataFrame(summary_data)

                band = (
                    alt.Chart(summary_df)
                    .mark_area(opacity=0.15, color="#8B5CF6")
                    .encode(
                        x=alt.X("Datum:T"),
                        y=alt.Y("Min:Q", title="CZK/MWh", axis=alt.Axis(format=",.0f")),
                        y2=alt.Y2("Max:Q"),
                    )
                )
                line = (
                    alt.Chart(summary_df)
                    .mark_line(color="#8B5CF6", strokeWidth=2.5, point=True)
                    .encode(
                        x=alt.X("Datum:T", title="Datum"),
                        y=alt.Y("Průměr:Q"),
                        tooltip=[
                            alt.Tooltip("Den:N"), alt.Tooltip("Průměr:Q", format=",.0f"),
                            alt.Tooltip("Min:Q", format=",.0f"), alt.Tooltip("Max:Q", format=",.0f"),
                        ],
                    )
                )
                st.altair_chart(
                    (band + line).properties(height=240, title="Počasí-enhanced predikce").interactive(),
                    use_container_width=True,
                )
                st.dataframe(
                    summary_df[["Den", "Min", "Max", "Průměr"]].rename(columns={
                        "Min": "Min (CZK/MWh)", "Max": "Max (CZK/MWh)", "Průměr": "Průměr (CZK/MWh)"
                    }),
                    use_container_width=True, hide_index=True,
                )
            else:
                st.info("Nepodařilo se vytvořit predikci.")
        except Exception as e:
            st.warning(f"Predikce s počasím není dostupná: {e}")
    else:
        st.info(f"Pro predikci je potřeba alespoň 7 dnů. Aktuálně {days_count}.")

    conn.close()


if __name__ == "__main__":
    main()
