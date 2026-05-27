"""
NEWS FETCHER - Value Signal
============================
Obtiene noticias de las empresas del watchlist desde Google News RSS,
filtrando por sitio (Diario Financiero, La Tercera, El Mercurio).

Salida: noticias_watchlist.json (consumido por el dashboard)

Frecuencia recomendada: cada 2-3 horas via tarea programada.
"""
import json
import logging
import re
import subprocess
import urllib.parse
import unicodedata
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
LOG_DIR = SCRIPT_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)
LOG_FILE = LOG_DIR / "news.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger(__name__)

# ============================================================
# CONFIGURACION
# ============================================================

# Diccionario: ticker -> lista de keywords a buscar
# Cada keyword se buscara con comillas (frase exacta) en Google News
WATCHLIST_KEYWORDS = {
    "HABITAT":    ["AFP Habitat"],
    "ZOFRI":      ["Zofri"],
    "PEHUENCHE":  ["Central Pehuenche", "Pehuenche electrica"],
    "TRICAHUE":   ["fondo Tricahue", "Tricahue Capital"],
    "COLBUN":     ["Colbun"],
    "ENELGXCH":   ["Enel Generacion Chile", "Enel Chile"],
    "LIPIGAS":    ["Empresas Lipigas", "Lipigas"],
    "NTGCLGAS":   ["Gasco"],
    "SOQUICOM":   ["SQM", "Soquimich"],
    "QUINENCO":   ["Quinenco"],
    "CENCOMALLS": ["Cencosud Shopping", "Cencomalls"],
}

# Sitios objetivo (3 medios principales)
SITIOS = [
    {"name": "Diario Financiero", "domain": "df.cl"},
    {"name": "La Tercera",        "domain": "latercera.com"},
    {"name": "El Mercurio",       "domain": "elmercurio.com"},
]

# Solo noticias de los ultimos N dias
DIAS_VENTANA = 7

# Google News RSS endpoint
BASE_URL = "https://news.google.com/rss/search"

OUTPUT_FILE = SCRIPT_DIR / "noticias_watchlist.json"

# ============================================================
# FETCH
# ============================================================

def build_query_url(keyword, site):
    """Construye URL del feed RSS de Google News para keyword + site."""
    query = f'"{keyword}" site:{site}'
    params = {
        "q": query,
        "hl": "es-CL",
        "gl": "CL",
        "ceid": "CL:es-419",
    }
    return f"{BASE_URL}?{urllib.parse.urlencode(params)}"


