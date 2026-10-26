"""Vzhled dashboardu ve stylu SunnyHome — barvy, CSS, Altair téma a HTML prvky."""

from __future__ import annotations

import base64
import re
from collections.abc import Iterator
from contextlib import contextmanager
from html import escape

import altair as alt
import streamlit as st

# Tokeny převzaté ze sunnyhome.cloud (:root proměnné)
BG = "#0b1220"
SURFACE = "#111a2e"
SURFACE_RAISED = "#17223a"
BORDER = "#1f2b45"
INK = "#eef2f8"
INK_MUTED = "#9aa6bd"
ACCENT = "#3b82f6"
ACCENT_INK = "#6ea8ff"
SOLAR = "#fbbf24"
BATTERY = "#22c55e"
BATTERY_INK = "#4ade80"
HOME = "#a855f7"
HOME_INK = "#c084fc"
GRID = "#f43f5e"
GRID_INK = "#fb7185"
READOUT = "#f5a524"

TONES = {
    "accent": ACCENT_INK,
    "solar": SOLAR,
    "battery": BATTERY_INK,
    "home": HOME_INK,
    "grid": GRID_INK,
    "readout": READOUT,
    "muted": INK_MUTED,
}

# Barvy cenové hladiny: zelená (levná) → žlutá → oranžová → červená (drahá)
LEVEL_RANGE = [BATTERY, "#86efac", SOLAR, READOUT, GRID]

# Ikony (Lucide, ISC licence) – vnitřek <svg viewBox="0 0 24 24">
ICONS = {
    "dashboard": "<rect width='7' height='9' x='3' y='3' rx='1'/><rect width='7' height='5' x='14' "
                 "y='3' rx='1'/><rect width='7' height='9' x='14' y='12' rx='1'/><rect width='7' "
                 "height='5' x='3' y='16' rx='1'/>",
    "zap": "<path d='M4 14a1 1 0 0 1-.78-1.63l9.9-10.2a.5.5 0 0 1 .86.46l-1.92 6.02A1 1 0 0 0 13 "
           "10h7a1 1 0 0 1 .78 1.63l-9.9 10.2a.5.5 0 0 1-.86-.46l1.92-6.02A1 1 0 0 0 11 14z'/>",
    "home": "<path d='M15 21v-8a1 1 0 0 0-1-1h-4a1 1 0 0 0-1 1v8'/><path d='M3 10a2 2 0 0 1 "
            ".709-1.528l7-5.999a2 2 0 0 1 2.582 0l7 5.999A2 2 0 0 1 21 10v9a2 2 0 0 1-2 2H5a2 2 "
            "0 0 1-2-2z'/>",
    "line": "<path d='M3 3v16a2 2 0 0 0 2 2h16'/><path d='m19 9-5 5-4-4-3 3'/>",
    "bars": "<path d='M3 3v16a2 2 0 0 0 2 2h16'/><path d='M18 17V9'/><path d='M13 17V5'/>"
            "<path d='M8 17v-3'/>",
    "activity": "<path d='M22 12h-2.48a2 2 0 0 0-1.93 1.46l-2.35 8.36a.25.25 0 0 1-.48 0L9.24 "
                "2.18a.25.25 0 0 0-.48 0l-2.35 8.36A2 2 0 0 1 4.49 12H2'/>",
    "shield": "<path d='M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 "
              "0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 "
              "1 1 1z'/>",
    "sparkles": "<path d='M9.937 15.5A2 2 0 0 0 8.5 14.063l-6.135-1.582a.5.5 0 0 1 0-.962L8.5 "
                "9.936A2 2 0 0 0 9.937 8.5l1.582-6.135a.5.5 0 0 1 .963 0L14.063 8.5A2 2 0 0 0 "
                "15.5 9.937l6.135 1.581a.5.5 0 0 1 0 .964L15.5 14.063a2 2 0 0 0-1.437 "
                "1.437l-1.582 6.135a.5.5 0 0 1-.963 0z'/>",
    "cloud": "<path d='M17.5 19H9a7 7 0 1 1 6.71-9h1.79a4.5 4.5 0 1 1 0 9Z'/>",
    "cloud_sun": "<path d='M12 2v2'/><path d='m4.93 4.93 1.41 1.41'/><path d='M20 12h2'/>"
                 "<path d='m19.07 4.93-1.41 1.41'/><path d='M15.947 12.65a4 4 0 0 0-5.925-4.128'/>"
                 "<path d='M13 22H7a5 5 0 1 1 4.9-6H13a3 3 0 0 1 0 6Z'/>",
    "clock": "<circle cx='12' cy='12' r='10'/><path d='M12 6v6l4 2'/>",
    "coins": "<circle cx='8' cy='8' r='6'/><path d='M18.09 10.37A6 6 0 1 1 10.34 18'/>"
             "<path d='M7 6h1v4'/><path d='m16.71 13.88.7.71-2.82 2.82'/>",
    "pole": "<path d='M12 2v20'/><path d='M2 5h20'/><path d='M3 3v2'/><path d='M7 3v2'/>"
            "<path d='M17 3v2'/><path d='M21 3v2'/><path d='m19 5-7 7-7-7'/>",
    "calendar": "<path d='M8 2v4'/><path d='M16 2v4'/><rect width='18' height='18' x='3' y='4' "
                "rx='2'/><path d='M3 10h18'/>",
    "alert": "<path d='m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 "
             "1.73-3'/><path d='M12 9v4'/><path d='M12 17h.01'/>",
    "down": "<path d='M22 17 13.5 8.5 8.5 13.5 2 7'/><path d='M16 17h6v-6'/>",
    "up": "<path d='M22 7 13.5 15.5 8.5 10.5 2 17'/><path d='M16 7h6v6'/>",
    "gauge": "<path d='m12 14 4-4'/><path d='M3.34 19a10 10 0 1 1 17.32 0'/>",
    "thermometer": "<path d='M14 4v10.54a4 4 0 1 1-4 0V4a2 2 0 0 1 4 0Z'/>",
    "wind": "<path d='M12.8 19.6A2 2 0 1 0 14 16H2'/><path d='M17.5 8a2.5 2.5 0 1 1 2 4H2'/>"
            "<path d='M9.8 4.4A2 2 0 1 1 11 8H2'/>",
    "table": "<path d='M12 3v18'/><rect width='18' height='18' x='3' y='3' rx='2'/>"
             "<path d='M3 9h18'/><path d='M3 15h18'/>",
    "history": "<path d='M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8'/><path d='M3 3v5h5'/>"
               "<path d='M12 7v5l4 2'/>",
    "sun": "<circle cx='12' cy='12' r='4'/><path d='M12 2v2'/><path d='M12 20v2'/>"
           "<path d='m4.93 4.93 1.41 1.41'/><path d='m17.66 17.66 1.41 1.41'/><path d='M2 12h2'/>"
           "<path d='M20 12h2'/><path d='m6.34 17.66-1.41 1.41'/><path d='m19.07 4.93-1.41 1.41'/>",
    "moon": "<path d='M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z'/>",
}


