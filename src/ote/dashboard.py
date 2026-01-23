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
from ote.spot import SpotPrice, fetch_spot_prices, get_current_price

# Časové pásmo pro Českou republiku
PRAGUE_TZ = ZoneInfo("Europe/Prague")


def load_prices_as_df(prices: list[SpotPrice]) -> pd.DataFrame:
    """Převede seznam cen na pandas DataFrame."""
    return pd.DataFrame([
        {
            "Čas": p.time_from,
            "Hodina": p.time_from.strftime("%H:%M"),
            "Cena (CZK/MWh)": p.price_czk,
            "Cena (EUR/MWh)": p.price_eur,
        }
        for p in prices
    ])


def main() -> None:
    """Hlavní funkce dashboard."""
    st.set_page_config(
        page_title="OTE Spotové ceny",
        page_icon="⚡",
        layout="wide",
    )

    # Auto-refresh každých 15 minut (900 sekund = 900000 ms)
    # Refresh probíhá v :00, :15, :30, :45
    st_autorefresh(interval=15 * 60 * 1000, key="price_refresh")

    st.title("⚡ OTE Spotové ceny elektřiny")

    # Zobraz čas posledního refreshe (české časové pásmo)
    now = datetime.now(PRAGUE_TZ)
    st.caption(f"Poslední aktualizace: {now.strftime('%H:%M:%S')} (CET/CEST)")

    # Hlavní navigace pomocí tabů
    tab_prices, tab_analysis, tab_profiles, tab_forecast, tab_weather = st.tabs([
        "Aktuální ceny",
        "Analýza",
        "Profily & Riziko",
        "Predikce",
        "Počasí",
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


def show_prices_tab() -> None:
    """Zobrazí tab s aktuálními cenami."""
    # Sidebar pro tento tab
    st.sidebar.header("Nastavení cen")
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
    """Zobrazí živá data z API."""
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

    # Metriky
    current = get_current_price(prices)
    df = load_prices_as_df(prices)

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        if current:
            st.metric(
                "Aktuální cena",
                f"{current.price_czk:,.0f} CZK/MWh",
                help=f"{current.time_from:%H:%M} - {current.time_to:%H:%M}",
            )
        else:
            st.metric("Aktuální cena", "N/A")

    with col2:
        st.metric("Minimum", f"{df['Cena (CZK/MWh)'].min():,.0f} CZK/MWh")

    with col3:
        st.metric("Maximum", f"{df['Cena (CZK/MWh)'].max():,.0f} CZK/MWh")

    with col4:
        st.metric("Průměr", f"{df['Cena (CZK/MWh)'].mean():,.0f} CZK/MWh")

    st.caption(f"Kurz ČNB: 1 EUR = {eur_czk_rate:.3f} CZK")

    # Graf
    st.subheader(f"Spotové ceny - {selected_date}")

    chart = (
        alt.Chart(df)
        .mark_bar(color="#1f77b4")
        .encode(
            x=alt.X("Hodina:N", title="Čas", sort=None),
            y=alt.Y("Cena (CZK/MWh):Q", title="Cena (CZK/MWh)"),
            tooltip=["Hodina", "Cena (CZK/MWh)", "Cena (EUR/MWh)"],
        )
        .properties(height=400)
        .interactive()
    )

    st.altair_chart(chart, width="stretch")

    # Tabulka
    with st.expander("Zobrazit tabulku"):
        st.dataframe(
            df[["Hodina", "Cena (CZK/MWh)", "Cena (EUR/MWh)"]],
            width="stretch",
            hide_index=True,
        )


def show_historical_data() -> None:
    """Zobrazí historická data z databáze."""
    conn = get_connection()
    dates = get_available_dates(conn)

    if not dates:
        st.warning("Databáze je prázdná. Použijte `ote save` pro uložení dat.")
        conn.close()
        return

    # Výběr data
    selected_date = st.sidebar.selectbox(
        "Vyberte datum",
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

    # Metriky
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric("Minimum", f"{stats['min']:,.0f} CZK/MWh")

    with col2:
        st.metric("Maximum", f"{stats['max']:,.0f} CZK/MWh")

    with col3:
        st.metric("Průměr", f"{stats['avg']:,.0f} CZK/MWh")

    with col4:
        st.metric("Záznamů", f"{stats['count']}")

    st.caption(f"Kurz ČNB: 1 EUR = {stats['eur_czk_rate']:.3f} CZK")

    # Graf
    st.subheader(f"Spotové ceny - {selected_date}")

    chart = (
        alt.Chart(df)
        .mark_bar(color="#2ca02c")
        .encode(
            x=alt.X("Hodina:N", title="Čas", sort=None),
            y=alt.Y("Cena (CZK/MWh):Q", title="Cena (CZK/MWh)"),
            tooltip=["Hodina", "Cena (CZK/MWh)", "Cena (EUR/MWh)"],
        )
        .properties(height=400)
        .interactive()
    )

    st.altair_chart(chart, width="stretch")

    # Porovnání dnů
    if len(dates) > 1:
        st.subheader("Porovnání dnů")

        all_data = []
        for d in dates[:7]:  # Posledních 7 dnů
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

            compare_chart = (
                alt.Chart(compare_df)
                .mark_bar()
                .encode(
                    x=alt.X("Datum:T", title="Datum"),
                    y=alt.Y("Průměr:Q", title="Průměrná cena (CZK/MWh)"),
                    color=alt.value("#1f77b4"),
                    tooltip=["Datum", "Min", "Max", "Průměr"],
                )
                .properties(height=300)
            )

            st.altair_chart(compare_chart, width="stretch")

    conn.close()


def show_analysis_tab() -> None:
    """Zobrazí tab s analýzou cenových vzorců."""
    conn = get_connection()
    days_count = get_data_days_count(conn)

    st.subheader("Analýza cenových vzorců")

    # Status dat
    if days_count == 0:
        st.warning("Databáze je prázdná. Použijte `ote save` pro uložení dat.")
        conn.close()
        return

    st.info(f"Dostupná historie: {days_count} dnů")

    if days_count < 7:
        st.warning(
            f"Pro analýzu vzorců je potřeba alespoň 7 dnů dat. "
            f"Aktuálně máte {days_count} dnů. Pokračujte ve sbírání dat pomocí `ote save`."
        )
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
    from ote.spot import get_current_price

    # Aktuální cenová hladina
    st.subheader("Aktuální cenová hladina")

    try:
        prices, _ = fetch_spot_prices(date.today())
        current = get_current_price(prices)

        if current:
            classification = classify_price(current.price_czk, conn)
            color = get_price_level_color(classification)

            col1, col2 = st.columns(2)
            with col1:
                st.metric("Aktuální cena", f"{current.price_czk:,.0f} CZK/MWh")
            with col2:
                st.markdown(
                    f"<div style='padding: 10px; background-color: {color}; "
                    f"border-radius: 5px; text-align: center; color: white; "
                    f"font-weight: bold;'>{classification.upper()}</div>",
                    unsafe_allow_html=True,
                )
        else:
            st.info("Aktuální cena není k dispozici.")
    except Exception:
        st.info("Nelze načíst aktuální cenu z API.")

    # Hodinové vzorce
    st.subheader("Průměrné ceny podle hodiny")

    patterns = get_hourly_patterns(conn, days_back=30)

    if patterns:
        pattern_df = pd.DataFrame([
            {
                "Hodina": p.hour,
                "Průměr (CZK/MWh)": p.avg_price,
                "Min": p.min_price,
                "Max": p.max_price,
            }
            for p in patterns
        ])

        # Graf hodinových vzorců
        pattern_chart = (
            alt.Chart(pattern_df)
            .mark_bar(color="#1f77b4")
            .encode(
                x=alt.X("Hodina:O", title="Hodina"),
                y=alt.Y("Průměr (CZK/MWh):Q", title="Cena (CZK/MWh)"),
                tooltip=["Hodina", "Průměr (CZK/MWh)", "Min", "Max"],
            )
            .properties(height=300)
            .interactive()
        )
        st.altair_chart(pattern_chart, width="stretch")

    # Nejlevnější a nejdražší hodiny
    col1, col2 = st.columns(2)

    with col1:
        st.subheader("Nejlevnější hodiny")
        best = get_best_hours(conn, top_n=5)
        for hour, price in best:
            st.markdown(f"**{hour:02d}:00** - {price:,.0f} CZK/MWh")

    with col2:
        st.subheader("Nejdražší hodiny")
        worst = get_worst_hours(conn, top_n=5)
        for hour, price in worst:
            st.markdown(f"**{hour:02d}:00** - {price:,.0f} CZK/MWh")

    # Týdenní heatmapa (pokud je dost dat)
    if days_count >= 14:
        st.subheader("Týdenní heatmapa cen")

        heatmap_data = get_weekday_hour_heatmap_data(conn, days_back=60)

        if heatmap_data:
            heatmap_df = pd.DataFrame(heatmap_data)

            heatmap = (
                alt.Chart(heatmap_df)
                .mark_rect()
                .encode(
                    x=alt.X("hour:O", title="Hodina"),
                    y=alt.Y(
                        "weekday_name:O",
                        title="Den",
                        sort=["Po", "Út", "St", "Čt", "Pá", "So", "Ne"],
                    ),
                    color=alt.Color(
                        "avg_price:Q",
                        title="Cena (CZK/MWh)",
                        scale=alt.Scale(scheme="redyellowgreen", reverse=True),
                    ),
                    tooltip=["weekday_name", "hour", "avg_price"],
                )
                .properties(height=250)
            )

            st.altair_chart(heatmap, width="stretch")
    else:
        st.info(
            f"Týdenní heatmapa vyžaduje alespoň 14 dnů dat. "
            f"Aktuálně máte {days_count} dnů."
        )

    # --- Negativní ceny ---
    st.markdown("---")
    st.subheader("Negativní ceny")

    neg_stats_30 = get_negative_price_stats(conn, days_back=30)
    neg_stats_7 = get_negative_price_stats(conn, days_back=7)

    col1, col2, col3 = st.columns(3)

    with col1:
        st.metric(
            "Negativní hodiny (30 dní)",
            f"{neg_stats_30.count}",
            help="Počet hodin s cenou <= 0 CZK/MWh",
        )

    with col2:
        st.metric(
            "Negativní hodiny (7 dní)",
            f"{neg_stats_7.count}",
        )

    with col3:
        min_price = neg_stats_30.min_price
        if min_price is not None:
            st.metric("Nejnižší cena", f"{min_price:,.0f} CZK/MWh")
        else:
            st.metric("Nejnižší cena", "N/A")

    # Alert pro zítřejší predikci negativních cen
    risky_hours = get_negative_price_forecast(conn)
    if risky_hours:
        hours_str = ", ".join(f"{h}:00" for h in risky_hours)
        st.warning(
            f"Pozor: Na základě historie mohou být zítra negativní ceny "
            f"v těchto hodinách: {hours_str}"
        )

    # Graf typických hodin s negativními cenami
    hours_dist = neg_stats_30.hours_distribution
    if hours_dist:
        dist_df = pd.DataFrame([
            {"Hodina": h, "Počet": c}
            for h, c in sorted(hours_dist.items())
        ])

        dist_chart = (
            alt.Chart(dist_df)
            .mark_bar(color="#dc3545")
            .encode(
                x=alt.X("Hodina:O", title="Hodina"),
                y=alt.Y("Počet:Q", title="Počet výskytů"),
                tooltip=["Hodina", "Počet"],
            )
            .properties(height=200, title="Typické hodiny s negativními cenami")
        )

        st.altair_chart(dist_chart, width="stretch")

    # Historie negativních cen
    neg_hours = get_negative_price_hours_list(conn, days_back=30)
    if neg_hours:
        with st.expander("Historie negativních cen (posledních 30 dní)"):
            neg_df = pd.DataFrame([
                {
                    "Datum": h.date.strftime("%d.%m.%Y"),
                    "Hodina": f"{h.hour:02d}:00",
                    "Cena (CZK/MWh)": f"{h.price_czk:,.0f}",
                }
                for h in neg_hours
            ])
            st.dataframe(neg_df, width="stretch", hide_index=True)
    else:
        st.info("Za posledních 30 dní nebyly zaznamenány žádné negativní ceny.")

    # --- Cenové trendy ---
    st.markdown("---")
    st.subheader("Cenové trendy")

    # Distribuce a percentily
    distribution = get_price_distribution(conn, days_back=30)
    trend = get_price_trend(conn, days_back=30)

    col1, col2, col3 = st.columns(3)

    with col1:
        percentiles = distribution.percentiles
        median = percentiles.get("p50")
        if median is not None:
            st.metric("Medián (30 dní)", f"{median:,.0f} CZK/MWh")
        else:
            st.metric("Medián (30 dní)", "N/A")

    with col2:
        direction = trend.direction
        change = trend.change_percent
        if change is not None:
            delta_str = f"{change:+.1f}%"
            st.metric(
                "Trend",
                direction,
                delta=delta_str,
                delta_color="inverse",  # Nižší cena = lepší
            )
        else:
            st.metric("Trend", direction)

    with col3:
        p90 = percentiles.get("p90")
        if p90 is not None:
            st.metric("90. percentil", f"{p90:,.0f} CZK/MWh")
        else:
            st.metric("90. percentil", "N/A")

    # Tabulka percentilů
    if percentiles:
        with st.expander("Percentily cen"):
            p10 = percentiles.get("p10", 0)
            p25 = percentiles.get("p25", 0)
            p50 = percentiles.get("p50", 0)
            p75 = percentiles.get("p75", 0)
            p90_val = percentiles.get("p90", 0)
            perc_df = pd.DataFrame([
                {"Percentil": "10%", "Cena (CZK/MWh)": f"{p10:,.0f}"},
                {"Percentil": "25%", "Cena (CZK/MWh)": f"{p25:,.0f}"},
                {"Percentil": "50% (medián)", "Cena (CZK/MWh)": f"{p50:,.0f}"},
                {"Percentil": "75%", "Cena (CZK/MWh)": f"{p75:,.0f}"},
                {"Percentil": "90%", "Cena (CZK/MWh)": f"{p90_val:,.0f}"},
            ])
            st.dataframe(perc_df, width="stretch", hide_index=True)

    # Histogram distribuce cen
    bins = distribution.bins
    counts = distribution.counts

    if bins and counts:
        hist_df = pd.DataFrame({
            "Cenové pásmo": bins,
            "Počet": counts,
        })

        hist_chart = (
            alt.Chart(hist_df)
            .mark_bar(color="#1f77b4")
            .encode(
                x=alt.X("Cenové pásmo:N", title="Cena (CZK/MWh)", sort=None),
                y=alt.Y("Počet:Q", title="Počet hodin"),
                tooltip=["Cenové pásmo", "Počet"],
            )
            .properties(height=250, title="Distribuce cen (histogram)")
        )

        st.altair_chart(hist_chart, width="stretch")

    # Graf trendu s klouzavými průměry
    if days_count >= 14:
        ma_data = get_moving_averages(conn, days_back=60)

        if ma_data:
            ma_df = pd.DataFrame([
                {
                    "Datum": d.date,
                    "Denní průměr": d.daily_avg,
                    "7denní MA": d.ma7,
                    "30denní MA": d.ma30,
                }
                for d in ma_data
            ])

            # Reshape pro Altair
            ma_long = ma_df.melt(
                id_vars=["Datum"],
                value_vars=["Denní průměr", "7denní MA", "30denní MA"],
                var_name="Typ",
                value_name="Cena",
            )

            # Filtruj None hodnoty
            ma_long = ma_long.dropna(subset=["Cena"])

            trend_chart = (
                alt.Chart(ma_long)
                .mark_line()
                .encode(
                    x=alt.X("Datum:T", title="Datum"),
                    y=alt.Y("Cena:Q", title="Cena (CZK/MWh)"),
                    color=alt.Color(
                        "Typ:N",
                        scale=alt.Scale(
                            domain=["Denní průměr", "7denní MA", "30denní MA"],
                            range=["#aaaaaa", "#1f77b4", "#ff7f0e"],
                        ),
                    ),
                    strokeWidth=alt.condition(
                        alt.datum.Typ == "Denní průměr",
                        alt.value(1),
                        alt.value(2),
                    ),
                    tooltip=["Datum", "Typ", "Cena"],
                )
                .properties(height=300, title="Vývoj cen s klouzavými průměry")
                .interactive()
            )

            st.altair_chart(trend_chart, width="stretch")

    conn.close()


def show_forecast_tab() -> None:
    """Zobrazí tab s predikcemi cen."""
    conn = get_connection()

    st.subheader("Predikce cen elektřiny")

    from ote.forecast import (
        get_data_sufficiency,
        get_forecast_for_days,
        get_tomorrow_prices,
    )

    sufficiency = get_data_sufficiency(conn)

    # Status dat
    st.sidebar.header("Status dat")
    st.sidebar.metric("Dnů historie", sufficiency.total_days)
    st.sidebar.markdown("**Dostupné metody:**")
    tomorrow_status = "Ano" if sufficiency.can_show_tomorrow else "Ne"
    st.sidebar.markdown(f"- Zítřejší ceny (D+1): {tomorrow_status}")
    hourly_status = "Ano" if sufficiency.can_show_hourly_patterns else "Ne (potřeba 7+ dnů)"
    st.sidebar.markdown(f"- Hodinové vzorce: {hourly_status}")
    stat_status = "Ano" if sufficiency.can_show_statistical_forecast else "Ne (potřeba 14+ dnů)"
    st.sidebar.markdown(f"- Statistická predikce: {stat_status}")

    # Zítřejší ceny (day-ahead)
    st.subheader("Zítřejší ceny (D+1)")
    st.caption("Day-ahead ceny publikované OTE (kolem 13:00 CET)")

    with st.spinner("Načítám zítřejší ceny z OTE..."):
        tomorrow_prices, eur_czk_rate, available = get_tomorrow_prices()

    if available and tomorrow_prices:
        tomorrow = date.today() + timedelta(days=1)
        df = load_prices_as_df(tomorrow_prices)

        # Metriky
        col1, col2, col3, col4 = st.columns(4)

        with col1:
            st.metric("Minimum", f"{df['Cena (CZK/MWh)'].min():,.0f} CZK/MWh")

        with col2:
            st.metric("Maximum", f"{df['Cena (CZK/MWh)'].max():,.0f} CZK/MWh")

        with col3:
            st.metric("Průměr", f"{df['Cena (CZK/MWh)'].mean():,.0f} CZK/MWh")

        with col4:
            st.metric("Kurz", f"{eur_czk_rate:.2f} CZK/EUR")

        # Graf
        chart = (
            alt.Chart(df)
            .mark_bar(color="#ff7f0e")
            .encode(
                x=alt.X("Hodina:N", title="Čas", sort=None),
                y=alt.Y("Cena (CZK/MWh):Q", title="Cena (CZK/MWh)"),
                tooltip=["Hodina", "Cena (CZK/MWh)", "Cena (EUR/MWh)"],
            )
            .properties(height=300, title=f"Spotové ceny - {tomorrow}")
            .interactive()
        )

        st.altair_chart(chart, width="stretch")

        # Tabulka
        with st.expander("Zobrazit tabulku"):
            st.dataframe(
                df[["Hodina", "Cena (CZK/MWh)", "Cena (EUR/MWh)"]],
                width="stretch",
                hide_index=True,
            )
    else:
        st.info(
            "Zítřejší ceny zatím nejsou publikovány. "
            "OTE zveřejňuje day-ahead ceny obvykle kolem 13:00 CET."
        )

    # Prognóza D+2 až D+7
    st.subheader("Prognóza D+2 až D+7")

    if not sufficiency.can_show_hourly_patterns:
        st.warning(
            f"Pro prognózu je potřeba alespoň 7 dnů historických dat. "
            f"Aktuálně máte {sufficiency.total_days} dnů. "
            f"Pokračujte ve sbírání dat pomocí `ote save`."
        )
        conn.close()
        return

    if sufficiency.can_show_statistical_forecast:
        method = "Statistická predikce"
    else:
        method = "Hodinové vzorce"
    st.caption(f"Metoda: {method}")

    forecasts = get_forecast_for_days(conn, days_ahead=7)

    if not forecasts:
        st.info("Nedostatek dat pro vytvoření prognózy.")
        conn.close()
        return

    # Zobraz prognózu pro každý den
    for target_date, day_forecasts in forecasts.items():
        with st.expander(f"{target_date.strftime('%A %d.%m.%Y')}", expanded=False):
            # Převod na DataFrame
            forecast_df = pd.DataFrame([
                {
                    "Čas": f.time_from,
                    "Hodina": f.time_from.strftime("%H:%M"),
                    "Predikce (CZK/MWh)": f.price_czk,
                    "Min": f.confidence_low,
                    "Max": f.confidence_high,
                }
                for f in day_forecasts
            ])

            # Metriky
            col1, col2, col3 = st.columns(3)
            pred_col = "Predikce (CZK/MWh)"
            with col1:
                st.metric("Predikovaný min", f"{forecast_df[pred_col].min():,.0f} CZK/MWh")
            with col2:
                st.metric("Predikovaný max", f"{forecast_df[pred_col].max():,.0f} CZK/MWh")
            with col3:
                st.metric("Predikovaný průměr", f"{forecast_df[pred_col].mean():,.0f} CZK/MWh")

            # Graf s confidence intervaly
            forecast_chart = (
                alt.Chart(forecast_df)
                .mark_bar(color="#9467bd")
                .encode(
                    x=alt.X("Hodina:N", title="Čas", sort=None),
                    y=alt.Y("Predikce (CZK/MWh):Q", title="Cena (CZK/MWh)"),
                    tooltip=["Hodina", "Predikce (CZK/MWh)", "Min", "Max"],
                )
                .properties(height=250)
                .interactive()
            )
            st.altair_chart(forecast_chart, width="stretch")

    conn.close()


def show_profiles_tab() -> None:
    """Zobrazí tab s profily spotřeby a rizikem."""
    conn = get_connection()
    days_count = get_data_days_count(conn)

    if days_count < 7:
        st.warning(
            f"Pro analýzu profilů je potřeba alespoň 7 dnů dat. "
            f"Aktuálně máte {days_count} dnů."
        )
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

    # --- Benchmark sekce ---
    st.subheader("Aktuální cenový benchmark")

    try:
        prices, _ = fetch_spot_prices(date.today())
        current = get_current_price(prices)

        if current:
            benchmark = get_current_benchmark(conn, current.price_czk)

            col1, col2, col3, col4 = st.columns(4)

            with col1:
                st.metric("Aktuální cena", f"{benchmark.current_price:,.0f} CZK/MWh")

            with col2:
                st.metric("Průměr 7d", f"{benchmark.avg_7d:,.0f} CZK/MWh")

            with col3:
                st.metric("Percentil", f"{benchmark.percentile_rank}.")

            with col4:
                # Barevná klasifikace
                color_map = {
                    "velmi levná": "#28a745",
                    "levná": "#7cb342",
                    "normální": "#ffc107",
                    "drahá": "#ff9800",
                    "velmi drahá": "#dc3545",
                }
                color = color_map.get(benchmark.classification, "#6c757d")
                st.markdown(
                    f"<div style='padding: 10px; background-color: {color}; "
                    f"border-radius: 5px; text-align: center; color: white; "
                    f"font-weight: bold;'>{benchmark.classification.upper()}</div>",
                    unsafe_allow_html=True,
                )
        else:
            st.info("Aktuální cena není k dispozici.")
    except Exception:
        st.info("Nelze načíst aktuální cenu z API.")

    st.markdown("---")

    # --- Profily spotřeby ---
    st.subheader("Spotřebitelské profily")

    profiles = get_all_profiles_comparison(conn)

    if profiles:
        # Tabulka profilů
        profile_data = []
        for p in profiles:
            profile_data.append({
                "Profil": p.name,
                "Popis": p.description,
                "Cena (CZK/MWh)": p.avg_price_czk,
                "Úspora (%)": p.savings_vs_flat_pct,
                "Nejlepší den": p.best_day,
            })

        profile_df = pd.DataFrame(profile_data)

        # Bar chart
        chart = (
            alt.Chart(profile_df)
            .mark_bar()
            .encode(
                x=alt.X("Profil:N", sort=None),
                y=alt.Y("Cena (CZK/MWh):Q"),
                color=alt.condition(
                    alt.datum["Úspora (%)"] > 0,
                    alt.value("#28a745"),
                    alt.value("#dc3545"),
                ),
                tooltip=["Profil", "Popis", "Cena (CZK/MWh)", "Úspora (%)"],
            )
            .properties(height=300, title="Průměrná cena podle profilu")
        )

        st.altair_chart(chart, use_container_width=True)

        # Tabulka
        st.dataframe(profile_df, use_container_width=True, hide_index=True)

        # Doporučení
        best_profile = profiles[0]
        st.success(
            f"**Doporučený profil:** {best_profile.name} "
            f"(úspora {best_profile.savings_vs_flat_pct:+.1f}% oproti flat tarifu)"
        )
    else:
        st.info("Nedostatek dat pro analýzu profilů.")

    st.markdown("---")

    # --- Volatilita a riziko ---
    st.subheader("Volatilita a riziko")

    metrics = get_volatility_metrics(conn)

    if metrics.volatility_trend != "nedostatek dat":
        col1, col2, col3 = st.columns(3)

        with col1:
            st.metric(
                "Denní volatilita",
                f"{metrics.daily_volatility:,.0f} CZK",
                help="Směrodatná odchylka denních průměrů",
            )

        with col2:
            st.metric(
                "Průměrné denní rozpětí",
                f"{metrics.avg_daily_swing:,.0f} CZK",
                help="Průměrný rozdíl max-min za den",
            )

        with col3:
            trend_icons = {
                "rostoucí": "📈",
                "klesající": "📉",
                "stabilní": "➡️",
            }
            icon = trend_icons.get(metrics.volatility_trend, "")
            st.metric("Trend volatility", f"{icon} {metrics.volatility_trend}")

        col1, col2 = st.columns(2)

        with col1:
            st.metric(
                "VaR 95%",
                f"{metrics.var_95:,.0f} CZK/MWh",
                help="95% cen je pod touto hodnotou",
            )

        with col2:
            st.metric(
                "Max denní rozpětí",
                f"{metrics.max_daily_swing:,.0f} CZK/MWh",
            )

    st.markdown("---")

    # --- Špičky ---
    st.subheader("Cenové špičky")

    peak_analysis = get_peak_analysis(conn)

    if peak_analysis.total_peaks_30d > 0:
        col1, col2, col3 = st.columns(3)

        with col1:
            st.metric("Hranice špičky (P90)", f"{peak_analysis.threshold_p90:,.0f} CZK")

        with col2:
            st.metric("Špičky za 30 dnů", f"{peak_analysis.total_peaks_30d}")

        with col3:
            risky_str = ", ".join(f"{h}:00" for h in peak_analysis.most_risky_hours[:3])
            st.metric("Nejrizikovější hodiny", risky_str)

        # Heatmapa pravděpodobnosti špiček
        probs = get_peak_probability_by_hour(conn)

        prob_data = [{"Hodina": h, "Pravděpodobnost": p * 100} for h, p in probs.items()]
        prob_df = pd.DataFrame(prob_data)

        chart = (
            alt.Chart(prob_df)
            .mark_bar()
            .encode(
                x=alt.X("Hodina:O"),
                y=alt.Y("Pravděpodobnost:Q", title="Pravděpodobnost (%)"),
                color=alt.Color(
                    "Pravděpodobnost:Q",
                    scale=alt.Scale(scheme="redyellowgreen", reverse=True),
                ),
                tooltip=["Hodina", "Pravděpodobnost"],
            )
            .properties(height=250, title="Pravděpodobnost cenové špičky podle hodiny")
        )

        st.altair_chart(chart, use_container_width=True)

        # Predikce pro zítřek
        st.subheader("Predikce špiček pro zítřek")

        predictions = predict_peaks_tomorrow(conn)
        risky = [p for p in predictions if p.probability >= 0.2]

        if risky:
            pred_data = [
                {
                    "Hodina": f"{p.hour:02d}:00",
                    "Pravděpodobnost (%)": p.probability * 100,
                    "Očekávaná cena": p.expected_price,
                    "Riziko": p.risk_level,
                }
                for p in sorted(risky, key=lambda x: x.probability, reverse=True)
            ]
            pred_df = pd.DataFrame(pred_data)
            st.dataframe(pred_df, use_container_width=True, hide_index=True)
        else:
            st.success("Zítra se neočekávají výrazné cenové špičky.")

    else:
        st.info("Žádné cenové špičky za posledních 30 dnů.")

    conn.close()


def show_weather_tab() -> None:
    """Zobrazí tab s počasím a jeho vlivem na ceny."""
    st.subheader("Počasí a ceny elektřiny")

    try:
        from ote.weather import fetch_weather_forecast, get_weather_price_correlation
    except ImportError:
        st.error("Modul počasí není dostupný.")
        return

    # Předpověď počasí
    st.subheader("Předpověď počasí (Praha)")

    try:
        with st.spinner("Načítám předpověď počasí..."):
            weather_forecasts = fetch_weather_forecast(days_ahead=7)

        if weather_forecasts:
            weather_data = []
            for f in weather_forecasts:
                impact = {
                    "sunny": "↓ nižší",
                    "windy": "↓ nižší",
                    "cloudy": "↑ vyšší",
                    "mixed": "~ běžné",
                }.get(f.weather_type, "?")

                weather_data.append({
                    "Datum": f.date,
                    "Typ": f.weather_type,
                    "Teplota (°C)": f.avg_temperature,
                    "Oblačnost (%)": f.avg_cloud_cover,
                    "Vítr (m/s)": f.avg_wind_speed,
                    "Vliv na ceny": impact,
                })

            weather_df = pd.DataFrame(weather_data)

            # Graf teploty a oblačnosti
            col1, col2 = st.columns(2)

            with col1:
                temp_chart = (
                    alt.Chart(weather_df)
                    .mark_line(point=True, color="#ff7f0e")
                    .encode(
                        x=alt.X("Datum:T", title="Datum"),
                        y=alt.Y("Teplota (°C):Q"),
                        tooltip=["Datum", "Teplota (°C)"],
                    )
                    .properties(height=200, title="Předpověď teploty")
                )
                st.altair_chart(temp_chart, use_container_width=True)

            with col2:
                cloud_chart = (
                    alt.Chart(weather_df)
                    .mark_bar(color="#1f77b4")
                    .encode(
                        x=alt.X("Datum:T", title="Datum"),
                        y=alt.Y("Oblačnost (%):Q"),
                        tooltip=["Datum", "Oblačnost (%)", "Typ"],
                    )
                    .properties(height=200, title="Předpověď oblačnosti")
                )
                st.altair_chart(cloud_chart, use_container_width=True)

            # Tabulka
            st.dataframe(weather_df, use_container_width=True, hide_index=True)

        else:
            st.warning("Nepodařilo se načíst předpověď počasí.")

    except Exception as e:
        st.error(f"Chyba při načítání počasí: {e}")

    st.markdown("---")

    # Korelace
    st.subheader("Korelace počasí a cen")

    conn = get_connection()
    days_count = get_data_days_count(conn)

    if days_count >= 14:
        try:
            with st.spinner("Analyzuji korelaci..."):
                correlation = get_weather_price_correlation(conn, days_back=30)

            if correlation:
                col1, col2, col3, col4 = st.columns(4)

                def corr_color(c: float) -> str:
                    if c > 0.3:
                        return "🔴"
                    elif c < -0.3:
                        return "🟢"
                    else:
                        return "🟡"

                with col1:
                    st.metric(
                        "Teplota",
                        f"{correlation.temperature_correlation:+.2f}",
                        help="Kladná = vyšší teplota = vyšší cena",
                    )

                with col2:
                    st.metric(
                        "Oblačnost",
                        f"{correlation.cloud_cover_correlation:+.2f}",
                        help="Kladná = více mraků = vyšší cena",
                    )

                with col3:
                    st.metric(
                        "Sluneční záření",
                        f"{correlation.solar_radiation_correlation:+.2f}",
                        help="Záporná = více slunce = nižší cena",
                    )

                with col4:
                    st.metric(
                        "Rychlost větru",
                        f"{correlation.wind_speed_correlation:+.2f}",
                        help="Záporná = více větru = nižší cena",
                    )

                st.info(
                    f"**Nejsilnější faktor:** {correlation.strongest_factor} "
                    f"(R² = {correlation.r_squared:.3f})"
                )

                # Interpretace
                st.markdown("""
                **Interpretace korelací:**
                - **Sluneční záření** (záporná korelace): Více slunce = více FVE = nižší ceny
                - **Rychlost větru** (záporná korelace): Více větru = více větrné energie
                - **Oblačnost** (kladná korelace): Zataženo = méně FVE = vyšší ceny
                - **Teplota**: Extrémní teploty = vyšší spotřeba = vyšší ceny
                """)

            else:
                st.warning("Nepodařilo se vypočítat korelaci (nedostatek historických dat).")

        except Exception as e:
            st.warning(f"Korelační analýza není dostupná: {e}")

    else:
        st.info(
            f"Pro korelační analýzu je potřeba alespoň 14 dnů dat. "
            f"Aktuálně máte {days_count} dnů."
        )

    conn.close()

    st.markdown("---")

    # Weather-enhanced predikce
    st.subheader("Predikce s počasím")

    conn = get_connection()
    days_count = get_data_days_count(conn)

    if days_count >= 7:
        from ote.forecast import get_forecast_for_days_with_weather

        try:
            with st.spinner("Vytvářím predikci s počasím..."):
                price_forecasts = get_forecast_for_days_with_weather(conn, days_ahead=5)

            if price_forecasts:
                # Souhrn pro každý den
                summary_data = []
                for dt, day_forecasts in sorted(price_forecasts.items()):
                    prices = [f.price_czk for f in day_forecasts]
                    summary_data.append({
                        "Datum": dt,
                        "Min": min(prices),
                        "Max": max(prices),
                        "Průměr": sum(prices) / len(prices),
                    })

                summary_df = pd.DataFrame(summary_data)

                chart = (
                    alt.Chart(summary_df)
                    .mark_bar(color="#9467bd")
                    .encode(
                        x=alt.X("Datum:T", title="Datum"),
                        y=alt.Y("Průměr:Q", title="Průměrná cena (CZK/MWh)"),
                        tooltip=["Datum", "Min", "Max", "Průměr"],
                    )
                    .properties(height=250, title="Počasí-enhanced predikce")
                )

                st.altair_chart(chart, use_container_width=True)

                st.dataframe(summary_df, use_container_width=True, hide_index=True)

            else:
                st.info("Nepodařilo se vytvořit predikci.")

        except Exception as e:
            st.warning(f"Predikce s počasím není dostupná: {e}")

    else:
        st.info(f"Pro predikci je potřeba alespoň 7 dnů dat. Aktuálně máte {days_count}.")

    conn.close()


if __name__ == "__main__":
    main()
