"""
🤖 CLAUDE AI ROUTES - RadimCare AI Brain
Kompletní AI služba s web search pro seniory
Nahrazuje Gemini - všechno v jednom: chat, zprávy, počasí, kvíz, příběhy

Version: 1.0.0
Author: Kolibri Team
"""

from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime
import os
import json
import logging
import asyncio

# Anthropic Claude SDK
try:
    from anthropic import Anthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False
    print("⚠️ Anthropic SDK not installed. Run: pip install anthropic")

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/radim", tags=["Claude AI"])

# ============================================================================
# CONFIGURATION
# ============================================================================

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-20250514")  # nebo claude-haiku-4-5-20251001 pro nižší cenu

# České jmeniny
NAMEDAY_CALENDAR = {
    1: {1: 'Nový rok', 2: 'Karina', 3: 'Radmila', 4: 'Diana', 5: 'Dalimil', 6: 'Tři králové', 7: 'Vilma', 8: 'Čestmír', 9: 'Vladan', 10: 'Břetislav', 11: 'Bohdana', 12: 'Pravoslav', 13: 'Edita', 14: 'Radovan', 15: 'Alice', 16: 'Ctirad', 17: 'Drahoslav', 18: 'Vladislav', 19: 'Doubravka', 20: 'Ilona', 21: 'Běla', 22: 'Slavomír', 23: 'Zdeněk', 24: 'Milena', 25: 'Miloš', 26: 'Zora', 27: 'Ingrid', 28: 'Otýlie', 29: 'Zdislava', 30: 'Robin', 31: 'Marika'},
    2: {1: 'Hynek', 2: 'Nela', 3: 'Blažej', 4: 'Jarmila', 5: 'Dobromila', 6: 'Vanda', 7: 'Veronika', 8: 'Milada', 9: 'Apolena', 10: 'Mojmír', 11: 'Božena', 12: 'Slavěna', 13: 'Věnceslav', 14: 'Valentýn', 15: 'Jiřina', 16: 'Ljuba', 17: 'Miloslava', 18: 'Gizela', 19: 'Patrik', 20: 'Oldřich', 21: 'Lenka', 22: 'Petr', 23: 'Svatopluk', 24: 'Matěj', 25: 'Liliana', 26: 'Dorota', 27: 'Alexandr', 28: 'Lumír', 29: 'Horymír'},
    3: {1: 'Bedřich', 2: 'Anežka', 3: 'Kamil', 4: 'Stela', 5: 'Kazimír', 6: 'Miroslav', 7: 'Tomáš', 8: 'Gabriela', 9: 'Františka', 10: 'Viktorie', 11: 'Anděla', 12: 'Řehoř', 13: 'Růžena', 14: 'Rút', 15: 'Ida', 16: 'Elena', 17: 'Vlastimil', 18: 'Eduard', 19: 'Josef', 20: 'Světlana', 21: 'Radek', 22: 'Leona', 23: 'Ivona', 24: 'Gabriel', 25: 'Marián', 26: 'Emanuel', 27: 'Dita', 28: 'Soňa', 29: 'Taťána', 30: 'Arnošt', 31: 'Kvido'},
    4: {1: 'Hugo', 2: 'Erika', 3: 'Richard', 4: 'Ivana', 5: 'Miroslava', 6: 'Vendula', 7: 'Heřman', 8: 'Ema', 9: 'Dušan', 10: 'Darja', 11: 'Izabela', 12: 'Julius', 13: 'Aleš', 14: 'Vincenc', 15: 'Anastázie', 16: 'Irena', 17: 'Rudolf', 18: 'Valérie', 19: 'Rostislav', 20: 'Marcela', 21: 'Alexandra', 22: 'Evženie', 23: 'Vojtěch', 24: 'Jiří', 25: 'Marek', 26: 'Oto', 27: 'Jaroslav', 28: 'Vlastislav', 29: 'Robert', 30: 'Blahoslav'},
    5: {1: 'Svátek práce', 2: 'Zikmund', 3: 'Alexej', 4: 'Květoslav', 5: 'Klaudie', 6: 'Radoslav', 7: 'Stanislav', 8: 'Den vítězství', 9: 'Ctibor', 10: 'Blažena', 11: 'Svatava', 12: 'Pankrác', 13: 'Servác', 14: 'Bonifác', 15: 'Žofie', 16: 'Přemysl', 17: 'Aneta', 18: 'Nataša', 19: 'Ivo', 20: 'Zbyšek', 21: 'Monika', 22: 'Emil', 23: 'Vladimír', 24: 'Jana', 25: 'Viola', 26: 'Filip', 27: 'Valdemar', 28: 'Vilém', 29: 'Maxim', 30: 'Ferdinand', 31: 'Kamila'},
    6: {1: 'Laura', 2: 'Jarmil', 3: 'Tamara', 4: 'Dalibor', 5: 'Dobroslav', 6: 'Norbert', 7: 'Iveta', 8: 'Medard', 9: 'Stanislava', 10: 'Gita', 11: 'Bruno', 12: 'Antonie', 13: 'Antonín', 14: 'Roland', 15: 'Vít', 16: 'Zbyněk', 17: 'Adolf', 18: 'Milan', 19: 'Leoš', 20: 'Květa', 21: 'Alois', 22: 'Pavla', 23: 'Zdeňka', 24: 'Jan', 25: 'Ivan', 26: 'Adriana', 27: 'Ladislav', 28: 'Lubomír', 29: 'Petr a Pavel', 30: 'Šárka'},
    7: {1: 'Jaroslava', 2: 'Patricie', 3: 'Radomír', 4: 'Prokop', 5: 'Cyril a Metoděj', 6: 'Jan Hus', 7: 'Bohuslava', 8: 'Nora', 9: 'Drahoslava', 10: 'Libuše', 11: 'Olga', 12: 'Bořek', 13: 'Markéta', 14: 'Karolína', 15: 'Jindřich', 16: 'Luboš', 17: 'Martina', 18: 'Drahomíra', 19: 'Čeněk', 20: 'Ilja', 21: 'Vítězslav', 22: 'Magdaléna', 23: 'Libor', 24: 'Kristýna', 25: 'Jakub', 26: 'Anna', 27: 'Věroslav', 28: 'Viktor', 29: 'Marta', 30: 'Bořivoj', 31: 'Ignác'},
    8: {1: 'Oskar', 2: 'Gustav', 3: 'Miluše', 4: 'Dominik', 5: 'Kristián', 6: 'Oldřiška', 7: 'Lada', 8: 'Soběslav', 9: 'Roman', 10: 'Vavřinec', 11: 'Zuzana', 12: 'Klára', 13: 'Alena', 14: 'Alan', 15: 'Hana', 16: 'Jáchym', 17: 'Petra', 18: 'Helena', 19: 'Ludvík', 20: 'Bernard', 21: 'Johana', 22: 'Bohuslav', 23: 'Sandra', 24: 'Bartoloměj', 25: 'Radim', 26: 'Luděk', 27: 'Otakar', 28: 'Augustýn', 29: 'Evelína', 30: 'Vladěna', 31: 'Pavlína'},
    9: {1: 'Linda', 2: 'Adéla', 3: 'Bronislav', 4: 'Jindřiška', 5: 'Boris', 6: 'Boleslav', 7: 'Regína', 8: 'Mariana', 9: 'Daniela', 10: 'Irma', 11: 'Denisa', 12: 'Marie', 13: 'Lubor', 14: 'Radka', 15: 'Jolana', 16: 'Ludmila', 17: 'Naděžda', 18: 'Kryštof', 19: 'Zita', 20: 'Oleg', 21: 'Matouš', 22: 'Darina', 23: 'Berta', 24: 'Jaromír', 25: 'Zlata', 26: 'Andrea', 27: 'Jonáš', 28: 'Václav', 29: 'Michal', 30: 'Jeroným'},
    10: {1: 'Igor', 2: 'Olivie', 3: 'Bohumil', 4: 'František', 5: 'Eliška', 6: 'Hanuš', 7: 'Justýna', 8: 'Věra', 9: 'Štefan', 10: 'Marina', 11: 'Andrej', 12: 'Marcel', 13: 'Renáta', 14: 'Agáta', 15: 'Tereza', 16: 'Havel', 17: 'Hedvika', 18: 'Lukáš', 19: 'Michaela', 20: 'Vendelín', 21: 'Brigita', 22: 'Sabina', 23: 'Teodor', 24: 'Nina', 25: 'Beáta', 26: 'Erik', 27: 'Šarlota', 28: 'Den vzniku ČSR', 29: 'Silvie', 30: 'Tadeáš', 31: 'Štěpánka'},
    11: {1: 'Felix', 2: 'Památka zesnulých', 3: 'Hubert', 4: 'Karel', 5: 'Miriam', 6: 'Liběna', 7: 'Saskie', 8: 'Bohumír', 9: 'Bohdan', 10: 'Evžen', 11: 'Martin', 12: 'Benedikt', 13: 'Tibor', 14: 'Sáva', 15: 'Leopold', 16: 'Otmar', 17: 'Den svobody', 18: 'Romana', 19: 'Alžběta', 20: 'Nikola', 21: 'Albert', 22: 'Cecílie', 23: 'Klement', 24: 'Emílie', 25: 'Kateřina', 26: 'Artur', 27: 'Xenie', 28: 'René', 29: 'Zina', 30: 'Ondřej'},
    12: {1: 'Iva', 2: 'Blanka', 3: 'Svatoslav', 4: 'Barbora', 5: 'Jitka', 6: 'Mikuláš', 7: 'Ambrož', 8: 'Květoslava', 9: 'Vratislav', 10: 'Julie', 11: 'Dana', 12: 'Simona', 13: 'Lucie', 14: 'Lýdie', 15: 'Radana', 16: 'Albína', 17: 'Daniel', 18: 'Miloslav', 19: 'Ester', 20: 'Dagmar', 21: 'Natálie', 22: 'Šimon', 23: 'Vlasta', 24: 'Štědrý den', 25: 'Boží hod', 26: 'Štěpán', 27: 'Žaneta', 28: 'Bohumila', 29: 'Judita', 30: 'David', 31: 'Silvestr'}
}

