"""Streamlit dashboard pro vizualizaci spotových cen (vzhled ve stylu SunnyHome)."""

import base64
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import altair as alt
import numpy as np
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
from ote.price_model import Evaluation
from ote.spot import (
    SpotPrice,
    fetch_spot_prices,
    get_current_price,
    get_current_price_debug,
    next_refresh_time,
    slot_label,
)
from ote.theme import (
    ACCENT,
    ACCENT_INK,
    BATTERY,
    BORDER,
    GRID,
    HOME,
    INK_MUTED,
    LEVEL_RANGE,
    READOUT,
    SOLAR,
    SURFACE_RAISED,
    card,
    chip,
    icon_img,
    inject_css,
    page_header,
    pill,
    rank_list,
    readout_table,
    reset_cards,
    show_chart,
    status_box,
)

PRAGUE_TZ = ZoneInfo("Europe/Prague")

# Barevná škála podle cenové hladiny
PRICE_COLORS = {
    "velmi levná": LEVEL_RANGE[0],
    "levná": LEVEL_RANGE[1],
    "normální": LEVEL_RANGE[2],
    "drahá": LEVEL_RANGE[3],
    "velmi drahá": LEVEL_RANGE[4],
    "nedostatek dat": "#6B7280",
}
LEVEL_NAMES = ["Velmi levná", "Levná", "Normální", "Drahá", "Velmi drahá"]


def price_color(price: float, p10: float, p30: float, p70: float, p90: float) -> str:
    if price <= p10:
        return LEVEL_RANGE[0]
    elif price <= p30:
        return LEVEL_RANGE[1]
    elif price <= p70:
        return LEVEL_RANGE[2]
    elif price <= p90:
        return LEVEL_RANGE[3]
    else:
        return LEVEL_RANGE[4]


def load_prices_as_df(prices: list[SpotPrice]) -> pd.DataFrame:
    return pd.DataFrame([
        {
            "Čas": p.time_from,
            "Hodina": slot_label(p.time_from),
            "Cena (CZK/MWh)": p.price_czk,
            "Cena (EUR/MWh)": p.price_eur,
        }
        for p in prices
    ])


# ─── Grafy ───────────────────────────────────────────────────────────────────

# Barvy čáry odspodu nahoru (gradient se roztáhne mezi min a max)
PRICE_STOPS = [
    alt.GradientStop(color=BATTERY, offset=0),
    alt.GradientStop(color=SOLAR, offset=0.45),
    alt.GradientStop(color=READOUT, offset=0.7),
    alt.GradientStop(color=GRID, offset=1),
]


# Výkup: čím výš, tím líp – nahoře zelená, dole (záporná cena) červená
SELL_STOPS = [
    alt.GradientStop(color=GRID, offset=0),
    alt.GradientStop(color=READOUT, offset=0.3),
    alt.GradientStop(color=SOLAR, offset=0.55),
    alt.GradientStop(color=BATTERY, offset=1),
]


def _gradient(stops: list[alt.GradientStop] = PRICE_STOPS) -> alt.Gradient:
    return alt.Gradient(gradient="linear", stops=stops, x1=1, x2=1, y1=1, y2=0)


def slot_key(day: date, time_from: datetime) -> str:
    """Klíč kategorické osy „dd.mm. HH:MM" (temporal osa se ve Streamlitu vykreslí prázdná)."""
    return f"{day:%d.%m.} {slot_label(time_from)}"


def slot_axis(slots: pd.Series, every: int = 3) -> alt.Axis:
    """Osa jen s celými hodinami dělitelnými `every` (klíč „dd.mm. HH:MM") – popisky i mřížka."""
    values = [s for s in slots if s[10:12] == "00" and int(s[7:9]) % every == 0]
    return alt.Axis(values=values, labelAngle=0, labelOverlap=False,
                    labelExpr="substring(datum.value, 7, 12)")


