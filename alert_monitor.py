"""
ALERT MONITOR - Value Signal System
====================================
Monitor que se ejecuta cada hora (via GitHub Actions) y envia alertas
por email cuando detecta eventos relevantes en el mercado.

Estado persistente: alert_state.json (commiteado al repo)

Eventos que disparan alerta:
- Cambio de zona (CARO -> NEUTRAL, etc.)
- Score >= 75 (OPORTUNIDAD)
- Score < 15 (MUY CARO)
- Score sube/baja >= 10 puntos en ultima consulta
- Drawdown <= -20%
- Noticia critica con impacto fuerte

Anti-spam:
- Misma alerta no se repite en 24h
- Maximo 3 alertas/dia
"""

import os
import json
import smtplib
import warnings
import sys
from datetime import datetime, timedelta, timezone
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from pathlib import Path

warnings.filterwarnings('ignore')

import numpy as np
import pandas as pd
import yfinance as yf
import urllib.request
import io

# ============================================================
# CONFIG desde variables de entorno (GitHub Secrets)
# ============================================================
SMTP_HOST     = 'smtp.gmail.com'
SMTP_PORT     = 587
SMTP_USER     = os.environ.get('GMAIL_USER', '')      # tu@gmail.com
SMTP_PASS     = os.environ.get('GMAIL_APP_PASSWORD', '')  # app password de Gmail
EMAIL_TO      = os.environ.get('EMAIL_TO', SMTP_USER) # destino (default: mismo)
GROQ_API_KEY  = os.environ.get('GROQ_API_KEY', '')

# Aportes (para calcular accion)
APORTE_SP500  = int(os.environ.get('APORTE_SP500', 140))
APORTE_NASDAQ = int(os.environ.get('APORTE_NASDAQ', 60))

# Estado persistente
SCRIPT_DIR = Path(__file__).parent
STATE_FILE = SCRIPT_DIR / 'alert_state.json'

MULT = {'CARO': 0.5, 'NEUTRAL': 1.0, 'ATRACTIVO': 1.5, 'OPORTUNIDAD': 2.5}
WEIGHTS = {'cape': 0.40, 'drawdown': 0.25, 'ey_vs_bond': 0.15, 'yield_curve': 0.10, 'momentum': 0.10}

# ============================================================
# ESTADO PERSISTENTE
# ============================================================
def load_state():
    if not STATE_FILE.exists():
        return {
            'last_check':       None,
            'sp_score_prev':    None,
            'sp_zona_prev':     None,
            'nq_score_prev':    None,
            'nq_zona_prev':     None,
            'alerts_sent':      {},  # {tipo: timestamp}
            'alerts_today':     0,
            'last_alert_date':  None,
        }
    try:
        with open(STATE_FILE, 'r') as f:
            return json.load(f)
    except Exception:
        return {}

def save_state(state):
    state['last_check'] = datetime.now(timezone.utc).isoformat()
    with open(STATE_FILE, 'w') as f:
        json.dump(state, f, indent=2, default=str)

# ============================================================
# DESCARGA DATOS
# ============================================================
def fetch_monthly(ticker, start='1990-01-01'):
    df = yf.download(ticker, start=start, progress=False, auto_adjust=True)
    if df.empty: return None
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df['Close'].resample('ME').last()

def fetch_cape():
    try:
        url = 'https://raw.githubusercontent.com/datasets/s-and-p-500/main/data/data.csv'
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=15) as r:
            shiller = pd.read_csv(io.BytesIO(r.read()))
        shiller['Date'] = pd.to_datetime(shiller['Date'])
        shiller = shiller.set_index('Date')
        cape = shiller['PE10'][shiller['PE10'] > 0]
        return cape.resample('ME').last().ffill()
    except Exception:
        return None