def icon_img(name: str, color: str = INK_MUTED, size: int = 20, stroke: float = 2) -> str:
    """Ikona jako <img> s data URI (st.html vyřezává inline <svg>)."""
    svg = (
        f"<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' "
        f"stroke='{color}' stroke-width='{stroke}' stroke-linecap='round' "
        f"stroke-linejoin='round'>{ICONS[name]}</svg>"
    )
    data = base64.b64encode(svg.encode()).decode()
    return (f"<img src='data:image/svg+xml;base64,{data}' width='{size}' height='{size}' "
            f"alt='' style='display:block'>")


def icon_badge(name: str, tone: str = "accent", size: int = 46) -> str:
    """Kulatý odznak s ikonou jako v hlavičkách karet SunnyHome."""
    color = TONES.get(tone, tone)
    return (
        f"<div class='sh-badge' style='width:{size}px;height:{size}px;background:{color}1f;"
        f"box-shadow:0 0 18px {color}22 inset;'>{icon_img(name, color, int(size * 0.44))}</div>"
    )


def pill(text: str, tone: str = "accent") -> str:
    color = TONES.get(tone, tone)
    return f"<span class='sh-pill' style='color:{color};background:{color}24'>{text}</span>"


def chip(text: str, icon: str | None = None) -> str:
    icon_html = icon_img(icon, INK_MUTED, 15) if icon else ""
    return f"<span class='sh-chip'>{icon_html}{text}</span>"


def card_header_html(
    title: str, subtitle: str | None = None, icon: str | None = None,
    tone: str = "accent", aside: str | None = None,
) -> str:
    badge = icon_badge(icon, tone) if icon else ""
    sub = f"<p>{subtitle}</p>" if subtitle else ""
    side = f"<div class='sh-card-aside'>{aside}</div>" if aside else ""
    return (
        f"<div class='sh-card-head'>{badge}<div class='sh-card-title'><h2>{title}</h2>{sub}</div>"
        f"{side}</div>"
    )


