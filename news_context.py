"""
NEWS CONTEXT MODULE - Value Signal System
==========================================

Descarga titulares financieros de fuentes USA gratuitas via RSS,
los filtra por relevancia para S&P 500 y Nasdaq, y los agrupa por tema.

Fuentes RSS gratuitas (sin API key):
- CNBC Markets / Top
- MarketWatch Top Stories / Market Pulse
- Yahoo Finance Headlines
- SeekingAlpha Market Currents

Uso desde value_signal.py:
    from news_context import fetch_news_context
    news = fetch_news_context(days_back=7)
    render_news(news)
"""

import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
import re
import socket

# Modulo opcional de interpretacion con IA via Groq (gratis en la nube)
try:
    from groq_interpreter import groq_available, interpret_news_batch, GROQ_MODEL
    GROQ_AVAILABLE_IMPORT = True
except ImportError:
    GROQ_AVAILABLE_IMPORT = False

# ============================================================
# FUENTES RSS (gratuitas, sin API key)
# ============================================================

FEEDS = {
    # CNBC - generalmente accesible
    'CNBC Top':          'https://www.cnbc.com/id/100003114/device/rss/rss.html',
    'CNBC Markets':      'https://www.cnbc.com/id/15839069/device/rss/rss.html',
    'CNBC Economy':      'https://www.cnbc.com/id/20910258/device/rss/rss.html',
    'CNBC Earnings':     'https://www.cnbc.com/id/15839135/device/rss/rss.html',
    # Investing.com - bastante accesible
    'Investing News':    'https://www.investing.com/rss/news.rss',
    'Investing Stocks':  'https://www.investing.com/rss/news_25.rss',
    # MarketWatch
    'MarketWatch Top':   'https://feeds.content.dowjones.io/public/rss/mw_topstories',
    'MarketWatch Pulse': 'https://feeds.content.dowjones.io/public/rss/mw_marketpulse',
    # Yahoo Finance (puede fallar con Cloudflare)
    'Yahoo Finance':     'https://finance.yahoo.com/news/rssindex',
    # NPR Business como respaldo
    'NPR Business':      'https://feeds.npr.org/1006/rss.xml',
}

# ============================================================
# CATEGORIZACIÓN DE NOTICIAS
# ============================================================

CATEGORIES = {
    'Política Monetaria (Fed/tasas)': [
        'fed', 'powell', 'fomc', 'interest rate', 'rate cut', 'rate hike',
        'monetary policy', 'central bank', 'treasury yield', 'bond yield',
        'inflation', 'cpi', 'pce', 'jobless claims', 'unemployment',
        'federal reserve', 'rate decision', 'jackson hole',
    ],
    'Earnings y Empresas': [
        'earnings', 'revenue', 'beat estimates', 'miss estimates', 'guidance',
        'quarterly results', 'q1', 'q2', 'q3', 'q4', 'profit', 'eps',
        'apple', 'microsoft', 'google', 'alphabet', 'meta', 'amazon',
        'nvidia', 'tesla', 'netflix', 'broadcom', 'oracle',
    ],
    'Tecnología / IA': [
        'ai ', 'artificial intelligence', 'chatgpt', 'openai', 'anthropic',
        'gemini', 'llm', 'chip', 'semiconductor', 'tech stock', 'tech sector',
        'cloud', 'data center', 'gpu', 'nvidia', 'tsmc',
    ],
    'Geopolítica / Comercio': [
        'china', 'tariff', 'trade war', 'sanctions', 'russia', 'ukraine',
        'middle east', 'iran', 'taiwan', 'oil price', 'opec',
        'trump', 'biden', 'congress', 'shutdown', 'debt ceiling',
    ],
    'Macro / Economía': [
        'gdp', 'recession', 'consumer spending', 'retail sales', 'pmi',
        'housing', 'real estate', 'manufacturing', 'ism', 'payrolls',
        'economic outlook', 'soft landing', 'hard landing',
    ],
    'Mercado / Volatilidad': [
        'vix', 'volatility', 'sell-off', 'rally', 'correction', 'bear market',
        'bull market', 'all-time high', 'record high', 'crash', 'plunge',
        'surge', 'jump', 'rebound', 'gains', 'losses',
    ],
}

