"""
GROQ INTERPRETER - Value Signal System
=======================================

Modulo que conecta con la API de Groq (gratis) para traducir titulares
al español y generar interpretacion de impacto en S&P 500 / Nasdaq.

Setup:
1. Registrarse en https://console.groq.com (Sign in with Google)
2. Crear API Key en "API Keys"
3. Guardar la key en archivo: groq_api_key.txt
   (solo el texto de la key, una sola linea)

Modelo usado: llama-3.3-70b-versatile (gratis en tier free)
Limites tier gratis:
- 30 requests / minuto
- 14,400 requests / dia
- Mas que suficiente para uso personal
"""

import json
import urllib.request
import urllib.error
import socket
import os
from pathlib import Path

# ============================================================
# CONFIGURACION
# ============================================================

GROQ_API_URL = 'https://api.groq.com/openai/v1/chat/completions'
GROQ_MODEL   = 'llama-3.3-70b-versatile'  # Modelo de calidad alta, gratis
GROQ_TIMEOUT = 20

# Archivo donde se guarda la API key (NO subir a Git)
SCRIPT_DIR = Path(__file__).parent
API_KEY_FILE = SCRIPT_DIR / 'groq_api_key.txt'

# Prompt template
SYSTEM_PROMPT = """Eres un analista financiero experto en mercados USA, especializado en S&P 500 y Nasdaq 100.

Para cada titular de noticia que recibas, devuelve EXACTAMENTE este formato (sin texto adicional, sin markdown, sin asteriscos):

TRADUCCION: [titular traducido al español, breve, natural y profesional]
IMPACTO: [1-2 frases concretas sobre como puede afectar a S&P 500 y Nasdaq. Indica si es positivo/negativo/neutral. Si afecta mas a uno que al otro, dilo explicitamente. Sin disclaimers ni hedging excesivo, directo y profesional.]

Responde SOLO con esas dos lineas. No agregues comentarios ni notas adicionales."""


# ============================================================
# CARGAR API KEY
# ============================================================

def load_api_key():
    """Lee la API key desde variable de entorno o archivo local."""
    # Primero intentar variable de entorno (Streamlit Cloud, GitHub Actions)
    env_key = os.environ.get('GROQ_API_KEY', '').strip()
    if env_key and env_key.startswith('gsk_'):
        return env_key
    # Fallback: archivo local
    if not API_KEY_FILE.exists():
        return None
    try:
        with open(API_KEY_FILE, 'r', encoding='utf-8') as f:
            key = f.read().strip()
        if key and key.startswith('gsk_'):
            return key
        return None
    except Exception:
        return None


def groq_available():
    """Verifica si hay API key valida configurada."""
    key = load_api_key()
    return key is not None, key


# ============================================================
# CONSULTA A GROQ
# ============================================================

def query_groq(user_prompt, api_key, model=None, timeout=None):
    """Envia consulta a Groq y devuelve respuesta. None si falla."""
    if model is None:
        model = GROQ_MODEL
    if timeout is None:
        timeout = GROQ_TIMEOUT

    payload = {
        'model': model,
        'messages': [
            {'role': 'system', 'content': SYSTEM_PROMPT},
            {'role': 'user',   'content': user_prompt}
        ],
        'temperature': 0.3,
        'max_tokens':  300,
    }

    try:
        data = json.dumps(payload).encode('utf-8')
        req = urllib.request.Request(
            GROQ_API_URL,
            data=data,
            headers={
                'Content-Type':  'application/json',
                'Authorization': f'Bearer {api_key}',
                'User-Agent':    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept':        'application/json',
                'Accept-Language': 'en-US,en;q=0.9',
            }
        )
        with urllib.request.urlopen(req, timeout=timeout) as r:
            response = json.loads(r.read())
        # Estructura OpenAI-compatible
        choices = response.get('choices', [])
        if choices:
            content = choices[0].get('message', {}).get('content', '')
            return content.strip()
        return None
    except urllib.error.HTTPError as e:
        # Si es rate limit (429), esperar un poco
        if e.code == 429:
            return 'RATE_LIMIT'
        return None
    except (urllib.error.URLError, socket.timeout, Exception):
        return None


