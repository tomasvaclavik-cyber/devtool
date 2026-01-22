# OTE

[![CI](https://github.com/tomasvaclavik-cyber/devtool/actions/workflows/ci.yml/badge.svg)](https://github.com/tomasvaclavik-cyber/devtool/actions/workflows/ci.yml)

CLI nástroj pro zobrazení spotových cen elektřiny z OTE (Operátor trhu s elektřinou) v CZK.

## Instalace

```bash
git clone https://github.com/tomasvaclavik-cyber/devtool.git
cd devtool
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

## Použití

```bash
ote spot              # aktuální spotová cena
ote spot --all        # všechny 15min intervaly
ote spot -d 2026-01-21  # data pro konkrétní den
```

## Zdroje dat

- **OTE** (ote-cr.cz) - spotové ceny elektřiny
- **ČNB** (cnb.cz) - kurz EUR/CZK