# Keywords que indican relevancia para S&P 500 / Nasdaq específicamente
RELEVANCE_KEYWORDS = [
    's&p', 'sp500', 'nasdaq', 'dow', 'stocks', 'stock market', 'wall street',
    'us stocks', 'equities', 'index', 'shares', 'futures',
    'fed', 'rate', 'inflation', 'earnings', 'treasury',
    'tech stocks', 'megacap', 'tech sector', 'magnificent',
]

# ============================================================
# DESCARGA Y PARSING
# ============================================================

def fetch_rss(url, timeout=10):
    """Descarga un feed RSS con headers de navegador completo (esquiva Cloudflare)."""
    try:
        req = urllib.request.Request(url, headers={
            'User-Agent':      'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept':          'application/rss+xml, application/xml, application/atom+xml, text/xml, text/html;q=0.9, */*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9,es;q=0.8',
            'Accept-Encoding': 'gzip, deflate',
            'Connection':      'keep-alive',
            'Cache-Control':   'no-cache',
        })
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = r.read()
            # Si viene comprimido con gzip, descomprimir
            if r.headers.get('Content-Encoding') == 'gzip':
                import gzip
                data = gzip.decompress(data)
            elif r.headers.get('Content-Encoding') == 'deflate':
                import zlib
                data = zlib.decompress(data)
            return data
    except urllib.error.HTTPError as e:
        if e.code == 403:
            # Cloudflare bloqueo - intentar sin Accept-Encoding
            try:
                req2 = urllib.request.Request(url, headers={
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                    'Accept': '*/*',
                })
                with urllib.request.urlopen(req2, timeout=timeout) as r2:
                    return r2.read()
            except Exception:
                return None
        return None
    except (urllib.error.URLError, socket.timeout, Exception):
        return None


def _find_first(item, paths, ns=None):
    """Busca el primer elemento que exista entre varios paths (compatible Python 3.14)."""
    if ns is None:
        ns = {}
    for path in paths:
        el = item.find(path, ns) if ns else item.find(path)
        if el is not None:
            return el
    return None


def parse_rss(data, source_name):
    """Parsea RSS/Atom y devuelve lista de items."""
    items = []
    try:
        # Limpiar caracteres problemáticos
        text = data.decode('utf-8', errors='ignore')
        # Algunos feeds tienen caracteres de control que rompen el parser
        text = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', text)
        root = ET.fromstring(text.encode('utf-8'))

        # Buscar items (RSS) o entries (Atom)
        ns = {'atom': 'http://www.w3.org/2005/Atom'}
        rss_items  = root.findall('.//item')
        atom_items = root.findall('.//atom:entry', ns)
        all_items = rss_items + atom_items

        for item in all_items[:30]:  # max 30 por feed
            title_el = _find_first(item, ['title', 'atom:title'], ns)
            link_el  = _find_first(item, ['link', 'atom:link'], ns)
            date_el  = _find_first(item, ['pubDate', 'atom:published', 'atom:updated',
                                          '{http://purl.org/dc/elements/1.1/}date'], ns)
            desc_el  = _find_first(item, ['description', 'atom:summary', 'atom:content'], ns)

            if title_el is None or not title_el.text:
                continue

            title = re.sub(r'<[^>]+>', '', title_el.text).strip()

            # Link
            if link_el is not None:
                if link_el.text:
                    link = link_el.text.strip()
                else:
                    link = link_el.get('href', '')
            else:
                link = ''

            # Fecha
            pub_date = None
            if date_el is not None and date_el.text:
                try:
                    pub_date = parsedate_to_datetime(date_el.text)
                    if pub_date.tzinfo is None:
                        pub_date = pub_date.replace(tzinfo=timezone.utc)
                except Exception:
                    try:
                        pub_date = datetime.fromisoformat(date_el.text.replace('Z', '+00:00'))
                    except Exception:
                        pass

            # Descripción
            description = ''
            if desc_el is not None and desc_el.text:
                description = re.sub(r'<[^>]+>', '', desc_el.text).strip()[:300]

            items.append({
                'title':       title,
                'link':        link,
                'date':        pub_date,
                'description': description,
                'source':      source_name,
            })
    except Exception:
        pass

    return items


def categorize(title, description=''):
    """Asigna categorías a una noticia según keywords. Una noticia puede estar en varias."""
    text = (title + ' ' + description).lower()
    matched = []
    for cat, keywords in CATEGORIES.items():
        for kw in keywords:
            if kw in text:
                matched.append(cat)
                break  # una keyword por categoría es suficiente
    return matched