# System prompt pro Radima
RADIM_SYSTEM_PROMPT = """Jsi Radim, přátelský AI asistent pro české seniory v aplikaci RadimCare.

🎯 TVOJE PRAVIDLA:
- Mluv česky, jednoduše a srozumitelně
- Používej krátké věty (max 2-3 věty najednou)
- Buď trpělivý, empatický a pozitivní
- Vyhni se cizím slovům a technickému žargonu
- Oslovuj seniory s úctou (pane/paní, vykání)

🔍 VYHLEDÁVÁNÍ:
- Pokud nevíš aktuální informaci, VŽDY použij web_search
- Pro počasí vyhledej "aktuální počasí Praha dnes"
- Pro zprávy vyhledej "české zprávy dnes" nebo specifickou kategorii
- Pro události vyhledej "co se děje v Praze dnes"

📰 KATEGORIE ZPRÁV:
- Politika: české politické zprávy
- Sport: český sport, hokej, fotbal
- Zdraví: zdravotní tipy pro seniory
- Kultura: divadlo, koncerty, výstavy v Praze
- Věda: zajímavosti, technologie
- Lokální: Praha, doprava, události

🎮 KVÍZY:
Když tě požádají o kvíz, vytvoř 5 otázek s možnostmi A, B, C, D.
Témata: historie Česka, příroda, zeměpis, zdraví, kultura.

📖 PŘÍBĚHY:
Vyprávěj krátké, pozitivní příběhy z českého prostředí.
Použij jednoduché věty a známá místa.

⏰ DNEŠNÍ INFORMACE:
- Datum: {date}
- Den: {day_name}
- Svátek: {nameday}
- Lokace: Praha, Česká republika

Vždy odpovídej přátelsky a s respektem k seniorům. 💚"""