def parse_response(text):
    """Parsea respuesta buscando TRADUCCION e IMPACTO."""
    if not text or text == 'RATE_LIMIT':
        return None, None

    traduccion = None
    impacto = None

    lines = text.strip().split('\n')
    current = None
    buffer = []

    for line in lines:
        line = line.strip().lstrip('*').lstrip('-').strip()
        if not line:
            continue
        upper = line.upper()
        if upper.startswith('TRADUCCION:') or upper.startswith('TRADUCCIÓN:'):
            if current == 'traduccion' and buffer:
                traduccion = ' '.join(buffer).strip()
            elif current == 'impacto' and buffer:
                impacto = ' '.join(buffer).strip()
            current = 'traduccion'
            rest = line.split(':', 1)[1].strip() if ':' in line else ''
            buffer = [rest] if rest else []
        elif upper.startswith('IMPACTO:'):
            if current == 'traduccion' and buffer:
                traduccion = ' '.join(buffer).strip()
            current = 'impacto'
            rest = line.split(':', 1)[1].strip() if ':' in line else ''
            buffer = [rest] if rest else []
        else:
            buffer.append(line)

    if current == 'traduccion' and buffer:
        traduccion = ' '.join(buffer).strip()
    elif current == 'impacto' and buffer:
        impacto = ' '.join(buffer).strip()

    return traduccion, impacto


# ============================================================
# PROCESAR NOTICIAS
# ============================================================

def interpret_news_item(item, api_key):
    """Procesa una noticia. Devuelve dict con traduccion e impacto."""
    title = item.get('title', '')
    categories = item.get('categories', [])
    category_str = ', '.join(categories) if categories else 'general'

    user_prompt = f"Titular: {title}\nCategoria: {category_str}"
    response = query_groq(user_prompt, api_key)

    if not response or response == 'RATE_LIMIT':
        return None

    traduccion, impacto = parse_response(response)
    return {
        'traduccion': traduccion,
        'impacto':    impacto,
    }


def interpret_news_batch(items, max_items=8, verbose=False):
    """Procesa lote de noticias. Maneja rate limits."""
    api_key = load_api_key()
    if not api_key:
        return items  # devuelve sin enriquecer

    enriched = []
    import time
    for i, item in enumerate(items[:max_items]):
        if verbose:
            print(f'    [{i+1}/{min(max_items, len(items))}] Procesando con IA...', end='\r', flush=True)
        interp = interpret_news_item(item, api_key)
        item_copy = dict(item)
        if interp:
            item_copy['traduccion'] = interp.get('traduccion')
            item_copy['impacto']    = interp.get('impacto')
        else:
            item_copy['traduccion'] = None
            item_copy['impacto']    = None
        enriched.append(item_copy)
        # Pequeña pausa para no saturar rate limit (30 req/min = 2 seg promedio)
        time.sleep(0.5)
    if verbose:
        print('    ' + ' '*50, end='\r')
    return enriched


# ============================================================
# TESTING
# ============================================================

if __name__ == '__main__':
    print("Verificando configuracion de Groq...")

    available, key = groq_available()
    if not available:
        print(f"\n❌ No se encontro API key en: {API_KEY_FILE}")
        print("\nPara configurar:")
        print("1. Registrate en: https://console.groq.com")
        print("2. Crea una API Key")
        print(f"3. Guardala en: {API_KEY_FILE}")
        print("   (solo el texto de la key, una sola linea)")
        exit(1)

    print(f"✓ API key encontrada: {key[:10]}...{key[-4:]}")

    # Test
    print("\nTest de traduccion + interpretacion...")
    test_item = {
        'title': 'Fed officials signal patience on rate cuts as inflation eases slowly',
        'categories': ['Politica Monetaria'],
    }
    print(f"\nTitular original: {test_item['title']}")
    result = interpret_news_item(test_item, key)
    if result:
        print(f"\nTraduccion: {result['traduccion']}")
        print(f"\nImpacto:    {result['impacto']}")
    else:
        print("❌ ERROR: no se pudo procesar")