def fetch_rss(url, timeout=20):
    """Descarga RSS y devuelve string XML."""
    req = urllib.request.Request(
        url, headers={"User-Agent": "Mozilla/5.0 (Value Signal News Fetcher)"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def parse_rss(xml_text):
    """Parsea XML RSS y devuelve lista de items."""
    items = []
    try:
        root = ET.fromstring(xml_text)
        for item in root.iter("item"):
            title_el = item.find("title")
            link_el = item.find("link")
            pubdate_el = item.find("pubDate")
            source_el = item.find("source")

            title = (title_el.text or "").strip() if title_el is not None else ""
            link = (link_el.text or "").strip() if link_el is not None else ""
            pubdate = (pubdate_el.text or "").strip() if pubdate_el is not None else ""
            source = (source_el.text or "").strip() if source_el is not None else ""

            if title and link:
                items.append({
                    "title": title,
                    "link": link,
                    "pubdate": pubdate,
                    "source": source,
                })
    except ET.ParseError as e:
        log.warning(f"  Error parseando XML: {e}")
    return items


def parse_pubdate(pubdate_str):
    """Convierte 'Wed, 27 May 2026 19:49:00 GMT' -> datetime aware."""
    try:
        return datetime.strptime(pubdate_str, "%a, %d %b %Y %H:%M:%S %Z").replace(
            tzinfo=timezone.utc
        )
    except (ValueError, TypeError):
        return None


def is_reciente(item, cutoff):
    """True si la noticia es mas reciente que cutoff."""
    dt = parse_pubdate(item.get("pubdate"))
    if dt is None:
        return False
    return dt >= cutoff


def clean_title(title):
    """Limpia el sufijo ' - Nombre Medio' que agrega Google al final."""
    # Patrones: " - Diario Financiero", " - La Tercera", etc.
    title = re.sub(r"\s+-\s+(Diario Financiero|La Tercera|El Mercurio|Pulso).*$", "", title)
    return title.strip()


def normalizar(s):
    """Quita tildes y baja a minusculas para comparar."""
    nfkd = unicodedata.normalize("NFKD", s)
    return "".join(c for c in nfkd if not unicodedata.combining(c)).lower()


def es_titulo_basura(title):
    """Filtra titulos genericos como 'Ultimas noticias', 'Untitled', etc."""
    basura = [
        "ultimas noticias",
        "ultima hora",
        "lo que debes saber",
        "untitled",
        "noticias escritas por",
        "noticias de ",
        "noticias sobre ",
        ". noticias",
        "talento local",
        "cuales son las organizaciones",
    ]
    t = normalizar(title)
    return any(b in t for b in basura)


# ============================================================
# MAIN
# ============================================================

def main():
    log.info("=" * 60)
    log.info("=== News Fetcher - Value Signal ===")
    log.info(f"Hora: {datetime.now().isoformat()}")
    log.info(f"Ventana: ultimos {DIAS_VENTANA} dias")
    log.info(f"Medios: {[s['name'] for s in SITIOS]}")
    log.info(f"Watchlist: {list(WATCHLIST_KEYWORDS.keys())}")

    cutoff = datetime.now(timezone.utc) - timedelta(days=DIAS_VENTANA)
    log.info(f"Cutoff fecha: {cutoff.isoformat()}")

    resultado = {
        "updated_at_utc": datetime.now(timezone.utc).isoformat(),
        "ventana_dias": DIAS_VENTANA,
        "medios": [s["name"] for s in SITIOS],
        "noticias_por_ticker": {},
        "stats": {
            "total_queries": 0,
            "queries_exitosas": 0,
            "queries_falladas": 0,
            "total_noticias_brutas": 0,
            "total_noticias_filtradas": 0,
        },
    }

    seen_links = set()  # para dedupe global

    for ticker, keywords in WATCHLIST_KEYWORDS.items():
        log.info(f"--- {ticker} ---")
        noticias_ticker = []

        for keyword in keywords:
            for sitio in SITIOS:
                resultado["stats"]["total_queries"] += 1
                url = build_query_url(keyword, sitio["domain"])
                try:
                    xml = fetch_rss(url)
                    items = parse_rss(xml)
                    resultado["stats"]["queries_exitosas"] += 1
                    resultado["stats"]["total_noticias_brutas"] += len(items)
                    log.info(f"  '{keyword}' @ {sitio['domain']}: {len(items)} items brutos")

                    for item in items:
                        # Filtro 1: reciente
                        if not is_reciente(item, cutoff):
                            continue
                        # Filtro 2: dedupe por link
                        if item["link"] in seen_links:
                            continue
                        # Filtro 3: titulo no basura
                        clean = clean_title(item["title"])
                        if es_titulo_basura(clean):
                            continue

                        seen_links.add(item["link"])
                        noticias_ticker.append({
                            "title": clean,
                            "link": item["link"],
                            "pubdate": item["pubdate"],
                            "source": item["source"] or sitio["name"],
                            "matched_keyword": keyword,
                        })
                except Exception as e:
                    resultado["stats"]["queries_falladas"] += 1
                    log.warning(f"  '{keyword}' @ {sitio['domain']}: ERROR {e}")

        # Ordenar por fecha descendente
        noticias_ticker.sort(
            key=lambda x: parse_pubdate(x["pubdate"]) or datetime.min.replace(tzinfo=timezone.utc),
            reverse=True,
        )

        resultado["noticias_por_ticker"][ticker] = noticias_ticker
        resultado["stats"]["total_noticias_filtradas"] += len(noticias_ticker)
        log.info(f"  {ticker}: {len(noticias_ticker)} noticias relevantes")

    # Guardar
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(resultado, f, ensure_ascii=False, indent=2)

    log.info("-" * 60)
    log.info(f"Guardado: {OUTPUT_FILE}")
    log.info(f"Stats: {resultado['stats']}")
    log.info(f"=== FIN ({datetime.now().strftime('%H:%M:%S')}) ===")


if __name__ == "__main__":
    main()