# ============================================================================
# MODELS
# ============================================================================

class ChatRequest(BaseModel):
    message: str = Field(..., description="Zpráva od uživatele")
    user_id: Optional[str] = Field(default="anonymous", description="ID uživatele")
    context: Optional[Dict[str, Any]] = Field(default={}, description="Kontext konverzace")
    use_search: Optional[bool] = Field(default=True, description="Povolit web search")

class ChatResponse(BaseModel):
    success: bool
    response: str
    sources: Optional[List[Dict[str, str]]] = None
    intent: Optional[str] = None
    timestamp: str

class NewsRequest(BaseModel):
    category: str = Field(default="general", description="Kategorie zpráv")
    count: int = Field(default=5, description="Počet zpráv")

class NewsResponse(BaseModel):
    success: bool
    category: str
    articles: List[Dict[str, Any]]
    ai_summary: Optional[str] = None
    timestamp: str

class WeatherResponse(BaseModel):
    success: bool
    location: str
    temperature: Optional[int] = None
    condition: str
    humidity: Optional[int] = None
    wind: Optional[int] = None
    forecast: Optional[str] = None
    timestamp: str

class QuizRequest(BaseModel):
    topic: str = Field(default="general", description="Téma kvízu")
    difficulty: str = Field(default="easy", description="Obtížnost: easy, medium, hard")
    count: int = Field(default=5, description="Počet otázek")

