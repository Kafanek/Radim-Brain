"""
🔧 APP.PY PATCH - Přidej tyto řádky do app.py

KROK 1: Najdi řádek kde se importuje speech_routes:
-------------------------------------------------
from speech_routes import speech_bp
app.register_blueprint(speech_bp)

KROK 2: Přidej HNED POD NĚJ tyto řádky:
-------------------------------------------------
"""

# === PŘIDEJ DO app.py PO speech_routes IMPORTU ===

# Import Claude AI routes - Radim s web search
from claude_routes import claude_bp
app.register_blueprint(claude_bp)
print("✅ Claude AI routes registered: /api/radim/*")

# === KONEC PATCH ===

"""
HOTOVO! Claude AI endpointy:
- GET  /api/radim/health      - Health check
- GET  /api/radim/nameday     - Dnešní svátek
- POST /api/radim/chat        - Chat s Radimem
- POST /api/radim/news        - České zprávy
- GET  /api/radim/weather     - Počasí
- POST /api/radim/quiz        - Kvíz
- POST /api/radim/story       - Příběh
- GET  /api/radim/dashboard-data - Všechna data
"""
