"""
VALUE SIGNAL SYSTEM - Standalone v2.1
======================================

Mejoras vs v2.0:
- Descripción educativa de cada componente del score
- Precios actuales de CFISPETF y CFINASDAQ en Racional
- Rangos de precios últimos 30 días, 6 meses y 1 año
- % distancia del precio actual vs mínimo/máximo del rango
- Indicador visual de posición en rango anual
- Alertas extra si ETFs están cerca de mínimos
"""

import sys
import os
import csv
import urllib.request
import io
import warnings
from datetime import datetime
from pathlib import Path

warnings.filterwarnings('ignore')

APORTE_SP500  = 140
APORTE_NASDAQ = 60

MULT = {'CARO': 0.5, 'NEUTRAL': 1.0, 'ATRACTIVO': 1.5, 'OPORTUNIDAD': 2.5}
WEIGHTS = {'cape': 0.40, 'drawdown': 0.25, 'ey_vs_bond': 0.15,
           'yield_curve': 0.10, 'momentum': 0.10}

COMPONENT_INFO = {
    'cape': {
        'name':   'CAPE',
        'weight': 0.40,
        'que_es': 'Valuacion del mercado vs su historia (Shiller P/E 10 anos)',
        'interpret': lambda score: (
            'MUY CARO: mercado en valuacion historica alta. Retornos esperados a 10 anos bajos. Modera aportes.' if score < 25 else
            'CARO: por sobre el promedio historico. Retornos esperados moderados.' if score < 50 else
            'RAZONABLE: valuacion cerca de la media historica. Buenos retornos esperados.' if score < 75 else
            'BARATO: valuacion historicamente baja. Retornos esperados altos a largo plazo. Buen momento para acumular.'
        ),
    },
    'drawdown': {
        'name':   'Drawdown',
        'weight': 0.25,
        'que_es': 'Caida actual desde el maximo historico',
        'interpret': lambda score: (
            'EN MAXIMOS: precio en o cerca del techo. Sin caida que aprovechar.' if score < 25 else
            'CAIDA LEVE: correccion menor en curso (5-12% bajo el maximo).' if score < 50 else
            'CAIDA SIGNIFICATIVA: correccion fuerte (15-25% bajo el maximo). Oportunidad emergente.' if score < 75 else
            'CRASH: caida muy profunda (>30%). Evento tipo 2008/2020. Cargar agresivamente.'
        ),
    },
    'ey_vs_bond': {
        'name':   'EY vs Bond',
        'weight': 0.15,
        'que_es': 'Premium de acciones vs bonos USA 10Y (Earnings Yield - Treasury 10Y)',
        'interpret': lambda score: (
            'BONOS GANAN: renta fija paga mas que acciones. Las acciones no compensan el riesgo extra.' if score < 25 else
            'PAREJO: premium bajo. Acciones y bonos ofrecen retornos similares.' if score < 50 else
            'ACCIONES FAVORECIDAS: premium normal-alto. Acciones compensan bien el riesgo.' if score < 75 else
            'ACCIONES MUY FAVORECIDAS: premium historicamente alto. Las acciones pagan mucho mas que bonos.'
        ),
    },
    'yield_curve': {
        'name':   'Yield Curve',
        'weight': 0.10,
        'que_es': 'Diferencia tasa 10 anos menos tasa 3 meses (regimen macro USA)',
        'interpret': lambda score: (
            'CURVA INVERTIDA: senal historica de recesion a 12-18 meses. Cautela.' if score < 25 else
            'CURVA PLANA: economia desacelerando, sin senal clara de recesion.' if score < 50 else
            'CURVA NORMAL: expansion economica saludable.' if score < 75 else
            'CURVA EMPINADA: expansion fuerte, condiciones financieras muy favorables.'
        ),
    },
    'momentum': {
        'name':   'Momentum',
        'weight': 0.10,
        'que_es': 'Tendencia ultimos 12 meses excluyendo el ultimo (Jegadeesh-Titman)',
        'interpret': lambda score: (
            'TENDENCIA BAJISTA: el mercado viene cayendo. No pelearse con la tendencia.' if score < 25 else
            'LATERAL O DEBIL: sin tendencia clara o subida modesta.' if score < 50 else
            'TENDENCIA ALCISTA: mercado en sostenida subida.' if score < 75 else
            'MOMENTUM FUERTE: tendencia alcista muy marcada. Cuidado con extension.'
        ),
    },
}