class QuizResponse(BaseModel):
    success: bool
    topic: str
    questions: List[Dict[str, Any]]
    timestamp: str

class StoryRequest(BaseModel):
    theme: str = Field(default="nature", description="Téma příběhu")
    length: str = Field(default="short", description="Délka: short, medium, long")
    style: str = Field(default="relaxing", description="Styl: relaxing, adventure, memory")

class StoryResponse(BaseModel):
    success: bool
    title: str
    content: str
    theme: str
    timestamp: str

class NameDayResponse(BaseModel):
    success: bool
    date: str
    nameday: str
    timestamp: str

# ============================================================================
# CLAUDE CLIENT
# ============================================================================

def get_claude_client():
    """Get Anthropic client"""
    if not ANTHROPIC_AVAILABLE:
        raise HTTPException(status_code=503, detail="Anthropic SDK not installed")
    
    if not ANTHROPIC_API_KEY:
        raise HTTPException(status_code=503, detail="ANTHROPIC_API_KEY not configured")
    
    return Anthropic(api_key=ANTHROPIC_API_KEY)

def get_today_info():
    """Get today's date info"""
    now = datetime.now()
    day_names = ['Pondělí', 'Úterý', 'Středa', 'Čtvrtek', 'Pátek', 'Sobota', 'Neděle']
    month_names = ['ledna', 'února', 'března', 'dubna', 'května', 'června', 
                   'července', 'srpna', 'září', 'října', 'listopadu', 'prosince']
    
    nameday = NAMEDAY_CALENDAR.get(now.month, {}).get(now.day, "Neznámý")
    
    return {
        "date": f"{now.day}. {month_names[now.month-1]} {now.year}",
        "day_name": day_names[now.weekday()],
        "nameday": nameday,
        "iso_date": now.strftime("%Y-%m-%d")
    }

def extract_text_from_response(response) -> str:
    """Extract text from Claude response"""
    text_parts = []
    for block in response.content:
        if hasattr(block, 'text'):
            text_parts.append(block.text)
    return "\n".join(text_parts)

def extract_citations(response) -> List[Dict[str, str]]:
    """Extract citations from web search results"""
    citations = []
    for block in response.content:
        if hasattr(block, 'type') and block.type == 'tool_use':
            if hasattr(block, 'name') and block.name == 'web_search':
                # Parse search results
                pass
    return citations

# ============================================================================
# ENDPOINTS
# ============================================================================

@router.get("/health")
async def health_check():
    """Health check for Claude AI service"""
    return {
        "status": "healthy" if ANTHROPIC_API_KEY else "degraded",
        "service": "Claude AI for RadimCare",
        "model": CLAUDE_MODEL,
        "anthropic_configured": bool(ANTHROPIC_API_KEY),
        "timestamp": datetime.utcnow().isoformat()
    }

@router.get("/nameday", response_model=NameDayResponse)
async def get_nameday():
    """Získat dnešní svátek"""
    info = get_today_info()
    return NameDayResponse(
        success=True,
        date=info["date"],
        nameday=info["nameday"],
        timestamp=datetime.utcnow().isoformat()
    )

