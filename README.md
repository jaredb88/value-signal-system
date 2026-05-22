# Value Signal System

Sistema cuantitativo para timing de aportes en ETFs Racional (CFISPETF + CFINASDAQ) que replican S&P 500 y Nasdaq 100.

## ¿Qué hace?

1. **Score 0-100** combinando 5 indicadores académicos: CAPE Shiller (40%), Drawdown (25%), EY vs Bond (15%), Yield Curve (10%), Momentum (10%)
2. **Recomienda multiplicador** del aporte según zona: CARO 0.5x · NEUTRAL 1.0x · ATRACTIVO 1.5x · OPORTUNIDAD 2.5x
3. **Contextualiza con noticias** financieras USA en español (vía IA local)
4. **Alertas por email** cuando hay eventos críticos (cambio de zona, OPORTUNIDAD, drawdown profundo)
5. **Dashboard web** accesible desde PC y celular

## Componentes del sistema

- `value_signal.py` — Script standalone para terminal (PC local)
- `streamlit_app.py` — Dashboard web (PC + móvil)
- `alert_monitor.py` — Sistema de alertas por email (corre 24/7 en GitHub Actions)
- `news_context.py` — Módulo de noticias financieras vía RSS
- `groq_interpreter.py` — Traducción + interpretación con Groq IA

## Setup

Ver guía completa en `DEPLOY.md` o la conversación de construcción del sistema.

### Variables/Secrets requeridos en GitHub

**Secrets** (Settings → Secrets and variables → Actions → Secrets):
- `GMAIL_USER` — tu email Gmail (envío)
- `GMAIL_APP_PASSWORD` — Gmail App Password (no la contraseña normal)
- `EMAIL_TO` — email donde recibir alertas (puede ser el mismo)
- `GROQ_API_KEY` — API key de Groq (de console.groq.com)

**Variables** (Settings → Secrets and variables → Actions → Variables):
- `APORTE_SP500` = 140
- `APORTE_NASDAQ` = 60

### Streamlit Cloud Secrets

En `https://share.streamlit.io` → app settings → Secrets:
```toml
GROQ_API_KEY = "gsk_..."
```

## Validación del sistema

- Walk-forward sobre datos reales 1990-2026
- 100% de ventanas con alpha positivo vs DCA puro
- Le gana al 100% de simulaciones aleatorias (p < 0.05)
- 5 indicadores con respaldo académico (Shiller, Jegadeesh-Titman)

## Disclaimers

- No es asesoría financiera. Sistema cuantitativo educativo.
- Performance pasada no garantiza performance futura.
- Mantener fondo de emergencia separado del capital de inversión.
- Re-validar sistema cada 12 meses.

## Uso local

```bash
# Setup
pip install -r requirements.txt
echo "TU_GROQ_API_KEY" > groq_api_key.txt

# Terminal
python value_signal.py

# Dashboard
streamlit run streamlit_app.py
```
