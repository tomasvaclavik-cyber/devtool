# OTE

[![CI](https://github.com/tomasvaclavik-cyber/devtool/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/tomasvaclavik-cyber/devtool/actions/workflows/ci.yml)
[![Daily OTE Save](https://github.com/tomasvaclavik-cyber/devtool/actions/workflows/daily-save.yml/badge.svg?branch=main)](https://github.com/tomasvaclavik-cyber/devtool/actions/workflows/daily-save.yml)

CLI nástroj pro zobrazení spotových cen elektřiny z OTE (Operátor trhu s elektřinou) v CZK.

## Instalace

```bash
git clone https://github.com/tomasvaclavik-cyber/devtool.git
cd devtool
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

Pro webový dashboard:
```bash
pip install -e ".[dashboard]"
```

## Použití

### Aktuální ceny

```bash
ote spot              # aktuální spotová cena
ote spot --all        # všechny 15min intervaly
ote spot -d 2026-01-21  # data pro konkrétní den
```

### Ukládání do databáze

```bash
ote save              # uloží dnešní data do SQLite
ote save -d 2026-01-21  # uloží konkrétní den
```

### Historie

```bash
ote history           # přehled všech uložených dnů
ote history -d 2026-01-22  # detail konkrétního dne
```

### Web Dashboard

```bash
ote dashboard         # spustí na http://localhost:8501
ote dashboard -p 8080 # vlastní port
```

Funkce dashboardu:
- Interaktivní grafy cen během dne
- Přepínání mezi živými daty (API) a historií (databáze)
- Statistiky (min, max, průměr)
- Porovnání posledních dnů

## Automatické stahování dat

Data se automaticky stahují každý den v 6:00 UTC pomocí GitHub Actions a ukládají do [`data/prices.db`](data/prices.db).

## Zdroje dat

- **OTE** (ote-cr.cz) - spotové ceny elektřiny (15min intervaly)
- **ČNB** (cnb.cz) - kurz EUR/CZK
- https://devtool-7b3d8cdtfvqgw9u5ns5vze.streamlit.app/