def is_relevant(title, description=''):
    """¿La noticia es relevante para S&P 500 / Nasdaq?"""
    text = (title + ' ' + description).lower()
    return any(kw in text for kw in RELEVANCE_KEYWORDS)


# ============================================================
# AGGREGATE
# ============================================================

def fetch_news_context(days_back=7, max_items_per_feed=20):
    """
    Descarga noticias de todas las fuentes, filtra por relevancia y
    recencia, devuelve estructura organizada.
    """
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=days_back)

    all_items = []
    feeds_ok = 0
    feeds_failed = []

    for source_name, url in FEEDS.items():
        data = fetch_rss(url)
        if data is None:
            feeds_failed.append(source_name)
            continue
        items = parse_rss(data, source_name)
        if items:
            feeds_ok += 1
            all_items.extend(items[:max_items_per_feed])

    # Filtrar: solo recientes y relevantes
    filtered = []
    for item in all_items:
        # Normalizar fecha: si viene sin timezone, asumir UTC
        item_date = item['date']
        if item_date is not None and item_date.tzinfo is None:
            item_date = item_date.replace(tzinfo=timezone.utc)
            item['date'] = item_date

        if item_date is None or item_date >= cutoff:
            if is_relevant(item['title'], item['description']):
                item['categories'] = categorize(item['title'], item['description'])
                filtered.append(item)

    # Deduplicar por título (primeros 60 chars)
    seen = set()
    deduped = []
    for item in filtered:
        key = item['title'][:60].lower().strip()
        if key not in seen:
            seen.add(key)
            deduped.append(item)

    # Ordenar por fecha desc (más recientes primero), items sin fecha al final
    def _sort_key(x):
        d = x.get('date')
        if d is None:
            return datetime.min.replace(tzinfo=timezone.utc)
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc)
        return d
    deduped.sort(key=_sort_key, reverse=True)

    # Contar categorías
    cat_count = {}
    for item in deduped:
        for cat in item['categories']:
            cat_count[cat] = cat_count.get(cat, 0) + 1

    return {
        'items':         deduped,
        'category_counts': cat_count,
        'feeds_ok':      feeds_ok,
        'feeds_total':   len(FEEDS),
        'feeds_failed':  feeds_failed,
        'cutoff':        cutoff,
        'now':           now,
        'ai_enriched': False,
    }


def enrich_with_groq(news, max_items=8, verbose=True):
    """
    Si Groq esta configurado (con API key), enriquece las noticias.
    Modifica news in-place y devuelve True si se enriquecio.
    """
    if not GROQ_AVAILABLE_IMPORT:
        return False

    available, _ = groq_available()
    if not available:
        return False

    if verbose:
        print(f'  {_C.DIM}Procesando con IA en la nube (Groq / {GROQ_MODEL})...{_C.RESET}')

    news['items'] = interpret_news_batch(news['items'], max_items=max_items, verbose=verbose)
    news['ai_enriched'] = True
    return True


# Alias para compatibilidad
def enrich_with_ollama(news, max_items=8, verbose=True):
    return enrich_with_groq(news, max_items, verbose)


# ============================================================
# RENDER (texto plano con colores ANSI)
# ============================================================

class _C:
    RED='\033[91m'; YELLOW='\033[93m'; GREEN='\033[92m'
    CYAN='\033[96m'; BLUE='\033[94m'; BOLD='\033[1m'; DIM='\033[2m'; RESET='\033[0m'


