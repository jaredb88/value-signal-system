"""
UPDATE PRICES - Orquestador
============================
Ejecuta el scraper de Bolsa de Santiago para los ETFs configurados
y guarda los precios en prices.json para que Streamlit los lea.

Uso:
    python update_prices.py

Se ejecuta automaticamente cada hora via GitHub Actions.
"""

import asyncio
import json
import sys
import logging
from datetime import datetime, timezone
from pathlib import Path

from bcs_scraper import fetch_bcs_resumen, extraer_datos_precio

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
log = logging.getLogger(__name__)

# ETFs a actualizar
TICKERS = ["CFISPETF", "CFINASDAQ"]

# Archivo de salida
SCRIPT_DIR = Path(__file__).parent
OUTPUT_FILE = SCRIPT_DIR / "prices.json"


async def main():
    log.info("=== Update Prices ===")
    log.info(f"Hora UTC: {datetime.now(timezone.utc).isoformat()}")
    log.info(f"Tickers a actualizar: {TICKERS}")

    # Cargar datos previos si existen (para preservar histórico)
    previous_data = {}
    if OUTPUT_FILE.exists():
        try:
            with open(OUTPUT_FILE, 'r', encoding='utf-8') as f:
                previous_data = json.load(f)
            log.info(f"Cargado prices.json previo")
        except Exception as e:
            log.warning(f"No se pudo cargar prices.json previo: {e}")

    # Scrapear cada ticker
    new_prices = {}
    errores = []

    for ticker in TICKERS:
        log.info(f"--- Scraping {ticker} ---")
        try:
            resumen = await fetch_bcs_resumen(ticker)
            datos = extraer_datos_precio(resumen, ticker)

            if datos.get("precio_cierre") is not None or datos.get("precio_actual") is not None:
                new_prices[ticker] = datos
                log.info(f"  OK: precio cierre {datos.get('precio_cierre')}")
            else:
                errores.append(f"{ticker}: sin precio en la respuesta")
                log.warning(f"  Sin precio para {ticker}")
                # Conservar dato previo si existe
                if ticker in previous_data.get("prices", {}):
                    new_prices[ticker] = previous_data["prices"][ticker]
                    new_prices[ticker]["stale"] = True
                    log.info(f"  Usando precio previo (stale)")
        except Exception as e:
            errores.append(f"{ticker}: {str(e)}")
            log.error(f"  ERROR: {e}")
            # Conservar dato previo si existe
            if ticker in previous_data.get("prices", {}):
                new_prices[ticker] = previous_data["prices"][ticker]
                new_prices[ticker]["stale"] = True

    # Construir el JSON final
    output_data = {
        "updated_at_utc": datetime.now(timezone.utc).isoformat(),
        "updated_at_chile": datetime.now(timezone.utc).astimezone(
            tz=datetime.now(timezone.utc).astimezone().tzinfo
        ).isoformat(),
        "tickers_solicitados": TICKERS,
        "errores": errores,
        "prices": new_prices,
    }

    # Guardar
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, indent=2, ensure_ascii=False, default=str)

    log.info(f"=== Guardado en {OUTPUT_FILE.name} ===")

    # Resumen final
    log.info("Resumen:")
    for ticker, data in new_prices.items():
        precio = data.get("precio_cierre") or data.get("precio_actual") or "N/A"
        stale = " (STALE)" if data.get("stale") else ""
        log.info(f"  {ticker}: ${precio} CLP{stale}")

    if errores:
        log.warning(f"Errores: {errores}")
        # No fallar el workflow, solo loggear

    # Exit code 0 si al menos un ticker funcionó
    if new_prices:
        return 0
    else:
        log.error("Ningún ticker se actualizó correctamente")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
