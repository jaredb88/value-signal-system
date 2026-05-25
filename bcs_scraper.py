"""
BCS PRICE SCRAPER - Standalone (v2 con debug)
==============================================
Versión simplificada del scraper de Bolsa de Santiago.
"""

import asyncio
import json
import sys
import time
import logging
from typing import Optional

from playwright.async_api import async_playwright

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
log = logging.getLogger(__name__)

# Configuración
TIMEOUT_CAPTURA_SEGS = 90  # Aumentado de 45 a 90
HEADLESS = True


async def fetch_bcs_resumen(nemo: str, debug: bool = True) -> Optional[dict]:
    """
    Obtiene el resumen del instrumento desde Bolsa de Santiago.
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
                "--disable-features=IsolateOrigins,site-per-process",
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
            extra_http_headers={
                "Accept-Language": "es-CL,es;q=0.9,en;q=0.8",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            },
        )
        await context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )
        page = await context.new_page()

        # Loggear TODAS las URLs para diagnóstico
        all_urls = []
        captured = {"resumen": None, "status": None}

        async def on_response(response):
            url = response.url
            status = response.status

            # Guardar todas las URLs (limitado)
            if len(all_urls) < 50:
                # Solo URLs interesantes (no imágenes/css/etc)
                if any(kw in url.lower() for kw in ['api', 'get', '.json', 'instrumento', 'resumen', 'capital']):
                    all_urls.append(f"[{status}] {url[:150]}")

            if "getResumenInstrumento" in url and captured["resumen"] is None:
                try:
                    post_data = response.request.post_data or ""
                    log.info(f"  >>> Detectado getResumenInstrumento, POST data: {post_data[:200]}")
                    if nemo not in post_data.upper():
                        log.warning(f"  >>> POST data NO contiene {nemo}")
                        return
                    body = await response.text()
                    captured["status"] = status
                    if status == 200:
                        data = json.loads(body)
                        items = data.get("listaResult", [])
                        captured["resumen"] = items[0] if items else {}
                        log.info(f"  OK Capturado getResumenInstrumento ({len(items)} items)")
                    else:
                        log.warning(f"  Status incorrecto: {status}")
                        log.warning(f"  Body: {body[:300]}")
                except Exception as e:
                    log.error(f"Error parseando: {e}")

        page.on("response", on_response)

        # Paso 1: visitar la home primero (warming up)
        log.info("  Paso 1: visitar home...")
        try:
            await page.goto(
                "https://www.bolsadesantiago.com/",
                wait_until="domcontentloaded",
                timeout=30000,
            )
            await page.wait_for_timeout(3000)
        except Exception as e:
            log.warning(f"  home goto warning: {e}")

        # Paso 2: ir a la página del instrumento
        log.info(f"  Paso 2: navegar a /resumen_instrumento/{nemo}")
        t0 = time.time()
        try:
            await page.goto(
                f"https://www.bolsadesantiago.com/resumen_instrumento/{nemo}",
                wait_until="domcontentloaded",
                timeout=60000,
            )
        except Exception as e:
            log.warning(f"  instrumento goto warning: {e}")

        # Esperar a que llegue la respuesta XHR
        deadline = t0 + TIMEOUT_CAPTURA_SEGS
        while captured["resumen"] is None and time.time() < deadline:
            await page.wait_for_timeout(1500)

        elapsed = time.time() - t0
        log.info(f"  fetch total tomó {elapsed:.1f}s")

        # Debug: mostrar URLs vistas
        if captured["resumen"] is None and debug:
            log.warning(f"  >>> URLs interesantes detectadas durante el fetch:")
            for u in all_urls[:20]:
                log.warning(f"    {u}")
            if not all_urls:
                log.warning(f"    (ninguna URL relevante detectada)")

            # Tomar screenshot para debugging
            try:
                screenshot_path = f"/tmp/bcs_{nemo}_fail.png"
                await page.screenshot(path=screenshot_path, full_page=False)
                log.info(f"  Screenshot guardado en {screenshot_path}")
            except Exception:
                pass

            # Loggear título y URL actual
            try:
                title = await page.title()
                current_url = page.url
                log.info(f"  Página actual: {title}")
                log.info(f"  URL actual: {current_url}")
            except Exception:
                pass

        await browser.close()

        return captured["resumen"]


def extraer_datos_precio(resumen: dict, nemo: str) -> dict:
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

    print("=" * 60)
    print("RESULTADOS FINALES")
    print("=" * 60)
    print(json.dumps(resultados, indent=2, ensure_ascii=False, default=str))


if __name__ == "__main__":
    asyncio.run(main())
