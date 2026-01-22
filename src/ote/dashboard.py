"""Streamlit dashboard pro vizualizaci spotových cen."""

from datetime import date, timedelta

import altair as alt
import pandas as pd
import streamlit as st

from ote.db import (
    get_available_dates,
    get_connection,
    get_daily_stats,
    get_data_days_count,
    get_prices_for_date,
)
from ote.spot import SpotPrice, fetch_spot_prices, get_current_price


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

    st.title("⚡ OTE Spotové ceny elektřiny")

    # Hlavní navigace pomocí tabů
    tab_prices, tab_analysis, tab_forecast = st.tabs([
        "Aktuální ceny",
        "Analýza",
        "Predikce",
    ])

    with tab_prices:
        show_prices_tab()

    with tab_analysis:
        show_analysis_tab()

    with tab_forecast:
        show_forecast_tab()


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
        .mark_area(
            line={"color": "#1f77b4"},
            color=alt.Gradient(  # type: ignore[no-untyped-call]
                gradient="linear",
                stops=[
                    alt.GradientStop(color="#1f77b4", offset=0),
                    alt.GradientStop(color="#a8d5ff", offset=1),
                ],
                x1=1, x2=1, y1=1, y2=0,
            ),
        )
        .encode(
            x=alt.X("Čas:T", title="Čas", axis=alt.Axis(format="%H:%M")),
            y=alt.Y("Cena (CZK/MWh):Q", title="Cena (CZK/MWh)"),
            tooltip=["Hodina", "Cena (CZK/MWh)", "Cena (EUR/MWh)"],
        )
        .properties(height=400)
        .interactive()
    )

    st.altair_chart(chart, use_container_width=True)

    # Tabulka
    with st.expander("Zobrazit tabulku"):
        st.dataframe(
            df[["Hodina", "Cena (CZK/MWh)", "Cena (EUR/MWh)"]],
            use_container_width=True,
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
        .mark_area(
            line={"color": "#2ca02c"},
            color=alt.Gradient(  # type: ignore[no-untyped-call]
                gradient="linear",
                stops=[
                    alt.GradientStop(color="#2ca02c", offset=0),
                    alt.GradientStop(color="#b5e7b5", offset=1),
                ],
                x1=1, x2=1, y1=1, y2=0,
            ),
        )
        .encode(
            x=alt.X("Čas:T", title="Čas", axis=alt.Axis(format="%H:%M")),
            y=alt.Y("Cena (CZK/MWh):Q", title="Cena (CZK/MWh)"),
            tooltip=["Hodina", "Cena (CZK/MWh)", "Cena (EUR/MWh)"],
        )
        .properties(height=400)
        .interactive()
    )

    st.altair_chart(chart, use_container_width=True)

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

            st.altair_chart(compare_chart, use_container_width=True)

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
        get_price_level_color,
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
        base = alt.Chart(pattern_df).encode(
            x=alt.X("Hodina:O", title="Hodina"),
        )

        area = base.mark_area(opacity=0.3, color="#1f77b4").encode(
            y=alt.Y("Min:Q", title="Cena (CZK/MWh)"),
            y2="Max:Q",
        )

        line = base.mark_line(color="#1f77b4", strokeWidth=2).encode(
            y=alt.Y("Průměr (CZK/MWh):Q"),
        )

        points = base.mark_circle(color="#1f77b4", size=50).encode(
            y=alt.Y("Průměr (CZK/MWh):Q"),
            tooltip=["Hodina", "Průměr (CZK/MWh)", "Min", "Max"],
        )

        pattern_chart = (area + line + points).properties(height=300).interactive()
        st.altair_chart(pattern_chart, use_container_width=True)

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

            st.altair_chart(heatmap, use_container_width=True)
    else:
        st.info(
            f"Týdenní heatmapa vyžaduje alespoň 14 dnů dat. "
            f"Aktuálně máte {days_count} dnů."
        )

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
            .mark_area(
                line={"color": "#ff7f0e"},
                color=alt.Gradient(  # type: ignore[no-untyped-call]
                    gradient="linear",
                    stops=[
                        alt.GradientStop(color="#ff7f0e", offset=0),
                        alt.GradientStop(color="#ffd699", offset=1),
                    ],
                    x1=1, x2=1, y1=1, y2=0,
                ),
            )
            .encode(
                x=alt.X("Čas:T", title="Čas", axis=alt.Axis(format="%H:%M")),
                y=alt.Y("Cena (CZK/MWh):Q", title="Cena (CZK/MWh)"),
                tooltip=["Hodina", "Cena (CZK/MWh)", "Cena (EUR/MWh)"],
            )
            .properties(height=300, title=f"Spotové ceny - {tomorrow}")
            .interactive()
        )

        st.altair_chart(chart, use_container_width=True)

        # Tabulka
        with st.expander("Zobrazit tabulku"):
            st.dataframe(
                df[["Hodina", "Cena (CZK/MWh)", "Cena (EUR/MWh)"]],
                use_container_width=True,
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
            base = alt.Chart(forecast_df).encode(
                x=alt.X("Čas:T", title="Čas", axis=alt.Axis(format="%H:%M")),
            )

            band = base.mark_area(opacity=0.3, color="#9467bd").encode(
                y=alt.Y("Min:Q", title="Cena (CZK/MWh)"),
                y2="Max:Q",
            )

            line = base.mark_line(color="#9467bd", strokeWidth=2).encode(
                y=alt.Y("Predikce (CZK/MWh):Q"),
                tooltip=["Hodina", "Predikce (CZK/MWh)", "Min", "Max"],
            )

            forecast_chart = (band + line).properties(height=250).interactive()
            st.altair_chart(forecast_chart, use_container_width=True)

    conn.close()


if __name__ == "__main__":
    main()