def render_news(news, max_show=10):
    """Imprime el contexto de noticias formateado."""
    print()
    print(f'{_C.BOLD}{"="*70}{_C.RESET}')
    print(f'{_C.BOLD}  CONTEXTO DE MERCADO - Noticias relevantes ultimos 7 dias{_C.RESET}')
    print(f'{_C.BOLD}{"="*70}{_C.RESET}')

    if news['feeds_ok'] == 0:
        print()
        print(f'  {_C.YELLOW}No se pudo descargar ninguna fuente de noticias.{_C.RESET}')
        print(f'  {_C.DIM}Posibles causas:{_C.RESET}')
        print(f'  {_C.DIM}- Sin conexion a internet{_C.RESET}')
        print(f'  {_C.DIM}- Firewall corporativo bloqueando feeds RSS{_C.RESET}')
        print(f'  {_C.DIM}- Fuentes RSS temporalmente caidas{_C.RESET}')
        return

    print()
    print(f'  {_C.DIM}Fuentes consultadas: {news["feeds_ok"]}/{news["feeds_total"]} OK{_C.RESET}')
    if news['feeds_failed']:
        print(f'  {_C.DIM}Caidas: {", ".join(news["feeds_failed"])}{_C.RESET}')

    items = news['items']
    if not items:
        print()
        print(f'  {_C.YELLOW}No hay noticias relevantes para S&P 500 / Nasdaq en los ultimos 7 dias.{_C.RESET}')
        return

    # ---- TEMAS DOMINANTES ----
    if news['category_counts']:
        print()
        print(f'  {_C.BOLD}Temas dominantes esta semana:{_C.RESET}')
        sorted_cats = sorted(news['category_counts'].items(), key=lambda x: -x[1])
        max_count = max(news['category_counts'].values()) if news['category_counts'] else 1
        for cat, count in sorted_cats[:6]:
            bar_len = int((count / max_count) * 20)
            bar = '#' * bar_len + '.' * (20 - bar_len)
            print(f'  {cat:<35} [{bar}] {count} menciones')

    # ---- TITULARES PRINCIPALES ----
    print()
    print(f'  {_C.BOLD}Titulares relevantes (top {min(max_show, len(items))}):{_C.RESET}')
    print()

    for i, item in enumerate(items[:max_show], 1):
        # Fecha
        if item['date']:
            date_str = item['date'].strftime('%Y-%m-%d')
            days_ago = (news['now'] - item['date']).days
            if days_ago == 0:
                date_str += ' (hoy)'
            elif days_ago == 1:
                date_str += ' (ayer)'
            elif days_ago > 0:
                date_str += f' (hace {days_ago}d)'
        else:
            date_str = '(sin fecha)'

        # Categorías
        cats = ', '.join(item['categories'][:2]) if item['categories'] else 'general'

        # Color de la categoría dominante
        cat_color = _C.CYAN
        if 'Política Monetaria' in cats:
            cat_color = _C.YELLOW
        elif 'Mercado / Volatilidad' in cats:
            cat_color = _C.RED
        elif 'Tecnología' in cats:
            cat_color = _C.BLUE
        elif 'Geopolítica' in cats:
            cat_color = _C.YELLOW

        # Título original
        title = item['title']
        if len(title) > 90:
            title = title[:87] + '...'

        print(f'  [{i}] [{date_str}] {_C.DIM}{item["source"]}{_C.RESET}')
        print(f'  {_C.BOLD}EN:{_C.RESET} {title}')

        # Traduccion al español (si Ollama disponible)
        if item.get('traduccion'):
            print(f'  {_C.BOLD}ES:{_C.RESET} {_C.CYAN}{item["traduccion"]}{_C.RESET}')

        # Impacto en mercados (si Ollama disponible)
        if item.get('impacto'):
            print(f'  {_C.BOLD}IMPACTO:{_C.RESET} {_C.GREEN}{item["impacto"]}{_C.RESET}')

        print(f'  {cat_color}Tema: {cats}{_C.RESET}')
        if item['link']:
            link = item['link']
            if len(link) > 80:
                link = link[:77] + '...'
            print(f'  {_C.DIM}{link}{_C.RESET}')
        print()

    # ---- DISCLAIMER ----
    if news.get('ai_enriched'):
        print(f'  {_C.DIM}Traduccion e interpretacion generadas por IA (Groq cloud).{_C.RESET}')
        print(f'  {_C.DIM}El analisis es heuristico, no asesoria financiera profesional.{_C.RESET}')
    print(f'  {_C.DIM}Nota: estas noticias dan contexto pero NO causan los movimientos.{_C.RESET}')
    print(f'  {_C.DIM}El mercado integra miles de factores simultaneamente.{_C.RESET}')
    print(f'  {_C.DIM}Usalas para entender el ambiente, no para predecir movimientos.{_C.RESET}')


# ============================================================
# SI SE EJECUTA COMO STANDALONE (testing)
# ============================================================

if __name__ == '__main__':
    print("Descargando contexto de noticias financieras...")
    news = fetch_news_context(days_back=7)
    render_news(news, max_show=10)
    input("\nPresiona ENTER para salir...")