_card_counter: dict[str, int] = {}


@contextmanager
def card(
    title: str | None = None, subtitle: str | None = None, icon: str | None = None,
    tone: str = "accent", aside: str | None = None, accent_top: str | None = None,
) -> Iterator[None]:
    """Karta (st.container) s hlavičkou: ikona v kroužku, titulek, podtitul."""
    slug = re.sub(r"[^a-z0-9]+", "-", (title or "karta").lower()).strip("-") or "karta"
    n = _card_counter.get(slug, 0)
    _card_counter[slug] = n + 1
    key = f"card-{slug}-{n}" + (f"-top-{accent_top}" if accent_top else "")
    with st.container(border=True, key=key):
        if title:
            st.html(card_header_html(title, subtitle, icon, tone, aside))
        yield


def reset_cards() -> None:
    """Klíče karet se počítají od nuly při každém běhu skriptu."""
    _card_counter.clear()


def readout_table(
    rows: list[dict], columns: tuple[str, str] = ("Teď", "Maximum"),
) -> str:
    """Tabulka hodnot pod grafem: barevná čárka, název, hodnota teď a extrém s časem.

    rows: {"color", "label", "note", "now", "now_time", "peak", "peak_time"}
    """
    head = (f"<div class='sh-rt-row sh-rt-head'><span></span><span>{columns[0]}</span>"
            f"<span>{columns[1]}</span></div>")
    body = []
    for r in rows:
        note = f"<em>{r['note']}</em>" if r.get("note") else ""
        body.append(
            f"<div class='sh-rt-row'><span class='sh-rt-name'><i style='background:{r['color']}'>"
            f"</i>{r['label']}{note}</span>"
            f"<span><b>{r.get('now', '—')}</b><small>{r.get('now_time', '')}</small></span>"
            f"<span><b>{r.get('peak', '—')}</b><small>{r.get('peak_time', '')}</small></span></div>"
        )
    return f"<div class='sh-rt'>{head}{''.join(body)}</div>"


def status_box(kicker: str, value: str, note: str = "", tone: str = "battery") -> str:
    """Zvýrazněný stav (jako plan-status v SunnyHome)."""
    color = TONES.get(tone, tone)
    return (
        f"<div class='sh-status' style='background:linear-gradient(135deg,{color}26,"
        f"{SURFACE_RAISED} 60%);border-color:{color}59'><small style='color:{color}'>"
        f"{kicker}</small><b>{value}</b><span>{note}</span></div>"
    )


def rank_list(items: list[tuple[str, str]], tone: str) -> str:
    """Seznam pořadí (čas → hodnota) v řádcích karty."""
    color = TONES.get(tone, tone)
    rows = "".join(
        f"<div class='sh-rank'><span class='sh-rank-n'>{i}</span><span>{escape(label)}</span>"
        f"<b style='color:{color}'>{value}</b></div>"
        for i, (label, value) in enumerate(items, start=1)
    )
    return f"<div class='sh-ranks'>{rows}</div>"


