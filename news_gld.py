"""
Fetch noticias macro relacionadas con el oro (GLD) desde Google News RSS.
Cubre: precio del oro, Fed/tasas, inflacion, DXY, geopolitica, bancos
centrales. Sin API key necesaria.

Output: noticias_gld.json
"""
import json
import logging
import re
import subprocess as _sp
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
LOG_DIR = SCRIPT_DIR / "logs"
LOG_DIR.mkdir(exist_ok=True)
LOG_FILE = LOG_DIR / "news_gld.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger(__name__)

OUTPUT_FILE = SCRIPT_DIR / "noticias_gld.json"
VENTANA_DIAS = 3  # ventana de noticias recientes
MAX_POR_CATEGORIA = 5

# Queries por categoria. Mezcla espanol + ingles para mayor cobertura.
QUERIES = {
    "precio": [
        "precio oro hoy",
        "gold price today",
        "oro spot XAU",
    ],
    "fed_macro": [
        "Federal Reserve tasas",
        "Fed rate decision",
        "inflacion EEUU CPI",
        "real yields treasury",
    ],
    "dolar": [
        "DXY dollar index",
        "indice dolar",
        "dolar debilidad fortaleza",
    ],
    "bancos_centrales": [
        "central bank gold buying",
        "bancos centrales oro reservas",
        "China gold reserves",
    ],
    "geopolitica": [
        "safe haven oro tensiones",
        "geopolitical tensions gold",
        "guerra impacto oro",
    ],
    "proyecciones": [
        "gold forecast 2026",
        "proyeccion precio oro Goldman",
        "JP Morgan gold target",
    ],
}

CATEGORIA_META = {
    "precio":          {"emoji": "💰", "label": "Precio del oro"},
    "fed_macro":       {"emoji": "🏦", "label": "Fed / Macro"},
    "dolar":           {"emoji": "💵", "label": "DXY / Dolar"},
    "bancos_centrales":{"emoji": "🏛️", "label": "Bancos centrales"},
    "geopolitica":     {"emoji": "🌍", "label": "Geopolitica"},
    "proyecciones":    {"emoji": "📈", "label": "Proyecciones"},
}


def build_query_url(keyword):
    """Construye URL de Google News RSS para una keyword."""
    q = urllib.parse.quote_plus(keyword)
    # hl=es-CL: titulares en espanol cuando existan, fallback ingles
    return f"https://news.google.com/rss/search?q={q}&hl=es-CL&gl=CL&ceid=CL:es"


def fetch_rss(url, timeout=20):
    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            },
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        log.warning(f"  fetch_rss fallo para {url[:80]}: {e}")
        return None


def parse_rss(xml_text):
    items = []
    if not xml_text:
        return items
    try:
        root = ET.fromstring(xml_text)
        channel = root.find("channel")
        if channel is None:
            return items
        for item in channel.findall("item"):
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            pubdate = (item.findtext("pubDate") or "").strip()
            source_el = item.find("source")
            source = (source_el.text if source_el is not None else "") or ""
            items.append({
                "title": title,
                "link": link,
                "pubdate": pubdate,
                "source": source.strip(),
            })
    except Exception as e:
        log.warning(f"  parse_rss fallo: {e}")
    return items


