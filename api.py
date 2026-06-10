from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import pandas as pd
import traceback
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
                    "(Bereich + Kompetenzcode stimmen nicht ueberein)."
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
        "Du bist eine paedagogische Fachkraft in einer Berliner Kita. "
        "Du arbeitest nach gaengigen Beobachtungs- und Planungsverfahren "
        "fuer Kinder zwischen 2,5 und 4,5 Jahren. "
        "Du formulierst Foerderziele, Aktivitaeten und Elternimpulse klar, "
        "wertschaetzend und praxisnah."
    )

    # Construction du message utilisateur sans triple guillemets
    user_msg_lines = [
        "Kontext:",
        f"- Bereich: {req.bereich}",
        f"- Kompetenz (Code intern): {req.kompetenz_code}",
        f"- Zielalter (Bezug Meilenstein): {bezug_meilenstein_alter}",
        f"- Foerderzeitraum: {foerderzeitraum}",
        f"- Kontext: {req.kontext}",
        f"- Alter des Kindes (ungefaehr): {req.alter}",
        "",
        "Aktuelle Beobachtung der Fachkraft:",
        f'"{req.beobachtung}"',
        "",
        "Interne Orientierungsdaten aus der Wissensbasis (bitte als Grundlage nutzen, aber nicht wortwoertlich kopieren):",
        "",
        "- Typische Beobachtung (Schema):",
        beobachtung_typisch,
        "",
        "- Internes Foerderziel (Richtung):",
        foerderziel,
        "",
        "- Moegliche Aktivitaeten in der Kita:",
        bullets(kita_akt),
        "",
        "- Moegliche Ideen fuer das Elternhaus:",
        bullets(eltern_akt),
        "",
        "- Moegliche Beobachtungsindikatoren:",
        bullets(indikatoren),
        "",
        "- Medien (Buecher/Spiele/Lieder/Rezepte), die grundsaetzlich dazu passen koennten:",
        f"  - Buecher (DE): {buch_de}",
        f"  - Buecher (FR): {buch_fr}",
        f"  - Buecher (EN): {buch_en}",
        f"  - Spielideen: {spielideen}",
        f"  - Videos: {videos}",
        f"  - Rezepte: {rezepte}",
        f"  - Lieder (DE): {lieder_de}",
        f"  - Lieder (FR): {lieder_fr}",
        f"  - Lieder (EN): {lieder_en}",
        "",
        "Aufgabe:",
        "Formuliere fuer DIESE konkrete Beobachtung:",
        "",
        "1. Ein kurzes, klares Foerderziel (2–3 Saetze).",
        "2. 3–5 konkrete Aktivitaeten fuer die Kita (Stichpunkte).",
        "3. 3–5 Ideen fuer das Elternhaus (Stichpunkte).",
        "4. 2–3 passende Medien (Buecher, Spiele, Lieder oder Rezepte), wenn sinnvoll.",
        '5. 2–3 Beobachtungsindikatoren ("Woran erkenne ich Fortschritte?").',
        "",
        "Sprache:",
        "- Du schreibst in hoeflichem, professionellem Deutsch.",
        "- Du schreibst so, dass Fachkraefte es direkt in die Foerderplanung uebernehmen koennen.",
    ]
    user_msg = "\n".join(user_msg_lines)

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

    except RateLimitError as e:
        # Log interne pour le debug (apparaitra dans les logs Render)
        print("RateLimitError in /generate:", repr(e))
        traceback.print_exc()
        return JSONResponse(
            status_code=429,
            content={
                "error": (
                    "OpenAI-Quota aufgebraucht oder voruebergehend begrenzt. "
                    "Bitte spaeter erneut versuchen oder Plan & Billing im OpenAI-Konto pruefen."
                )
            },
        )
    except OpenAIError as e:
        # Log interne
        print("OpenAIError in /generate:", repr(e))
        traceback.print_exc()
        return JSONResponse(
            status_code=502,
            content={
                "error": (
                    "Fehler beim Aufruf der OpenAI-API. "
                    "Bitte spaeter erneut versuchen oder die Konfiguration pruefen."
                )
            },
        )
    except Exception as e:
        # Log interne pour toute autre erreur
        print("Unexpected error in /generate:", repr(e))
        traceback.print_exc()
        return JSONResponse(
            status_code=500,
            content={
                "error": (
                    "Interner Fehler beim Generieren der Foerderideen. "
                    "Bitte spaeter erneut versuchen."
                )
            },
        )

