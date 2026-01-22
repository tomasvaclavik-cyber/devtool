"""Streamlit dashboard pro vizualizaci spotových cen."""

from datetime import date, timedelta

import altair as alt
import pandas as pd
import streamlit as st

from ote.db import get_available_dates, get_connection, get_daily_stats, get_prices_for_date
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

    # Sidebar
    st.sidebar.header("Nastavení")
    data_source = st.sidebar.radio(
        "Zdroj dat",
        ["Živá data (API)", "Databáze (historie)"],
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


if __name__ == "__main__":
    main()