# ============================================================
# CALCULO SCORES (idéntico al sistema principal)
# ============================================================
def calc_scores(price, rate_10y, yc, cape_external=None):
    df = pd.DataFrame({'price': price}).dropna()
    if cape_external is not None:
        df['cape'] = cape_external.reindex(df.index).ffill()
        mask = df['cape'].isna()
        if mask.any():
            proxy = df['price'] / df['price'].rolling(120, min_periods=60).mean()
            df.loc[mask, 'cape'] = proxy[mask] * df['cape'].dropna().mean()
    else:
        df['cape'] = df['price'] / df['price'].rolling(120, min_periods=60).mean()
    df['drawdown'] = (df['price'] - df['price'].cummax()) / df['price'].cummax()
    df['momentum'] = df['price'].shift(1) / df['price'].shift(12) - 1
    df['r10y'] = rate_10y; df['yc'] = yc
    df[['r10y','yc']] = df[['r10y','yc']].ffill()
    df['s_cape'] = df['cape'].rolling(240, min_periods=60).apply(
        lambda x: (x.iloc[-1] < x).mean()*100, raw=False)
    df['s_drawdown'] = np.clip(-df['drawdown']*200, 0, 100)
    df['s_ey_vs_bond'] = (1/df['cape'] - df['r10y']/100).rolling(240, min_periods=60).apply(
        lambda x: (x.iloc[-1] > x).mean()*100, raw=False)
    df['s_yield_curve'] = np.clip((df['yc']+2)/5*100, 0, 100)
    df['s_momentum'] = np.clip((df['momentum']+0.2)/0.6*100, 0, 100)
    df['score'] = sum(df[f's_{k}']*v for k,v in WEIGHTS.items())
    df['zona'] = df['score'].apply(
        lambda s: 'sin_datos' if pd.isna(s)
        else 'CARO' if s<25 else 'NEUTRAL' if s<50 else 'ATRACTIVO' if s<75 else 'OPORTUNIDAD')
    return df

# ============================================================
# DETECCION DE EVENTOS
# ============================================================
def detect_events(last_sp, last_nq, state):
    """Detecta eventos que ameritan alerta. Devuelve lista de dicts."""
    events = []
    now = datetime.now(timezone.utc)

    for asset_name, ticker, last, score_prev_key, zona_prev_key in [
        ('S&P 500',   'CFISPETF',  last_sp, 'sp_score_prev', 'sp_zona_prev'),
        ('Nasdaq 100','CFINASDAQ', last_nq, 'nq_score_prev', 'nq_zona_prev'),
    ]:
        score = float(last['score'])
        zona  = last['zona']
        score_prev = state.get(score_prev_key)
        zona_prev  = state.get(zona_prev_key)

        # Evento 1: Cambio de zona
        if zona_prev and zona != zona_prev:
            events.append({
                'type':     f'ZONA_{asset_name}_{zona}',
                'priority': 'alta',
                'titulo':   f'⚡ {asset_name}: cambio de zona {zona_prev} → {zona}',
                'asset':    asset_name,
                'ticker':   ticker,
                'detalle':  f'Score: {score:.1f} ({zona})',
            })

        # Evento 2: Score cruza umbral OPORTUNIDAD
        if score >= 75 and (score_prev is None or score_prev < 75):
            events.append({
                'type':     f'OPORTUNIDAD_{asset_name}',
                'priority': 'critica',
                'titulo':   f'🟢🟢 {asset_name}: OPORTUNIDAD HISTORICA (score {score:.1f})',
                'asset':    asset_name,
                'ticker':   ticker,
                'detalle':  'Desplegar cash táctico. Eventos tipo Covid 2020 o crashes.',
            })

        # Evento 3: Score muy caro
        if score < 15 and (score_prev is None or score_prev >= 15):
            events.append({
                'type':     f'MUY_CARO_{asset_name}',
                'priority': 'media',
                'titulo':   f'🔴 {asset_name}: MUY CARO (score {score:.1f})',
                'asset':    asset_name,
                'ticker':   ticker,
                'detalle':  'Pausar aportes nuevos, mantener núcleo invertido.',
            })

        # Evento 4: Cambio rápido del score
        if score_prev is not None:
            delta = score - score_prev
            if abs(delta) >= 10:
                direction = 'subio' if delta > 0 else 'bajo'
                emoji = '📈' if delta > 0 else '📉'
                events.append({
                    'type':     f'CAMBIO_RAPIDO_{asset_name}_{int(delta)}',
                    'priority': 'media',
                    'titulo':   f'{emoji} {asset_name}: score {direction} {abs(delta):.1f} puntos',
                    'asset':    asset_name,
                    'ticker':   ticker,
                    'detalle':  f'Anterior: {score_prev:.1f} → Actual: {score:.1f} ({zona})',
                })

        # Evento 5: Drawdown profundo
        dd = float(last['drawdown']) * 100
        if dd <= -20:
            events.append({
                'type':     f'DRAWDOWN_{asset_name}_{int(abs(dd)/5)*5}',  # buckets de 5%
                'priority': 'critica',
                'titulo':   f'📉 {asset_name}: drawdown {dd:.1f}% — aporte extra',
                'asset':    asset_name,
                'ticker':   ticker,
                'detalle':  'Considera aporte extra desde cash táctico. Eventos tipo 2008/2020.',
            })

    return events

