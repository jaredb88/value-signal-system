"""
VALUE SIGNAL DASHBOARD - Streamlit
====================================
Dashboard web del sistema Value Signal.
Funciona en local y en Streamlit Cloud.

Local:    streamlit run streamlit_app.py
Cloud:    deploy desde GitHub a https://share.streamlit.io

Estructura:
- Sidebar: configuracion (aportes, frecuencia)
- Tab 1:   Dashboard principal con cards de S&P y Nasdaq
- Tab 2:   Componentes detallados con barras
- Tab 3:   Noticias con traduccion + impacto
- Tab 4:   Historial CSV (si existe)
"""

import streamlit as st
import pandas as pd
import numpy as np
import yfinance as yf
import urllib.request
import io
import warnings
from datetime import datetime, timedelta, timezone
from pathlib import Path

warnings.filterwarnings('ignore')

# Modulo de Dividend ETFs (SCHD, JEPQ)
try:
    from dividend_etf_signal import analyze_dividend_etf, fetch_usd_clp, DIVIDEND_ETFS
    DIVIDEND_ETFS_AVAILABLE = True
except Exception:
    DIVIDEND_ETFS_AVAILABLE = False

# ============================================================
# CONFIGURACION PAGINA
# ============================================================
st.set_page_config(
    page_title="Value Signal System",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Mobile-friendly styles
st.markdown("""
<style>
.main { padding: 1rem; }
.score-card { padding: 1.5rem; border-radius: 10px; margin: 0.5rem 0; }
.zone-caro { background: linear-gradient(135deg, #ff6b6b, #c0392b); color: white; }
.zone-neutral { background: linear-gradient(135deg, #f39c12, #d35400); color: white; }
.zone-atractivo { background: linear-gradient(135deg, #2ecc71, #27ae60); color: white; }
.zone-oportunidad { background: linear-gradient(135deg, #00b09b, #96c93d); color: white; }
.big-score { font-size: 3.5rem; font-weight: bold; line-height: 1; }
.zone-label { font-size: 1.5rem; font-weight: bold; }
.metric-label { font-size: 1.3rem; opacity: 0.95; text-transform: uppercase; font-weight: 700; letter-spacing: 0.5px; margin-bottom: 0.5rem; }
.metric-value { font-size: 1.4rem; font-weight: bold; }
.ticker-name { font-size: 1.6rem; font-weight: bold; opacity: 1; margin-bottom: 0.3rem; }
.ticker-mapping { font-size: 1.1rem; opacity: 0.85; font-weight: 500; margin-bottom: 0.8rem; }
.score-max { font-size: 1.4rem; opacity: 0.7; font-weight: 500; }
.scale-bar { display: flex; height: 8px; border-radius: 4px; overflow: hidden; margin: 0.8rem 0 0.3rem 0; opacity: 0.95; }
.scale-segment { flex: 1; }
.scale-caro { background: #c0392b; }
.scale-neutral { background: #f39c12; }
.scale-atractivo { background: #27ae60; }
.scale-oportunidad { background: #00b09b; }
.scale-marker { position: relative; height: 0; }
.scale-marker-dot { position: absolute; top: -7px; width: 22px; height: 22px; background: white; border: 3px solid #2c3e50; border-radius: 50%; transform: translateX(-50%); box-shadow: 0 2px 6px rgba(0,0,0,0.4); }
.scale-legend { display: flex; justify-content: space-between; font-size: 0.7rem; opacity: 0.85; font-weight: 600; margin-top: 0.3rem; }
.news-card { background: #1e1e2e; padding: 1rem; border-radius: 8px; margin: 0.5rem 0; border-left: 4px solid #4a90e2; }
.news-impact-positive { border-left-color: #2ecc71; }
.news-impact-negative { border-left-color: #e74c3c; }
.news-impact-neutral { border-left-color: #95a5a6; }

/* Estilo sobrio (plain) - mismo look que cards de Dividend ETFs */
.score-card-plain { padding: 0.5rem 0; margin: 0.5rem 0; }
.ticker-name-plain { font-size: 1.6rem; font-weight: bold; color: inherit; margin-bottom: 0.2rem; }
.ticker-mapping-plain { font-size: 1rem; color: rgba(128,128,128,0.85); margin-bottom: 1rem; }
.big-score-plain { font-size: 3.5rem; font-weight: bold; line-height: 1; color: inherit; }
.score-max-plain { font-size: 1.4rem; opacity: 0.5; font-weight: 500; }
.zone-label-plain { font-size: 1.3rem; font-weight: bold; margin: 0.3rem 0 0.8rem 0; color: inherit; }

/* Summary card - vista compacta para resumen arriba (2x2) */
.summary-card { padding: 0.5rem 0; margin: 0.5rem 0; }
.summary-ticker { font-size: 1.6rem; font-weight: bold; color: inherit; margin-bottom: 0.2rem; }
.summary-sub { font-size: 1rem; color: rgba(128,128,128,0.85); margin-bottom: 0.8rem; }
.summary-score { font-size: 3rem; font-weight: bold; line-height: 1; color: inherit; }
.summary-score-max { font-size: 1.2rem; opacity: 0.5; font-weight: 500; }
.summary-zone { font-size: 1.2rem; font-weight: bold; margin: 0.3rem 0 0.6rem 0; color: inherit; }
@media (max-width: 768px) {
    .big-score { font-size: 2.5rem; }
    .ticker-name { font-size: 1.3rem; }
    .ticker-mapping { font-size: 0.95rem; }
}
</style>
""", unsafe_allow_html=True)

# ============================================================
# CONFIGURACION (sidebar)
# ============================================================
with st.sidebar:
    st.title("⚙️ Configuración")
    APORTE_SP500 = st.number_input("Aporte base S&P 500 (USD/mes)", value=140, min_value=0, step=10)
    APORTE_NASDAQ = st.number_input("Aporte base Nasdaq (USD/mes)", value=60, min_value=0, step=10)
    show_news = st.checkbox("Mostrar noticias", value=True)
    max_news = st.slider("Cantidad de noticias", 4, 12, 8)

    st.divider()
    st.subheader("💰 Dividend ETFs")
    APORTE_SCHD = st.number_input("Aporte SCHD (USD/mes)", value=140, min_value=0, step=10, help="Schwab US Dividend Equity ETF")
    APORTE_JEPQ = st.number_input("Aporte JEPQ (USD/mes)", value=60, min_value=0, step=10, help="JPMorgan Nasdaq Equity Premium Income ETF")

    st.divider()
    st.caption("Multiplicadores por zona:")
    st.caption("• CARO: 0.5x")
    st.caption("• NEUTRAL: 1.0x")
    st.caption("• ATRACTIVO: 1.5x")
    st.caption("• OPORTUNIDAD: 2.5x")

    st.divider()
    if st.button("🔄 Actualizar datos", use_container_width=True):
        st.cache_data.clear()
        st.rerun()

MULT = {'CARO': 0.5, 'NEUTRAL': 1.0, 'ATRACTIVO': 1.5, 'OPORTUNIDAD': 2.5}
WEIGHTS = {'cape': 0.40, 'drawdown': 0.25, 'ey_vs_bond': 0.15, 'yield_curve': 0.10, 'momentum': 0.10}

# ============================================================
# CACHE - 1 hora para no agotar APIs
# ============================================================
@st.cache_data(ttl=3600)
def fetch_monthly(ticker, start='1990-01-01'):
    import time
    for attempt in range(3):
        try:
            df = yf.download(ticker, start=start, progress=False, auto_adjust=True)
            if df.empty:
                if attempt < 2:
                    time.sleep(2)
                    continue
                return None
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            return df['Close'].resample('ME').last()
        except Exception:
            if attempt < 2:
                time.sleep(2)
                continue
            return None
    return None

@st.cache_data(ttl=3600)
def fetch_daily(ticker, period='1y'):
    import time
    for attempt in range(3):
        try:
            df = yf.download(ticker, period=period, progress=False, auto_adjust=True)
            if df.empty:
                if attempt < 2:
                    time.sleep(2)
                    continue
                return None
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            return df['Close']
        except Exception:
            if attempt < 2:
                time.sleep(2)
                continue
            return None
    return None

@st.cache_data(ttl=86400)  # 24 horas, CAPE es mensual
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
# CALCULO DE SCORES
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

def get_zone_class(zona):
    return {'CARO':'zone-caro', 'NEUTRAL':'zone-neutral',
            'ATRACTIVO':'zone-atractivo', 'OPORTUNIDAD':'zone-oportunidad'}.get(zona, '')

def get_zone_emoji(zona):
    return {'CARO':'🔴', 'NEUTRAL':'🟡', 'ATRACTIVO':'🟢', 'OPORTUNIDAD':'🟢🟢'}.get(zona, '⚪')

# ============================================================
# RANGOS DE PRECIO ETF
# ============================================================
@st.cache_data(ttl=600)  # 10 min cache
def load_bcs_prices():
    """Carga precios de prices.json (actualizado por GitHub Actions)."""
    import json
    from pathlib import Path
    try:
        prices_file = Path(__file__).parent / 'prices.json'
        if not prices_file.exists():
            return None
        with open(prices_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None


def get_bcs_price(bcs_data, ticker):
    """Extrae el precio de un ticker desde el dict de prices.json."""
    if not bcs_data or 'prices' not in bcs_data:
        return None
    ticker_data = bcs_data['prices'].get(ticker)
    if not ticker_data:
        return None
    precio = ticker_data.get('precio_cierre') or ticker_data.get('precio_actual')
    return float(precio) if precio else None


def analyze_etf(daily, name, ticker, bcs_data=None, bcs_ticker=None):
    if daily is None or len(daily) < 5:
        return None
    # Intentar precio oficial BCS primero
    current_bcs = None
    bcs_freshness = None
    if bcs_data and bcs_ticker:
        current_bcs = get_bcs_price(bcs_data, bcs_ticker)
        bcs_freshness = bcs_data.get('updated_at_utc')

    # Si hay precio BCS oficial, usarlo. Si no, fallback a Yahoo.
    if current_bcs:
        current = current_bcs
        precio_fuente = "BCS (oficial)"
    else:
        current = float(daily.iloc[-1])
        precio_fuente = "Yahoo Finance"

    def range_stats(series, days):
        if len(series) == 0: return None
        cutoff = series.index[-1] - pd.Timedelta(days=days)
        recent = series[series.index >= cutoff]
        if len(recent) == 0: return None
        return {'min': float(recent.min()), 'max': float(recent.max()),
                'avg': float(recent.mean())}

    return {
        'name': name, 'ticker': ticker,
        'current': current, 'date': daily.index[-1].strftime('%Y-%m-%d'),
        'precio_fuente': precio_fuente,
        'bcs_freshness': bcs_freshness,
        'r30': range_stats(daily, 30),
        'r180': range_stats(daily, 180),
        'r365': range_stats(daily, 365),
    }

# ============================================================
# UI PRINCIPAL
# ============================================================
st.title("📊 Value Signal System")
st.caption(f"Sistema cuantitativo para timing de aportes — Consulta: {datetime.now().strftime('%Y-%m-%d %H:%M')}")

with st.expander("ℹ️ ¿Cómo leer el score? (0-100)", expanded=False):
    st.markdown("""
    El **Score** combina 5 indicadores académicos en un puntaje de **0 a 100**, donde:
    - **0-25 = 🔴 CARO** → mercado en valuación alta vs su historia. Invierte la mitad ($100 base × 0.5)
    - **25-50 = 🟡 NEUTRAL** → valuación normal. Invierte lo planificado (DCA normal × 1.0)
    - **50-75 = 🟢 ATRACTIVO** → buena ventana de entrada. Invierte 50% más (× 1.5)
    - **75-100 = 🟢🟢 OPORTUNIDAD** → evento tipo Covid o crash. Carga fuerte (× 2.5)

    **Score más alto = mejor para comprar**. Score más bajo = mercado caro, modera aportes.
    """)

# Descargar datos
with st.spinner("Descargando datos de mercado..."):
    sp500 = fetch_monthly('^GSPC')
    nasdaq = fetch_monthly('^NDX')
    rate_10y = fetch_monthly('^TNX')
    rate_3m = fetch_monthly('^IRX')
    cape_official = fetch_cape()

    cfisp_daily = fetch_daily('CFISP500.SN')
    cfinasd_daily = fetch_daily('CFINASDAQ.SN')

# Cargar precios oficiales de Bolsa de Santiago (actualizado cada hora)
bcs_data = load_bcs_prices()

if sp500 is None or nasdaq is None:
    st.error("⏳ Yahoo Finance esta temporalmente saturado. Refresca en 5 minutos.")
    st.info("Esto puede pasar si hay muchas consultas. El sistema usa cache por 1 hora.")
    if st.button("🔄 Reintentar ahora"):
        st.cache_data.clear()
        st.rerun()
    st.stop()

data = pd.DataFrame({
    'sp500': sp500, 'nasdaq': nasdaq,
    'rate_10y': rate_10y, 'rate_3m': rate_3m,
})
data['yield_curve'] = data['rate_10y'] - data['rate_3m']

sp = calc_scores(data['sp500'], data['rate_10y'], data['yield_curve'], cape_official)
nq = calc_scores(data['nasdaq'], data['rate_10y'], data['yield_curve'], None)
etf_sp = analyze_etf(cfisp_daily, 'S&P 500', 'CFISP500.SN', bcs_data, 'CFISPETF')
etf_nq = analyze_etf(cfinasd_daily, 'Nasdaq 100', 'CFINASDAQ.SN', bcs_data, 'CFINASDAQ')

last_sp = sp.dropna(subset=['score']).iloc[-1]
last_nq = nq.dropna(subset=['score']).iloc[-1]

# ============================================================
# CARDS PRINCIPALES (ambos arriba para vista de un vistazo)
# ============================================================

# Cargar Dividend ETFs (SCHD, JEPQ) temprano para usar en resumen
div_results = {}
if DIVIDEND_ETFS_AVAILABLE:
    with st.spinner("Analizando Dividend ETFs..."):
        div_aportes = {"SCHD": APORTE_SCHD, "JEPQ": APORTE_JEPQ}
        for ticker_div in ["SCHD", "JEPQ"]:
            try:
                result = analyze_dividend_etf(
                    ticker_div,
                    aporte_base_usd=div_aportes[ticker_div],
                    usd_clp=None,
                )
                if result:
                    div_results[ticker_div] = result
            except Exception as e:
                st.warning(f"No se pudo analizar {ticker_div}: {e}")


def render_summary_card(col, ticker_label, sub_label, score, zona):
    """
    Card compacta para vista resumen arriba.
    Solo muestra: ticker, sub-label, score, zona y barra. Sin métricas detalladas.
    """
    emoji = {"CARO": "🔴", "NEUTRAL": "🟡", "ATRACTIVO": "🟢", "OPORTUNIDAD": "🟢🟢"}.get(zona, "")
    score_pct = max(0, min(100, score))

    with col:
        st.markdown(f'''<div class="summary-card">
            <div class="summary-ticker">{ticker_label}</div>
            <div class="summary-sub">{sub_label}</div>
            <div class="summary-score">{score:.1f}<span class="summary-score-max"> / 100</span></div>
            <div class="summary-zone">{emoji} {zona}</div>
            <div class="scale-bar" style="margin: 0.5rem 0 0.2rem 0;">
                <div class="scale-segment scale-caro"></div>
                <div class="scale-segment scale-neutral"></div>
                <div class="scale-segment scale-atractivo"></div>
                <div class="scale-segment scale-oportunidad"></div>
            </div>
            <div class="scale-marker">
                <div class="scale-marker-dot" style="left:{score_pct}%; width:16px; height:16px; top:-5px; border-width:2px;"></div>
            </div>
        </div>''', unsafe_allow_html=True)


# ============================================================
# SECCIÓN RESUMEN - 4 ETFs en 2x2
# ============================================================
st.subheader("📋 Resumen de inversiones")
st.caption("Vista rápida de todos los ETFs. Detalle completo más abajo.")

# Fila 1: Índices Bursátiles
sum_row1_col1, sum_row1_col2 = st.columns(2)

mult_sp = MULT.get(last_sp['zona'], 1.0)
render_summary_card(
    sum_row1_col1, "S&P 500", "CFISPETF · Índice Bursátil",
    last_sp['score'], last_sp['zona'],
)

mult_nq = MULT.get(last_nq['zona'], 1.0)
render_summary_card(
    sum_row1_col2, "Nasdaq 100", "CFINASDAQ · Índice Bursátil",
    last_nq['score'], last_nq['zona'],
)

# Fila 2: Dividend ETFs
sum_row2_col1, sum_row2_col2 = st.columns(2)

if "SCHD" in div_results:
    r_schd = div_results["SCHD"]
    render_summary_card(
        sum_row2_col1, "SCHD", "Dividend Growth",
        r_schd['score'], r_schd['zona'],
    )
else:
    with sum_row2_col1:
        st.info("SCHD no disponible")

if "JEPQ" in div_results:
    r_jepq = div_results["JEPQ"]
    render_summary_card(
        sum_row2_col2, "JEPQ", "Covered Call Income",
        r_jepq['score'], r_jepq['zona'],
    )
else:
    with sum_row2_col2:
        st.info("JEPQ no disponible")


# ============================================================
# SECCIÓN: ÍNDICES BURSÁTILES (S&P + Nasdaq detallados)
# ============================================================
st.divider()
st.header("📈 Índices Bursátiles (USA)")
st.caption("Detalle de S&P 500 y Nasdaq 100 — acceso desde Chile vía Singular AGF")

col1, col2 = st.columns(2)

def render_score_card(col, last, etf, name, ticker, aporte_base):
    mult = MULT.get(last['zona'], 1.0)
    aporte = aporte_base * mult
    emoji = get_zone_emoji(last['zona'])

    # Mapear zona a etiqueta de "tipo" (paralelo a Dividend ETFs)
    tipo_etf = "Índice Bursátil USA"

    with col:
        score_pct = max(0, min(100, last["score"]))

        # Card sobria (sin fondo de color, solo estructura limpia)
        st.markdown(f'''<div class="score-card-plain">
            <div class="ticker-name-plain">{name}</div>
            <div class="ticker-mapping-plain">→ {ticker} en Racional · {tipo_etf}</div>
            <div class="big-score-plain">{last["score"]:.1f}<span class="score-max-plain"> / 100</span></div>
            <div class="zone-label-plain">{emoji} {last["zona"]}</div>
            <div class="scale-bar">
                <div class="scale-segment scale-caro"></div>
                <div class="scale-segment scale-neutral"></div>
                <div class="scale-segment scale-atractivo"></div>
                <div class="scale-segment scale-oportunidad"></div>
            </div>
            <div class="scale-marker">
                <div class="scale-marker-dot" style="left:{score_pct}%"></div>
            </div>
            <div class="scale-legend">
                <span>0 CARO</span>
                <span>25 NEUTRAL</span>
                <span>50 ATRACTIVO</span>
                <span>75 OPORTUNIDAD</span>
                <span>100</span>
            </div>
        </div>''', unsafe_allow_html=True)

        # Métricas debajo de la card (mismo formato que Dividend ETFs)
        m1, m2, m3 = st.columns(3)
        m1.metric("Multiplicador", f"{mult}x")
        m2.metric("Aporte sugerido", f"${aporte:.0f} USD")
        if etf:
            m3.metric("Precio CLP", f"${etf['current']:,.0f}")

        # Indicadores clave (mismo formato sobrio que Dividend ETFs)
        st.markdown("**Indicadores clave:**")
        ic1, ic2 = st.columns(2)
        with ic1:
            st.caption(f"CAPE: **{last['cape']:.1f}**")
            st.caption(f"Drawdown vs máximo: **{last['drawdown']*100:+.1f}%**")
            st.caption(f"Earnings Yield vs Bono 10Y: **{last.get('ey_minus_bond', 0)*100:+.2f} pp**" if not pd.isna(last.get('ey_minus_bond', np.nan)) else "EY vs Bono: N/A")
        with ic2:
            st.caption(f"Momentum 12-1m: **{last.get('mom_12_1', 0)*100:+.1f}%**" if not pd.isna(last.get('mom_12_1', np.nan)) else "Momentum: N/A")
            st.caption(f"Yield Curve 10Y-3M: **{last.get('yield_spread', 0)*100:+.2f} pp**" if not pd.isna(last.get('yield_spread', np.nan)) else "Yield Curve: N/A")
            if etf:
                fuente = etf.get('precio_fuente', 'Yahoo Finance')
                st.caption(f"Fuente precio: **{fuente}**")

        # Descripción del índice (plegable)
        with st.expander(f"ℹ️ Acerca de {name}"):
            if name == "S&P 500":
                st.markdown("**S&P 500 (Standard & Poor's 500)**")
                st.markdown(
                    "Índice de las 500 compañías más grandes de USA por capitalización de mercado. "
                    "Cubre ~80% del mercado accionario norteamericano. Sectores diversificados: "
                    "tecnología, financiero, salud, consumo, energía, industrial. "
                    "Componentes seleccionados por un comité usando criterios de tamaño, liquidez y representatividad sectorial."
                )
                st.markdown("- **ETF accesible en Chile:** CFISPETF (FI ETF Singular S&P 500)")
                st.markdown("- **Emisor:** Singular AGF")
                st.markdown("- **Moneda:** CLP")
                st.markdown("- **Estrategia:** Pasiva (réplica del índice)")
            else:  # Nasdaq 100
                st.markdown("**Nasdaq 100 (NDX)**")
                st.markdown(
                    "Las 100 mayores compañías no-financieras listadas en Nasdaq. "
                    "Fuerte sesgo tecnológico: Apple, Microsoft, Nvidia, Google, Amazon, Meta, Tesla, etc. "
                    "También incluye consumo (Costco, Starbucks), salud (Amgen), industriales y otros. "
                    "Es el principal benchmark del sector tech/crecimiento USA."
                )
                st.markdown("- **ETF accesible en Chile:** CFINASDAQ (FI ETF Singular Nasdaq 100)")
                st.markdown("- **Emisor:** Singular AGF")
                st.markdown("- **Moneda:** CLP")
                st.markdown("- **Estrategia:** Pasiva (réplica del índice)")

        # Desglose del score (plegable)
        with st.expander("🔍 Desglose del score"):
            componentes_info = [
                ("CAPE (Shiller P/E)", "s_cape", "40%"),
                ("Drawdown vs máximo", "s_drawdown", "25%"),
                ("EY vs Bond", "s_ey_vs_bond", "15%"),
                ("Yield Curve", "s_yield_curve", "10%"),
                ("Momentum 12-1m", "s_momentum", "10%"),
            ]
            for nombre_c, key_c, peso_c in componentes_info:
                valor_c = last.get(key_c, 0)
                if pd.isna(valor_c):
                    valor_c = 0
                st.caption(f"**{nombre_c}** ({peso_c}): {valor_c:.1f}/100")

render_score_card(col1, last_sp, etf_sp, "S&P 500", "CFISPETF", APORTE_SP500)
render_score_card(col2, last_nq, etf_nq, "Nasdaq 100", "CFINASDAQ", APORTE_NASDAQ)

# ============================================================
# RESUMEN ACCION
# ============================================================
st.divider()
st.subheader("💰 Acción este mes")

# Calcular totales incluyendo Dividend ETFs
total_indices = APORTE_SP500 * MULT.get(last_sp['zona'], 1.0) + APORTE_NASDAQ * MULT.get(last_nq['zona'], 1.0)
base_indices = APORTE_SP500 + APORTE_NASDAQ

total_dividend = 0
base_dividend = 0
if "SCHD" in div_results:
    total_dividend += div_results["SCHD"]["aporte_sugerido_usd"]
    base_dividend += APORTE_SCHD
if "JEPQ" in div_results:
    total_dividend += div_results["JEPQ"]["aporte_sugerido_usd"]
    base_dividend += APORTE_JEPQ

total_invertir = total_indices + total_dividend
total_base = base_indices + base_dividend
cash_tactico = total_base - total_invertir

c1, c2, c3 = st.columns(3)
c1.metric("Total a invertir", f"${total_invertir:.0f} USD")
c2.metric("Base normal", f"${total_base:.0f} USD")
if cash_tactico > 0:
    c3.metric("💰 Guardar en cash", f"${cash_tactico:.0f} USD", delta="acumular")
elif cash_tactico < 0:
    c3.metric("💸 Sacar de cash", f"${-cash_tactico:.0f} USD", delta="desplegar", delta_color="inverse")
else:
    c3.metric("Cash táctico", "$0 USD", delta="estable")

# Desglose por tipo de ETF
with st.expander("📊 Desglose por tipo de ETF"):
    de1, de2 = st.columns(2)
    with de1:
        st.markdown("**📈 Índices Bursátiles**")
        st.caption(f"S&P 500 (CFISPETF): ${APORTE_SP500 * MULT.get(last_sp['zona'], 1.0):.0f} USD")
        st.caption(f"Nasdaq 100 (CFINASDAQ): ${APORTE_NASDAQ * MULT.get(last_nq['zona'], 1.0):.0f} USD")
        st.caption(f"**Subtotal: ${total_indices:.0f} USD**")
    with de2:
        st.markdown("**💰 Dividend ETFs**")
        if "SCHD" in div_results:
            st.caption(f"SCHD: ${div_results['SCHD']['aporte_sugerido_usd']:.0f} USD")
        if "JEPQ" in div_results:
            st.caption(f"JEPQ: ${div_results['JEPQ']['aporte_sugerido_usd']:.0f} USD")
        st.caption(f"**Subtotal: ${total_dividend:.0f} USD**")

# ============================================================
# TABS DE DETALLE
# ============================================================
tab1, tab2, tab3, tab4 = st.tabs(["📈 Componentes", "📰 Noticias", "📅 Histórico", "ℹ️ Sobre el sistema"])

# ============================================================
# TAB 1: Componentes detallados
# ============================================================
with tab1:
    COMPONENT_INFO = {
        'cape': ('CAPE', 0.40, 'Valuación largo plazo (Shiller P/E 10 años)'),
        'drawdown': ('Drawdown', 0.25, 'Caída desde el máximo histórico'),
        'ey_vs_bond': ('EY vs Bond', 0.15, 'Premium acciones vs bonos USA 10Y'),
        'yield_curve': ('Yield Curve', 0.10, 'Curva tasas 10Y-3M (régimen macro)'),
        'momentum': ('Momentum', 0.10, 'Tendencia 12-1 meses'),
    }

    def render_components(last, name):
        st.markdown(f"### {name}")
        for key, (label, weight, desc) in COMPONENT_INFO.items():
            v = last[f's_{key}']
            if pd.isna(v): v = 0
            color = "🔴" if v < 25 else "🟡" if v < 50 else "🟢" if v < 75 else "🟢🟢"
            interpret = (
                'MUY CARO' if key == 'cape' and v < 25 else
                'CARO' if key == 'cape' and v < 50 else
                'RAZONABLE' if key == 'cape' and v < 75 else
                'BARATO' if key == 'cape' else
                'EN MÁXIMOS' if key == 'drawdown' and v < 25 else
                'CAÍDA LEVE' if key == 'drawdown' and v < 50 else
                'CAÍDA SIGNIFICATIVA' if key == 'drawdown' and v < 75 else
                'CRASH' if key == 'drawdown' else
                'BONOS GANAN' if key == 'ey_vs_bond' and v < 25 else
                'PAREJO' if key == 'ey_vs_bond' and v < 50 else
                'ACCIONES MEJOR' if key == 'ey_vs_bond' else
                'CURVA INVERTIDA' if key == 'yield_curve' and v < 25 else
                'CURVA PLANA' if key == 'yield_curve' and v < 50 else
                'CURVA NORMAL' if key == 'yield_curve' else
                'BAJISTA' if key == 'momentum' and v < 25 else
                'LATERAL' if key == 'momentum' and v < 50 else
                'ALCISTA' if key == 'momentum' and v < 75 else
                'MUY ALCISTA'
            )
            st.markdown(f"**{color} {label}** ({weight:.0%}) — {interpret}")
            st.progress(v/100, text=f"{v:.1f}/100 · {desc}")

    c1, c2 = st.columns(2)
    with c1: render_components(last_sp, "S&P 500")
    with c2: render_components(last_nq, "Nasdaq 100")

# ============================================================
# TAB 2: Noticias
# ============================================================
with tab2:
    if not show_news:
        st.info("Activa el toggle de noticias en el sidebar para ver el contexto.")
    else:
        with st.spinner("Descargando contexto de noticias..."):
            try:
                from news_context import fetch_news_context
                news = fetch_news_context(days_back=7)

                # Enrich con Groq si está disponible
                try:
                    import os
                    # En Streamlit Cloud, leer la API key desde st.secrets
                    if 'GROQ_API_KEY' in st.secrets:
                        key_value = st.secrets['GROQ_API_KEY']
                        # Limpiar duplicado "gsk_gsk_" si existe (bug histórico)
                        if key_value.startswith('gsk_gsk_'):
                            key_value = key_value[4:]
                        os.environ['GROQ_API_KEY'] = key_value

                    # Procesar con IA si hay API key disponible
                    if os.environ.get('GROQ_API_KEY'):
                        from news_context import enrich_with_groq
                        with st.spinner("Procesando con IA (~20-30s)..."):
                            enrich_with_groq(news, max_items=max_news, verbose=False)
                except Exception:
                    # Si Groq falla, mostramos las noticias sin traducción
                    pass
            except Exception as e:
                st.error(f"Error cargando noticias: {e}")
                news = None

        if news and news.get('items'):
            # Temas dominantes
            if news.get('category_counts'):
                st.subheader("Temas dominantes esta semana")
                cat_df = pd.DataFrame([
                    {'Tema': k, 'Menciones': v}
                    for k, v in sorted(news['category_counts'].items(), key=lambda x: -x[1])
                ])
                st.bar_chart(cat_df.set_index('Tema'))

            # Noticias
            st.subheader(f"Top {min(max_news, len(news['items']))} titulares relevantes")
            for item in news['items'][:max_news]:
                impacto = (item.get('impacto') or '').lower()
                if 'positivo' in impacto and 'negativo' not in impacto:
                    border = 'news-impact-positive'
                elif 'negativo' in impacto:
                    border = 'news-impact-negative'
                else:
                    border = 'news-impact-neutral'

                date_str = item['date'].strftime('%Y-%m-%d') if item.get('date') else 'sin fecha'
                cats = ', '.join(item.get('categories', [])[:2]) or 'general'

                st.markdown(f'<div class="news-card {border}">', unsafe_allow_html=True)
                st.markdown(f"**[{date_str}]** *{item['source']}* — {cats}")
                st.markdown(f"**EN:** {item['title']}")
                if item.get('traduccion'):
                    st.markdown(f"**ES:** {item['traduccion']}")
                if item.get('impacto'):
                    st.markdown(f"**Impacto:** {item['impacto']}")
                if item.get('link'):
                    st.markdown(f"[Leer original →]({item['link']})")
                st.markdown('</div>', unsafe_allow_html=True)
        else:
            st.warning("No se pudieron cargar noticias.")

# ============================================================
# TAB 3: Histórico
# ============================================================
with tab3:
    st.subheader("Evolución del score (últimos 5 años)")

    c1, c2 = st.columns(2)
    sp5 = sp.dropna(subset=['score']).tail(60)
    nq5 = nq.dropna(subset=['score']).tail(60)

    with c1:
        st.markdown("**S&P 500**")
        st.line_chart(sp5['score'], height=300)
    with c2:
        st.markdown("**Nasdaq 100**")
        st.line_chart(nq5['score'], height=300)

    # CSV histórico si existe
    history_file = Path('value_signal_history.csv')
    if history_file.exists():
        st.subheader("Historial de consultas")
        try:
            hist = pd.read_csv(history_file)
            st.dataframe(hist.tail(20), use_container_width=True)
            csv = hist.to_csv(index=False)
            st.download_button("📥 Descargar histórico completo", csv,
                               "value_signal_history.csv", "text/csv")
        except Exception as e:
            st.warning(f"No se pudo leer el historial: {e}")

# ============================================================
# TAB 4: Sobre el sistema
# ============================================================
with tab4:
    st.markdown("""
    ### Sobre Value Signal System

    Sistema cuantitativo para timing de aportes en bolsa USA via ETFs Racional (CFISPETF + CFINASDAQ).

    **Componentes del score (0-100):**
    - **CAPE (40%):** Valuación largo plazo basada en Shiller P/E 10 años
    - **Drawdown (25%):** Caída desde el máximo histórico
    - **EY vs Bond (15%):** Premium de acciones vs bonos Treasury 10Y
    - **Yield Curve (10%):** Régimen macro vía curva de tasas
    - **Momentum (10%):** Tendencia 12-1 meses (Jegadeesh-Titman)

    **Zonas y multiplicadores:**
    - 🔴 CARO (0-25): 0.5x el aporte base
    - 🟡 NEUTRAL (25-50): 1.0x el aporte base
    - 🟢 ATRACTIVO (50-75): 1.5x el aporte base
    - 🟢🟢 OPORTUNIDAD (75-100): 2.5x el aporte base

    **Validación:** Walk-forward sobre datos reales 1990-2026, 100% ventanas con alpha positivo vs DCA puro.

    **Disclaimers:**
    - No es asesoría financiera. Sistema cuantitativo educativo.
    - Performance pasada no garantiza performance futura.
    - Mantener fondo de emergencia separado del capital de inversión.
    """)

# ====================================================================
# SECCIÓN: DIVIDEND ETFs DETALLE (SCHD, JEPQ)
# Ya descargados arriba en div_results
# ====================================================================
if DIVIDEND_ETFS_AVAILABLE:
    st.divider()
    st.header("💰 Dividend ETFs (USA)")
    st.caption("ETFs de income/dividendos para diversificación. Valores en USD.")

    # Mostrar cards de SCHD y JEPQ (los datos ya están en div_results)
    if div_results:
        col_schd, col_jepq = st.columns(2)

        for col, ticker_div in [(col_schd, "SCHD"), (col_jepq, "JEPQ")]:
            if ticker_div not in div_results:
                continue
            r = div_results[ticker_div]

            score_pct = max(0, min(100, r["score"]))

            with col:
                st.markdown(f'''<div class="score-card-plain">
                    <div class="ticker-name-plain">{r['name']}</div>
                    <div class="ticker-mapping-plain">{r['type']}</div>
                    <div class="big-score-plain">{r['score']:.1f}<span class="score-max-plain"> / 100</span></div>
                    <div class="zone-label-plain">{r['emoji']} {r['zona']}</div>
                    <div class="scale-bar">
                        <div class="scale-segment scale-caro"></div>
                        <div class="scale-segment scale-neutral"></div>
                        <div class="scale-segment scale-atractivo"></div>
                        <div class="scale-segment scale-oportunidad"></div>
                    </div>
                    <div class="scale-marker">
                        <div class="scale-marker-dot" style="left:{score_pct}%"></div>
                    </div>
                    <div class="scale-legend">
                        <span>0 CARO</span>
                        <span>25 NEUTRAL</span>
                        <span>50 ATRACTIVO</span>
                        <span>75 OPORTUNIDAD</span>
                        <span>100</span>
                    </div>
                </div>''', unsafe_allow_html=True)

                # Métricas debajo de la card
                m1, m2, m3 = st.columns(3)
                m1.metric("Multiplicador", f"{r['multiplicador']}x")
                m2.metric("Aporte sugerido", f"${r['aporte_sugerido_usd']:.0f} USD")
                m3.metric("Precio actual", f"${r['precio_usd']:.2f}")

                # Indicadores clave
                st.markdown("**Indicadores clave:**")
                ic1, ic2 = st.columns(2)
                with ic1:
                    st.caption(f"DY actual: **{r['dy_actual_pct']}%**")
                    st.caption(f"DY promedio 3y: **{r['dy_historico_3y_pct']}%**")
                    st.caption(f"DGR 3y: **{r['dgr_3y_pct']}%**")
                with ic2:
                    st.caption(f"CAGR precio 3y: **{r['cagr_precio_3y_pct']}%**")
                    if r.get('cagr_precio_5y_pct'):
                        st.caption(f"CAGR precio 5y: **{r['cagr_precio_5y_pct']}%**")
                    else:
                        st.caption("CAGR 5y: N/A")
                    st.caption(f"Drawdown: **{r['drawdown_pct']}%**")

                # Descripción del ETF (plegable)
                with st.expander(f"ℹ️ Acerca de {r['name']}"):
                    st.markdown(f"**{r['long_name']}**")
                    st.markdown(r['description'])
                    st.markdown(f"- **Inception:** {r['inception']}")
                    st.markdown(f"- **Expense ratio:** {r['expense_ratio']*100:.2f}%")
                    st.markdown(f"- **Frecuencia de pago:** {r['frequency']}")

                # Desglose del score
                with st.expander("🔍 Desglose del score"):
                    componentes_info = [
                        ("DY actual vs histórico", "dy_vs_historico", "35%"),
                        ("Drawdown vs máximo", "drawdown", "25%"),
                        ("Balance CAGR + DY", "balance_cagr", "15%"),
                        ("Momentum 12-1m", "momentum", "10%"),
                        ("Dividend Growth Rate", "dgr", "15%"),
                    ]
                    for nombre, key, peso in componentes_info:
                        valor = r['componentes'].get(key, 0)
                        st.caption(f"**{nombre}** ({peso}): {valor:.1f}/100")

    with st.expander("ℹ️ ¿Cómo se calcula el score de Dividend ETFs?"):
        st.markdown("""
        A diferencia de los ETFs de índices (S&P 500, Nasdaq), los Dividend ETFs se evalúan con criterios específicos de income investing:

        - **DY actual vs histórico (35%)**: si el yield actual está arriba de su promedio 3y, el precio está atractivo
        - **Drawdown vs máximo (25%)**: caídas generan oportunidades de entrada
        - **Balance CAGR + DY (15%)**: total return esperado (apreciación + income)
        - **Momentum 12-1m (10%)**: confirmación de tendencia
        - **Dividend Growth Rate (15%)**: premio a ETFs donde los dividendos crecen consistentemente

        Multiplicadores: misma lógica que ETFs de índices (0.5x CARO, 1.0x NEUTRAL, 1.5x ATRACTIVO, 2.5x OPORTUNIDAD).
        """)

else:
    st.warning("Módulo de Dividend ETFs no disponible. Verifica que dividend_etf_signal.py esté en el repo.")


# Footer
st.divider()
st.caption("Value Signal System v2.2 · Datos: Yahoo Finance + Shiller Online + BCS · IA: Groq Llama 3.3")