CSS = f"""
<style>
  .stApp {{ background:
      radial-gradient(1200px 500px at 70% -10%, {ACCENT}14, transparent 60%), {BG}; }}
  [data-testid="stHeader"] {{ background: transparent; }}
  .block-container {{ padding-top: 2.2rem; max-width: 1320px; }}
  h1, h2, h3 {{ letter-spacing: 0 !important; }}
  h3 {{ font-size: 1.05rem !important; font-weight: 500 !important;
        color: {ACCENT_INK} !important; }}
  hr {{ border-color: {BORDER} !important; }}
  [data-testid="stCaptionContainer"], .stCaption {{ color: {INK_MUTED} !important; }}

  /* Karty */
  [class*="st-key-card-"] {{
      background: {SURFACE}; border: 1px solid {BORDER} !important; border-radius: 14px !important;
      box-shadow: inset 0 1px 0 #ffffff0a, 0 10px 30px #02061273; padding: 20px !important;
  }}
  /* Sloupce s kartami se při nedostatku místa zalomí pod sebe */
  [data-testid="stHorizontalBlock"]:has([class*="st-key-card-"]) {{ flex-wrap:wrap; }}
  [data-testid="stHorizontalBlock"]:has([class*="st-key-card-"]) > [data-testid="stColumn"] {{
      min-width:min(100%, 400px); }}
  [class*="-top-solar"] {{ border-top: 3px solid {SOLAR} !important; }}
  [class*="-top-accent"] {{ border-top: 3px solid {ACCENT} !important; }}
  [class*="-top-home"] {{ border-top: 3px solid {HOME} !important; }}
  .sh-card-head {{ display:flex; align-items:center; gap:14px; margin-bottom:4px; }}
  .sh-badge {{ border-radius:50%; display:grid; place-items:center; flex:none; }}
  .sh-card-title {{ min-width:0; }}
  .sh-card-title h2 {{ margin:0; font-size:17px !important; font-weight:500 !important;
                       line-height:24px; color:{INK} !important; padding:0 !important; }}
  .sh-card-title p {{ margin:0; font-size:12.5px; line-height:17px; color:{INK_MUTED}; }}
  .sh-card-aside {{ margin-left:auto; color:{INK_MUTED}; font-size:13px; text-align:right; }}

  /* Pilulky a čipy */
  .sh-pill {{ display:inline-flex; align-items:center; gap:6px; height:24px; padding:0 10px;
              border-radius:8px; font-size:12px; font-weight:500; white-space:nowrap; }}
  .sh-chip {{ display:inline-flex; align-items:center; gap:8px; min-height:34px; padding:4px 12px;
              border:1px solid {BORDER}; border-radius:10px; background:{SURFACE_RAISED};
              color:{INK}; font-size:12px; }}

  /* Metriky jako odečty */
  [data-testid="stMetric"] {{ background:{SURFACE_RAISED}; border:1px solid {BORDER};
      border-radius:10px; padding:12px 16px; }}
  [data-testid="stMetricLabel"] p {{ font-size:12px !important; color:{INK_MUTED} !important; }}
  [data-testid="stMetricValue"] {{ color:{INK}; }}
  [data-testid="stMetricValue"] > div, [data-testid="stMetricLabel"] *,
  [data-testid="stMetricDelta"] * {{ white-space:normal !important; overflow:visible !important;
      text-overflow:clip !important; line-height:1.3; }}

  /* Tabulka hodnot pod grafem */
  .sh-rt {{ margin-top:6px; font-size:13.5px; }}
  .sh-rt-row {{ display:grid; grid-template-columns:minmax(0,1.6fr) 1fr 1fr; gap:10px;
               align-items:center; padding:8px 2px; border-top:1px solid {BORDER}; }}
  .sh-rt-head {{ border-top:none; color:{INK_MUTED}; font-size:12px; padding-bottom:2px; }}
  .sh-rt-row > span:not(.sh-rt-name) {{ text-align:right; white-space:nowrap; }}
  .sh-rt-name {{ display:flex; align-items:center; gap:10px; font-weight:500; }}
  .sh-rt-name i {{ width:18px; height:4px; border-radius:4px; flex:none; }}
  .sh-rt-name em {{ font-style:normal; color:{INK_MUTED}; font-size:12px; font-weight:400; }}
  .sh-rt small {{ color:{INK_MUTED}; margin-left:8px; font-size:12px; }}

  .sh-rt {{ container-type:inline-size; }}
  @container (max-width: 440px) {{
    .sh-rt-row {{ font-size:12.5px; grid-template-columns:minmax(0,1.3fr) 1fr 1fr; gap:6px; }}
    .sh-rt-name em, .sh-rt small {{ display:none; }}
    .sh-rt-name {{ gap:6px; }}
  }}

  /* Zvýrazněný stav */
  .sh-status {{ border:1px solid; border-radius:14px; padding:14px 20px; }}
  .sh-status small {{ display:block; font-size:11px; font-weight:600; letter-spacing:1px;
                      text-transform:uppercase; }}
  .sh-status b {{ display:block; font-size:24px; font-weight:700; line-height:1.25; margin:2px 0; }}
  .sh-status span {{ color:{INK_MUTED}; font-size:13px; }}

  /* Pořadí hodin */
  .sh-ranks {{ display:flex; flex-direction:column; gap:6px; }}
  .sh-rank {{ display:flex; align-items:center; gap:12px; padding:9px 14px; border-radius:10px;
              background:{SURFACE_RAISED}; border:1px solid {BORDER}; }}
  .sh-rank b {{ margin-left:auto; font-weight:600; }}
  .sh-rank-n {{ width:22px; height:22px; border-radius:50%; display:grid; place-items:center;
                background:{BORDER}; color:{INK_MUTED}; font-size:11px; }}

  /* Hlavička stránky */
  .sh-page {{ display:flex; align-items:flex-end; justify-content:space-between; gap:16px;
              flex-wrap:wrap; margin-bottom:6px; }}
  .sh-page h1 {{ font-size:26px !important; font-weight:600 !important; margin:0 !important;
                 padding:0 !important; }}
  .sh-page p {{ margin:2px 0 0; color:{INK_MUTED}; font-size:13px; }}

  /* Logo a navigace v sidebaru */
  img[data-testid="stSidebarLogo"] {{ height:46px !important; max-width:230px !important; }}
  [data-testid="stLogoLink"] {{ height:auto !important; }}
  [data-testid="stSidebarHeader"] {{ height:auto !important; margin-bottom:12px; }}
  [data-testid="stSidebarNav"] a {{ border-radius:12px; padding:10px 14px; margin:2px 0;
      border:1px solid transparent; }}
  [data-testid="stSidebarNav"] a span {{ color:{INK} !important; font-size:15px; }}
  [data-testid="stSidebarNav"] a:hover {{ background:{SURFACE_RAISED}; }}
  [data-testid="stSidebarNav"] a[aria-current="page"] {{
      background:linear-gradient(180deg,#2563eb,#1f4fb8); border-color:#6ea8ff99;
      box-shadow:0 0 0 2px #3b82f633, 0 8px 24px #1f4fb855; }}
  [data-testid="stSidebarNav"] a[aria-current="page"] span {{ color:#fff !important;
      font-weight:500; }}
  [data-testid="stSidebarNav"] a [data-testid="stIconMaterial"] {{ color:{INK_MUTED}; }}
  [data-testid="stSidebarNav"] a[aria-current="page"] [data-testid="stIconMaterial"] {{
      color:#fff; }}
  [data-testid="stSidebar"] h2, [data-testid="stSidebar"] h3 {{ font-size:13px !important;
      color:{INK_MUTED} !important; text-transform:uppercase; letter-spacing:.8px !important; }}

  /* Expandery a záložky */
  [data-testid="stExpander"] details {{ border:1px solid {BORDER} !important; border-radius:10px;
      background:{SURFACE_RAISED}; }}
  [data-testid="stTabs"] [role="tab"] {{ font-weight:500; }}
</style>
"""