def filter_anti_spam(events, state):
    """Filtra eventos ya enviados en ultimas 24h."""
    now = datetime.now(timezone.utc)
    filtered = []
    sent = state.get('alerts_sent', {})
    today_str = now.date().isoformat()

    # Reset contador diario
    if state.get('last_alert_date') != today_str:
        state['alerts_today'] = 0
        state['last_alert_date'] = today_str

    for ev in events:
        # No mas de 3 alertas al dia
        if state['alerts_today'] >= 3:
            break
        # No repetir tipo en 24h
        last_sent = sent.get(ev['type'])
        if last_sent:
            try:
                last_dt = datetime.fromisoformat(last_sent.replace('Z', '+00:00'))
                if now - last_dt < timedelta(hours=24):
                    continue
            except Exception:
                pass
        filtered.append(ev)
        sent[ev['type']] = now.isoformat()
        state['alerts_today'] += 1

    state['alerts_sent'] = sent
    return filtered

# ============================================================
# ANALISIS DE NOTICIAS CON IMPACTO FUERTE
# ============================================================
def fetch_critical_news():
    """Busca noticias con impacto critico via news_context + Groq."""
    try:
        sys.path.insert(0, str(SCRIPT_DIR))
        from news_context import fetch_news_context, enrich_with_groq

        news = fetch_news_context(days_back=2)  # solo 2 días para ser relevante
        if not news.get('items'):
            return []

        # Enriquecer con IA si hay Groq
        if GROQ_API_KEY:
            enrich_with_groq(news, max_items=5, verbose=False)

        # Filtrar las que tienen impacto fuerte
        critical = []
        for item in news['items'][:8]:
            impacto = (item.get('impacto') or '').lower()
            title = item.get('title', '').lower()

            # Heuristica: impacto critico si menciona ciertas palabras
            critical_keywords = [
                'fuerte', 'significativo', 'crash', 'plunge', 'surge', 'rally',
                'recession', 'crisis', 'emergency', 'shock', 'sell-off',
                'all-time high', 'record', 'collapse',
            ]
            negative_keywords = ['fed cut', 'rate cut', 'recession', 'crash', 'bear market']

            is_critical = (
                any(kw in impacto for kw in ['fuerte', 'significativo', 'shock', 'crisis']) or
                any(kw in title for kw in negative_keywords)
            )

            if is_critical:
                critical.append(item)

        return critical[:3]  # max 3 noticias críticas
    except Exception as e:
        print(f"Error fetching news: {e}")
        return []