@router.post("/chat", response_model=ChatResponse)
async def chat_with_radim(request: ChatRequest):
    """
    💬 Hlavní chat endpoint s Claude + Web Search
    Radim odpovídá na dotazy seniorů s možností vyhledávání na webu
    """
    try:
        client = get_claude_client()
        info = get_today_info()
        
        # Připravit system prompt
        system = RADIM_SYSTEM_PROMPT.format(
            date=info["date"],
            day_name=info["day_name"],
            nameday=info["nameday"]
        )
        
        # Tools pro web search
        tools = []
        if request.use_search:
            tools = [{
                "type": "web_search_20250305",
                "name": "web_search",
                "max_uses": 3
            }]
        
        # Volání Claude API
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=1024,
            system=system,
            tools=tools if tools else None,
            messages=[{
                "role": "user",
                "content": request.message
            }]
        )
        
        # Extrahovat odpověď
        text = extract_text_from_response(response)
        sources = extract_citations(response)
        
        # Detekovat intent
        intent = "general"
        msg_lower = request.message.lower()
        if any(w in msg_lower for w in ["počasí", "teplota", "prší", "sněží"]):
            intent = "weather"
        elif any(w in msg_lower for w in ["zprávy", "novinky", "co se děje"]):
            intent = "news"
        elif any(w in msg_lower for w in ["kvíz", "otázky", "test"]):
            intent = "quiz"
        elif any(w in msg_lower for w in ["příběh", "povídka", "vyprávěj"]):
            intent = "story"
        elif any(w in msg_lower for w in ["svátek", "jmeniny"]):
            intent = "nameday"
        
        logger.info(f"Chat response | User: {request.user_id} | Intent: {intent}")
        
        return ChatResponse(
            success=True,
            response=text,
            sources=sources if sources else None,
            intent=intent,
            timestamp=datetime.utcnow().isoformat()
        )
        
    except Exception as e:
        logger.error(f"Chat error: {e}")
        # Fallback odpověď
        return ChatResponse(
            success=False,
            response="Promiňte, právě mám technické potíže. Zkuste to prosím za chvilku znovu.",
            intent="error",
            timestamp=datetime.utcnow().isoformat()
        )

@router.post("/news", response_model=NewsResponse)
async def get_news(request: NewsRequest):
    """
    📰 Získat aktuální české zprávy pomocí Claude + Web Search
    """
    try:
        client = get_claude_client()
        info = get_today_info()
        
        category_queries = {
            "politics": "české politické zprávy dnes aktuální",
            "sports": "český sport zprávy hokej fotbal dnes",
            "health": "zdraví zprávy tipy pro seniory Česko",
            "culture": "kultura Praha divadlo koncerty výstavy dnes",
            "science": "věda technika zajímavosti Česko",
            "local": "Praha zprávy doprava události dnes",
            "general": "hlavní české zprávy dnes"
        }
        
        query = category_queries.get(request.category, category_queries["general"])
        
        system = f"""Jsi zpravodajský asistent. Vyhledej aktuální české zprávy a shrň je.

PRAVIDLA:
- Vyhledej {request.count} aktuálních zpráv z kategorie: {request.category}
- Pro každou zprávu uveď: titulek, krátký popis, zdroj
- Odpověz ve formátu JSON pole
- Dnešní datum: {info['date']}

FORMÁT ODPOVĚDI (pouze JSON):
[
  {{"title": "Titulek zprávy", "description": "Krátký popis", "source": "Název zdroje", "category": "{request.category}"}},
  ...
]"""

        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=2048,
            system=system,
            tools=[{
                "type": "web_search_20250305",
                "name": "web_search",
                "max_uses": 5
            }],
            messages=[{
                "role": "user",
                "content": f"Vyhledej a shrň {request.count} aktuálních českých zpráv: {query}"
            }]
        )
        
        text = extract_text_from_response(response)
        
        # Parsovat JSON
        articles = []
        try:
            # Najít JSON v odpovědi
            import re
            json_match = re.search(r'\[.*\]', text, re.DOTALL)
            if json_match:
                articles = json.loads(json_match.group())
        except:
            # Fallback - vytvořit článek z textu
            articles = [{
                "title": f"Zprávy z kategorie {request.category}",
                "description": text[:200],
                "source": "Claude AI",
                "category": request.category
            }]
        
        # AI summary
        summary = f"Přehled {len(articles)} zpráv z kategorie {request.category} ke dni {info['date']}."
        
        return NewsResponse(
            success=True,
            category=request.category,
            articles=articles,
            ai_summary=summary,
            timestamp=datetime.utcnow().isoformat()
        )
        
    except Exception as e:
        logger.error(f"News error: {e}")
        return NewsResponse(
            success=False,
            category=request.category,
            articles=[],
            ai_summary="Nepodařilo se načíst zprávy.",
            timestamp=datetime.utcnow().isoformat()
        )

