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
EXCEL_PATH = "Wissensbasis_v7_komplett_mit_Medien_LoRA.xlsx"  # adapte au nom réel de ton fichier
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
    en s'appuyant sur la Wissensbasis + un appel OpenAI.
    """

    # 1) Filtrer d'abord par Bereich + Kompetenzcode
    sub = df[
        (df["bereich"] == req.bereich)
        & (df["kompetenzcode"] == req.kompetenz_code)
    ]

    if sub.empty:
        return JSONResponse(
            status_code=404,
            content={
                "error": (
                    "Keine passende Zeile in der Wissensbasis gefunden "
                    "(Bereich + Kompetenzcode stimmen nicht überein)."
                )
            },
        )

    # 2) Si plusieurs lignes, essayer de filtrer par Kontext
    sub_kontext = sub[sub["kontext"] == req.kontext]
    if not sub_kontext.empty:
        row = sub_kontext.iloc[0]
    else:
        # Pas de correspondance exacte sur le contexte : on prend la première Zeile
        row = sub.iloc[0]

    foerderziel = row["foerderziel"]
    beobachtung_typisch = row["beobachtung"]
    kita_akt = row["kita_aktivitaeten"]
    eltern_akt = row["eltern_aktivitaeten"]
    indikatoren = row["indikatoren"]
    bezug_meilenstein_alter = row["bezug_meilenstein_alter"]
    foerderzeitraum = row["foerderzeitraum"]

    buch_de = row.get("buch_empfehlung_de", "")
    buch_fr = row.get("buch_empfehlung_fr", "")
    buch_en = row.get("buch_empfehlung_en", "")
    spielideen = row.get("spielideen", "")
    videos = row.get("paedagogische_videos", "")
    rezepte = row.get("rezepte", "")
    lieder_de = row.get("lieder_de", "")
    lieder_fr = row.get("lieder_fr", "")
    lieder_en = row.get("lieder_en", "")

    def bullets(text: str) -> str:
        if not text:
            return ""
        parts = [p.strip() for p in text.split(";") if p.strip()]
        if not parts:
            return ""
        return "\n".join(f"- {p}" for p in parts)

    system_msg = (
        "Du bist eine pädagogische Fachkraft in einer Berliner Kita. "
        "Du arbeitest nach gängigen Beobachtungs- und Planungsverfahren "
        "für Kinder zwischen 2,5 und 4,5 Jahren. "
        "Du formulierst Förderziele, Aktivitäten und Elternimpulse klar, "
        "wertschätzend und praxisnah."
    )

    user_msg = f"""
Kontext:
- Bereich: {req.bereich}
- Kompetenz (Code intern): {req.kompetenz_code}
- Zielalter (Bezug Meilenstein): {bezug_meilenstein_alter}
- Förderzeitraum: {foerderzeitraum}
- Kontext: {req.kontext}
- Alter des Kindes (ungefähr): {req.alter}

Aktuelle Beobachtung der Fachkraft:
\"\"\"{req.beobachtung}\"\"\"


Interne Orientierungsdaten aus der Wissensbasis (bitte als Grundlage nutzen, aber nicht wortwörtlich kopieren):

- Typische Beobachtung (Schema):
{beobachtung_typisch}

- Internes Förderziel (Richtung):
{foerderziel}

- Mögliche Aktivitäten in der Kita:
{bullets(kita_akt)}

- Mögliche Ideen für das Elternhaus:
{bullets(eltern_akt)}

- Mögliche Beobachtungsindikatoren:
{bullets(indikatoren)}

- Medien (Bücher/Spiele/Lieder/Rezepte), die grundsätzlich dazu passen könnten:
  - Bücher (DE): {buch_de}
  - Bücher (FR): {buch_fr}
  - Bücher (EN): {buch_en}
  - Spielideen: {spielideen}
  - Videos: {videos}
  - Rezepte: {rezepte}
  - Lieder (DE): {lieder_de}
  - Lieder (FR): {lieder_fr}
  - Lieder (EN): {lieder_en}

Aufgabe:
Formuliere für DIESE konkrete Beobachtung:

1. Ein kurzes, klares Förderziel (2–3 Sätze).
2. 3–5 konkrete Aktivitäten für die Kita (Stichpunkte).
3. 3–5 Ideen für das Elternhaus (Stichpunkte).
4. 2–3 passende Medien (Bücher, Spiele, Lieder oder Rezepte), wenn sinnvoll.
5. 2–3 Beobachtungsindikatoren („Woran erkenne ich Fortschritte?“).

Sprache:
- Du schreibst in höflichem, professionellem Deutsch.
- Du schreibst so, dass Fachkräfte es direkt in die Förderplanung übernehmen können.
"""

    try:
        completion = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": user_msg},
            ],
        )
        answer = completion.choices[0].message.content
        return {"text": answer}

    except RateLimitError:
        return JSONResponse(
            status_code=429,
            content={
                "error": (
                    "OpenAI-Quota aufgebraucht oder vorübergehend begrenzt. "
                    "Bitte später erneut versuchen oder Plan & Billing in deinem OpenAI-Konto prüfen."
                )
            },
        )
    except OpenAIError as e:
        return JSONResponse(
            status_code=502,
            content={"error": f"Fehler von OpenAI: {e}"},
        )
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"error": f"Interner Fehler: {e}"},
        )