def inject_css() -> None:
    st.markdown(CSS, unsafe_allow_html=True)


def page_header(title: str, subtitle: str, aside: str = "") -> None:
    st.html(f"<div class='sh-page'><div><h1>{title}</h1><p>{subtitle}</p></div>"
            f"<div>{aside}</div></div>")


@alt.theme.register("sunnyhome", enable=True)
def sunnyhome_theme() -> alt.theme.ThemeConfig:
    axis = {
        "domain": False, "ticks": False, "gridColor": BORDER, "gridOpacity": 0.9,
        "labelColor": INK_MUTED, "labelFontSize": 11, "labelFont": "Poppins",
        "titleColor": INK_MUTED, "titleFontSize": 11, "titleFontWeight": 400,
        "titleFont": "Poppins", "labelPadding": 6,
    }
    return alt.theme.ThemeConfig({
        "config": {
            "background": "transparent",
            "font": "Poppins",
            "view": {"stroke": None},
            "axis": axis,
            "axisX": {"grid": True},
            "axisY": {"grid": True},
            "legend": {"labelColor": INK, "titleColor": INK_MUTED, "labelFont": "Poppins",
                       "titleFont": "Poppins", "labelFontSize": 12, "titleFontWeight": 400,
                       "symbolType": "stroke", "symbolStrokeWidth": 4, "orient": "bottom"},
            "title": {"color": INK, "font": "Poppins", "fontSize": 14, "fontWeight": 500,
                      "anchor": "start", "offset": 12},
            "line": {"strokeWidth": 2.2, "strokeCap": "round", "strokeJoin": "round"},
            "bar": {"cornerRadiusTopLeft": 4, "cornerRadiusTopRight": 4},
            "range": {"category": [ACCENT, SOLAR, HOME, GRID, BATTERY, READOUT, ACCENT_INK]},
            "text": {"color": INK, "font": "Poppins"},
        }
    })


def show_chart(chart: alt.TopLevelMixin) -> None:
    """Altair graf s tématem SunnyHome (Streamlit téma by ho přebilo)."""
    st.altair_chart(chart, use_container_width=True, theme=None)