SCRIPT_DIR = Path(__file__).parent
HISTORY_FILE = SCRIPT_DIR / 'value_signal_history.csv'

def enable_windows_ansi():
    if os.name == 'nt':
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
        except Exception:
            pass

enable_windows_ansi()

class C:
    RED='\033[91m'; YELLOW='\033[93m'; GREEN='\033[92m'; BGREEN='\033[1;92m'
    BLUE='\033[94m'; CYAN='\033[96m'; BOLD='\033[1m'; DIM='\033[2m'; RESET='\033[0m'

def check_dependencies():
    missing = []
    try: import yfinance
    except ImportError: missing.append('yfinance')
    try: import pandas
    except ImportError: missing.append('pandas')
    try: import numpy
    except ImportError: missing.append('numpy')
    if missing:
        print(f"\n{C.RED}Faltan dependencias: {', '.join(missing)}{C.RESET}")
        print(f"\nInstala con: pip install {' '.join(missing)}\n")
        input("Presiona ENTER para salir...")
        sys.exit(1)

check_dependencies()

import numpy as np
import pandas as pd
import yfinance as yf

# Modulo opcional de noticias
try:
    from news_context import fetch_news_context, render_news
    NEWS_AVAILABLE = True
except ImportError:
    NEWS_AVAILABLE = False

pd.options.display.float_format = '{:,.2f}'.format

def fetch_monthly(ticker, start='1990-01-01'):
    df = yf.download(ticker, start=start, progress=False, auto_adjust=True)
    if df.empty: return None
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df['Close'].resample('ME').last()

def fetch_daily(ticker, period='1y'):
    df = yf.download(ticker, period=period, progress=False, auto_adjust=True)
    if df.empty: return None
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df['Close']

def fetch_cape_official():
    try:
        url = 'https://raw.githubusercontent.com/datasets/s-and-p-500/main/data/data.csv'
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=15) as r:
            shiller = pd.read_csv(io.BytesIO(r.read()))
        shiller['Date'] = pd.to_datetime(shiller['Date'])
        shiller = shiller.set_index('Date')
        cape = shiller['PE10'].copy()
        cape = cape[cape > 0]
        return cape.resample('ME').last().ffill()
    except Exception:
        return None

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
    df['r10y'] = rate_10y
    df['yc'] = yc
    df[['r10y','yc']] = df[['r10y','yc']].ffill()
    df['s_cape'] = df['cape'].rolling(240, min_periods=60).apply(
        lambda x: (x.iloc[-1] < x).mean()*100, raw=False)
    df['s_drawdown'] = np.clip(-df['drawdown']*200, 0, 100)
    df['s_ey_vs_bond'] = (1/df['cape'] - df['r10y']/100).rolling(240, min_periods=60).apply(
        lambda x: (x.iloc[-1] > x).mean()*100, raw=False)
    df['s_yield_curve'] = np.clip((df['yc']+2)/5*100, 0, 100)
    df['s_momentum'] = np.clip((df['momentum']+0.2)/0.6*100, 0, 100)
    df['score'] = sum(df[f's_{k}']*v for k,v in WEIGHTS.items())
    df['zona']  = df['score'].apply(
        lambda s: 'sin_datos' if pd.isna(s)
        else 'CARO' if s<25
        else 'NEUTRAL' if s<50
        else 'ATRACTIVO' if s<75
        else 'OPORTUNIDAD')
    return df

def analyze_etf_prices(daily_prices, name, ticker):
    if daily_prices is None or len(daily_prices) < 5:
        return None
    current = float(daily_prices.iloc[-1])
    last_date = daily_prices.index[-1]

    def range_stats(series, days):
        if len(series) == 0:
            return None
        cutoff = series.index[-1] - pd.Timedelta(days=days)
        recent = series[series.index >= cutoff]
        if len(recent) == 0:
            return None
        return {
            'min': float(recent.min()),
            'max': float(recent.max()),
            'min_date': recent.idxmin().strftime('%Y-%m-%d'),
            'max_date': recent.idxmax().strftime('%Y-%m-%d'),
            'avg': float(recent.mean()),
            'days_real': len(recent),
        }

    return {
        'name':    name,
        'ticker':  ticker,
        'current': current,
        'date':    last_date.strftime('%Y-%m-%d'),
        'r30':     range_stats(daily_prices, 30),
        'r180':    range_stats(daily_prices, 180),
        'r365':    range_stats(daily_prices, 365),
    }