def parse_pubdate(pubdate_str):
    """Parsea pubDate RSS (RFC 2822) a datetime UTC."""
    try:
        from email.utils import parsedate_to_datetime
        dt = parsedate_to_datetime(pubdate_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def is_reciente(item, cutoff):
    dt = parse_pubdate(item.get("pubdate", ""))
    if dt is None:
        return False
    return dt >= cutoff


def clean_title(title):
    """Limpia el sufijo ' - Medio' que Google News agrega al final."""
    title = re.sub(r"\s+-\s+[^-]+$", "", title)
    return title.strip()


def normalizar(s):
    """Para deduplicar: minusculas, sin tildes, sin puntuacion."""
    import unicodedata
    s = unicodedata.normalize("NFD", s.lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = re.sub(r"[^a-z0-9 ]", "", s)
    return re.sub(r"\s+", " ", s).strip()


def fetch_categoria(categoria, keywords, cutoff):
    """Fetch + filter + dedupe para una categoria."""
    log.info(f"\n--- Categoria: {categoria} ---")
    items_brutos = []
    for kw in keywords:
        url = build_query_url(kw)
        xml = fetch_rss(url)
        items = parse_rss(xml)
        items_brutos.extend(items)
        log.info(f"  '{kw}': {len(items)} resultados")

    # Filtrar por ventana de tiempo
    recientes = [it for it in items_brutos if is_reciente(it, cutoff)]
    log.info(f"  Recientes (<={VENTANA_DIAS}d): {len(recientes)}")

    # Deduplicar por titulo normalizado
    vistos = set()
    unicos = []
    for it in recientes:
        clave = normalizar(clean_title(it["title"]))
        if clave and clave not in vistos:
            vistos.add(clave)
            unicos.append({
                "title": clean_title(it["title"]),
                "link": it["link"],
                "source": it["source"],
                "pubdate": it["pubdate"],
                "pubdate_iso": parse_pubdate(it["pubdate"]).isoformat() if parse_pubdate(it["pubdate"]) else "",
            })

    # Ordenar por fecha desc y top N
    unicos.sort(key=lambda x: x.get("pubdate_iso", ""), reverse=True)
    top = unicos[:MAX_POR_CATEGORIA]
    log.info(f"  Unicos: {len(unicos)}, top {len(top)} seleccionados")
    return top


def ejecutar_git(args):
    try:
        r = _sp.run(["git"] + args, cwd=SCRIPT_DIR, capture_output=True, text=True, timeout=60)
        return r.returncode, r.stdout, r.stderr
    except Exception as e:
        return -1, "", str(e)


def git_sync_and_push():
    code, out, _ = ejecutar_git(["status", "--porcelain", "noticias_gld.json"])
    if not out.strip():
        log.info("Sin cambios en noticias_gld.json")
        return
    ejecutar_git(["pull", "--rebase", "--autostash"])
    ejecutar_git(["add", "noticias_gld.json"])
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    ejecutar_git(["commit", "-m", f"chore: update noticias GLD {ts} [skip ci]"])
    code, _, err = ejecutar_git(["push"])
    if code != 0:
        log.warning(f"git push fallo: {err}. Reintentando con pull...")
        ejecutar_git(["pull", "--rebase", "--autostash"])
        ejecutar_git(["push"])
    log.info("git push OK")


def main():
    log.info("=" * 60)
    log.info("=== Update Noticias GLD ===")
    log.info(f"Hora: {datetime.now().isoformat()}")

    cutoff = datetime.now(timezone.utc) - timedelta(days=VENTANA_DIAS)
    log.info(f"Cutoff: {cutoff.isoformat()}")

    noticias_por_categoria = {}
    total = 0
    for categoria, keywords in QUERIES.items():
        noticias = fetch_categoria(categoria, keywords, cutoff)
        noticias_por_categoria[categoria] = noticias
        total += len(noticias)

    output = {
        "updated_at_utc": datetime.now(timezone.utc).isoformat(),
        "ventana_dias": VENTANA_DIAS,
        "categorias_meta": CATEGORIA_META,
        "noticias_por_categoria": noticias_por_categoria,
        "stats": {
            "total_noticias": total,
            "por_categoria": {k: len(v) for k, v in noticias_por_categoria.items()},
        },
    }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    log.info(f"\nGuardado: {OUTPUT_FILE} ({total} noticias)")

    git_sync_and_push()
    log.info(f"=== FIN ({datetime.now().strftime('%H:%M:%S')}) ===")


if __name__ == "__main__":
    main()
