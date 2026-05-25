"""
BCS PRICE SCRAPER - Standalone
================================
Versión simplificada del scraper de Bolsa de Santiago, adaptado del MCP
local de Jared (C:\\mcp-bolsa\\server.py) para correr en GitHub Actions.

Estrategia:
- Lanza Chromium headless con Playwright
- Navega a https://www.bolsadesantiago.com/resumen_instrumento/<TICKER>
- Intercepta la respuesta XHR de "getResumenInstrumento"
- Extrae el precio oficial de cierre/actual
- Devuelve un dict con los datos

Uso:
    python bcs_scraper.py CFISPETF
    python bcs_scraper.py CFINASDAQ
"""

import asyncio
import json
import sys
import time
import logging
from typing import Optional

from playwright.async_api import async_playwright

# Logging básico (visible en GitHub Actions)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
log = logging.getLogger(__name__)

# Configuración
TIMEOUT_CAPTURA_SEGS = 45
HEADLESS = True


async def fetch_bcs_resumen(nemo: str) -> Optional[dict]:
    """
    Obtiene el resumen del instrumento desde Bolsa de Santiago.
    Devuelve un dict con los campos o None si falla.
    """
    nemo = nemo.upper()
    log.info(f"Iniciando scraping para {nemo}")

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=HEADLESS,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--no-sandbox",
            ],
        )
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            locale="es-CL",
            viewport={"width": 1920, "height": 1080},
        )
        await context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )
        page = await context.new_page()

        # Variable para capturar la respuesta XHR
        captured = {"resumen": None, "status": None}

        async def on_response(response):
            url = response.url
            if "getResumenInstrumento" in url and captured["resumen"] is None:
                try:
                    post_data = response.request.post_data or ""
                    # Solo capturamos si el POST data contiene nuestro ticker
                    if nemo not in post_data.upper():
                        return
                    body = await response.text()
                    captured["status"] = response.status
                    if response.status == 200:
                        data = json.loads(body)
                        items = data.get("listaResult", [])
                        captured["resumen"] = items[0] if items else {}
                        log.info(f"  Capturado getResumenInstrumento OK")
                    else:
                        log.warning(f"  getResumenInstrumento status {response.status}")
                except Exception as e:
                    log.error(f"Error parseando: {e}")

        page.on("response", on_response)

        # Navegar a la página
        t0 = time.time()
        try:
            await page.goto(
                f"https://www.bolsadesantiago.com/resumen_instrumento/{nemo}",
                wait_until="domcontentloaded",
                timeout=60000,
            )
        except Exception as e:
            log.warning(f"goto warning: {e}")

        # Esperar a que llegue la respuesta XHR
        deadline = t0 + TIMEOUT_CAPTURA_SEGS
        while captured["resumen"] is None and time.time() < deadline:
            await page.wait_for_timeout(1500)

        page.remove_listener("response", on_response)
        elapsed = time.time() - t0
        log.info(f"  fetch tomó {elapsed:.1f}s")

        await browser.close()

        return captured["resumen"]


def extraer_datos_precio(resumen: dict, nemo: str) -> dict:
    """
    Extrae los campos relevantes de precio desde el dict del resumen.
    Devuelve un dict normalizado.
    """
    if not resumen:
        return {
            "ticker": nemo,
            "precio_cierre": None,
            "precio_actual": None,
            "razon_social": nemo,
            "fecha": None,
            "fuente": "BCS",
            "error": "Sin datos del scraper",
        }

    precio_cierre = resumen.get("PRECIO_CIERRE")
    precio_actual = resumen.get("PRECIO_COMPRA") or resumen.get("PRECIO_VENTA") or precio_cierre

    return {
        "ticker": nemo,
        "precio_cierre": float(precio_cierre) if precio_cierre else None,
        "precio_actual": float(precio_actual) if precio_actual else None,
        "razon_social": resumen.get("RAZON_SOCIAL", nemo),
        "moneda": resumen.get("MONEDA", "CLP"),
        "variacion_pct": resumen.get("VARIACION"),
        "monto_transado": resumen.get("MONTO_MONEDA"),
        "fecha_dato": resumen.get("FECHA_HORA_INFORMACION"),
        "fuente": "BCS",
        "error": None,
    }


async def main():
    if len(sys.argv) < 2:
        print("Uso: python bcs_scraper.py <TICKER1> [TICKER2] ...")
        print("Ej:  python bcs_scraper.py CFISPETF CFINASDAQ")
        sys.exit(1)

    tickers = sys.argv[1:]
    resultados = {}

    for ticker in tickers:
        log.info(f"=== Procesando {ticker} ===")
        try:
            resumen = await fetch_bcs_resumen(ticker)
            datos = extraer_datos_precio(resumen, ticker)
            resultados[ticker] = datos
            log.info(f"  Precio cierre: {datos['precio_cierre']}")
        except Exception as e:
            log.error(f"  ERROR scraping {ticker}: {e}")
            resultados[ticker] = {
                "ticker": ticker,
                "error": str(e),
                "fuente": "BCS",
            }

    # Imprimir resultados como JSON (para que GitHub Actions lo capture)
    print("=" * 60)
    print("RESULTADOS FINALES")
    print("=" * 60)
    print(json.dumps(resultados, indent=2, ensure_ascii=False, default=str))


if __name__ == "__main__":
    asyncio.run(main())