@router.get("/weather", response_model=WeatherResponse)
async def get_weather(location: str = "Praha"):
    """
    🌤️ Získat aktuální počasí pomocí Claude + Web Search
    """
    try:
        client = get_claude_client()
        
        system = """Jsi meteorologický asistent. Vyhledej aktuální počasí a odpověz strukturovaně.

FORMÁT ODPOVĚDI (pouze JSON):
{
  "temperature": 5,
  "condition": "Oblačno",
  "humidity": 75,
  "wind": 12,
  "forecast": "Odpoledne se očekává déšť."
}

Teplota v °C, vlhkost v %, vítr v km/h."""

        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=512,
            system=system,
            tools=[{
                "type": "web_search_20250305",
                "name": "web_search",
                "max_uses": 2
            }],
            messages=[{
                "role": "user",
                "content": f"Jaké je aktuální počasí v {location}? Vyhledej aktuální předpověď."
            }]
        )
        
        text = extract_text_from_response(response)
        
        # Parsovat JSON
        weather_data = {}
        try:
            import re
            json_match = re.search(r'\{.*\}', text, re.DOTALL)
            if json_match:
                weather_data = json.loads(json_match.group())
        except:
            weather_data = {
                "condition": "Informace nedostupná",
                "forecast": text[:100]
            }
        
        return WeatherResponse(
            success=True,
            location=location,
            temperature=weather_data.get("temperature"),
            condition=weather_data.get("condition", "Neznámé"),
            humidity=weather_data.get("humidity"),
            wind=weather_data.get("wind"),
            forecast=weather_data.get("forecast"),
            timestamp=datetime.utcnow().isoformat()
        )
        
    except Exception as e:
        logger.error(f"Weather error: {e}")
        return WeatherResponse(
            success=False,
            location=location,
            condition="Nepodařilo se načíst počasí",
            timestamp=datetime.utcnow().isoformat()
        )

@router.post("/quiz", response_model=QuizResponse)
async def generate_quiz(request: QuizRequest):
    """
    🎮 Vygenerovat kvíz pro seniory
    """
    try:
        client = get_claude_client()
        
        topic_prompts = {
            "history": "české dějiny, významné události, osobnosti",
            "nature": "česká příroda, zvířata, rostliny",
            "geography": "česká města, hory, řeky, zajímavá místa",
            "health": "zdravý životní styl, prevence, výživa pro seniory",
            "culture": "české tradice, svátky, lidové zvyky",
            "general": "obecné znalosti, zajímavosti z Česka"
        }
        
        topic_desc = topic_prompts.get(request.topic, topic_prompts["general"])
        
        difficulty_desc = {
            "easy": "jednoduché, pro běžné znalosti",
            "medium": "středně těžké",
            "hard": "náročnější, pro znalce"
        }
        
        system = f"""Vytvoř kvíz pro české seniory.

PRAVIDLA:
- Téma: {topic_desc}
- Obtížnost: {difficulty_desc.get(request.difficulty, 'jednoduché')}
- Počet otázek: {request.count}
- Každá otázka má 4 možnosti (A, B, C, D)
- Otázky jsou pozitivní a zajímavé
- Vyhni se záludným formulacím

FORMÁT ODPOVĚDI (pouze JSON):
[
  {{
    "question": "Text otázky?",
    "options": {{"A": "Možnost A", "B": "Možnost B", "C": "Možnost C", "D": "Možnost D"}},
    "correct": "A",
    "explanation": "Krátké vysvětlení správné odpovědi."
  }}
]"""

        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=2048,
            system=system,
            messages=[{
                "role": "user",
                "content": f"Vytvoř {request.count} kvízových otázek na téma: {request.topic}"
            }]
        )
        
        text = extract_text_from_response(response)
        
        # Parsovat JSON
        questions = []
        try:
            import re
            json_match = re.search(r'\[.*\]', text, re.DOTALL)
            if json_match:
                questions = json.loads(json_match.group())
        except:
            questions = [{
                "question": "Který hrad je největší na světě?",
                "options": {"A": "Pražský hrad", "B": "Windsor", "C": "Versailles", "D": "Kreml"},
                "correct": "A",
                "explanation": "Pražský hrad je podle Guinessovy knihy rekordů největší hradní komplex na světě."
            }]
        
        return QuizResponse(
            success=True,
            topic=request.topic,
            questions=questions,
            timestamp=datetime.utcnow().isoformat()
        )
        
    except Exception as e:
        logger.error(f"Quiz error: {e}")
        return QuizResponse(
            success=False,
            topic=request.topic,
            questions=[],
            timestamp=datetime.utcnow().isoformat()
        )