def render_etf_panel(etf_data):
    if etf_data is None:
        print(f'  {C.DIM}(sin datos del ETF){C.RESET}')
        return
    cur = etf_data['current']
    print()
    print(f'  Precio actual {etf_data["ticker"]}: '
          f'{C.CYAN}${cur:,.2f} CLP{C.RESET}  ({etf_data["date"]})')
    print()

    periods = [
        ('Ultimos 30 dias',  etf_data['r30']),
        ('Ultimos 6 meses',  etf_data['r180']),
        ('Ultimo ano',       etf_data['r365']),
    ]
    print(f'  {C.BOLD}Rangos historicos del ETF:{C.RESET}')
    print(f'  {"Periodo":<18}{"Minimo":>12}{"Maximo":>12}{"vs Min":>10}{"vs Max":>10}')
    print(f'  {"-"*62}')

    for label, r in periods:
        if r is None: continue
        pct_vs_min = ((cur / r['min']) - 1) * 100
        pct_vs_max = ((cur / r['max']) - 1) * 100
        max_color = C.RED if pct_vs_max >= -3 else C.YELLOW if pct_vs_max >= -10 else C.GREEN
        min_color = C.GREEN if pct_vs_min <= 3 else C.YELLOW if pct_vs_min <= 10 else C.DIM
        print(f'  {label:<18}{r["min"]:>12,.2f}{r["max"]:>12,.2f}'
              f'{min_color}{pct_vs_min:>+9.1f}%{C.RESET}'
              f'{max_color}{pct_vs_max:>+9.1f}%{C.RESET}')

    if etf_data['r365']:
        r = etf_data['r365']
        pos = (cur - r['min']) / (r['max'] - r['min']) if r['max'] > r['min'] else 0.5
        pos = max(0, min(1, pos))
        bar_len = 30
        marker_pos = min(int(pos * bar_len), bar_len - 1)
        bar = ['-'] * bar_len
        bar[marker_pos] = '*'
        bar_str = ''.join(bar)
        position_label = (
            f'{C.RED}cerca maximo{C.RESET}'  if pos >= 0.85 else
            f'{C.YELLOW}zona alta{C.RESET}'  if pos >= 0.60 else
            f'{C.YELLOW}zona media{C.RESET}' if pos >= 0.40 else
            f'{C.GREEN}zona baja{C.RESET}'   if pos >= 0.15 else
            f'{C.GREEN}cerca minimo{C.RESET}'
        )
        print()
        print(f'  Posicion en rango anual:')
        print(f'  min [{bar_str}] max   {pos*100:.0f}% del rango -- {position_label}')

def color_for_zone(zona):
    return {'CARO': C.RED, 'NEUTRAL': C.YELLOW,
            'ATRACTIVO': C.GREEN, 'OPORTUNIDAD': C.BGREEN}.get(zona, '')

def emoji_for_zone(zona):
    return {'CARO': '[CARO]', 'NEUTRAL': '[NEUTRAL]',
            'ATRACTIVO': '[ATRACTIVO]', 'OPORTUNIDAD': '[OPORTUNIDAD]'}.get(zona, '')