# ============================================================
# RENDER EMAIL HTML
# ============================================================
def render_email_html(events, last_sp, last_nq, critical_news):
    """Genera el HTML del email con todas las alertas."""

    zone_color = {
        'CARO':        '#e74c3c',
        'NEUTRAL':     '#f39c12',
        'ATRACTIVO':   '#27ae60',
        'OPORTUNIDAD': '#16a085',
    }
    sp_color = zone_color.get(last_sp['zona'], '#7f8c8d')
    nq_color = zone_color.get(last_nq['zona'], '#7f8c8d')

    aporte_sp = APORTE_SP500 * MULT.get(last_sp['zona'], 1.0)
    aporte_nq = APORTE_NASDAQ * MULT.get(last_nq['zona'], 1.0)
    total = aporte_sp + aporte_nq
    base = APORTE_SP500 + APORTE_NASDAQ
    cash_adj = base - total

    # Construir eventos HTML
    events_html = ''
    for ev in events:
        priority_color = {
            'critica': '#e74c3c',
            'alta':    '#f39c12',
            'media':   '#3498db',
        }.get(ev['priority'], '#7f8c8d')

        events_html += f'''
        <div style="background:#fff;border-left:6px solid {priority_color};padding:15px;margin:10px 0;border-radius:5px;box-shadow:0 1px 3px rgba(0,0,0,0.1);">
            <h3 style="margin:0 0 8px 0;color:#2c3e50;font-size:17px;">{ev['titulo']}</h3>
            <p style="margin:5px 0;color:#555;">{ev['detalle']}</p>
            <span style="display:inline-block;padding:3px 10px;background:{priority_color};color:white;border-radius:3px;font-size:11px;font-weight:bold;text-transform:uppercase;">prioridad {ev['priority']}</span>
        </div>
        '''

    # Noticias críticas
    news_html = ''
    if critical_news:
        news_html = '<h2 style="color:#2c3e50;border-bottom:2px solid #3498db;padding-bottom:8px;">📰 Noticias con impacto fuerte</h2>'
        for n in critical_news:
            news_html += f'''
            <div style="background:#fff;padding:12px;margin:10px 0;border-radius:5px;border-left:4px solid #9b59b6;">
                <p style="margin:0;font-weight:bold;color:#2c3e50;">{n.get('traduccion') or n['title']}</p>
                {f'<p style="margin:8px 0 0 0;color:#555;font-size:14px;"><b>Impacto:</b> {n["impacto"]}</p>' if n.get('impacto') else ''}
                <p style="margin:8px 0 0 0;font-size:12px;color:#7f8c8d;">Fuente: {n.get('source', '')}</p>
                {f'<a href="{n["link"]}" style="font-size:12px;color:#3498db;">Leer original →</a>' if n.get('link') else ''}
            </div>
            '''

    html = f'''<!DOCTYPE html>
<html><head><meta charset="UTF-8"></head>
<body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#f5f5f7;margin:0;padding:20px;">
    <div style="max-width:600px;margin:0 auto;background:white;border-radius:10px;overflow:hidden;box-shadow:0 4px 20px rgba(0,0,0,0.1);">

        <div style="background:linear-gradient(135deg,#667eea,#764ba2);color:white;padding:25px;text-align:center;">
            <h1 style="margin:0;font-size:24px;">📊 Value Signal Alert</h1>
            <p style="margin:8px 0 0 0;opacity:0.9;font-size:14px;">{datetime.now().strftime('%Y-%m-%d %H:%M UTC')}</p>
        </div>

        <div style="padding:25px;">
            <h2 style="color:#2c3e50;border-bottom:2px solid #3498db;padding-bottom:8px;">⚡ Eventos detectados</h2>
            {events_html}

            <h2 style="color:#2c3e50;border-bottom:2px solid #3498db;padding-bottom:8px;margin-top:25px;">Estado actual del mercado</h2>
            <table style="width:100%;border-collapse:collapse;margin:15px 0;">
                <tr style="background:#ecf0f1;">
                    <th style="padding:10px;text-align:left;color:#2c3e50;">Activo</th>
                    <th style="padding:10px;text-align:center;color:#2c3e50;">Score</th>
                    <th style="padding:10px;text-align:center;color:#2c3e50;">Zona</th>
                    <th style="padding:10px;text-align:right;color:#2c3e50;">Aporte</th>
                </tr>
                <tr>
                    <td style="padding:10px;border-bottom:1px solid #ecf0f1;"><b>S&P 500</b> (CFISPETF)</td>
                    <td style="padding:10px;text-align:center;border-bottom:1px solid #ecf0f1;font-weight:bold;">{last_sp['score']:.1f}</td>
                    <td style="padding:10px;text-align:center;border-bottom:1px solid #ecf0f1;"><span style="background:{sp_color};color:white;padding:4px 10px;border-radius:3px;font-size:12px;font-weight:bold;">{last_sp['zona']}</span></td>
                    <td style="padding:10px;text-align:right;border-bottom:1px solid #ecf0f1;font-weight:bold;">${aporte_sp:.0f}</td>
                </tr>
                <tr>
                    <td style="padding:10px;"><b>Nasdaq 100</b> (CFINASDAQ)</td>
                    <td style="padding:10px;text-align:center;font-weight:bold;">{last_nq['score']:.1f}</td>
                    <td style="padding:10px;text-align:center;"><span style="background:{nq_color};color:white;padding:4px 10px;border-radius:3px;font-size:12px;font-weight:bold;">{last_nq['zona']}</span></td>
                    <td style="padding:10px;text-align:right;font-weight:bold;">${aporte_nq:.0f}</td>
                </tr>
            </table>

            <div style="background:#ecf0f1;padding:15px;border-radius:5px;margin:15px 0;">
                <p style="margin:0 0 5px 0;color:#7f8c8d;font-size:12px;text-transform:uppercase;font-weight:bold;">Acción este mes</p>
                <p style="margin:0;font-size:18px;color:#2c3e50;"><b>Total a invertir: ${total:.0f} USD</b></p>
                {f'<p style="margin:5px 0 0 0;color:#27ae60;">💰 Guardar ${cash_adj:.0f} en cash táctico</p>' if cash_adj > 0 else ''}
                {f'<p style="margin:5px 0 0 0;color:#e74c3c;">💸 Sacar ${-cash_adj:.0f} del cash táctico</p>' if cash_adj < 0 else ''}
            </div>

            {news_html}
        </div>

        <div style="background:#34495e;color:#bdc3c7;padding:20px;text-align:center;font-size:12px;">
            <p style="margin:0;">Value Signal System · Alerta automática</p>
            <p style="margin:8px 0 0 0;opacity:0.7;">No es asesoría financiera. Sistema cuantitativo educativo.</p>
        </div>
    </div>
</body></html>
'''
    return html

