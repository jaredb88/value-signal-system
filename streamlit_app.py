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
.metric-label { font-size: 0.8rem; opacity: 0.9; text-transform: uppercase; }
.metric-value { font-size: 1.4rem; font-weight: bold; }
.news-card { background: #1e1e2e; padding: 1rem; border-radius: 8px; margin: 0.5rem 0; border-left: 4px solid #4a90e2; }
.news-impact-positive { border-left-color: #2ecc71; }
.news-impact-negative { border-left-color: #e74c3c; }
.news-impact-neutral { border-left-color: #95a5a6; }
@media (max-width: 768px) {
    .big-score { font-size: 2.5rem; }
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
    df = yf.download(ticker, start=start, progress=False, auto_adjust=True)
    if df.empty: return None
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df['Close'].resample('ME').last()

@st.cache_data(ttl=3600)
def fetch_daily(ticker, period='1y'):
    df = yf.download(ticker, period=period, progress=False, auto_adjust=True)
    if df.empty: return None
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df['Close']

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
def analyze_etf(daily, name, ticker):
    if daily is None or len(daily) < 5:
        return None
    current = float(daily.iloc[-1])

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
        'r30': range_stats(daily, 30),
        'r180': range_stats(daily, 180),
        'r365': range_stats(daily, 365),
    }

# ============================================================
# UI PRINCIPAL
# ============================================================
st.title("📊 Value Signal System")
st.caption(f"Sistema cuantitativo para timing de aportes — Consulta: {datetime.now().strftime('%Y-%m-%d %H:%M')}")

# Descargar datos
with st.spinner("Descargando datos de mercado..."):
    sp500 = fetch_monthly('^GSPC')
    nasdaq = fetch_monthly('^NDX')
    rate_10y = fetch_monthly('^TNX')
    rate_3m = fetch_monthly('^IRX')
    cape_official = fetch_cape()

    cfisp_daily = fetch_daily('CFISP500.SN')
    cfinasd_daily = fetch_daily('CFINASDAQ.SN')

if sp500 is None or nasdaq is None:
    st.error("❌ Error descargando datos. Verifica tu conexion.")
    st.stop()

data = pd.DataFrame({
    'sp500': sp500, 'nasdaq': nasdaq,
    'rate_10y': rate_10y, 'rate_3m': rate_3m,
})
data['yield_curve'] = data['rate_10y'] - data['rate_3m']

sp = calc_scores(data['sp500'], data['rate_10y'], data['yield_curve'], cape_official)
nq = calc_scores(data['nasdaq'], data['rate_10y'], data['yield_curve'], None)
etf_sp = analyze_etf(cfisp_daily, 'S&P 500', 'CFISP500.SN')
etf_nq = analyze_etf(cfinasd_daily, 'Nasdaq 100', 'CFINASDAQ.SN')

last_sp = sp.dropna(subset=['score']).iloc[-1]
last_nq = nq.dropna(subset=['score']).iloc[-1]

# ============================================================
# CARDS PRINCIPALES (ambos arriba para vista de un vistazo)
# ============================================================
col1, col2 = st.columns(2)

def render_score_card(col, last, etf, name, ticker, aporte_base):
    mult = MULT.get(last['zona'], 1.0)
    aporte = aporte_base * mult
    zone_class = get_zone_class(last['zona'])
    emoji = get_zone_emoji(last['zona'])

    with col:
        st.markdown(f'<div class="score-card {zone_class}">', unsafe_allow_html=True)
        st.markdown(f'<div class="metric-label">{name} → {ticker}</div>', unsafe_allow_html=True)
        st.markdown(f'<div class="big-score">{last["score"]:.1f}</div>', unsafe_allow_html=True)
        st.markdown(f'<div class="zone-label">{emoji} {last["zona"]}</div>', unsafe_allow_html=True)
        st.markdown('</div>', unsafe_allow_html=True)

        # Sub-metricas
        c1, c2, c3 = st.columns(3)
        c1.metric("Multiplicador", f"{mult}x")
        c2.metric("Aporte mes", f"${aporte:.0f}")
        if etf:
            c3.metric("Precio CLP", f"${etf['current']:,.0f}")

        # Drawdown
        st.metric("Drawdown vs máximo", f"{last['drawdown']*100:+.1f}%",
                  delta=f"CAPE {last['cape']:.1f}", delta_color="off")

render_score_card(col1, last_sp, etf_sp, "S&P 500", "CFISPETF", APORTE_SP500)
render_score_card(col2, last_nq, etf_nq, "Nasdaq 100", "CFINASDAQ", APORTE_NASDAQ)

# ============================================================
# RESUMEN ACCION
# ============================================================
st.divider()
st.subheader("💰 Acción este mes")

total_invertir = APORTE_SP500 * MULT.get(last_sp['zona'], 1.0) + APORTE_NASDAQ * MULT.get(last_nq['zona'], 1.0)
total_base = APORTE_SP500 + APORTE_NASDAQ
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

                # Enrich con Groq si está disponible (lee de st.secrets o archivo local)
                try:
                    import os
                    # En Streamlit Cloud, el secret esta en st.secrets
                    if 'GROQ_API_KEY' in st.secrets:
                        os.environ['GROQ_API_KEY'] = st.secrets['GROQ_API_KEY']
                        # Tambien crear el archivo temporal que groq_interpreter espera
                        try:
                            Path('groq_api_key.txt').write_text(st.secrets['GROQ_API_KEY'])
                        except Exception:
                            pass

                    if os.environ.get('GROQ_API_KEY') or Path('groq_api_key.txt').exists():
                        from news_context import enrich_with_groq
                        with st.spinner("Procesando con IA (esto toma 20-30 seg)..."):
                            enrich_with_groq(news, max_items=max_news, verbose=False)
                except Exception as e:
                    st.warning(f"No se pudo procesar con IA: {e}")
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
                impacto = item.get('impacto', '').lower()
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

# Footer
st.divider()
st.caption("Value Signal System v2.1 · Datos: Yahoo Finance + Shiller Online · IA: Groq Llama 3.3")