def _now_layers(now: datetime | None, color: str = READOUT) -> list[alt.Chart]:
    if now is None:
        return []
    now_slot = slot_key(now.date(), now.replace(minute=now.minute // 15 * 15))
    return [
        alt.Chart(pd.DataFrame({"Slot": [now_slot]}))
        .mark_rule(color=color, strokeDash=[4, 4], strokeWidth=1.5)
        .encode(x=alt.X("Slot:N", sort=None))
    ]


def _day_keys(slots: pd.Series) -> list[str]:
    """Dny v grafu jako „dd.mm." v pořadí, v jakém jdou za sebou."""
    return list(dict.fromkeys(s[:6] for s in slots))


def _day_layers(day_keys: list[str]) -> list[alt.Chart]:
    if len(day_keys) < 2:
        return []
    today = date.today()
    names = {f"{today:%d.%m.}": "dnes", f"{today + timedelta(days=1):%d.%m.}": "zítra"}
    day_df = pd.DataFrame([
        {"Slot": f"{key} 00:00", "label": names.get(key, key)} for key in day_keys
    ])
    return [
        alt.Chart(day_df.iloc[1:]).mark_rule(color="#334155", strokeWidth=1)
        .encode(x=alt.X("Slot:N", sort=None)),
        alt.Chart(day_df).mark_text(align="left", dx=5, color=INK_MUTED, fontSize=11)
        .encode(x=alt.X("Slot:N", sort=None), y=alt.value(8), text="label:N"),
    ]


def gradient_line_chart(
    df: pd.DataFrame,
    value_col: str,
    y_title: str,
    tooltip: list[alt.Tooltip],
    now: datetime | None = None,
    nt_bands: bool = False,
    y_format: str = ",.0f",
    height: int = 300,
    stops: list[alt.GradientStop] = PRICE_STOPS,
) -> alt.LayerChart:
    """Schodová čára s barevným přechodem podle výšky ceny (styl SunnyHome).

    df musí mít sloupec „Slot" (klíč „dd.mm. HH:MM"), volitelně „Tarif" pro pásy NT.
    """
    df = df.copy()
    df["band_lo"] = min(0.0, df[value_col].min())
    df["band_hi"] = df[value_col].max()
    days = _day_keys(df["Slot"])
    every = 3 if len(days) == 1 else 6
    x = alt.X("Slot:N", title=None, sort=None, axis=slot_axis(df["Slot"], every))
    y = alt.Y(f"{value_col}:Q", title=y_title, axis=alt.Axis(format=y_format))

    # Neviditelné sloupce přes celou výšku nesou tooltip, NT je podbarvený
    if nt_bands and "Tarif" in df:
        opacity = alt.condition("datum.Tarif == 'NT'", alt.value(0.10), alt.value(0.001))
        band_color = alt.value(BATTERY)
    else:
        opacity = alt.value(0.001)
        band_color = alt.value(ACCENT)
    bands = (
        alt.Chart(df).mark_bar(width={"band": 1})
        .encode(x=x, y="band_lo:Q", y2="band_hi:Q", color=band_color, opacity=opacity,
                tooltip=tooltip)
    )
    area = (
        alt.Chart(df).mark_area(interpolate="step-after", opacity=0.18, color=_gradient(stops))
        .encode(x=x, y=y)
    )
    glow = (
        alt.Chart(df).mark_line(interpolate="step-after", strokeWidth=7, opacity=0.18,
                                color=_gradient(stops))
        .encode(x=x, y=y)
    )
    line = (
        alt.Chart(df).mark_line(interpolate="step-after", strokeWidth=2.2, color=_gradient(stops))
        .encode(x=x, y=y)
    )
    layers = [bands, area, glow, line, *_day_layers(days), *_now_layers(now)]
    if df[value_col].min() < 0:
        layers.insert(1, alt.Chart(pd.DataFrame({"y": [0]})).mark_rule(
            color=INK_MUTED, strokeWidth=1, opacity=0.6).encode(y="y:Q"))
    return alt.layer(*layers).properties(height=height, width="container")


def multi_line_chart(
    df: pd.DataFrame,
    series: dict[str, str],
    y_title: str,
    now: datetime | None = None,
    y_format: str = ",.2f",
    height: int = 300,
) -> alt.LayerChart:
    """Více schodových čar se září (jako graf „Dnešní výkon" v SunnyHome).

    df: sloupec „Slot" + jeden sloupec na sérii; series = {sloupec: barva}.
    """
    long = df.melt(id_vars=["Slot"], value_vars=list(series), var_name="Série",
                   value_name="Hodnota")
    days = _day_keys(df["Slot"])
    every = 3 if len(days) == 1 else 6
    x = alt.X("Slot:N", title=None, sort=None, axis=slot_axis(df["Slot"], every))
    y = alt.Y("Hodnota:Q", title=y_title, axis=alt.Axis(format=y_format))
    color = alt.Color("Série:N", scale=alt.Scale(domain=list(series), range=list(series.values())),
                      legend=None)
    glow = (
        alt.Chart(long).mark_line(interpolate="step-after", strokeWidth=7, opacity=0.16)
        .encode(x=x, y=y, color=color)
    )
    line = (
        alt.Chart(long).mark_line(interpolate="step-after", strokeWidth=2)
        .encode(x=x, y=y, color=color)
    )
    # Neviditelné sloupce přes celou výšku nesou tooltip se všemi sériemi
    hover_df = df.assign(band_lo=min(0.0, long["Hodnota"].min()), band_hi=long["Hodnota"].max())
    hover = (
        alt.Chart(hover_df).mark_bar(width={"band": 1}, opacity=0.001)
        .encode(
            x=x, y="band_lo:Q", y2="band_hi:Q",
            tooltip=[alt.Tooltip("Slot:N", title="Čas"),
                     *[alt.Tooltip(f"{col}:Q", format=y_format) for col in series]],
        )
    )
    # Čára „teď“ neutrálně, aby se neplétla s barvami sérií
    now_rule = _now_layers(now, color="#cbd5e1")
    return alt.layer(glow, line, *_day_layers(days), *now_rule, hover).properties(
        height=height, width="container",
    )


def spot_price_chart(
    df: pd.DataFrame, day: date, now: datetime | None = None, height: int = 340,
) -> alt.LayerChart:
    """Průběh spotové ceny jednoho dne v CZK/MWh (dříve barevné sloupce)."""
    vals = df["Cena (CZK/MWh)"]
    p10, p30, p70, p90 = (vals.quantile(q) for q in (0.10, 0.30, 0.70, 0.90))
    df = df.assign(
        Slot=[slot_key(day, t) for t in df["Čas"]],
        Hladina=[
            LEVEL_NAMES[0] if v <= p10 else LEVEL_NAMES[1] if v <= p30 else
            LEVEL_NAMES[2] if v <= p70 else LEVEL_NAMES[3] if v <= p90 else LEVEL_NAMES[4]
            for v in vals
        ],
    )
    show_now = now if now is not None and now.date() == day else None
    return gradient_line_chart(
        df, "Cena (CZK/MWh)", "CZK/MWh",
        tooltip=[
            alt.Tooltip("Hodina:N", title="Čas"),
            alt.Tooltip("Cena (CZK/MWh):Q", title="CZK/MWh", format=",.0f"),
            alt.Tooltip("Cena (EUR/MWh):Q", title="EUR/MWh", format=",.2f"),
            alt.Tooltip("Hladina:N", title="Hladina"),
        ],
        now=show_now, height=height,
    )


def level_legend() -> str:
    return "".join(
        f"<span style='display:inline-flex;align-items:center;gap:6px;margin-right:14px;"
        f"color:{INK_MUTED};font-size:12px'><i style='width:14px;height:4px;border-radius:4px;"
        f"background:{c}'></i>{n}</span>"
        for n, c in zip(LEVEL_NAMES, LEVEL_RANGE)
    )


# ─── Aplikace ────────────────────────────────────────────────────────────────

PAGES = [
    # (funkce, titulek, ikona, url, podtitul)
    ("show_overview_page", "Přehled", ":material/dashboard:", "prehled",
     "Koncová cena, spot a počasí na jednom místě"),
    ("show_prices_tab", "Aktuální ceny", ":material/bolt:", "ceny",
     "Spotové ceny OTE po 15 minutách"),
    ("show_my_price_tab", "Moje cena", ":material/home:", "moje-cena",
     "Koncová cena podle tarifu Electree + ČEZ D25d"),
    ("show_trend_tab", "Vývoj cen", ":material/show_chart:", "vyvoj",
     "Měsíční průměry spotu"),
    ("show_analysis_tab", "Analýza", ":material/insights:", "analyza",
     "Vzorce, negativní ceny a trendy"),
    ("show_profiles_tab", "Profily & riziko", ":material/shield:", "profily",
     "Benchmark, kdy je spotřeba nejlevnější a volatilita"),
    ("show_forecast_tab", "Predikce", ":material/auto_awesome:", "predikce",
     "Dnes + 6 dní modelem s počasím a jeho přesnost"),
    ("show_weather_tab", "Počasí", ":material/partly_cloudy_day:", "pocasi",
     "Předpověď pro Kravaře a vliv na ceny"),
]

LOGO_SVG = f"""<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 240 48'>
<rect x='1' y='5' width='38' height='38' rx='10' fill='#0e1626' stroke='{BORDER}'/>
<g fill='none' stroke='{SOLAR}' stroke-width='2.4' stroke-linecap='round'>
<path d='M11 31a9 9 0 0 1 18 0'/><path d='M20 12v4M10 16l2.6 2.6M30 16l-2.6 2.6M8 26h3M29 26h3'/>
<path d='M12 36h16'/></g>
<text x='50' y='24' fill='#eef2f8' font-family='Poppins,Segoe UI,sans-serif' font-size='18'
 font-weight='600'>Spot Home</text>
<text x='50' y='40' fill='{INK_MUTED}' font-family='Poppins,Segoe UI,sans-serif'
 font-size='10.5'>Ceny elektřiny OTE · Kravaře</text></svg>"""


def main() -> None:
    st.set_page_config(page_title="OTE Spotové ceny", page_icon="⚡", layout="wide")
    inject_css()
    reset_cards()
    logo = "data:image/svg+xml;base64," + base64.b64encode(LOGO_SVG.encode()).decode()
    st.logo(logo, size="large")

    now = datetime.now(PRAGUE_TZ)
    next_refresh = next_refresh_time(now)

    # Obnova zarovnaná na xx:00:05, :15:05, :30:05, :45:05 – interval se přepočítá při každém běhu
    delay_ms = max(int((next_refresh - now).total_seconds() * 1000), 5000)
    st_autorefresh(interval=delay_ms, debounce=False, key="price_refresh")

    pages = {
        title: st.Page(globals()[func], title=title, icon=icon, url_path=url, default=i == 0)
        for i, (func, title, icon, url, _) in enumerate(PAGES)
    }
    nav = st.navigation(list(pages.values()), position="sidebar")
    subtitle = next(sub for _, title, *_, sub in PAGES if title == nav.title)
    page_header(
        nav.title, subtitle,
        chip(f"Aktualizováno {now:%H:%M:%S} · další obnova {next_refresh:%H:%M}", "clock"),
    )
    nav.run()


# ─── Přehled ─────────────────────────────────────────────────────────────────

def next_tariff_change(now: datetime) -> datetime:
    """Čas nejbližší změny NT ↔ VT."""
    from ote.tariff import is_low_tariff

    low = is_low_tariff(now.hour)
    t = now.replace(minute=0, second=0, microsecond=0)
    for _ in range(48):
        t += timedelta(hours=1)
        if is_low_tariff(t.hour) != low:
            return t
    return t


def price_flow_html(spot_kwh: float, low: bool, now: datetime) -> str:
    """Složení koncové ceny jako diagram toku (obdoba „Aktuální tok energie")."""
    from ote.tariff import (
        DISTRIBUTION_NT,
        DISTRIBUTION_VT,
        ELECTREE_FEE,
        ENERGY_TAX,
        SYSTEM_SERVICES,
        VAT,
    )

    spot_vat = spot_kwh * VAT
    distribution = DISTRIBUTION_NT if low else DISTRIBUTION_VT
    fees = ELECTREE_FEE + SYSTEM_SERVICES + ENERGY_TAX
    total = spot_vat + distribution + fees
    tariff_color = BATTERY if low else GRID
    change = next_tariff_change(now)

    def node(cls: str, color: str, icon: str, value: float, label: str, sub: str) -> str:
        return (
            f"<div class='pf-node {cls}' style='--c:{color}'>{icon_img(icon, color, 22)}"
            f"<b>{value:.2f}</b><span class='pf-unit'>Kč/kWh</span>"
            f"<span class='pf-sub'>{label}</span><span class='pf-sub2'>{sub}</span></div>"
        )

    return f"""
    <style>
      .pf {{ display:grid; grid-template-columns:1fr 34px auto 34px 1fr;
             grid-template-rows:auto 30px auto 30px auto; align-items:center; justify-items:center;
             max-width:560px; margin:10px auto 0; }}
      .pf-node {{ width:clamp(104px,24vw,150px); aspect-ratio:1; border-radius:50%;
                  border:4px solid var(--c); background:radial-gradient(circle at 50% 35%,
                  #16213a, #0e1626 70%); box-shadow:0 0 26px color-mix(in srgb,var(--c) 45%,
                  transparent), inset 0 0 18px color-mix(in srgb,var(--c) 22%, transparent);
                  display:flex; flex-direction:column; align-items:center; justify-content:center;
                  gap:1px; text-align:center; }}
      .pf-node b {{ font-size:clamp(17px,3.4vw,22px); font-weight:600; line-height:1.15;
                    margin-top:4px; }}
      .pf-unit {{ font-size:11px; color:{INK_MUTED}; }}
      .pf-sub {{ font-size:12px; margin-top:3px; border-top:1px solid #ffffff14; padding-top:3px; }}
      .pf-sub2 {{ font-size:11px; color:{INK_MUTED}; }}
      .pf-top {{ grid-area:1/3; }} .pf-bottom {{ grid-area:5/3; }}
      .pf-left {{ grid-area:3/1; }} .pf-right {{ grid-area:3/5; }}
      .pf-hub {{ grid-area:3/3; border:2.5px solid {ACCENT}; border-radius:16px;
                 background:#0e1626; padding:14px 16px; text-align:center;
                 box-shadow:0 0 28px {ACCENT}55, inset 0 0 14px {ACCENT}33; min-width:118px; }}
      .pf-hub b {{ display:block; font-size:clamp(22px,4.4vw,30px); font-weight:700;
                   line-height:1.1; margin-top:4px; }}
      .pf-hub span {{ font-size:11.5px; color:{INK_MUTED}; display:block; }}
      .pf-hub .pf-t {{ color:{tariff_color}; font-weight:600; font-size:12px; }}
      .pf-v {{ width:0; height:100%; border-left:2px dotted #5f6b84; }}
      .pf-h {{ height:0; width:100%; border-top:2px dotted #5f6b84; }}
      .pf-c1 {{ grid-area:2/3; }} .pf-c2 {{ grid-area:4/3; }}
      .pf-c3 {{ grid-area:3/2; }} .pf-c4 {{ grid-area:3/4; }}
      .pf-hub img {{ margin:0 auto; }}
      .pf-wrap {{ container-type:inline-size; }}
      @container (max-width: 480px) {{
        .pf {{ grid-template-columns:1fr 12px auto 12px 1fr; grid-template-rows:auto 18px auto
               18px auto; }}
        .pf-node {{ width:86px; height:86px; border-width:3px; }}
        .pf-node b {{ font-size:15px; margin-top:2px; }}
        .pf-node img {{ width:16px; height:16px; }}
        .pf-sub {{ font-size:10px; }} .pf-unit {{ font-size:9px; }} .pf-sub2 {{ display:none; }}
        .pf-hub {{ min-width:0; padding:10px 8px; }}
        .pf-hub b {{ font-size:20px; }}
      }}
    </style>
    <div class='pf-wrap'><div class='pf'>
      {node('pf-top', SOLAR, 'zap', spot_vat, 'Spot s DPH', f'{spot_kwh:.2f} bez DPH')}
      <div class='pf-v pf-c1'></div>
      {node('pf-left', tariff_color, 'clock', distribution, 'Distribuce ' + ('NT' if low else 'VT'),
            f"{'NT' if low else 'VT'} do {change:%H:%M}")}
      <div class='pf-h pf-c3'></div>
      <div class='pf-hub'>{icon_img('home', ACCENT_INK, 22)}<b>{total:.2f}</b>
        <span>Kč/kWh teď</span><span class='pf-t'>{'NÍZKÝ' if low else 'VYSOKÝ'} TARIF</span></div>
      <div class='pf-h pf-c4'></div>
      {node('pf-right', HOME, 'coins', fees, 'Poplatky a daň', 'Electree + služby')}
      <div class='pf-v pf-c2'></div>
      {node('pf-bottom', ACCENT_INK, 'pole', spot_vat + distribution, 'Energie + síť',
            'bez poplatků')}
    </div></div>
    """


def show_overview_page() -> None:
    from ote.tariff import compute_tariff_prices, is_low_tariff, sell_price_kwh

    now = datetime.now(PRAGUE_TZ)
    today = now.date()
    try:
        prices, _ = fetch_spot_prices(today)
    except Exception as e:
        st.error(f"Chyba při načítání dat: {e}")
        return
    try:
        tomorrow_prices, _ = fetch_spot_prices(today + timedelta(days=1))
    except Exception:
        tomorrow_prices = []
    if not prices:
        st.warning("Žádná data nejsou k dispozici.")
        return

    current = get_current_price(prices)
    days = [(today, prices)] + ([(today + timedelta(days=1), tomorrow_prices)]
                               if tomorrow_prices else [])
    rows = []
    for day, day_prices in days:
        for r in compute_tariff_prices([(p.time_from, p.price_czk) for p in day_prices]):
            rows.append({
                "Slot": slot_key(day, r.time_from),
                "Čas": f"{day:%d.%m.} {r.time_from:%H:%M}",
                "Nákup": r.total_kwh,
                "Prodej": sell_price_kwh(r.spot_kwh),
            })
    df = pd.DataFrame(rows)

    left, right = st.columns([1, 1.15], gap="medium")
    with left:
        with card("Složení ceny teď", "Spot, distribuce a poplatky · Electree + ČEZ D25d",
                  icon="activity", tone="accent"):
            if current is not None:
                st.html(price_flow_html(current.price_czk / 1000, is_low_tariff(now.hour), now))
                slot = (f"{current.time_from:%H:%M}–"
                        f"{current.time_from + timedelta(minutes=15):%H:%M}")
                st.html(
                    f"<div style='display:flex;gap:8px;flex-wrap:wrap;margin-top:14px'>"
                    f"{chip(f'Interval {slot}', 'clock')}"
                    f"{chip(f'Spot {current.price_czk:,.0f} CZK/MWh', 'zap')}</div>"
                )
            else:
                st.info("Aktuální cena není k dispozici.")

    with right:
        period = "Dnes a zítra" if tomorrow_prices else "Dnes"
        with card("Průběh cen", "Moje nákupní a prodejní cena v Kč/kWh",
                  icon="line", tone="accent", aside=pill(period, "muted")):
            series = {"Nákup": READOUT, "Prodej": BATTERY}
            show_chart(multi_line_chart(df, series, "Kč/kWh", now=now, height=300))
            now_slot = slot_key(today, now.replace(minute=now.minute // 15 * 15))
            now_row = df[df["Slot"] == now_slot]
            # Nejvýhodnější = nejlevnější nákup a nejvyšší prodej
            best_buy = df.loc[df["Nákup"].idxmin()]
            best_sell = df.loc[df["Prodej"].idxmax()]
            table_rows = [
                {"color": READOUT, "label": "Nákup", "note": "s DPH a distribucí",
                 "now": f"{now_row['Nákup'].iloc[0]:.2f} Kč" if not now_row.empty else "—",
                 "now_time": f"{now:%H:%M}",
                 "peak": f"{best_buy['Nákup']:.2f} Kč", "peak_time": best_buy["Čas"]},
                {"color": BATTERY, "label": "Prodej", "note": "spot − poplatek",
                 "now": f"{now_row['Prodej'].iloc[0]:.2f} Kč" if not now_row.empty else "—",
                 "now_time": f"{now:%H:%M}",
                 "peak": f"{best_sell['Prodej']:.2f} Kč", "peak_time": best_sell["Čas"]},
            ]
            st.html(readout_table(table_rows, ("Teď", "Nejvýhodněji")))
            st.caption("Nákup = koncová cena s DPH, poplatky a distribucí NT/VT. "
                       "Prodej = spot bez DPH − 499 Kč/MWh Electree (distribuce se u prodeje "
                       "neplatí). Nejvýhodněji = nejlevnější nákup a nejvyšší prodej.")

    show_sell_card(now, prices, tomorrow_prices, current, height=240)

    show_three_hour_weather_card()

    totals = df["Nákup"]
    today_df = df[df["Slot"].str.startswith(f"{today:%d.%m.}")]
    cheapest = today_df.loc[today_df["Nákup"].idxmin()]
    priciest = today_df.loc[today_df["Nákup"].idxmax()]
    with card("Dnešní souhrn", "Nákupní cena s DPH a distribucí", icon="calendar",
              tone="solar"):
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Průměr dnes", f"{today_df['Nákup'].mean():.2f} Kč/kWh")
        c2.metric("Nejlevněji", f"{cheapest['Nákup']:.2f} Kč/kWh",
                  help=f"Čtvrthodina {cheapest['Čas']}")
        c3.metric("Nejdráž", f"{priciest['Nákup']:.2f} Kč/kWh",
                  help=f"Čtvrthodina {priciest['Čas']}")
        c4.metric("Průměr zítra",
                  f"{totals[~df['Slot'].isin(today_df['Slot'])].mean():.2f} Kč/kWh"
                  if tomorrow_prices else "—",
                  help=None if tomorrow_prices else "Ceny na zítřek budou po 13:10")
        st.caption(f"Nejlevnější čtvrthodina dnes {cheapest['Čas']}, nejdražší {priciest['Čas']}.")


# ─── Aktuální ceny ───────────────────────────────────────────────────────────

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


def price_kpis(values: pd.Series, current: SpotPrice | None = None) -> None:
    cols = st.columns(5 if current is not None else 4)
    i = 0
    if current is not None:
        cols[0].metric("Aktuální cena", f"{current.price_czk:,.0f} CZK/MWh",
                       help=f"{current.time_from:%H:%M}–{current.time_to:%H:%M}")
        i = 1
    cols[i].metric("Minimum", f"{values.min():,.0f} CZK/MWh")
    cols[i + 1].metric("Maximum", f"{values.max():,.0f} CZK/MWh")
    cols[i + 2].metric("Průměr", f"{values.mean():,.0f} CZK/MWh")
    cols[i + 3].metric("Rozpětí", f"{values.max() - values.min():,.0f} CZK/MWh",
                       help="Max − Min za den")


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
    now = datetime.now(PRAGUE_TZ)

    with card("Spotová cena", f"{selected_date:%d. %m. %Y} · 15min intervaly OTE",
              icon="zap", tone="solar", aside=pill(f"1 EUR = {eur_czk_rate:.3f} CZK", "muted")):
        price_kpis(df["Cena (CZK/MWh)"], current if selected_date == now.date() else None)
        show_chart(spot_price_chart(df, selected_date, now=now))
        st.html(level_legend())

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

    with card("Spotová cena z historie", f"{selected_date:%d. %m. %Y}", icon="history",
              tone="solar", aside=pill(f"1 EUR = {stats['eur_czk_rate']:.3f} CZK", "muted")):
        price_kpis(df["Cena (CZK/MWh)"])
        show_chart(spot_price_chart(df, selected_date))
        st.html(level_legend())

    # Porovnání posledních 30 dnů
    if len(dates) > 1:
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
            with card("Vývoj průměrných cen", "Posledních 30 dní, pásmo = min–max dne",
                      icon="line", tone="accent"):
                show_chart(range_line_chart(compare_df, "Datum:T", "CZK/MWh", ACCENT,
                                            date_format="%d.%m.%Y", height=280))

    conn.close()


def range_line_chart(
    df: pd.DataFrame, x_field: str, y_title: str, color: str,
    date_format: str = "%d.%m.", height: int = 260, label_field: str | None = None,
) -> alt.LayerChart:
    """Průměr jako zářící čára s bodem, pásmo min–max (sloupce Průměr, Min, Max)."""
    x = alt.X(x_field, title=None,
              axis=alt.Axis(format=date_format, tickCount="day") if x_field.endswith(":T")
              else alt.Axis(labelAngle=0))
    tooltip = [
        alt.Tooltip(label_field or x_field, title="Den",
                    **({"format": date_format} if x_field.endswith(":T") and not label_field
                       else {})),
        alt.Tooltip("Průměr:Q", title="Průměr", format=",.0f"),
        alt.Tooltip("Min:Q", title="Min", format=",.0f"),
        alt.Tooltip("Max:Q", title="Max", format=",.0f"),
    ]
    band = (
        alt.Chart(df).mark_area(opacity=0.14, color=color)
        .encode(x=x, y=alt.Y("Min:Q", title=y_title, axis=alt.Axis(format=",.0f")),
                y2=alt.Y2("Max:Q"))
    )
    glow = alt.Chart(df).mark_line(color=color, strokeWidth=7, opacity=0.18).encode(
        x=x, y="Průměr:Q")
    line = alt.Chart(df).mark_line(color=color, strokeWidth=2.4).encode(
        x=x, y="Průměr:Q", tooltip=tooltip)
    points = alt.Chart(df).mark_point(filled=True, size=46, color=color).encode(
        x=x, y="Průměr:Q", tooltip=tooltip)
    return alt.layer(band, glow, line, points).properties(height=height, width="container")


# ─── Moje cena ───────────────────────────────────────────────────────────────

def tariff_df(prices: list[SpotPrice], day: date) -> pd.DataFrame:
    """Spotové a koncové ceny v Kč/kWh po 15min intervalech."""
    from ote.tariff import compute_tariff_prices

    rows = compute_tariff_prices([(p.time_from, p.price_czk) for p in prices])
    return pd.DataFrame([
        {
            "Slot": slot_key(day, r.time_from),
            "Hodina": slot_label(r.time_from),
            "Čas": f"{day:%d.%m.} {r.time_from:%H:%M}",
            "Spot (Kč/kWh)": r.spot_kwh,
            "Tarif": "NT" if r.is_low_tariff else "VT",
            "Celkem (Kč/kWh)": r.total_kwh,
        }
        for r in rows
    ])


LEVEL_COLORS = {"nízká": BATTERY, "normální": SOLAR, "vysoká": GRID}
LEVEL_TONES = {"nízká": "battery", "normální": "solar", "vysoká": "grid"}
WEEKDAY_SHORT = ["po", "út", "st", "čt", "pá", "so", "ne"]
WEEKDAY_CZ = ["Po", "Út", "St", "Čt", "Pá", "So", "Ne"]
WEEKDAY_FULL = ["Pondělí", "Úterý", "Středa", "Čtvrtek", "Pátek", "Sobota", "Neděle"]


def show_week_comparison(current: SpotPrice, total: float, low: bool) -> None:
    """Koncová cena teď vs. stejná čtvrthodina (stejný den v týdnu) před 1 a 2 týdny."""
    from ote.db import get_price_at
    from ote.tariff import czk_mwh_to_kwh, price_level, total_price_kwh

    conn = get_connection()
    past = []
    for weeks in (1, 2):
        # Stejný lokální čas – přes změnu času se porovnává podle hodin na zdi
        time_from = current.time_from.replace(fold=0) - timedelta(weeks=weeks)
        price = get_price_at(conn, time_from)
        past_total = (
            total_price_kwh(czk_mwh_to_kwh(price), low) if price is not None else None
        )
        past.append((weeks, time_from, past_total))
    conn.close()

    level = price_level(total, [t for _, _, t in past if t is not None])
    with card("Srovnání s minulými týdny", "Stejný den v týdnu a stejná čtvrthodina",
              icon="history", tone="home",
              aside=pill(f"cena {level}", LEVEL_TONES[level]) if level else None):
        cols = st.columns(3)
        for col, (weeks, time_from, past_total) in zip(cols, past):
            label = (
                f"Před {'týdnem' if weeks == 1 else '2 týdny'} "
                f"({WEEKDAY_SHORT[time_from.weekday()]} {time_from:%d.%m. %H:%M})"
            )
            with col:
                if past_total is None:
                    st.metric(label, "—", help="Pro tento interval nejsou v historii data")
                else:
                    diff = total - past_total
                    pct = diff / past_total * 100 if past_total else 0.0
                    st.metric(
                        label, f"{past_total:.2f} Kč/kWh",
                        delta=f"{diff:+.2f} Kč/kWh ({pct:+.0f} %)",
                        delta_color="inverse",
                    )
        with cols[2]:
            if level:
                st.html(status_box("Vůči minulým týdnům", level.upper(),
                                   f"teď {total:.2f} Kč/kWh", LEVEL_TONES[level]))
            else:
                st.metric("Hodnocení", "—", help="Chybí data z minulých týdnů")
        st.caption(
            "Koncová cena s DPH a distribucí; šipka = o kolik je cena teď vyšší/nižší. "
            "Starší ceny přepočteny dnešním ceníkem, rozdíl je tedy jen ve spotu. "
            "Vysoká/nízká = o více než 15 % nad/pod průměrem obou týdnů."
        )


def final_price_chart(
    days: list[tuple[date, list[SpotPrice]]], now: datetime, height: int = 320,
) -> alt.LayerChart:
    """Schodový graf koncové ceny (NT/VT) přes dnešek a zítřek, NT podbarvený."""
    df = pd.concat([tariff_df(p, d) for d, p in days], ignore_index=True)
    return gradient_line_chart(
        df, "Celkem (Kč/kWh)", "Kč/kWh",
        tooltip=[
            alt.Tooltip("Čas:N", title="Čas"),
            alt.Tooltip("Tarif:N", title="Tarif"),
            alt.Tooltip("Celkem (Kč/kWh):Q", title="Koncová cena", format=",.2f"),
            alt.Tooltip("Spot (Kč/kWh):Q", title="Spot bez DPH", format=",.2f"),
        ],
        now=now, nt_bands=True, y_format=",.0f", height=height,
    )


def show_final_price_card(
    now: datetime, prices: list[SpotPrice], tomorrow_prices: list[SpotPrice],
    current: SpotPrice | None,
) -> None:
    """Karta „Ceny elektřiny": velká aktuální koncová cena + graf NT/VT na dnes a zítra."""
    from ote.tariff import compute_tariff_prices, czk_mwh_to_kwh, is_low_tariff, total_price_kwh

    days = [(now.date(), prices)]
    if tomorrow_prices:
        days.append((now.date() + timedelta(days=1), tomorrow_prices))
    totals = pd.Series([
        r.total_kwh
        for _, day_prices in days
        for r in compute_tariff_prices([(p.time_from, p.price_czk) for p in day_prices])
    ])

    period = "Dnes a zítra" if tomorrow_prices else "Dnes"
    with card("Ceny elektřiny", "Koncová cena s DPH a distribucí", icon="coins",
              tone="readout", aside=pill(period, "muted")):
        if current is not None:
            low = is_low_tariff(now.hour)
            total = total_price_kwh(czk_mwh_to_kwh(current.price_czk), low)
            badge = price_color(total, *totals.quantile([0.10, 0.30, 0.70, 0.90]))
            tariff = pill("NT", "battery") if low else pill("VT", "grid")
            st.html(
                f"<div style='margin-top:6px;color:{INK_MUTED};font-size:14px;display:flex;"
                f"align-items:center;gap:8px'>Nyní {tariff} s DPH a distribucí</div>"
                f"<div style='display:inline-block;margin:6px 0;padding:2px 18px;"
                f"background:{badge};color:#0b1220;border-radius:12px;font-size:2.6rem;"
                f"font-weight:700;line-height:1.25;box-shadow:0 0 30px {badge}55'>"
                f"{total:.2f} Kč/kWh</div>"
                f"<div style='color:{INK_MUTED};font-size:14px'>Min {totals.min():.2f} Kč/kWh "
                f"· Max {totals.max():.2f} Kč/kWh</div>"
            )
        show_chart(final_price_chart(days, now))
        st.caption("Zeleně podbarvený je nízký tarif (NT), oranžová čárkovaná čára = teď.")


def show_sell_card(
    now: datetime, prices: list[SpotPrice], tomorrow_prices: list[SpotPrice],
    current: SpotPrice | None, height: int = 280,
) -> None:
    """Karta „Prodej": za kolik teď prodávám do sítě (spot bez DPH − poplatek Electree)."""
    from ote.tariff import SELL_FEE, czk_mwh_to_kwh, sell_price_kwh

    days = [(now.date(), prices)]
    if tomorrow_prices:
        days.append((now.date() + timedelta(days=1), tomorrow_prices))
    df = pd.DataFrame([
        {
            "Slot": slot_key(day, p.time_from),
            "Čas": f"{day:%d.%m.} {p.time_from:%H:%M}",
            "Spot (Kč/kWh)": czk_mwh_to_kwh(p.price_czk),
            "Výkup (Kč/kWh)": sell_price_kwh(czk_mwh_to_kwh(p.price_czk)),
        }
        for day, day_prices in days for p in day_prices
    ])
    sells = df["Výkup (Kč/kWh)"]
    best = df.loc[sells.idxmax()]
    negative = int((sells < 0).sum())

    period = "Dnes a zítra" if tomorrow_prices else "Dnes"
    with card("Prodej", f"Výkup do sítě · spot bez DPH − {SELL_FEE * 1000:.0f} Kč/MWh Electree",
              icon="sun", tone="battery", aside=pill(period, "muted")):
        if current is not None:
            spot = czk_mwh_to_kwh(current.price_czk)
            sell = sell_price_kwh(spot)
            # Barva podle hladiny výkupu: nahoře zelená, záporná cena červená
            q30, q70 = sells.quantile([0.30, 0.70])
            badge = GRID if sell < 0 else BATTERY if sell >= q70 else SOLAR if sell >= q30 \
                else READOUT
            note = ("teď se prodávat nevyplatí – za dodávku do sítě se platí" if sell < 0
                    else f"spot {spot:.2f} − poplatek {SELL_FEE:.3f} Kč/kWh")
            st.html(
                f"<div style='margin-top:6px;color:{INK_MUTED};font-size:14px'>Teď prodávám za"
                f"</div><div style='display:inline-block;margin:6px 0;padding:2px 18px;"
                f"background:{badge};color:#0b1220;border-radius:12px;font-size:2.6rem;"
                f"font-weight:700;line-height:1.25;box-shadow:0 0 30px {badge}55'>"
                f"{sell:.2f} Kč/kWh</div>"
                f"<div style='color:{INK_MUTED};font-size:14px'>{note}</div>"
            )
        c1, c2, c3 = st.columns(3)
        c1.metric("Nejvíc", f"{best['Výkup (Kč/kWh)']:.2f} Kč/kWh",
                  help=f"Čtvrthodina {best['Čas']}")
        c2.metric("Nejméně", f"{sells.min():.2f} Kč/kWh",
                  help=f"Čtvrthodina {df.loc[sells.idxmin(), 'Čas']}")
        c3.metric("Záporný výkup", f"{negative} × 15 min",
                  help="Čtvrthodiny, kdy by se za dodávku do sítě platilo")
        show_chart(gradient_line_chart(
            df, "Výkup (Kč/kWh)", "Kč/kWh",
            tooltip=[alt.Tooltip("Čas:N", title="Čas"),
                     alt.Tooltip("Výkup (Kč/kWh):Q", title="Výkup", format=",.2f"),
                     alt.Tooltip("Spot (Kč/kWh):Q", title="Spot bez DPH", format=",.2f")],
            now=now, y_format=",.1f", height=height, stops=SELL_STOPS,
        ))
        st.caption(f"Nejlépe se prodává {best['Čas']}. Poplatek Electree za služby obchodu "
                   f"{SELL_FEE * 1000:.0f} Kč/MWh s DPH se odečítá od spotu bez DPH.")


def show_my_price_tab() -> None:
    from ote.tariff import (
        DISTRIBUTION_NT,
        DISTRIBUTION_VT,
        ELECTREE_FEE,
        ENERGY_TAX,
        SYSTEM_SERVICES,
        czk_mwh_to_kwh,
        high_tariff_price,
        is_low_tariff,
        low_tariff_price,
    )

    now = datetime.now(PRAGUE_TZ)
    today = now.date()

    with st.spinner("Načítám ceny z OTE..."):
        try:
            prices, _ = fetch_spot_prices(today)
        except Exception as e:
            st.error(f"Chyba při načítání dat: {e}")
            return
        try:
            tomorrow_prices, _ = fetch_spot_prices(today + timedelta(days=1))
        except Exception:
            tomorrow_prices = []

    if not prices:
        st.warning("Žádná data nejsou k dispozici.")
        return

    df_today = tariff_df(prices, today)
    df_tomorrow = (
        tariff_df(tomorrow_prices, today + timedelta(days=1)) if tomorrow_prices else None
    )
    current = get_current_price(prices)

    # ── Karta s koncovou cenou NT/VT ──
    show_final_price_card(now, prices, tomorrow_prices, current)
    show_sell_card(now, prices, tomorrow_prices, current)

    # ── Přehled cen ──
    slot = (
        f"{current.time_from:%H:%M}–{current.time_from + timedelta(minutes=15):%H:%M}"
        if current else None
    )
    spot = czk_mwh_to_kwh(current.price_czk) if current else None
    low = is_low_tariff(now.hour)
    total = None
    if spot is not None:
        total = low_tariff_price(spot) if low else high_tariff_price(spot)
    with card("Přehled cen", f"Ceny platí pro interval {slot or '—'}", icon="gauge",
              tone="solar"):
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Spot", f"{spot:.2f} Kč/kWh" if spot is not None else "—",
                      help="Aktuální spotová cena bez DPH")
        with col2:
            st.metric("Nízký tarif",
                      f"{low_tariff_price(spot):.2f} Kč/kWh" if spot is not None else "—")
        with col3:
            st.metric("Vysoký tarif",
                      f"{high_tariff_price(spot):.2f} Kč/kWh" if spot is not None else "—")

        if total is not None:
            st.html(status_box(
                f"{slot} platí", "NÍZKÝ TARIF" if low else "VYSOKÝ TARIF",
                f"{total:.2f} Kč/kWh · změna v {next_tariff_change(now):%H:%M}",
                "battery" if low else "grid",
            ))

        col1, col2 = st.columns(2)
        with col1:
            st.metric("Průměr spotu dnes", f"{df_today['Spot (Kč/kWh)'].mean():.2f} Kč/kWh")
        with col2:
            if df_tomorrow is not None:
                st.metric("Průměr spotu zítra",
                          f"{df_tomorrow['Spot (Kč/kWh)'].mean():.2f} Kč/kWh")
            else:
                st.metric("Průměr spotu zítra", "—",
                          help="Ceny zítra budou k dispozici po 13:10")

    # ── Srovnání se stejnou čtvrthodinou před 1 a 2 týdny ──
    if current is not None and total is not None:
        show_week_comparison(current, total, low)

    # ── Spot dnes a zítra ──
    df_spot = pd.concat([d for d in (df_today, df_tomorrow) if d is not None], ignore_index=True)
    with card("Spot", "Spotová cena bez DPH v Kč/kWh", icon="zap", tone="solar",
              aside=pill("Dnes a zítra" if df_tomorrow is not None else "Dnes", "muted")):
        show_chart(gradient_line_chart(
            df_spot, "Spot (Kč/kWh)", "Kč/kWh",
            tooltip=[alt.Tooltip("Čas:N", title="Čas"),
                     alt.Tooltip("Spot (Kč/kWh):Q", title="Spot", format=",.2f")],
            now=now, y_format=",.1f", height=280,
        ))
        if df_tomorrow is None:
            st.caption("Ceny zítra budou k dispozici po 13:10.")

    with st.expander("Jak se cena počítá"):
        st.markdown(
            f"""
            **Celkem = spot × 1,21 (DPH) + poplatek Electree + distribuce + systémové služby
            + daň z elektřiny**

            | Složka | Kč/kWh |
            |--------|-------:|
            | Poplatek Electree (odběr ze spotu) | {ELECTREE_FEE:.4f} |
            | Distribuce VT (D25d, ČEZ 2026) | {DISTRIBUTION_VT:.5f} |
            | Distribuce NT (D25d, ČEZ 2026) | {DISTRIBUTION_NT:.5f} |
            | Systémové služby | {SYSTEM_SERVICES:.5f} |
            | Daň z elektřiny | {ENERGY_TAX:.5f} |

            Nízký tarif: 00:00–06:00 a 19:00–21:00, jinak vysoký tarif.
            """
        )

    with st.expander("Tabulka dat"):
        st.dataframe(
            df_today[["Hodina", "Tarif", "Spot (Kč/kWh)", "Celkem (Kč/kWh)"]],
            use_container_width=True, hide_index=True,
            column_config={
                "Spot (Kč/kWh)": st.column_config.NumberColumn(format="%.2f"),
                "Celkem (Kč/kWh)": st.column_config.NumberColumn(format="%.2f"),
            },
        )


# ─── Vývoj cen ───────────────────────────────────────────────────────────────

MONTH_NAMES = [
    "Leden", "Únor", "Březen", "Duben", "Květen", "Červen",
    "Červenec", "Srpen", "Září", "Říjen", "Listopad", "Prosinec",
]


def hour_line_chart(
    df: pd.DataFrame, x_field: str, y_field: str, y_title: str, color: str,
    tooltip: list, height: int = 220, area: bool = True, y_format: str = ",.0f",
    interpolate: str = "monotone",
) -> alt.LayerChart:
    """Jedna zářící čára (volitelně s plochou) přes hodiny dne nebo jiné kategorie."""
    x = alt.X(x_field, title=None, sort=None, axis=alt.Axis(labelAngle=0))
    y = alt.Y(y_field, title=y_title, axis=alt.Axis(
        format=y_format, tickMinStep=1 if y_format == "d" else alt.Undefined))
    layers = []
    if area:
        layers.append(alt.Chart(df).mark_area(color=alt.Gradient(
            gradient="linear", x1=1, x2=1, y1=1, y2=0,
            stops=[alt.GradientStop(color=f"{color}00", offset=0),
                   alt.GradientStop(color=f"{color}55", offset=1)],
        ), interpolate=interpolate).encode(x=x, y=y))
    layers += [
        alt.Chart(df).mark_line(color=color, strokeWidth=7, opacity=0.18,
                                interpolate=interpolate).encode(x=x, y=y),
        alt.Chart(df).mark_line(color=color, strokeWidth=2.2, interpolate=interpolate,
                                point=alt.OverlayMarkDef(filled=True, size=30, color=color))
        .encode(x=x, y=y, tooltip=tooltip),
    ]
    return alt.layer(*layers).properties(height=height, width="container")


def show_trend_tab() -> None:
    from ote.db import get_available_years, get_monthly_stats

    conn = get_connection()
    years = get_available_years(conn)

    if not years:
        st.warning("Databáze je prázdná.")
        conn.close()
        return

    year = st.segmented_control(
        "Rok", options=years, default=years[0], key="trend_year",
        format_func=str,
    ) or years[0]

    stats = get_monthly_stats(conn, year)
    ly_stats = {m.month: m for m in get_monthly_stats(conn, year - 1)}
    conn.close()

    if not stats:
        st.info(f"Pro rok {year} nejsou v databázi žádná data.")
        return

    total_intervals = sum(s.intervals for s in stats)
    year_avg = sum(s.avg_price * s.intervals for s in stats) / total_intervals
    cheapest = min(stats, key=lambda s: s.avg_price)
    priciest = max(stats, key=lambda s: s.avg_price)
    days = sum(s.days for s in stats)

    # ── Základní údaje ──
    first, last = stats[0].month, stats[-1].month
    coverage = (
        f"Data pokrývají {MONTH_NAMES[first - 1].lower()} – {MONTH_NAMES[last - 1].lower()} "
        f"{year}; průměr roku je jen z těchto měsíců." if len(stats) < 12 else "Celý rok"
    )
    with card(f"Rok {year}", coverage, icon="calendar", tone="solar"):
        col1, col2, col3, col4, col5 = st.columns(5)
        with col1:
            st.metric("Průměr roku", f"{year_avg:,.0f} CZK/MWh",
                      help=f"{year_avg / 1000:.2f} Kč/kWh bez DPH, vážený přes všechny intervaly")
        with col2:
            st.metric("Nejlevnější měsíc", MONTH_NAMES[cheapest.month - 1],
                      help=f"{cheapest.avg_price:,.0f} CZK/MWh")
        with col3:
            st.metric("Nejdražší měsíc", MONTH_NAMES[priciest.month - 1],
                      help=f"{priciest.avg_price:,.0f} CZK/MWh")
        with col4:
            st.metric("Dnů s daty", days, help=f"Měsíců s daty: {len(stats)} z 12")
        with col5:
            st.metric("Negativní intervaly", f"{sum(s.negative_count for s in stats):,}",
                      help="Počet 15min intervalů se zápornou cenou")

    # ── Graf ──
    month_df = pd.DataFrame([
        {
            "Měsíc": MONTH_NAMES[s.month - 1],
            "Průměr": s.avg_price,
            "Kč/kWh": s.avg_price / 1000,
            "Min": s.min_price,
            "Max": s.max_price,
            "Dnů": s.days,
            "Negativní intervaly": s.negative_count,
            "LY": ly_stats[s.month].avg_price if s.month in ly_stats else None,
            "Změna vs LY (%)": (
                (s.avg_price / ly_stats[s.month].avg_price - 1) * 100
                if s.month in ly_stats and ly_stats[s.month].avg_price else None
            ),
        }
        for s in stats
    ])

    cy, ly = str(year), str(year - 1)
    chart_df = pd.concat([
        pd.DataFrame([
            {"Měsíc": MONTH_NAMES[m.month - 1], "Rok": ly, "Průměr": m.avg_price,
             "Dnů": m.days, "Změna vs LY (%)": None}
            for m in ly_stats.values()
        ]),
        month_df[["Měsíc", "Průměr", "Dnů", "Změna vs LY (%)"]].assign(Rok=cy),
    ], ignore_index=True)

    x = alt.X("Měsíc:N", title=None, sort=MONTH_NAMES,
              scale=alt.Scale(domain=MONTH_NAMES), axis=alt.Axis(labelAngle=0))
    y = alt.Y("Průměr:Q", title="CZK/MWh", axis=alt.Axis(format=",.0f"))
    color = alt.Color("Rok:N", scale=alt.Scale(domain=[ly, cy], range=["#5f6b84", ACCENT]),
                      legend=alt.Legend(title=None, orient="top"))
    dash = alt.StrokeDash("Rok:N", scale=alt.Scale(domain=[ly, cy], range=[[5, 4], [1, 0]]),
                          legend=None)
    tooltip = [
        alt.Tooltip("Měsíc:N"), alt.Tooltip("Rok:N"),
        alt.Tooltip("Průměr:Q", title="Průměr CZK/MWh", format=",.0f"),
        alt.Tooltip("Dnů:Q"), alt.Tooltip("Změna vs LY (%):Q", format="+.1f"),
    ]
    base = alt.Chart(chart_df)
    glow = base.mark_line(strokeWidth=8, opacity=0.16).encode(x=x, y=y, color=color)
    lines = base.mark_line(strokeWidth=2.4).encode(x=x, y=y, color=color, strokeDash=dash)
    points = base.mark_point(filled=True, size=60).encode(x=x, y=y, color=color,
                                                           tooltip=tooltip)
    labels = (
        alt.Chart(chart_df[chart_df["Rok"] == cy])
        .mark_text(dy=-14, fontSize=11, color="#eef2f8")
        .encode(x=x, y="Průměr:Q", text=alt.Text("Průměr:Q", format=",.0f"))
    )
    avg_rule = (
        alt.Chart(pd.DataFrame({"Průměr roku": [year_avg]}))
        .mark_rule(color=READOUT, strokeDash=[6, 4], strokeWidth=1.6)
        .encode(y="Průměr roku:Q", tooltip=[alt.Tooltip("Průměr roku:Q", format=",.0f")])
    )

    common = [m for m in month_df.itertuples() if m.LY is not None and not pd.isna(m.LY)]
    if not ly_stats:
        note = (f"Oranžová čára = průměr roku {year}. Pro rok {year - 1} nejsou v databázi "
                f"data, porovnání vs LY zatím není k dispozici.")
    else:
        note = (f"Oranžová čára = průměr roku {year}. Čárkovaně = {year - 1}, "
                f"porovnání je k dispozici pro {len(common)} "
                f"{'měsíc' if len(common) == 1 else 'měsíce' if len(common) < 5 else 'měsíců'}.")
    with card("Průměrná cena podle měsíců", f"{year} vs {year - 1}", icon="line", tone="accent"):
        show_chart(alt.layer(glow, lines, points, labels, avg_rule)
                   .properties(height=360, width="container"))
        st.caption(note)

    with st.expander("Tabulka po měsících"):
        st.dataframe(
            month_df,
            use_container_width=True, hide_index=True,
            column_config={
                "Průměr": st.column_config.NumberColumn("Průměr (CZK/MWh)", format="%.0f"),
                "Kč/kWh": st.column_config.NumberColumn("Průměr (Kč/kWh)", format="%.2f"),
                "Min": st.column_config.NumberColumn("Min (CZK/MWh)", format="%.0f"),
                "Max": st.column_config.NumberColumn("Max (CZK/MWh)", format="%.0f"),
                "LY": st.column_config.NumberColumn(f"{year - 1} (CZK/MWh)", format="%.0f"),
                "Změna vs LY (%)": st.column_config.NumberColumn(format="%+.1f %%"),
            },
        )


# ─── Analýza ─────────────────────────────────────────────────────────────────

LEVEL_TONE_BY_NAME = {
    "velmi levná": "battery", "levná": "battery", "normální": "solar",
    "drahá": "readout", "velmi drahá": "grid",
}


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
        get_price_trend,
        get_weekday_hour_heatmap_data,
        get_worst_hours,
    )

    # ── Aktuální cenová hladina + průměr podle hodiny ──
    left, right = st.columns([1, 2], gap="medium")
    with left:
        with card("Cenová hladina", "Aktuální spot vůči posledním 30 dnům", icon="gauge",
                  tone="solar"):
            try:
                prices, _ = fetch_spot_prices(date.today())
                current = get_current_price(prices)
                if current:
                    classification = classify_price(current.price_czk, conn)
                    st.metric("Aktuální cena", f"{current.price_czk:,.0f} CZK/MWh")
                    st.html(status_box(
                        "Hladina", classification.upper(),
                        f"interval {current.time_from:%H:%M}",
                        LEVEL_TONE_BY_NAME.get(classification, "muted"),
                    ))
                else:
                    st.info("Aktuální cena není k dispozici.")
            except Exception:
                st.info("Nelze načíst aktuální cenu z API.")

    with right:
        patterns = get_hourly_patterns(conn, days_back=30)
        with card("Průměrné ceny podle hodiny", "Posledních 30 dní, pásmo = min–max",
                  icon="activity", tone="accent"):
            if patterns:
                pattern_df = pd.DataFrame([
                    {"Hodina": p.hour, "Průměr": p.avg_price, "Min": p.min_price,
                     "Max": p.max_price}
                    for p in patterns
                ])
                show_chart(range_line_chart(pattern_df, "Hodina:O", "CZK/MWh", ACCENT,
                                            height=250, label_field="Hodina:O"))

    # Nejlevnější / nejdražší hodiny
    col1, col2 = st.columns(2, gap="medium")
    with col1:
        with card("Nejlevnější hodiny", "Průměr za 30 dní", icon="down", tone="battery"):
            best = get_best_hours(conn, top_n=5)
            st.html(rank_list([(f"{h:02d}:00", f"{p:,.0f} CZK") for h, p in best], "battery"))
    with col2:
        with card("Nejdražší hodiny", "Průměr za 30 dní", icon="up", tone="grid"):
            worst = get_worst_hours(conn, top_n=5)
            st.html(rank_list([(f"{h:02d}:00", f"{p:,.0f} CZK") for h, p in worst], "grid"))

    # ── Týdenní heatmapa ──
    if days_count >= 14:
        heatmap_data = get_weekday_hour_heatmap_data(conn, days_back=60)
        if heatmap_data:
            heatmap_df = pd.DataFrame(heatmap_data)
            heatmap = (
                alt.Chart(heatmap_df)
                .mark_rect(cornerRadius=4, stroke="#111a2e", strokeWidth=2)
                .encode(
                    x=alt.X("hour:O", title="Hodina", axis=alt.Axis(labelAngle=0, grid=False)),
                    y=alt.Y("weekday_name:O", title=None,
                            sort=["Po", "Út", "St", "Čt", "Pá", "So", "Ne"],
                            axis=alt.Axis(labelFontSize=12, grid=False)),
                    color=alt.Color(
                        "avg_price:Q", title="CZK/MWh",
                        scale=alt.Scale(range=LEVEL_RANGE),
                        legend=alt.Legend(gradientLength=220, orient="bottom",
                                          direction="horizontal"),
                    ),
                    tooltip=[
                        alt.Tooltip("weekday_name:O", title="Den"),
                        alt.Tooltip("hour:O", title="Hodina"),
                        alt.Tooltip("avg_price:Q", title="Průměr CZK/MWh", format=",.0f"),
                    ],
                )
                .properties(height=250, width="container")
            )
            with card("Heatmapa: hodina × den v týdnu", "Průměrná cena za 60 dní",
                      icon="table", tone="readout"):
                show_chart(heatmap)

    # ── Negativní ceny ──
    neg_stats_30 = get_negative_price_stats(conn, days_back=30)
    neg_stats_7 = get_negative_price_stats(conn, days_back=7)
    with card("Negativní ceny", "Hodiny se zápornou cenou", icon="down", tone="battery"):
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
            st.html(status_box("Zítra", "Riziko negativních cen", f"kolem {hours_str}",
                               "battery"))

        hours_dist = neg_stats_30.hours_distribution
        if hours_dist:
            # Všechny hodiny dne, aby čára nespojovala vzdálené hodiny přes mezeru
            dist_df = pd.DataFrame([
                {"Hodina": h, "Počet": hours_dist.get(h, 0)} for h in range(24)
            ])
            st.caption("Typické hodiny s negativními cenami")
            show_chart(hour_line_chart(
                dist_df, "Hodina:O", "Počet:Q", "Výskytů", BATTERY,
                tooltip=["Hodina", "Počet"], height=180, y_format="d", interpolate="linear",
            ))

    neg_hours = get_negative_price_hours_list(conn, days_back=30)
    if neg_hours:
        with st.expander("Historie negativních cen (30 dní)"):
            neg_df = pd.DataFrame([
                {"Datum": h.date.strftime("%d.%m.%Y"), "Hodina": f"{h.hour:02d}:00",
                 "Cena (CZK/MWh)": f"{h.price_czk:,.0f}"}
                for h in neg_hours
            ])
            st.dataframe(neg_df, use_container_width=True, hide_index=True)

    # ── Cenové trendy ──
    distribution = get_price_distribution(conn, days_back=30)
    trend = get_price_trend(conn, days_back=30)

    with card("Cenové trendy", "Distribuce cen a klouzavé průměry", icon="line", tone="home"):
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
                .mark_bar(color=HOME, fillOpacity=0.4, stroke=HOME, strokeWidth=1.5)
                .encode(
                    x=alt.X("Pásmo:N", title="Cena (CZK/MWh)", sort=None,
                            axis=alt.Axis(labelAngle=-45, labelFontSize=10, grid=False)),
                    y=alt.Y("Počet:Q", title="Počet 15min intervalů"),
                    tooltip=["Pásmo", "Počet"],
                )
                .properties(height=220, width="container",
                            title="Distribuce cen — histogram (30 dní)")
            )
            show_chart(hist_chart)

        # Klouzavé průměry
        if days_count >= 14:
            ma_data = get_moving_averages(conn, days_back=60)
            if ma_data:
                ma_df = pd.DataFrame([
                    {"Datum": d.date, "Denní průměr": d.daily_avg, "7denní MA": d.ma7,
                     "30denní MA": d.ma30}
                    for d in ma_data
                ])
                ma_long = ma_df.melt(
                    id_vars=["Datum"],
                    value_vars=["Denní průměr", "7denní MA", "30denní MA"],
                    var_name="Typ", value_name="Cena",
                ).dropna(subset=["Cena"])

                encode = {
                    "x": alt.X("Datum:T", title=None, axis=alt.Axis(format="%d.%m.")),
                    "y": alt.Y("Cena:Q", title="CZK/MWh", axis=alt.Axis(format=",.0f")),
                    "color": alt.Color("Typ:N", scale=alt.Scale(
                        domain=["Denní průměr", "7denní MA", "30denní MA"],
                        range=["#5f6b84", ACCENT, SOLAR],
                    ), legend=alt.Legend(title=None, orient="bottom")),
                }
                base = alt.Chart(ma_long)
                glow = base.transform_filter(alt.datum.Typ != "Denní průměr").mark_line(
                    strokeWidth=7, opacity=0.16).encode(**encode)
                lines = base.mark_line().encode(
                    **encode,
                    strokeWidth=alt.condition(alt.datum.Typ == "Denní průměr", alt.value(1.2),
                                              alt.value(2.4)),
                    tooltip=[alt.Tooltip("Datum:T", format="%d.%m.%Y"), "Typ:N",
                             alt.Tooltip("Cena:Q", format=",.0f")],
                )
                show_chart(alt.layer(glow, lines).properties(
                    height=280, width="container", title="Vývoj cen s klouzavými průměry"))

    conn.close()


# ─── Profily & riziko ────────────────────────────────────────────────────────

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
    with card("Aktuální cenový benchmark", "Spot teď vs. průměry 7 a 30 dní", icon="gauge",
              tone="solar"):
        try:
            prices, _ = fetch_spot_prices(date.today())
            current = get_current_price(prices)
            if current:
                bm = get_current_benchmark(conn, current.price_czk)

                col1, col2, col3, col4 = st.columns(4)
                with col1:
                    st.metric("Aktuální cena", f"{bm.current_price:,.0f} CZK/MWh")
                with col2:
                    st.metric("Průměr 7 dní", f"{bm.avg_7d:,.0f} CZK/MWh")
                with col3:
                    st.metric("Průměr 30 dní", f"{bm.avg_30d:,.0f} CZK/MWh")
                with col4:
                    st.metric("Percentil", f"{bm.percentile_rank}.")

                st.html(status_box("Hladina", bm.classification.upper(),
                                   f"{bm.percentile_rank}. percentil za 30 dní",
                                   LEVEL_TONE_BY_NAME.get(bm.classification, "muted")))

                if bm.vs_yesterday_pct is not None or bm.vs_last_week_pct is not None:
                    c1, c2 = st.columns(2)
                    with c1:
                        if bm.vs_yesterday_pct is not None:
                            st.metric("Vs. včera", f"{bm.vs_yesterday_pct:+.1f} %",
                                      delta=f"{bm.vs_yesterday_pct:+.1f}%",
                                      delta_color="inverse")
                    with c2:
                        if bm.vs_last_week_pct is not None:
                            st.metric("Vs. minulý týden", f"{bm.vs_last_week_pct:+.1f} %",
                                      delta=f"{bm.vs_last_week_pct:+.1f}%",
                                      delta_color="inverse")
            else:
                st.info("Aktuální cena není k dispozici.")
        except Exception:
            st.info("Nelze načíst aktuální cenu z API.")

    # ── Kdy je spotřeba nejlevnější ──
    profiles = get_all_profiles_comparison(conn)

    if profiles:
        flat_total = profiles[0].flat_total_kwh
        flat_spot = profiles[0].flat_avg_czk / 1000
        profile_df = pd.DataFrame([{
            "Kdy": p.description,
            "Profil": p.name,
            "Koncová cena (Kč/kWh)": p.avg_total_kwh,
            "Oproti rovnoměrné spotřebě (%)": -p.savings_total_pct,
            "Spot bez DPH (Kč/kWh)": p.avg_price_czk / 1000,
            "Spot oproti průměru (%)": -p.savings_vs_flat_pct,
            "Nejlevnější den": p.best_day,
        } for p in profiles])
        profile_df["Výsledek"] = np.where(
            profile_df["Oproti rovnoměrné spotřebě (%)"] < 0, "levnější", "dražší")

        y = alt.Y("Kdy:N", sort=None, title=None, axis=alt.Axis(labelFontSize=12, labelLimit=260,
                                                               grid=False))
        bars = (
            alt.Chart(profile_df)
            .mark_bar(cornerRadiusTopRight=6, cornerRadiusBottomRight=6, fillOpacity=0.35,
                      strokeWidth=2, size=22)
            .encode(
                x=alt.X("Koncová cena (Kč/kWh):Q", title="Kč/kWh s DPH a distribucí",
                        axis=alt.Axis(format=",.1f")),
                y=y,
                color=alt.Color("Výsledek:N", scale=alt.Scale(domain=["levnější", "dražší"],
                                                              range=[BATTERY, GRID]),
                                legend=None),
                stroke=alt.Stroke("Výsledek:N", scale=alt.Scale(domain=["levnější", "dražší"],
                                                                range=[BATTERY, GRID]),
                                  legend=None),
                tooltip=[
                    "Kdy",
                    alt.Tooltip("Koncová cena (Kč/kWh):Q", format=".2f"),
                    alt.Tooltip("Oproti rovnoměrné spotřebě (%):Q", format="+.1f"),
                    alt.Tooltip("Spot bez DPH (Kč/kWh):Q", format=".2f"),
                    "Nejlevnější den",
                ],
            )
        )
        labels = (
            alt.Chart(profile_df)
            .mark_text(align="left", dx=6, fontSize=12, color="#eef2f8")
            .encode(x="Koncová cena (Kč/kWh):Q", y=y,
                    text=alt.Text("Koncová cena (Kč/kWh):Q", format=".2f"))
        )
        flat_rule = (
            alt.Chart(pd.DataFrame({"x": [flat_total],
                                    "label": [f"rovnoměrně celý den {flat_total:.2f}"]}))
            .mark_rule(color=READOUT, strokeDash=[6, 4], strokeWidth=1.6)
            .encode(x="x:Q", tooltip=[alt.Tooltip("label:N", title="Srovnání")])
        )
        chart = alt.layer(bars, labels, flat_rule).properties(
            height=46 * len(profile_df), width="container")

        best = profiles[0]
        with card("Kdy je spotřeba nejlevnější", "Průměr za posledních 30 dní podle mého tarifu "
                  "(Electree + ČEZ D25d)", icon="home", tone="home",
                  aside=pill(f"nejlevněji: {best.name}", "battery")):
            st.html(status_box(
                "Nejlevnější je spotřeba", best.description,
                f"{best.avg_total_kwh:.2f} Kč/kWh – o {best.savings_total_pct:.0f} % méně než "
                f"při rovnoměrné spotřebě ({flat_total:.2f} Kč/kWh)", "battery",
            ))
            show_chart(chart)
            st.caption(
                "Koncová cena = spot × 1,21 (DPH) + poplatky Electree + systémové služby + daň + "
                "distribuce podle NT/VT v dané hodině. Oranžová čára = **rovnoměrná spotřeba**: "
                "stejné množství v každé čtvrthodině dne (dřív tu bylo označení „flat tarif“). "
                f"Samotný spot bez DPH byl v průměru {flat_spot:.2f} Kč/kWh."
            )
            with st.expander("Tabulka"):
                st.dataframe(
                    profile_df.drop(columns=["Výsledek"]), use_container_width=True,
                    hide_index=True,
                    column_config={
                        "Koncová cena (Kč/kWh)": st.column_config.NumberColumn(format="%.2f"),
                        "Oproti rovnoměrné spotřebě (%)": st.column_config.NumberColumn(
                            format="%+.1f %%"),
                        "Spot bez DPH (Kč/kWh)": st.column_config.NumberColumn(format="%.2f"),
                        "Spot oproti průměru (%)": st.column_config.NumberColumn(
                            format="%+.1f %%"),
                    },
                )

    # ── Volatilita ──
    metrics = get_volatility_metrics(conn)

    if metrics.volatility_trend != "nedostatek dat":
        with card("Volatilita a riziko", "Jak moc ceny kolísají", icon="activity", tone="grid"):
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
                st.metric("Trend volatility", metrics.volatility_trend)

            c1, c2 = st.columns(2)
            with c1:
                st.metric("VaR 95%", f"{metrics.var_95:,.0f} CZK/MWh",
                          help="95 % cen je pod touto hodnotou")
            with c2:
                st.metric("VaR 99%", f"{metrics.var_99:,.0f} CZK/MWh")

    # ── Cenové špičky ──
    peak_analysis = get_peak_analysis(conn)

    with card("Cenové špičky", "Intervaly nad 90. percentilem", icon="up", tone="readout"):
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
            st.caption("Pravděpodobnost cenové špičky podle hodiny")
            show_chart(hour_line_chart(
                prob_df, "Hodina:O", "Pravděpodobnost (%):Q", "%", READOUT,
                tooltip=["Hodina", alt.Tooltip("Pravděpodobnost (%):Q", format=".1f")],
                height=220,
            ))

            st.markdown("### Predikce špiček pro zítřek")
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
                st.html(status_box("Zítra", "Bez výrazných špiček",
                                   "žádná hodina nemá pravděpodobnost ≥ 20 %", "battery"))
        else:
            st.info("Žádné cenové špičky za posledních 30 dní.")

    conn.close()


# ─── Predikce ────────────────────────────────────────────────────────────────

FORECAST_DAYS = 7  # dnes + 6 dní


def load_price_frame(days_back: int) -> pd.DataFrame:
    """Ceny z DB za posledních `days_back` dní + dnešek a zítřek z API (time_from, price_czk)."""
    from ote.db import get_prices_for_range

    today = date.today()
    conn = get_connection()
    rows = get_prices_for_range(conn, today - timedelta(days=days_back),
                                today + timedelta(days=1))
    conn.close()
    prices = {p.time_from: p.price_czk for p in rows}
    # DB se plní jednou denně – dnešek a zítřek doplní živé API
    for day in (today, today + timedelta(days=1)):
        if sum(1 for t in prices if t.date() == day) < 90:
            try:
                live, _ = fetch_spot_prices(day)
            except Exception:
                live = []
            prices.update({p.time_from: p.price_czk for p in live})
    df = pd.DataFrame({"time_from": list(prices), "price_czk": list(prices.values())})
    return df.sort_values("time_from").reset_index(drop=True)


def last_complete_day(prices: pd.DataFrame) -> date:
    """Poslední den, pro který OTE už zveřejnilo celý den cen."""
    counts = prices.groupby(prices["time_from"].dt.date).size()
    return max(d for d, n in counts.items() if n >= 90)


@st.cache_data(ttl=3600, show_spinner=False)
def cached_week_forecast(cache_key: str) -> tuple[pd.DataFrame, date]:
    """Ceny dnes … dnes+6: skutečnost OTE + predikce modelu (klíč = den + hodina)."""
    from ote.price_model import TRAIN_DAYS, fetch_weather, forecast

    prices = load_price_frame(TRAIN_DAYS + 5)
    last_known = last_complete_day(prices)
    until = date.today() + timedelta(days=FORECAST_DAYS - 1)
    predicted = forecast(prices, fetch_weather(), last_known, until)
    return pd.concat([
        prices[prices["time_from"].dt.date >= date.today()].assign(kind="OTE"),
        predicted.rename(columns={"predicted": "price_czk"}).assign(kind="predikce"),
    ], ignore_index=True), last_known


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def cached_evaluation(cache_key: str) -> Evaluation | None:
    """Backtest modelu na posledních 14 dnech (počasí z tehdejší předpovědi)."""
    from ote.price_model import TRAIN_DAYS, evaluate, fetch_weather_lagged

    prices = load_price_frame(TRAIN_DAYS + 30)
    return evaluate(prices, fetch_weather_lagged(past_days=60), origins=14)


def week_forecast_chart(df: pd.DataFrame, now: datetime, height: int = 340) -> alt.LayerChart:
    """Skutečnost OTE (plná čára) + predikce (čárkovaně) s pásmem 10–90 % chyb z backtestu."""
    days = list(dict.fromkeys(t.date() for t in df["time_from"]))
    df = df.assign(
        Slot=[slot_key(t.date(), t) for t in df["time_from"]],
        Čas=[f"{WEEKDAY_CZ[t.weekday()]} {t:%d.%m. %H:%M}" for t in df["time_from"]],
    )
    values = [f"{d:%d.%m.} 00:00" for d in days]
    # Vrstvy mají různá data – pořadí čtvrthodin musí být dané pevně
    order = list(dict.fromkeys(df.sort_values("time_from")["Slot"]))
    x = alt.X("Slot:N", title=None, sort=order, scale=alt.Scale(domain=order), axis=alt.Axis(
        values=values, labelAngle=0, labelExpr="substring(datum.value, 0, 6)"))
    y_title = "CZK/MWh"
    actual = df[df["kind"] == "OTE"]
    pred = df[df["kind"] == "predikce"]
    # Predikce navazuje na poslední známou čtvrthodinu, aby čáry nebyly přerušené
    if not actual.empty and not pred.empty:
        bridge = actual.iloc[[-1]].assign(kind="predikce", low=actual["price_czk"].iloc[-1],
                                          high=actual["price_czk"].iloc[-1])
        pred = pd.concat([bridge, pred], ignore_index=True)
    layers = []
    if not pred.empty and "low" in pred:
        layers.append(alt.Chart(pred).mark_area(interpolate="step-after", color=HOME,
                                                 opacity=0.16)
                      .encode(x=x, y=alt.Y("low:Q", title=y_title), y2="high:Q"))
    tooltip = [alt.Tooltip("Čas:N"), alt.Tooltip("kind:N", title="Zdroj"),
               alt.Tooltip("price_czk:Q", title="CZK/MWh", format=",.0f")]
    if not actual.empty:
        layers += [
            alt.Chart(actual).mark_line(interpolate="step-after", color=SOLAR, strokeWidth=7,
                                        opacity=0.16).encode(x=x, y="price_czk:Q"),
            alt.Chart(actual).mark_line(interpolate="step-after", color=SOLAR, strokeWidth=2)
            .encode(x=x, y=alt.Y("price_czk:Q", title=y_title, axis=alt.Axis(format=",.0f")),
                    tooltip=tooltip),
        ]
    if not pred.empty:
        layers += [
            alt.Chart(pred).mark_line(interpolate="step-after", color=HOME, strokeWidth=7,
                                      opacity=0.16).encode(x=x, y="price_czk:Q"),
            alt.Chart(pred).mark_line(interpolate="step-after", color=HOME, strokeWidth=2,
                                      strokeDash=[5, 3])
            .encode(x=x, y=alt.Y("price_czk:Q", title=y_title, axis=alt.Axis(format=",.0f")),
                    tooltip=tooltip),
        ]
    day_df = pd.DataFrame([{"Slot": v, "label": f"{WEEKDAY_CZ[d.weekday()]} {d:%d.%m.}"}
                           for v, d in zip(values, days)])
    layers += [
        alt.Chart(day_df.iloc[1:]).mark_rule(color="#334155").encode(x=x),
        alt.Chart(day_df).mark_text(align="left", dx=5, color=INK_MUTED, fontSize=11)
        .encode(x=x, y=alt.value(8), text="label:N"),
        alt.Chart(pd.DataFrame({"Slot": [slot_key(now.date(),
                                                   now.replace(minute=now.minute // 15 * 15))]}))
        .mark_rule(color=READOUT, strokeDash=[4, 4], strokeWidth=1.5).encode(x=x),
    ]
    return alt.layer(*layers).properties(height=height, width="container")


def daily_forecast_rows(df: pd.DataFrame) -> list[dict]:
    """Řádky denního přehledu: průměr, minimum a nejlevnější 2 hodiny dne."""
    rows = []
    for day, part in df.groupby(df["time_from"].dt.date):
        part = part.sort_values("time_from").reset_index(drop=True)
        window = part["price_czk"].rolling(8).mean()  # 8 čtvrthodin = 2 h
        start = part.loc[window.idxmin() - 7, "time_from"] if window.notna().any() else None
        kind = "OTE" if (part["kind"] == "OTE").all() else "predikce"
        rows.append({
            "color": SOLAR if kind == "OTE" else HOME,
            "label": f"{WEEKDAY_CZ[day.weekday()]} {day:%d.%m.}",
            "note": "OTE" if kind == "OTE" else "predikce",
            "now": f"{part['price_czk'].mean():,.0f}",
            "now_time": "",
            "peak": f"{start:%H:%M}" if start is not None else "—",
            "peak_time": f"{window.min():,.0f}" if start is not None else "",
        })
    return rows


def show_forecast_tab() -> None:
    from ote.forecast import get_data_sufficiency, get_tomorrow_prices

    conn = get_connection()
    sufficiency = get_data_sufficiency(conn)
    conn.close()

    st.sidebar.header("Stav dat")
    st.sidebar.metric("Dnů v historii", sufficiency.total_days)

    now = datetime.now(PRAGUE_TZ)
    # ── Predikce dnes + 6 dní ──
    with card("Predikce na 7 dní", "Dnes + 6 dní · skutečnost OTE, dál model s počasím",
              icon="sparkles", tone="home"):
        try:
            with st.spinner("Počítám predikci (model + počasí)..."):
                week, last_known = cached_week_forecast(f"{now:%Y-%m-%d %H}")
                evaluation = cached_evaluation(f"{last_known}")
        except Exception as e:
            st.error(f"Predikci se nepodařilo spočítat: {e}")
            return

        if evaluation is not None:
            q = evaluation.residual_quantiles.set_index("h")
            pred_mask = week["kind"] == "predikce"
            week.loc[pred_mask, "low"] = (week.loc[pred_mask, "price_czk"]
                                          + week.loc[pred_mask, "h"].map(q["q10"]))
            week.loc[pred_mask, "high"] = (week.loc[pred_mask, "price_czk"]
                                           + week.loc[pred_mask, "h"].map(q["q90"]))

        predicted = week[week["kind"] == "predikce"]
        known_until = f"{WEEKDAY_CZ[last_known.weekday()]} {last_known:%d.%m.}"
        st.html(
            f"<div style='display:flex;gap:8px;flex-wrap:wrap;margin:4px 0 6px'>"
            f"{pill(f'OTE známé do {known_until}', 'solar')}"
            f"{pill(f'predikce {len(predicted) // 96} dní', 'home')}"
            + (pill(f"průměrná chyba ± {evaluation.mae:,.0f} CZK/MWh", "muted")
               if evaluation is not None else "")
            + "</div>"
        )
        show_chart(week_forecast_chart(week, now))
        st.html(readout_table(daily_forecast_rows(week), ("Průměr dne", "Nejlevnější 2 h")))
        st.caption(
            "Ceny v CZK/MWh bez DPH. Žlutá = zveřejněné ceny OTE, fialová čárkovaná = predikce; "
            "fialové pásmo = rozsah, do kterého v backtestu padlo 80 % skutečných cen. "
            "„Nejlevnější 2 h“ = začátek nejlevnějšího dvouhodinového okna a jeho průměr."
        )

    # ── Přesnost modelu ──
    with card("Přesnost modelu", "Poctivý backtest: posledních 14 výchozích dnů, predikce na "
              "1–6 dní, počasí z tehdejší předpovědi", icon="gauge", tone="accent"):
        if evaluation is None:
            st.info("Pro vyhodnocení je potřeba aspoň 37 dní historie cen.")
        else:
            gain = (1 - evaluation.mae / evaluation.baseline_mae) * 100
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Chyba modelu (MAE)", f"{evaluation.mae:,.0f} CZK/MWh",
                      help="Průměrná absolutní chyba čtvrthodinové ceny")
            c2.metric("Průměr 30 dní (MAE)", f"{evaluation.baseline_mae:,.0f} CZK/MWh",
                      help="Srovnání: průměr stejné čtvrthodiny za 30 dní (všední den / víkend)")
            c3.metric("Zlepšení", f"{gain:+.0f} %", help="O kolik je model přesnější než průměr")
            c4.metric("Chyba denního průměru", f"{evaluation.daily_mae:,.0f} CZK/MWh",
                      help=f"Systematická odchylka (bias) {evaluation.bias:+,.0f} CZK/MWh; "
                           "kladná = model cenu podstřeluje")

            by_h = evaluation.by_horizon.rename(columns={
                "model_mae": "Model s počasím", "baseline_mae": "Průměr 30 dní"})
            long = by_h.melt(id_vars="h", var_name="Metoda", value_name="MAE")
            long["Horizont"] = long["h"].map(
                lambda h: f"{h} {'den' if h == 1 else 'dny' if h < 5 else 'dní'}")
            color = alt.Color("Metoda:N", scale=alt.Scale(
                domain=["Model s počasím", "Průměr 30 dní"], range=[HOME, "#5f6b84"]),
                legend=alt.Legend(title=None, orient="top"))
            x = alt.X("Horizont:N", sort=None, title=None, axis=alt.Axis(labelAngle=0))
            y = alt.Y("MAE:Q", title="MAE CZK/MWh", scale=alt.Scale(zero=True),
                      axis=alt.Axis(format=",.0f"))
            base = alt.Chart(long)
            horizon_chart = alt.layer(
                base.mark_line(strokeWidth=7, opacity=0.16).encode(x=x, y=y, color=color),
                base.mark_line(strokeWidth=2.2, point=alt.OverlayMarkDef(filled=True, size=50))
                .encode(x=x, y=y, color=color,
                        tooltip=["Horizont", "Metoda", alt.Tooltip("MAE:Q", format=",.0f")]),
            ).properties(height=230, width="container", title="Chyba podle horizontu")

            last = evaluation.last_run
            last_long = pd.concat([
                last[["time_from", "actual"]].rename(columns={"actual": "price_czk"})
                .assign(Série="Skutečnost"),
                last[["time_from", "predicted"]].rename(columns={"predicted": "price_czk"})
                .assign(Série="Predikce"),
            ])
            last_long["Slot"] = [slot_key(t.date(), t) for t in last_long["time_from"]]
            first_day = last["time_from"].min().date()
            values = [f"{first_day + timedelta(days=i):%d.%m.} 00:00" for i in range(6)]
            run_order = list(dict.fromkeys(last_long.sort_values("time_from")["Slot"]))
            run_chart = alt.Chart(last_long).mark_line(
                interpolate="step-after", strokeWidth=1.8,
            ).encode(
                x=alt.X("Slot:N", sort=run_order, title=None, axis=alt.Axis(
                    values=values, labelAngle=0, labelExpr="substring(datum.value, 0, 6)")),
                y=alt.Y("price_czk:Q", title="CZK/MWh", axis=alt.Axis(format=",.0f")),
                color=alt.Color("Série:N", scale=alt.Scale(domain=["Skutečnost", "Predikce"],
                                                           range=[SOLAR, HOME]),
                                legend=alt.Legend(title=None, orient="top")),
                strokeDash=alt.StrokeDash("Série:N", scale=alt.Scale(
                    domain=["Skutečnost", "Predikce"], range=[[1, 0], [5, 3]]), legend=None),
            ).properties(height=230, width="container",
                         title=f"Poslední backtest: ceny známé do "
                               f"{first_day - timedelta(days=1):%d.%m.}")
            col1, col2 = st.columns(2, gap="medium")
            with col1:
                show_chart(horizon_chart)
            with col2:
                show_chart(run_chart)

    with st.expander("Jak model funguje"):
        st.markdown("""
        - **Model:** gradient boosting (scikit-learn `HistGradientBoostingRegressor`, ztráta MAE),
          trénuje se znovu z **posledních 30 dní** po 15 minutách; starší dny mají menší váhu
          (poločas 10 dní). Minulý rok se nepoužívá.
        - **Vstupy:** čtvrthodina dne, den v týdnu, český svátek a **předpověď počasí**
          zprůměrovaná přes 8 bodů v ČR a Německu – sluneční záření (FVE), vítr ve 100 m
          (zvlášť sever Německa), teplota, oblačnost. Zdroj Open-Meteo.
        - **Cenová hladina:** model předpovídá odchylku od průměru posledních 7 dní, takže drží
          aktuální úroveň cen.
        - **Vyhodnocení:** pro každý ze 14 posledních výchozích dnů se model natrénuje jen na
          tehdy známých datech a počasí se vezme z tehdejší předpovědi (Open-Meteo Previous Runs),
          ne ze skutečnosti. Pásmo nejistoty = 10.–90. percentil chyb pro daný horizont.
        - Bez počasí by model nebyl lepší než prostý průměr – rozhoduje hlavně slunce a vítr.
        """)

    # ── Zítřejší ceny ──
    with st.spinner("Načítám zítřejší ceny..."):
        tomorrow_prices, eur_czk_rate, available = get_tomorrow_prices()

    tomorrow = date.today() + timedelta(days=1)
    with card("Zítřejší ceny (D+1)", "Day-ahead ceny OTE — obvykle kolem 13:00",
              icon="calendar", tone="solar",
              aside=pill(f"{tomorrow:%d. %m. %Y}", "muted")):
        if available and tomorrow_prices:
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

            show_chart(spot_price_chart(df, tomorrow, height=320))
            st.html(level_legend())

            with st.expander("Tabulka"):
                st.dataframe(df[["Hodina", "Cena (CZK/MWh)", "Cena (EUR/MWh)"]],
                             use_container_width=True, hide_index=True)
        else:
            st.info("Zítřejší ceny zatím nejsou publikovány (OTE zveřejňuje kolem 13:00 CET).")


# ─── Počasí ──────────────────────────────────────────────────────────────────

_SVG_SUN = (
    "<g stroke='#FBBF24' stroke-width='1.6' stroke-linecap='round'>"
    "<path d='M{x} {y1}v-2.5M{x} {y2}v2.5M{x1} {y}h-2.5M{x2} {y}h2.5'/></g>"
    "<circle cx='{x}' cy='{y}' r='{r}' fill='#FBBF24'/>"
)
_SVG_MOON = "<path d='M{x} {y}a{r} {r} 0 1 0 {d} {d}a{q} {q} 0 0 1 -{d} -{d}z' fill='#FCD34D'/>"
_SVG_CLOUD = (
    "<path d='M9 26h15a5 5 0 0 0 .4-10 7 7 0 0 0-13.3 1.6A4.3 4.3 0 0 0 9 26z' "
    "fill='{fill}'/>"
)


def _sun(x: float, y: float, r: float) -> str:
    return _SVG_SUN.format(x=x, y=y, r=r, y1=y - r - 1.5, y2=y + r + 1.5,
                           x1=x - r - 1.5, x2=x + r + 1.5)


def _moon(x: float, y: float, r: float) -> str:
    return _SVG_MOON.format(x=x - r * 0.3, y=y - r, r=r, d=r, q=r * 0.9)


def weather_icon(code: int, is_day: bool, size: int = 34, cloud: str = "#CBD5E1") -> str:
    """SVG ikona podle WMO kódu (Open-Meteo), denní/noční varianta."""
    celestial = _sun(16, 16, 6) if is_day else _moon(18, 16, 7)
    small = _sun(12, 11, 4.5) if is_day else _moon(13, 11, 5.5)
    cloud = _SVG_CLOUD.format(fill=cloud)
    # Tmavší mrak posunutý nahoru, aby se pod něj vešly kapky / vločky / blesk
    raised_cloud = f"<g transform='translate(0,-5)'>{_SVG_CLOUD.format(fill='#94A3B8')}</g>"
    if code == 0:
        body = celestial
    elif code in (1, 2):
        body = small + cloud
    elif code == 3:
        body = cloud
    elif code in (45, 48):
        body = ("<g stroke='#94A3B8' stroke-width='2' stroke-linecap='round'>"
                "<path d='M6 12h20M4 17h24M7 22h18'/></g>")
    elif code >= 95:
        body = raised_cloud + "<path d='M17 21l-4 6h3l-1.5 4 5-6.5h-3l1.5-3.5z' fill='#FACC15'/>"
    elif code in (71, 73, 75, 77, 85, 86):
        body = raised_cloud + "".join(f"<circle cx='{cx}' cy='{cy}' r='1.3' fill='#F1F5F9'/>"
                      for cx, cy in ((11, 25), (16, 28), (21, 25)))
    else:  # mrholení, déšť, přeháňky
        body = (small if code in (80, 81, 82) else "") \
            + raised_cloud \
            + "<g stroke='#60A5FA' stroke-width='1.7' stroke-linecap='round'>" \
            + "<path d='M11 24l-1 3.5M16 24l-1 3.5M21 24l-1 3.5'/></g>"
    svg = f"<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'>{body}</svg>"
    # st.html vyřezává inline SVG, jako obrázek projde
    data = base64.b64encode(svg.encode()).decode()
    return f"<img src='data:image/svg+xml;base64,{data}' width='{size}' height='{size}' alt=''>"


WEATHER_CSS = f"""
<style>
  .w3-scroll {{ overflow-x:auto; margin-top:6px; }}
  .w3-grid {{ min-width:560px; }}
  .w3-row, .w3-heads {{ display:grid; grid-template-columns:76px repeat(8, 1fr); }}
  .w3-head {{ text-align:center; color:{INK_MUTED}; font-size:12px; padding:6px 0; }}
  .w3-row {{ background:{SURFACE_RAISED}; border:1px solid {BORDER}; border-radius:14px;
             margin-top:8px; border-left:4px solid transparent; }}
  .w3-today {{ border-left-color:{SOLAR}; }}
  .w3-day {{ display:flex; flex-direction:column; justify-content:center; padding-left:10px; }}
  .w3-day b {{ font-size:15px; font-weight:600; }}
  .w3-day span {{ color:{INK_MUTED}; font-size:12.5px; font-weight:500; }}
  .w3-cell {{ display:flex; flex-direction:column; align-items:center; gap:4px;
             padding:10px 0 12px; border-left:1px solid {BORDER}; }}
  .w3-past {{ opacity:0.4; }}
  .w3-now {{ background:{SOLAR}14; }}
  .w3-temp {{ font-weight:700; font-size:17px; }}
  .w3-pill {{ background:#ffffff0d; color:#cbd5e1; border-radius:999px; padding:2px 9px;
             font-size:11.5px; margin-top:2px; }}
  .w3-foot {{ color:{INK_MUTED}; font-size:12.5px; margin-top:12px; }}
  .w3-foot a {{ color:#cbd5e1; }}
  .w7 {{ display:grid; grid-template-columns:repeat(7, minmax(84px, 1fr)); gap:8px;
         overflow-x:auto; }}
  .w7-day {{ background:{SURFACE_RAISED}; border:1px solid {BORDER}; border-radius:14px;
             padding:12px 6px; display:flex; flex-direction:column; align-items:center; gap:4px; }}
  .w7-day small {{ color:{INK_MUTED}; font-size:12px; }}
  .w7-day b {{ font-size:17px; font-weight:700; }}
</style>
"""


def show_three_hour_weather_card() -> None:
    """Karta „Počasí": předpověď po 3 hodinách na dnes a zítra (obdoba karty v HA)."""
    from ote.weather import ThreeHourBlock, fetch_three_hour_forecast

    try:
        blocks = fetch_three_hour_forecast(days=2)
    except RuntimeError as e:
        st.warning(str(e))
        return
    if not blocks:
        return

    now = datetime.now(PRAGUE_TZ).replace(tzinfo=None)
    today = now.date()
    by_day: dict[date, dict[int, ThreeHourBlock]] = {}
    for b in blocks:
        by_day.setdefault(b.start.date(), {})[b.start.hour] = b

    header = "".join(
        f"<div class='w3-head'>{h:02d}–{h + 3:02d}</div>" for h in range(0, 24, 3)
    )
    rows = []
    for day, day_blocks in sorted(by_day.items()):
        label = "Dnes" if day == today else "Zítra" if day == today + timedelta(days=1) else ""
        cells = []
        for h in range(0, 24, 3):
            b = day_blocks.get(h)
            if b is None:
                cells.append("<div class='w3-cell'><div class='w3-temp'>—°</div>"
                             "<div class='w3-pill'>—%</div></div>")
                continue
            past = b.start + timedelta(hours=3) <= now
            current = b.start <= now < b.start + timedelta(hours=3)
            temp = round(b.temperature)
            temp_txt = f"{temp}°".replace("-", "−") if temp != 0 else "0°"
            cls = "w3-cell" + (" w3-past" if past else "") + (" w3-now" if current else "")
            cells.append(
                f"<div class='{cls}' title='{b.start:%H:%M}–{b.start + timedelta(hours=3):%H:%M}'>"
                f"{weather_icon(b.weather_code, b.is_day)}"
                f"<div class='w3-temp'>{temp_txt}</div>"
                f"<div class='w3-pill'>{b.precipitation_probability} %</div></div>"
            )
        rows.append(
            f"<div class='w3-row{' w3-today' if day == today else ''}'>"
            f"<div class='w3-day'><b>{label}</b><span>{day.day}. {day.month}.</span></div>"
            f"{''.join(cells)}</div>"
        )

    with card("Počasí", "Předpověď po 3 hodinách na dnes a zítra · Kravaře", icon="cloud",
              tone="solar", accent_top="solar"):
        st.html(f"""{WEATHER_CSS}
        <div class='w3-scroll'><div class='w3-grid'>
          <div class='w3-heads'><div></div>{header}</div>
          {''.join(rows)}
        </div></div>
        <div class='w3-foot'>Teplota = průměr bloku, % = nejvyšší pravděpodobnost srážek
          v bloku · aktualizováno {now:%d. %m. %Y %H:%M} · Data o počasí:
          <a href='https://open-meteo.com/' target='_blank'>Open-Meteo.com</a></div>
        """)


WEATHER_TYPE_CODE = {"sunny": 0, "mixed": 2, "cloudy": 3}
WEATHER_IMPACT = {
    "sunny": ("↓ levnější", "battery"), "windy": ("↓ levnější", "battery"),
    "cloudy": ("↑ dražší", "grid"), "mixed": ("~ běžné", "solar"),
}


def show_weather_tab() -> None:
    try:
        from ote.weather import fetch_weather_forecast, get_weather_price_correlation
    except ImportError:
        st.error("Modul počasí není dostupný.")
        return

    show_three_hour_weather_card()

    try:
        with st.spinner("Načítám předpověď počasí..."):
            weather_forecasts = fetch_weather_forecast(days_ahead=7)

        if weather_forecasts:
            weather_df = pd.DataFrame([{
                "Datum": f.date,
                "Den": f"{WEEKDAY_CZ[f.date.weekday()]} {f.date:%d.%m.}",
                "Typ": f.weather_type,
                "Teplota (°C)": f.avg_temperature,
                "Oblačnost (%)": f.avg_cloud_cover,
                "Vítr (m/s)": f.avg_wind_speed,
            } for f in weather_forecasts])

            tiles = []
            for f in weather_forecasts:
                text, tone = WEATHER_IMPACT.get(f.weather_type, ("?", "muted"))
                icon = (icon_img("wind", ACCENT_INK, 30) if f.weather_type == "windy"
                        else weather_icon(WEATHER_TYPE_CODE.get(f.weather_type, 2), True, 34))
                tiles.append(
                    f"<div class='w7-day'><small>{WEEKDAY_CZ[f.date.weekday()]} "
                    f"{f.date:%d.%m.}</small>{icon}<b>{f.avg_temperature:.0f}°C</b>"
                    f"{pill(text, tone)}</div>"
                )

            with card("Předpověď na 7 dní", "Kravaře · průměr dne a odhad vlivu na ceny",
                      icon="cloud_sun", tone="accent"):
                st.html(f"{WEATHER_CSS}<div class='w7'>{''.join(tiles)}</div>")

                col1, col2 = st.columns(2)
                with col1:
                    show_chart(hour_line_chart(
                        weather_df, "Den:N", "Teplota (°C):Q", "°C", SOLAR,
                        tooltip=[alt.Tooltip("Den:N"),
                                 alt.Tooltip("Teplota (°C):Q", format=".1f")],
                        height=200, y_format=".0f",
                    ).properties(title="Teplota"))
                with col2:
                    show_chart(hour_line_chart(
                        weather_df, "Den:N", "Oblačnost (%):Q", "%", ACCENT_INK,
                        tooltip=[alt.Tooltip("Den:N"),
                                 alt.Tooltip("Oblačnost (%):Q", format=".0f")],
                        height=200,
                    ).properties(title="Oblačnost"))
                show_chart(hour_line_chart(
                    weather_df, "Den:N", "Vítr (m/s):Q", "m/s", BATTERY,
                    tooltip=[alt.Tooltip("Den:N"), alt.Tooltip("Vítr (m/s):Q", format=".1f")],
                    height=170, y_format=".1f",
                ).properties(title="Rychlost větru"))

        else:
            st.warning("Nepodařilo se načíst předpověď počasí.")

    except Exception as e:
        st.error(f"Chyba: {e}")

    # ── Korelace ──
    conn = get_connection()
    days_count = get_data_days_count(conn)

    with card("Korelace počasí a cen elektřiny", "Posledních 30 dní", icon="activity",
              tone="home"):
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
                            st.metric(label, f"{val:+.2f}", help=help_text)

                    st.html(status_box("Nejsilnější faktor", correlation.strongest_factor,
                                       f"R² = {correlation.r_squared:.3f}", "home"))

                    with st.expander("Interpretace korelací"):
                        st.markdown("""
                        | Faktor | Vztah | Důvod |
                        |--------|-------|-------|
                        | Sluneční záření | Záporná korelace | Více slunce = více FVE = nižší ceny |
                        | Rychlost větru | Záporná korelace | Více větru = více větrné energie |
                        | Oblačnost | Kladná korelace | Zataženo = méně FVE = vyšší ceny |
                        | Teplota | Smíšená | Extrémy = vyšší spotřeba = vyšší ceny |
                        """)
            except Exception as e:
                st.warning(f"Korelační analýza není dostupná: {e}")
        else:
            st.info(f"Pro korelační analýzu je potřeba alespoň 14 dnů dat. Aktuálně {days_count}.")

    conn.close()

    # ── Predikce cen s počasím (stejný model jako na stránce Predikce) ──
    with card("Predikce cen s počasím", "Model z posledních 30 dní + předpověď počasí",
              icon="sparkles", tone="home"):
        try:
            with st.spinner("Počítám predikci..."):
                week, _ = cached_week_forecast(f"{datetime.now(PRAGUE_TZ):%Y-%m-%d %H}")
            st.html(readout_table(daily_forecast_rows(week), ("Průměr dne", "Nejlevnější 2 h")))
            st.caption("CZK/MWh bez DPH. Graf, pásmo nejistoty a přesnost modelu jsou na "
                       "stránce Predikce.")
        except Exception as e:
            st.warning(f"Predikce s počasím není dostupná: {e}")


if __name__ == "__main__":
    main()
