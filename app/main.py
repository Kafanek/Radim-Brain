from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routers import windsurf

app = FastAPI(
    title="Radim Brain API",
    description="Integration layer between Windsurf and Radim Brain (Claude API proxy)",
    version="1.0.0",
)

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(windsurf.router, prefix="/api", tags=["windsurf"])

@app.get("/")
async def root():
    return {
        "message": "Radim Brain API",
        "description": "Integration layer between Windsurf and Radim Brain (Claude API proxy)",
    }

@app.get("/health")
async def health_check():
    return {"status": "healthy"}