def render_panel(df, name, ticker_racional, aporte_base, etf_data=None):
    valid = df.dropna(subset=['score'])
    last = valid.iloc[-1]
    prev = valid.iloc[-2] if len(valid) >= 2 else last
    mult = MULT.get(last['zona'], 1.0)
    aporte = aporte_base * mult
    color = color_for_zone(last['zona'])

    print()
    print('=' * 70)
    print(f'  {C.BOLD}{name}{C.RESET}  -->  {C.BLUE}{ticker_racional}{C.RESET} en Racional')
    print(f'  Datos del indice al {last.name.date()}')
    print('=' * 70)

    if etf_data:
        render_etf_panel(etf_data)

    print()
    print(f'  {C.BOLD}Metricas del indice subyacente:{C.RESET}')
    print(f'  Precio indice:    {last["price"]:>12,.2f}')
    print(f'  CAPE:             {last["cape"]:>12.2f}')
    print(f'  Score:            {color}{last["score"]:>12.1f}{C.RESET}  / 100')
    print(f'  Zona:             {color}{last["zona"]}{C.RESET}')
    print()

    if last['zona'] != prev['zona']:
        print(f'  *** CAMBIO DE ZONA: {prev["zona"]} -> {last["zona"]} ***')
        print()

    delta = last['score'] - prev['score']
    arrow = 'sube' if delta > 0 else 'baja' if delta < 0 else 'igual'
    print(f'  Cambio vs periodo anterior:  {arrow} {delta:+.1f} pts')
    print(f'  Drawdown vs maximo:          {last["drawdown"]*100:+.1f}%')
    print()

    print(f'  {C.BOLD}ACCION ESTE MES:{C.RESET}')
    print(f'     Multiplicador:       {mult}x')
    print(f'     Aportar a {ticker_racional:<10}  ${aporte:>5.0f}  (base ${aporte_base})')

    diff = aporte_base - aporte
    if diff > 0:
        print(f'     (+) Cash tactico:   guardar ${diff:.0f}')
    elif diff < 0:
        print(f'     (-) Cash tactico:   sacar ${-diff:.0f}')

    print()
    print(f'  {C.BOLD}Componentes del score:{C.RESET}')
    print(f'  {C.DIM}(cada uno va de 0 a 100; mayor = mas favorable para comprar){C.RESET}')

    component_keys = ['cape', 'drawdown', 'ey_vs_bond', 'yield_curve', 'momentum']
    for key in component_keys:
        info = COMPONENT_INFO[key]
        v = last[f's_{key}']
        if pd.isna(v): v = 0
        bar_len = int(max(0, min(v, 100))/5)
        bar = '#' * bar_len + '.' * (20 - bar_len)
        val_color = C.RED if v < 25 else C.YELLOW if v < 50 else C.GREEN if v < 75 else C.BGREEN
        weight_pct = int(info['weight'] * 100)
        interpretacion = info['interpret'](v)
        print()
        print(f'  {C.BOLD}{info["name"]:<12}{C.RESET} ({weight_pct}%): [{bar}] {val_color}{v:>5.1f}{C.RESET}')
        print(f'     {C.DIM}Que mide: {info["que_es"]}{C.RESET}')
        print(f'     {val_color}>>> {interpretacion}{C.RESET}')

    return last, aporte

