from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import pandas as pd
import os

from openai import OpenAI, OpenAIError, RateLimitError

# --- Initialisation du client OpenAI (lit OPENAI_API_KEY dans l'environnement) ---
client = OpenAI()
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")

app = FastAPI()

# Nom de la feuille et chemin du fichier Excel
EXCEL_PATH = "Wissensbasis_v7_komplett_mit_Medien_LoRA.xlsx"  # adapte si ton fichier a un autre nom
SHEET_NAME = "Wissensbasis"

# --- Charger la Wissensbasis au démarrage ---
df = pd.read_excel(EXCEL_PATH, sheet_name=SHEET_NAME).fillna("")

# Liste des domaines / Bereiche
BEREICHE = sorted(df["bereich"].dropna().unique())

# Mapping Bereich -> compétences (code interne + label lisible)
bereich_to_competences = {}
for bereich in BEREICHE:
    sub = df[df["bereich"] == bereich]
    pairs = (
        sub[["kompetenzcode", "kompetenzbeschreibung"]]
        .drop_duplicates()
        .to_dict(orient="records")
    )
    comps = []
    for p in pairs:
        code = p["kompetenzcode"]
        beschr = p["kompetenzbeschreibung"]
        label = beschr  # possibilité de reformuler plus tard
        comps.append({"code": code, "label": label})
    bereich_to_competences[bereich] = comps


class GenerateRequest(BaseModel):
    alter: str
    bereich: str
    kompetenz_code: str
    kontext: str
    beobachtung: str


# --- Servir les fichiers statiques (HTML/JS/CSS) depuis ./static ---
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/", response_class=HTMLResponse)
async def index():
    """Renvoie la page HTML principale."""
    with open("static/index.html", "r", encoding="utf-8") as f:
        return f.read()


@app.get("/bereiche")
async def get_bereiche():
    """Liste des Bereiche disponibles dans la Wissensbasis."""
    return {"bereiche": BEREICHE}


@app.get("/kompetenzen")
async def get_kompetenzen(bereich: str):
    """Liste des compétences pour un Bereich donné."""
    return {"kompetenzen": bereich_to_competences.get(bereich, [])}


@app.post("/generate")
async def generate(req: GenerateRequest):
    """
    Génère des idées de Förderung pour une observation donnée,
    en s'ap