@router.post("/story", response_model=StoryResponse)
async def generate_story(request: StoryRequest):
    """
    📖 Vygenerovat uklidňující příběh pro seniory
    """
    try:
        client = get_claude_client()
        
        theme_prompts = {
            "nature": "příroda, les, zahrada, zvířata",
            "memory": "vzpomínky, dětství, tradice, rodina",
            "adventure": "cestování po Česku, výlety, objevování",
            "relaxing": "klid, odpočinek, pohoda, harmonie",
            "seasonal": "roční období, svátky, tradice"
        }
        
        length_words = {
            "short": "100-150 slov",
            "medium": "200-300 slov",
            "long": "400-500 slov"
        }
        
        theme_desc = theme_prompts.get(request.theme, theme_prompts["relaxing"])
        length_desc = length_words.get(request.length, length_words["short"])
        
        system = f"""Jsi vypravěč příběhů pro české seniory.

PRAVIDLA:
- Téma: {theme_desc}
- Délka: {length_desc}
- Styl: {request.style}
- Použij česká jména a místa
- Příběh je pozitivní a uklidňující
- Jednoduché věty, srozumitelný jazyk
- Vyvolej příjemné pocity a vzpomínky

FORMÁT ODPOVĚDI (pouze JSON):
{{
  "title": "Název příběhu",
  "content": "Text příběhu..."
}}"""

        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=1024,
            system=system,
            messages=[{
                "role": "user",
                "content": f"Vyprávěj {request.style} příběh na téma: {request.theme}"
            }]
        )
        
        text = extract_text_from_response(response)
        
        # Parsovat JSON
        story_data = {}
        try:
            import re
            json_match = re.search(r'\{.*\}', text, re.DOTALL)
            if json_match:
                story_data = json.loads(json_match.group())
        except:
            story_data = {
                "title": f"Příběh o {request.theme}",
                "content": text
            }
        
        return StoryResponse(
            success=True,
            title=story_data.get("title", "Příběh"),
            content=story_data.get("content", text),
            theme=request.theme,
            timestamp=datetime.utcnow().isoformat()
        )
        
    except Exception as e:
        logger.error(f"Story error: {e}")
        return StoryResponse(
            success=False,
            title="Chyba",
            content="Nepodařilo se vytvořit příběh. Zkuste to prosím znovu.",
            theme=request.theme,
            timestamp=datetime.utcnow().isoformat()
        )

# ============================================================================
# COMPOSITE ENDPOINTS
# ============================================================================

@router.get("/dashboard-data")
async def get_dashboard_data():
    """
    📊 Získat všechna data pro dashboard (počasí, svátek, top zpráva)
    Jeden request místo mnoha - optimalizace pro seniory
    """
    try:
        info = get_today_info()
        
        # Základní data bez API volání
        result = {
            "success": True,
            "date": info["date"],
            "day_name": info["day_name"],
            "nameday": info["nameday"],
            "weather": None,
            "top_news": None,
            "greeting": get_greeting(),
            "timestamp": datetime.utcnow().isoformat()
        }
        
        # Pokusit se získat počasí
        try:
            weather_response = await get_weather()
            if weather_response.success:
                result["weather"] = {
                    "temperature": weather_response.temperature,
                    "condition": weather_response.condition,
                    "humidity": weather_response.humidity,
                    "wind": weather_response.wind
                }
        except:
            pass
        
        return result
        
    except Exception as e:
        logger.error(f"Dashboard data error: {e}")
        info = get_today_info()
        return {
            "success": False,
            "date": info["date"],
            "day_name": info["day_name"],
            "nameday": info["nameday"],
            "greeting": get_greeting(),
            "timestamp": datetime.utcnow().isoformat()
        }

def get_greeting():
    """Získat pozdrav podle denní doby"""
    hour = datetime.now().hour
    if 5 <= hour < 12:
        return "Dobré ráno! ☀️"
    elif 12 <= hour < 18:
        return "Dobré odpoledne! 🌤️"
    elif 18 <= hour < 22:
        return "Dobrý večer! 🌙"
    else:
        return "Dobrou noc! 🌟"

# ============================================================================
# LOGGING
# ============================================================================

logger.info("✅ Claude AI Routes loaded - Radim is ready!")