def save_to_history(last_sp, last_nq, aporte_sp, aporte_nq, etf_sp, etf_nq):
    is_new = not HISTORY_FILE.exists()
    with open(HISTORY_FILE, 'a', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        if is_new:
            w.writerow([
                'timestamp_consulta', 'fecha_dato',
                'sp500_precio_indice', 'sp500_cape', 'sp500_score', 'sp500_zona', 'sp500_aporte',
                'cfispetf_precio_clp', 'cfispetf_min_30d', 'cfispetf_max_30d',
                'nasdaq_precio_indice', 'nasdaq_cape', 'nasdaq_score', 'nasdaq_zona', 'nasdaq_aporte',
                'cfinasdaq_precio_clp', 'cfinasdaq_min_30d', 'cfinasdaq_max_30d',
                'total_aporte', 'cash_tactico_ajuste'
            ])
        total = aporte_sp + aporte_nq
        base_total = APORTE_SP500 + APORTE_NASDAQ
        ajuste = base_total - total
        w.writerow([
            datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            last_sp.name.date(),
            f"{last_sp['price']:.2f}", f"{last_sp['cape']:.2f}",
            f"{last_sp['score']:.1f}", last_sp['zona'], f"{aporte_sp:.0f}",
            f"{etf_sp['current']:.2f}" if etf_sp else '',
            f"{etf_sp['r30']['min']:.2f}" if etf_sp and etf_sp['r30'] else '',
            f"{etf_sp['r30']['max']:.2f}" if etf_sp and etf_sp['r30'] else '',
            f"{last_nq['price']:.2f}", f"{last_nq['cape']:.2f}",
            f"{last_nq['score']:.1f}", last_nq['zona'], f"{aporte_nq:.0f}",
            f"{etf_nq['current']:.2f}" if etf_nq else '',
            f"{etf_nq['r30']['min']:.2f}" if etf_nq and etf_nq['r30'] else '',
            f"{etf_nq['r30']['max']:.2f}" if etf_nq and etf_nq['r30'] else '',
            f"{total:.0f}", f"{ajuste:.0f}"
        ])
    print(f'\n  Guardado en historial: {HISTORY_FILE.name}')

def generate_narrative(last_sp, last_nq, etf_sp, etf_nq):
    """Genera un parrafo narrativo combinando todos los indicadores."""
    lines = []
    lines.append('')
    lines.append(f'{C.BOLD}{"="*70}{C.RESET}')
    lines.append(f'{C.BOLD}  LECTURA COMPLETA DEL MERCADO HOY{C.RESET}')
    lines.append(f'{C.BOLD}{"="*70}{C.RESET}')
    lines.append('')

    # ---- TABLA RESUMEN ----
    lines.append(f'  {C.BOLD}Resumen de indicadores:{C.RESET}')
    lines.append(f'  {"Indicador":<14}{"S&P 500":<22}{"Nasdaq":<22}')
    lines.append(f'  {"-"*58}')

    def label_for(key, score):
        info = COMPONENT_INFO[key]
        # Extraer solo la primera palabra clave de la interpretacion
        full = info['interpret'](score)
        # Tomar antes del primer ':' o primeras 2 palabras
        label = full.split(':')[0]
        return f'{label} ({score:.0f})'

    sp_score = last_sp['score']
    nq_score = last_nq['score']
    sp_zona = last_sp['zona']
    nq_zona = last_nq['zona']

    sp_color = color_for_zone(sp_zona)
    nq_color = color_for_zone(nq_zona)

    lines.append(f'  {"Score":<14}{sp_color}{sp_score:.1f} ({sp_zona}){C.RESET}'.ljust(50) +
                 f'  {nq_color}{nq_score:.1f} ({nq_zona}){C.RESET}')

    for key in ['cape', 'drawdown', 'ey_vs_bond', 'yield_curve', 'momentum']:
        sp_val = last_sp[f's_{key}']
        nq_val = last_nq[f's_{key}']
        sp_label = label_for(key, sp_val)
        nq_label = label_for(key, nq_val)
        info_name = COMPONENT_INFO[key]['name']
        lines.append(f'  {info_name:<14}{sp_label:<22}{nq_label:<22}')

    lines.append('')

    # ---- HISTORIA EN UN PARRAFO ----
    lines.append(f'  {C.BOLD}La historia completa:{C.RESET}')
    lines.append('')

    # Construir frases dinamicas segun valores
    frases = []

    # Frase 1: Valuacion (CAPE)
    sp_cape = last_sp['s_cape']
    nq_cape = last_nq['s_cape']
    if sp_cape < 25 and nq_cape < 25:
        frases.append('El mercado USA esta caro vs su historia (CAPE en zona alta)')
    elif sp_cape > 75 and nq_cape > 75:
        frases.append('El mercado USA esta historicamente barato (CAPE bajo)')
    elif sp_cape < 50 and nq_cape < 50:
        frases.append('El mercado USA esta por sobre su valuacion historica promedio')
    else:
        frases.append('El mercado USA esta en valuacion razonable vs su historia')

    # Frase 2: Drawdown / posicion ETFs
    sp_dd = last_sp['drawdown']
    nq_dd = last_nq['drawdown']

    etf_sp_pos = None
    etf_nq_pos = None
    if etf_sp and etf_sp['r365']:
        r = etf_sp['r365']
        if r['max'] > r['min']:
            etf_sp_pos = (etf_sp['current'] - r['min']) / (r['max'] - r['min'])
    if etf_nq and etf_nq['r365']:
        r = etf_nq['r365']
        if r['max'] > r['min']:
            etf_nq_pos = (etf_nq['current'] - r['min']) / (r['max'] - r['min'])

    if sp_dd >= -0.02 and nq_dd >= -0.02:
        if etf_sp_pos is not None and etf_sp_pos >= 0.95:
            frases.append('y los ETFs Racional estan exactamente en sus maximos del año (100% del rango anual)')
        else:
            frases.append('y los indices estan en o muy cerca de sus maximos historicos')
    elif sp_dd <= -0.20 or nq_dd <= -0.20:
        worst = min(sp_dd, nq_dd)
        frases.append(f'pero hay una correccion significativa en curso (drawdown de {worst*100:.0f}%)')
    elif sp_dd <= -0.10 or nq_dd <= -0.10:
        frases.append('con una correccion menor en curso (drawdown 10-15%)')

    # Frase 3: Renta fija vs acciones
    sp_ey = last_sp['s_ey_vs_bond']
    if sp_ey < 25:
        frases.append('Ademas, los bonos USA pagan mas que las acciones, lo que reduce el atractivo relativo de la bolsa')
    elif sp_ey > 75:
        frases.append('Ademas, las acciones pagan mucho mas que los bonos, dando un premium historicamente alto')

    # Frase 4: Macro (yield curve)
    sp_yc = last_sp['s_yield_curve']
    if sp_yc < 25:
        frases.append('La curva de tasas esta invertida, senal historica de recesion en 12-18 meses')
    elif sp_yc > 50:
        frases.append('La economia esta sana (curva de tasas normal, sin senal de recesion inminente)')
    else:
        frases.append('La economia esta desacelerando aunque sin senales claras de recesion')

    # Frase 5: Momentum
    sp_mom = last_sp['s_momentum']
    nq_mom = last_nq['s_momentum']
    if sp_mom > 75 and nq_mom > 75:
        frases.append('y la tendencia alcista sigue siendo muy fuerte, especialmente en Nasdaq')
    elif sp_mom > 50:
        frases.append('y la tendencia sigue siendo alcista')
    elif sp_mom < 25:
        frases.append('y la tendencia es bajista, no pelearse con ella')
    else:
        frases.append('con tendencia lateral o debil')

    # Frase 6: Diagnostico final
    if sp_score < 25 and nq_score < 25:
        if sp_yc > 50:
            frases.append('Es un mercado caro pero no en panico. La economia funciona bien pero las valuaciones son altas')
        else:
            frases.append('Combinacion riesgosa: valuaciones altas Y macro debilitandose')
    elif sp_score > 75 or nq_score > 75:
        frases.append('Combinacion historicamente atractiva: posiblemente la mejor ventana en años para entrar agresivamente')
    elif sp_score > 50 or nq_score > 50:
        frases.append('Hay ventana razonable de entrada, sin ser euforica')

    # Armar el parrafo: detectar conectores (frases que empiezan con minuscula)
    # y unirlas con coma en vez de punto.
    narrative = ''
    for i, f in enumerate(frases):
        if i == 0:
            narrative = f
        elif f and f[0].islower():
            narrative += ', ' + f
        else:
            narrative += '. ' + f
    narrative += '.'
    import textwrap
    wrapped = textwrap.fill(narrative, width=66, initial_indent='  ', subsequent_indent='  ')
    lines.append(wrapped)

    lines.append('')

    # ---- ESTRATEGIA RECOMENDADA ----
    lines.append(f'  {C.BOLD}Estrategia correcta para hoy:{C.RESET}')
    lines.append('')

    sp_mult = MULT.get(sp_zona, 1.0)
    nq_mult = MULT.get(nq_zona, 1.0)
    aporte_sp = APORTE_SP500 * sp_mult
    aporte_nq = APORTE_NASDAQ * nq_mult
    total = aporte_sp + aporte_nq
    base = APORTE_SP500 + APORTE_NASDAQ
    cash_ajuste = base - total

    if sp_score < 25 and nq_score < 25:
        lines.append(f'  - Aportar la mitad: ${aporte_sp:.0f} a CFISPETF + ${aporte_nq:.0f} a CFINASDAQ = ${total:.0f}')
        lines.append(f'  - Guardar la otra mitad (${cash_ajuste:.0f}) en cash tactico')
        lines.append(f'  - Esperar correcciones para desplegarlo (eventos tipo Covid 2020 o crashes)')
        lines.append(f'  - NO entrar en panico ni vender lo que ya tienes: el mercado puede seguir caro un tiempo')
    elif sp_score > 75 or nq_score > 75:
        lines.append(f'  - APORTAR FUERTE: ${aporte_sp:.0f} a CFISPETF + ${aporte_nq:.0f} a CFINASDAQ = ${total:.0f}')
        lines.append(f'  - Desplegar ${-cash_ajuste:.0f} extra desde tu cash tactico acumulado')
        lines.append(f'  - Esta es la ventana que estabas esperando: cargar agresivamente')
        lines.append(f'  - No esperar el fondo perfecto, solo se ve en retrospectiva')
    elif sp_score > 50 or nq_score > 50:
        lines.append(f'  - Aportar mas que lo normal: ${aporte_sp:.0f} a CFISPETF + ${aporte_nq:.0f} a CFINASDAQ = ${total:.0f}')
        lines.append(f'  - Sacar ${-cash_ajuste:.0f} del cash tactico para reforzar')
        lines.append(f'  - Ventana razonable de entrada gradual')
    else:
        lines.append(f'  - DCA normal: ${aporte_sp:.0f} a CFISPETF + ${aporte_nq:.0f} a CFINASDAQ = ${total:.0f}')
        lines.append(f'  - Sin movimiento del cash tactico')
        lines.append(f'  - Mantener disciplina, sin urgencia')

    for line in lines:
        print(line)


def main():
    print()
    print(f'{C.BOLD}{"="*70}{C.RESET}')
    print(f'{C.BOLD}  VALUE SIGNAL SYSTEM v2.1{C.RESET}')
    print(f'  Consulta: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}')
    print(f'{C.BOLD}{"="*70}{C.RESET}')

    print(f'\n{C.DIM}Descargando datos de mercado...{C.RESET}')
    sp500    = fetch_monthly('^GSPC')
    nasdaq   = fetch_monthly('^NDX')
    rate_10y = fetch_monthly('^TNX')
    rate_3m  = fetch_monthly('^IRX')

    if sp500 is None or nasdaq is None:
        print(f'\n{C.RED}Error descargando datos.{C.RESET}')
        input('\nPresiona ENTER para salir...')
        return

    data = pd.DataFrame({
        'sp500': sp500, 'nasdaq': nasdaq,
        'rate_10y': rate_10y, 'rate_3m': rate_3m,
    })
    data['yield_curve'] = data['rate_10y'] - data['rate_3m']
    print(f'  OK Indices hasta {data.index[-1].date()}')

    print(f'{C.DIM}Descargando ETFs Racional (CFISP500.SN, CFINASDAQ.SN)...{C.RESET}')
    cfisp_daily   = fetch_daily('CFISP500.SN', period='1y')
    cfinasd_daily = fetch_daily('CFINASDAQ.SN', period='1y')
    etf_sp = analyze_etf_prices(cfisp_daily,   'S&P 500',    'CFISP500.SN')
    etf_nq = analyze_etf_prices(cfinasd_daily, 'Nasdaq 100', 'CFINASDAQ.SN')
    if etf_sp:
        print(f'  OK CFISPETF: ${etf_sp["current"]:,.2f} CLP ({etf_sp["date"]})')
    if etf_nq:
        print(f'  OK CFINASDAQ: ${etf_nq["current"]:,.2f} CLP ({etf_nq["date"]})')

    print(f'{C.DIM}Descargando CAPE oficial...{C.RESET}')
    cape_official = fetch_cape_official()
    if cape_official is not None:
        print(f'  OK CAPE oficial: {cape_official.iloc[-1]:.2f} (media historica 26.83)')
    else:
        print(f'  ! CAPE oficial no disponible, usando proxy')

    sp = calc_scores(data['sp500'], data['rate_10y'], data['yield_curve'], cape_official)
    nq = calc_scores(data['nasdaq'], data['rate_10y'], data['yield_curve'], None)

    last_sp, aporte_sp = render_panel(sp, 'S&P 500',    'CFISPETF',  APORTE_SP500, etf_sp)
    last_nq, aporte_nq = render_panel(nq, 'Nasdaq 100', 'CFINASDAQ', APORTE_NASDAQ, etf_nq)

    total_invertir = aporte_sp + aporte_nq
    total_base = APORTE_SP500 + APORTE_NASDAQ
    ajuste = total_base - total_invertir

    print()
    print(f'{C.BOLD}{"="*70}{C.RESET}')
    print(f'{C.BOLD}  RESUMEN PARA EJECUTAR EN RACIONAL{C.RESET}')
    print(f'{C.BOLD}{"="*70}{C.RESET}')
    print(f'  CFISPETF  (S&P 500):  invertir ${aporte_sp:>5.0f}  ({color_for_zone(last_sp["zona"])}{last_sp["zona"]}{C.RESET})')
    if etf_sp:
        print(f'                        precio CLP: {C.CYAN}${etf_sp["current"]:,.2f}{C.RESET}')
    print(f'  CFINASDAQ (Nasdaq):   invertir ${aporte_nq:>5.0f}  ({color_for_zone(last_nq["zona"])}{last_nq["zona"]}{C.RESET})')
    if etf_nq:
        print(f'                        precio CLP: {C.CYAN}${etf_nq["current"]:,.2f}{C.RESET}')
    print(f'  {"-"*50}')
    print(f'  TOTAL invertir este mes:        ${total_invertir:>5.0f} USD')
    print(f'  Total base normal:              ${total_base:>5.0f} USD')
    print()
    if ajuste > 0:
        print(f'  GUARDAR en cash tactico:   ${ajuste:.0f} USD')
        print(f'  (Fintual, FM, DAP corto plazo)')
    elif ajuste < 0:
        print(f'  SACAR del cash tactico:    ${-ajuste:.0f} USD')
    else:
        print(f'  Sin movimiento de cash tactico')

    print()
    valid_sp = sp.dropna(subset=['score'])
    valid_nq = nq.dropna(subset=['score'])
    alerts = []

    if len(valid_sp) >= 2:
        delta_sp = valid_sp.iloc[-1]['score'] - valid_sp.iloc[-2]['score']
        if delta_sp >= 20:
            alerts.append(f'S&P 500 subio +{delta_sp:.0f} pts vs mes anterior')
        if valid_sp.iloc[-1]['zona'] != valid_sp.iloc[-2]['zona']:
            alerts.append(f'S&P 500 cambio de zona: {valid_sp.iloc[-2]["zona"]} -> {valid_sp.iloc[-1]["zona"]}')

    if len(valid_nq) >= 2:
        delta_nq = valid_nq.iloc[-1]['score'] - valid_nq.iloc[-2]['score']
        if delta_nq >= 20:
            alerts.append(f'Nasdaq subio +{delta_nq:.0f} pts vs mes anterior')
        if valid_nq.iloc[-1]['zona'] != valid_nq.iloc[-2]['zona']:
            alerts.append(f'Nasdaq cambio de zona: {valid_nq.iloc[-2]["zona"]} -> {valid_nq.iloc[-1]["zona"]}')

    if last_sp['drawdown'] <= -0.20:
        alerts.append(f'S&P 500 con drawdown {last_sp["drawdown"]*100:.0f}% -- aporte extra')
    if last_nq['drawdown'] <= -0.20:
        alerts.append(f'Nasdaq con drawdown {last_nq["drawdown"]*100:.0f}% -- aporte extra')

    if last_sp['score'] >= 75:
        alerts.append(f'S&P 500 en OPORTUNIDAD -- despliega 25% del cash tactico')
    if last_nq['score'] >= 75:
        alerts.append(f'Nasdaq en OPORTUNIDAD -- despliega 25% del cash tactico')

    if etf_sp and etf_sp['r365']:
        pos = (etf_sp['current'] - etf_sp['r365']['min']) / (etf_sp['r365']['max'] - etf_sp['r365']['min']) if etf_sp['r365']['max'] > etf_sp['r365']['min'] else 0.5
        if pos <= 0.15:
            alerts.append(f'CFISPETF cerca del minimo anual (posicion {pos*100:.0f}%)')
    if etf_nq and etf_nq['r365']:
        pos = (etf_nq['current'] - etf_nq['r365']['min']) / (etf_nq['r365']['max'] - etf_nq['r365']['min']) if etf_nq['r365']['max'] > etf_nq['r365']['min'] else 0.5
        if pos <= 0.15:
            alerts.append(f'CFINASDAQ cerca del minimo anual (posicion {pos*100:.0f}%)')

    if alerts:
        print(f'{C.BOLD}{"="*70}{C.RESET}')
        print(f'{C.BOLD}  ALERTAS{C.RESET}')
        print(f'{C.BOLD}{"="*70}{C.RESET}')
        for a in alerts:
            print(f'  ! {a}')

    generate_narrative(last_sp, last_nq, etf_sp, etf_nq)

    # Noticias financieras + interpretacion IA local (opcional)
    if NEWS_AVAILABLE:
        try:
            print(f'\n{C.DIM}Descargando contexto de noticias...{C.RESET}')
            news = fetch_news_context(days_back=7)
            # Si Groq esta configurado, traducir + interpretar
            try:
                from news_context import enrich_with_groq
                enrich_with_groq(news, max_items=8, verbose=True)
            except Exception:
                pass  # silencioso si Groq no disponible
            render_news(news, max_show=8)
        except Exception as e:
            print(f'\n{C.YELLOW}Error descargando noticias (no critico): {e}{C.RESET}')

    save_to_history(last_sp, last_nq, aporte_sp, aporte_nq, etf_sp, etf_nq)

    print()
    print(f'{C.DIM}Para salir, presiona ENTER...{C.RESET}')
    input()

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print(f'\n{C.YELLOW}Cancelado por el usuario.{C.RESET}')
    except Exception as e:
        print(f'\n{C.RED}Error: {e}{C.RESET}')
        import traceback
        traceback.print_exc()
        input('\nPresiona ENTER para salir...')