# ============================================================
# ENVIO DE EMAIL
# ============================================================
def send_email(subject, html_body):
    if not SMTP_USER or not SMTP_PASS:
        print("ERROR: Faltan credenciales Gmail (GMAIL_USER, GMAIL_APP_PASSWORD)")
        return False

    msg = MIMEMultipart('alternative')
    msg['Subject'] = subject
    msg['From'] = SMTP_USER
    msg['To'] = EMAIL_TO
    msg.attach(MIMEText(html_body, 'html'))

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASS)
            server.send_message(msg)
        print(f"✓ Email enviado a {EMAIL_TO}")
        return True
    except Exception as e:
        print(f"ERROR enviando email: {e}")
        return False

# ============================================================
# MAIN
# ============================================================
def main():
    print(f"=== Value Signal Alert Monitor ===")
    print(f"Hora UTC: {datetime.now(timezone.utc).isoformat()}")

    state = load_state()

    # Descargar datos
    print("Descargando datos...")
    sp500    = fetch_monthly('^GSPC')
    nasdaq   = fetch_monthly('^NDX')
    rate_10y = fetch_monthly('^TNX')
    rate_3m  = fetch_monthly('^IRX')
    cape     = fetch_cape()

    if sp500 is None or nasdaq is None:
        print("ERROR: no se pudo descargar datos. Saltando esta ejecucion.")
        return

    data = pd.DataFrame({'sp500': sp500, 'nasdaq': nasdaq,
                         'rate_10y': rate_10y, 'rate_3m': rate_3m})
    data['yield_curve'] = data['rate_10y'] - data['rate_3m']

    sp = calc_scores(data['sp500'], data['rate_10y'], data['yield_curve'], cape)
    nq = calc_scores(data['nasdaq'], data['rate_10y'], data['yield_curve'], None)
    last_sp = sp.dropna(subset=['score']).iloc[-1]
    last_nq = nq.dropna(subset=['score']).iloc[-1]

    print(f"S&P 500: score {last_sp['score']:.1f} ({last_sp['zona']})")
    print(f"Nasdaq:  score {last_nq['score']:.1f} ({last_nq['zona']})")

    # Detectar eventos
    events = detect_events(last_sp, last_nq, state)
    print(f"Eventos detectados: {len(events)}")
    for ev in events:
        print(f"  - {ev['titulo']}")

    # Filtrar anti-spam
    events_to_send = filter_anti_spam(events, state)
    print(f"Eventos a enviar (post anti-spam): {len(events_to_send)}")

    # Si hay eventos, buscar noticias críticas y enviar email
    if events_to_send:
        print("Buscando noticias criticas...")
        critical_news = fetch_critical_news()
        print(f"Noticias criticas: {len(critical_news)}")

        # Subject del email
        top_event = events_to_send[0]
        subject = f"[Value Signal] {top_event['titulo']}"
        if len(events_to_send) > 1:
            subject += f" (+{len(events_to_send)-1} más)"

        html = render_email_html(events_to_send, last_sp, last_nq, critical_news)
        send_email(subject, html)
    else:
        print("Sin eventos relevantes. No se envia email.")

    # Actualizar estado
    state['sp_score_prev'] = float(last_sp['score'])
    state['sp_zona_prev']  = last_sp['zona']
    state['nq_score_prev'] = float(last_nq['score'])
    state['nq_zona_prev']  = last_nq['zona']
    save_state(state)

    print("Monitor completado.")

if __name__ == '__main__':
    main()
