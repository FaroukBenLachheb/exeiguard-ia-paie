"""
frontend/app.py

Interface Streamlit pilotant le pipeline réel A1->A6. Destinée à être
montrée au CEO : AUCUNE donnée n'est simulée ou codée en dur ici. Chaque
écran appelle les vraies API HTTP (orchestrateur, extracteur-evp via
l'orchestrateur, compliance-validation via l'orchestrateur,
integration-sage via l'orchestrateur, rag directement) et n'affiche que
ce que ces services renvoient réellement.

Trois principes non négociables du projet, rappelés à l'écran à chaque
endroit pertinent :
  1. Traçabilité complète -> écran 4 (journal d'audit), toujours accessible.
  2. Validation humaine obligatoire -> dès que le dossier atteint un état
     qui la requiert, une fenêtre de dialogue (st.dialog) s'ouvre
     automatiquement sur l'écran de suivi : aucune transition qui engage
     une décision réglementaire n'est déclenchée ailleurs que par un
     clic explicite dans cette fenêtre.
  3. Rule Engine (déterministe, décisionnel) vs RAG (documentaire,
     jamais décisionnel) -> bandeau explicite sur l'écran RAG, et les
     résultats du Rule Engine (écran de suivi) sont toujours présentés
     comme LA source de la décision de conformité, jamais le RAG.

JOUR 3 : le workflow commence désormais par l'enregistrement du contrat
de travail (écran 0), qui fixe le référentiel du dossier AVANT même le
dépôt de l'EVP (écran 1) — cf. commentaire en tête de ecran_enregistrement()
pour le détail. Design sobre, sans emoji (cf. frontend/.streamlit/config.toml
pour le thème et les fonctions _banniere/_badge/_style_conforme ci-dessous
pour la différenciation par couleur/gras plutôt que par icône).

Lancement local (stack docker-compose.dev.yml déjà démarrée, ports hôte
8000 = orchestrateur, 8001 = rag) :
    cd frontend
    streamlit run app.py
"""

from __future__ import annotations

import base64
import io
import json
import os
import sys
from datetime import date
from enum import Enum
from pathlib import Path
from typing import get_args

import httpx
import openpyxl
import pandas as pd
import streamlit as st

# --------------------------------------------------------------------------
# Configuration — URLs des vraies API (ports publiés par docker-compose.dev.yml)
# --------------------------------------------------------------------------

ORCHESTRATEUR_URL = os.environ.get("ORCHESTRATEUR_URL", "http://localhost:8000")
RAG_URL = os.environ.get("RAG_URL", "http://localhost:8001")
# extracteur-evp n'a jamais de port publié sur l'hôte (cf.
# docker-compose.dev.yml, "expose" seulement, contrairement à
# orchestrateur/rag ci-dessus) : le défaut ci-dessous ne fonctionne donc
# qu'en conteneur (nom de service Docker), où docker-compose.dev.yml le
# surcharge explicitement. Un lancement natif de ce fichier (hors
# conteneur) devra publier temporairement ce port et surcharger cette
# variable pour utiliser l'écran 0 "Nouveau salarié" (extraction PDF).
EXTRACTEUR_EVP_URL = os.environ.get("EXTRACTEUR_EVP_URL", "http://extracteur-evp:8000")
HTTP_TIMEOUT = 15.0

_ROOT = Path(__file__).resolve().parents[1]
_FIXTURES_DIR = _ROOT / "tests" / "fixtures"

# Rend `shared.schemas` importable (contrat.py n'est dupliqué nulle part
# ici : l'écran 0 valide le contrat saisi manuellement avec le VRAI
# modèle Pydantic ContratTravail, mêmes règles de cohérence que le reste
# du pipeline — cf. ecran_enregistrement()).
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
from shared.schemas import ContratTravail  # noqa: E402

st.set_page_config(page_title="Exeiguard — Pilotage du pipeline paie", layout="wide")


# --------------------------------------------------------------------------
# Appels HTTP réels — aucune donnée simulée, gestion d'erreur systématique
# --------------------------------------------------------------------------


def api_get(url: str, **kwargs) -> tuple[bool, object]:
    try:
        resp = httpx.get(url, timeout=HTTP_TIMEOUT, **kwargs)
    except httpx.HTTPError as exc:
        return False, f"Service injoignable ({url}) : {exc}"
    if resp.status_code >= 400:
        return False, f"Erreur {resp.status_code} de {url} : {resp.text[:300]}"
    return True, resp.json()


def api_post(url: str, **kwargs) -> tuple[bool, object]:
    try:
        resp = httpx.post(url, timeout=HTTP_TIMEOUT, **kwargs)
    except httpx.HTTPError as exc:
        return False, f"Service injoignable ({url}) : {exc}"
    if resp.status_code >= 400:
        try:
            detail = resp.json().get("detail", resp.text)
        except Exception:
            detail = resp.text
        return False, f"Erreur {resp.status_code} de {url} : {detail}"
    return True, resp.json()


# --------------------------------------------------------------------------
# Design sans emoji : différenciation par couleur/gras (bandeaux HTML
# personnalisés et cellules de tableau stylées), cf. frontend/.streamlit/
# config.toml pour la palette générale (bleu marine/gris/blanc). Les
# couleurs sémantiques (vert/rouge-orange/bleu) sont volontairement
# conservées pour les bandeaux et cellules de statut : c'est la couleur +
# le gras qui portent le sens, jamais une icône.
# --------------------------------------------------------------------------

_TONALITES = {
    "succes": ("#E6F4EA", "#1A7F37", "#B7DFC3"),
    "attention": ("#FDF3E7", "#B3541E", "#F3D9B8"),
    "erreur": ("#FDECEA", "#B3261E", "#F3C6C2"),
    "info": ("#EEF2F7", "#1F3A5F", "#C9D6E8"),
}


def _banniere(texte: str, tonalite: str = "info") -> None:
    """Bandeau de statut personnalisé (span/div HTML avec background-color
    et border-radius) — remplace st.success/st.warning/st.error/st.info,
    dont les icônes par défaut ne sont pas souhaitées ici."""
    fond, couleur_texte, bordure = _TONALITES.get(tonalite, _TONALITES["info"])
    st.markdown(
        f'<div style="background-color:{fond}; color:{couleur_texte}; '
        f'border:1px solid {bordure}; border-radius:6px; padding:10px 14px; '
        f'font-weight:600; margin-bottom:10px;">{texte}</div>',
        unsafe_allow_html=True,
    )


def _badge(texte: str, tonalite: str = "info") -> str:
    """Petit badge inline (pour insertion au milieu d'une phrase markdown)."""
    fond, couleur_texte, bordure = _TONALITES.get(tonalite, _TONALITES["info"])
    return (
        f'<span style="background-color:{fond}; color:{couleur_texte}; '
        f'border:1px solid {bordure}; border-radius:4px; padding:1px 8px; '
        f'font-weight:600; font-size:0.9em;">{texte}</span>'
    )


def _style_conforme(valeur: str) -> str:
    if valeur == "Conforme":
        return "color: #1A7F37; font-weight: 700;"
    return "color: #B3261E; font-weight: 700;"


def _tableau_controles(controles: list[dict]):
    """DataFrame stylé (texte coloré/gras, sans icône) pour un ensemble de
    résultats de contrôle de conformité — réutilisé sur l'écran de suivi
    et dans les fenêtres de décision."""
    df = pd.DataFrame(
        [
            {
                "Règle": c["regle_id"],
                "Conforme": "Conforme" if c["resultat"] == "conforme" else "Non conforme",
                "Explication complète": c["explication"],
            }
            for c in controles
        ]
    )
    return df.style.map(_style_conforme, subset=["Conforme"])


# --------------------------------------------------------------------------
# Cas de test (tests/fixtures/) — dropdown, cas réels en premier
# --------------------------------------------------------------------------


def lister_fixtures() -> list[Path]:
    if not _FIXTURES_DIR.is_dir():
        return []
    fichiers = sorted(_FIXTURES_DIR.glob("*.json"))
    reels = sorted(f for f in fichiers if "_reel" in f.stem)
    autres = sorted(f for f in fichiers if "_reel" not in f.stem)
    return reels + autres


def charger_fixture(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------
# Construction d'un classeur .xlsx EVP à partir d'un dict EVPMensuel (cas de
# test) : ce n'est PAS une donnée simulée, c'est le contenu réel de la
# fixture réencodé dans le format que l'API extracteur-evp attend
# réellement (upload multipart d'un .xlsx), pour que l'appel à /extraire
# soit un vrai appel, avec un vrai fichier, et non un dict envoyé en JSON.
# Même disposition que documentée dans
# extracteur-evp/app/parsers/excel_parser.py.
# --------------------------------------------------------------------------

NB_COLONNES = 28
COL_MATRICULE, COL_NOM, COL_PRENOM, COL_POSTE = 0, 1, 2, 3
COL_TYPE_CONTRAT, COL_DEBUT_CONTRAT, COL_SALAIRE_AN = 4, 5, 8
COL_NB_TICKET_RESTAURANT, COL_PASS_NAVIGO = 10, 11


def construire_xlsx_depuis_evp(evp: dict) -> bytes:
    row = [None] * NB_COLONNES
    row[COL_MATRICULE] = 1
    row[COL_NOM] = evp.get("nom")
    row[COL_PRENOM] = evp["prenom"]
    row[COL_POSTE] = evp["poste"]
    row[COL_TYPE_CONTRAT] = evp["type_contrat"]
    row[COL_DEBUT_CONTRAT] = date.fromisoformat(evp["debut_contrat"])
    row[COL_SALAIRE_AN] = evp["salaire_an"]
    row[COL_NB_TICKET_RESTAURANT] = evp.get("nb_ticket_restaurant", 0)
    row[COL_PASS_NAVIGO] = "OUI" if evp.get("pass_navigo") else "NON"

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["VARIABLES SOFT IT"] + [None] * (NB_COLONNES - 1))
    ws.append(["DATE", date.fromisoformat(evp["periode"])] + [None] * (NB_COLONNES - 2))
    ws.append([None] * NB_COLONNES)
    ws.append([None] * NB_COLONNES)
    ws.append([None] * NB_COLONNES)
    ws.append(row)

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# --------------------------------------------------------------------------
# État partagé entre écrans (st.session_state)
# --------------------------------------------------------------------------

if "dossier_id" not in st.session_state:
    st.session_state.dossier_id = None
if "evp_bytes" not in st.session_state:
    st.session_state.evp_bytes = None
if "evp_nom_fichier" not in st.session_state:
    st.session_state.evp_nom_fichier = None


def dossier_actuel() -> tuple[bool, dict | str]:
    if not st.session_state.dossier_id:
        return False, "Aucun dossier en cours."
    return api_get(f"{ORCHESTRATEUR_URL}/dossiers/{st.session_state.dossier_id}/etat")


# --------------------------------------------------------------------------
# Machine à états côté affichage (labels lisibles, jamais de logique de
# décision ici : la légalité des transitions vient uniquement de
# triggers_disponibles renvoyé par l'API)
# --------------------------------------------------------------------------

ETAPES_PRINCIPALES = ["A1", "A2", "A3", "A4", "A5", "A6"]
LIBELLE_ETAPE = {
    "A1": "A1 — Collecte",
    "A2": "A2 — Contrôle pré-calcul",
    "A2_3": "A2.3 — Écart détecté",
    "A3": "A3 — Calcul de paie",
    "A3_3": "A3.3 — Échec du calcul",
    "A4": "A4 — Validation post-calcul",
    "A4_3": "A4.3 — Correction demandée",
    "A5": "A5 — Paiement",
    "A6": "A6 — DSN / obligations légales",
    "TERMINE": "Terminé",
    "REJETE": "Rejeté",
}
ETATS_DECISION_HUMAINE = {"A2", "A2_3", "A4", "A4_3"}

LIBELLE_TRANSITION = {
    "extraire_evp": "Extraire l'EVP",
    "valider_transmission": "Valider la transmission",
    "detecter_ecart": "Signaler un écart",
    "corriger_evp": "Corriger et revenir à la collecte (A1)",
    "calcul_termine": "Lancer le calcul de paie (mock Sage)",
    "echec_calcul": "Signaler un échec de calcul",
    "relancer_calcul": "Relancer le calcul",
    "valider_bulletin": "Valider le bulletin",
    "demander_correction": "Demander une correction",
    "rejeter": "Rejeter le dossier",
    "retour_calcul": "Retour au calcul (A3)",
    "retour_controle": "Retour au contrôle (A2.3)",
    "autoriser_paiement": "Autoriser le paiement",
    "cloturer": "Clôturer le dossier",
}


def transitionner(action: str, acteur: str, commentaire: str | None = None) -> tuple[bool, object]:
    body = {"action": action, "acteur": acteur, "commentaire": commentaire}
    if action == "extraire_evp":
        if not st.session_state.evp_bytes:
            return False, "Aucun fichier EVP disponible pour cette action (retournez à l'écran 1)."
        body["evp_fichier_base64"] = base64.b64encode(st.session_state.evp_bytes).decode("ascii")
    return api_post(
        f"{ORCHESTRATEUR_URL}/dossiers/{st.session_state.dossier_id}/transition", json=body
    )


# --------------------------------------------------------------------------
# ÉCRAN 0 — Enregistrement du salarié (contrat de travail)
# --------------------------------------------------------------------------
#
# JOUR 3 : le contrat de travail devient une contrainte de référence pour
# tout le traitement (au même titre que la convention collective), et
# doit donc être enregistré AVANT même le dépôt de l'EVP. Ce écran crée
# le dossier (POST /dossiers) avec ce seul contrat, evp=None : le dossier
# existe en base, en A1, sans aucune donnée EVP tant que l'écran 1 n'a
# pas été utilisé.
#
# JOUR 4 : la saisie manuelle et les cas de test (fixtures) sont
# remplacés par le cœur du scénario de démo CEO — soit un salarié DÉJÀ
# CONNU (contrat recopié depuis son dernier dossier, GET /salaries), soit
# un NOUVEAU salarié dont le contrat est extrait automatiquement de son
# PDF réel (POST /extraire-contrat sur extracteur-evp, parsing
# déterministe par libellé + fallback LLM sous le seuil de confiance —
# cf. extracteur-evp/app/parsers/contrat_parser.py). Dans les deux cas,
# c'est toujours l'humain qui valide (clic explicite) avant que le
# contrat ne devienne la contrainte de référence du dossier — même
# principe que les fenêtres de décision de l'écran 2.


def _seuil_tonalite(confiance: float) -> str:
    if confiance >= 0.8:
        return "succes"
    if confiance >= 0.5:
        return "attention"
    return "erreur"


def _type_attendu_contrat(champ: str) -> type | None:
    """Type Python attendu par ContratTravail pour ce champ (Optional[X]
    déballé en X), pour choisir le bon widget de saisie manuelle."""
    info = ContratTravail.model_fields.get(champ)
    if info is None:
        return None
    annotation = info.annotation
    args = get_args(annotation)
    if args and type(None) in args:
        autres = [a for a in args if a is not type(None)]
        annotation = autres[0] if len(autres) == 1 else annotation
    return annotation


def _widget_correction_manuelle(champ: str, valeur_actuelle):
    """Champ de saisie manuelle éditable pour un champ dont l'extraction a
    totalement échoué (confiance 0, y compris après rejet du fallback LLM
    par la validation de type - cf. contrat_llm_fallback.py). Cohérent avec
    le principe du projet : validation humaine avant qu'une donnée ne
    devienne une contrainte de référence, ici appliquée au cas où
    l'extraction automatique n'a rien pu proposer, plutôt que de laisser
    l'utilisateur découvrir un crash Pydantic après coup au clic sur
    « Confirmer et créer le dossier »."""
    attendu = _type_attendu_contrat(champ)
    cle = f"c0_correction_{champ}"

    if attendu is bool:
        return st.checkbox(f"Valeur pour « {champ} »", value=bool(valeur_actuelle), key=cle)
    if attendu in (int, float):
        saisie = st.text_input(
            f"Valeur pour « {champ} » (laisser vide si non applicable)", value="", key=cle
        )
        if not saisie.strip():
            return None
        try:
            nombre = float(saisie.strip().replace(",", "."))
        except ValueError:
            st.caption(f"⚠ « {saisie} » n'est pas un nombre valide pour ce champ.")
            return None
        return int(nombre) if attendu is int else nombre
    if attendu is date:
        saisie_date = st.date_input(f"Valeur pour « {champ} »", value=None, key=cle)
        return saisie_date.isoformat() if saisie_date else None
    if isinstance(attendu, type) and issubclass(attendu, Enum):
        options = ["— non renseigné —"] + [e.value for e in attendu]
        choix = st.selectbox(f"Valeur pour « {champ} »", options=options, key=cle)
        return None if choix == options[0] else choix
    args_litteral = get_args(attendu) if attendu is not None else ()
    if args_litteral and all(isinstance(a, str) for a in args_litteral):
        options = ["— non renseigné —"] + list(args_litteral)
        choix = st.selectbox(f"Valeur pour « {champ} »", options=options, key=cle)
        return None if choix == options[0] else choix

    saisie_texte = st.text_input(f"Valeur pour « {champ} »", value="", key=cle)
    return saisie_texte.strip() or None


def _ecran_salarie_connu():
    ok, salaries = api_get(f"{ORCHESTRATEUR_URL}/salaries")
    if not ok:
        _banniere(str(salaries), "erreur")
        return
    if not salaries:
        _banniere("Aucun salarié déjà connu dans le système — utilisez « Nouveau salarié ».", "attention")
        return

    labels = [
        f"{s['prenom']} {s.get('nom') or ''} — {s['contrat'].get('poste', '?')} (matricule {s['matricule']})".strip()
        for s in salaries
    ]
    choix = st.selectbox("Salarié déjà connu", options=range(len(salaries)), format_func=lambda i: labels[i])
    salarie = salaries[choix]
    with st.expander("Voir le contrat de ce salarié (dernier dossier connu)"):
        st.json(salarie["contrat"])

    if st.button("Créer le dossier pour ce salarié", type="primary"):
        payload = {"matricule_reference": salarie["matricule"], "evp": None}
        ok, resultat = api_post(f"{ORCHESTRATEUR_URL}/dossiers", json=payload)
        if not ok:
            _banniere(str(resultat), "erreur")
            return
        st.session_state.dossier_id = resultat["id"]
        _banniere(
            f"Dossier {resultat['id']} créé pour {resultat['prenom']} (état initial {resultat['etat']}), "
            "contrat recopié depuis son dernier dossier. Rendez-vous sur l'écran « 1. Dépôt EVP ».",
            "succes",
        )


def _ecran_nouveau_salarie():
    upload = st.file_uploader("Contrat de travail (PDF)", type=["pdf"])
    if upload is not None and st.button("Extraire les données du contrat", type="primary"):
        ok, resultat = api_post(
            f"{EXTRACTEUR_EVP_URL}/extraire-contrat",
            files={"fichier": (upload.name, upload.getvalue(), "application/pdf")},
        )
        if not ok:
            _banniere(str(resultat), "erreur")
            return
        st.session_state.c0_contrat_extrait = resultat["contrat"]
        st.session_state.c0_confiance_par_champ = resultat["confiance_par_champ"]
        st.session_state.c0_llm_utilise = resultat["llm_utilise"]
        st.session_state.c0_champs_completes_par_llm = resultat["champs_completes_par_llm"]

    contrat_extrait = st.session_state.get("c0_contrat_extrait")
    if not contrat_extrait:
        return

    confiances = st.session_state.get("c0_confiance_par_champ") or {}
    completes_llm = set(st.session_state.get("c0_champs_completes_par_llm") or [])

    st.subheader("Données extraites du contrat")
    st.caption(
        "Extraction déterministe par libellé de section (jamais par numéro d'article fixe), "
        "complétée si besoin par un modèle de langage pour les seuls champs à faible confiance. "
        "Vérifiez chaque valeur avant de confirmer."
    )
    if st.session_state.get("c0_llm_utilise"):
        _banniere(
            "Le modèle de langage a été sollicité pour compléter les champs marqués ci-dessous "
            "(confiance parsing initial insuffisante).",
            "info",
        )

    corrections_manuelles = {}
    for champ, valeur in contrat_extrait.items():
        if champ not in confiances:
            continue
        confiance = confiances[champ]
        origine = (
            f" — Complété par le modèle de langage (confiance parsing initial insuffisante)"
            if champ in completes_llm
            else ""
        )
        _banniere(f"{champ} : {valeur!r} — confiance {confiance:.2f}{origine}", _seuil_tonalite(confiance))
        if confiance == 0:
            corrections_manuelles[champ] = _widget_correction_manuelle(champ, valeur)

    matricule = st.text_input("Matricule (identifiant interne du dossier)", key="c0_matricule_pdf")

    if st.button("Confirmer et créer le dossier", type="primary"):
        contrat_corrige = {**contrat_extrait, **corrections_manuelles}
        try:
            contrat_valide = ContratTravail(**contrat_corrige)
        except Exception as exc:
            _banniere(f"Contrat invalide ou incomplet : {exc}", "erreur")
            return

        payload = {
            "matricule": matricule or None,
            "contrat": contrat_valide.model_dump(mode="json"),
            "evp": None,
        }
        ok, resultat = api_post(f"{ORCHESTRATEUR_URL}/dossiers", json=payload)
        if not ok:
            _banniere(str(resultat), "erreur")
            return

        st.session_state.dossier_id = resultat["id"]
        for cle in ("c0_contrat_extrait", "c0_confiance_par_champ", "c0_llm_utilise", "c0_champs_completes_par_llm"):
            st.session_state.pop(cle, None)
        _banniere(
            f"Salarié enregistré — dossier {resultat['id']} — état initial {resultat['etat']} "
            f"({resultat['prenom']}). Rendez-vous sur l'écran « 1. Dépôt EVP ».",
            "succes",
        )


def ecran_enregistrement():
    st.header("0. Enregistrement du salarié")
    st.caption(
        "Le contrat de travail est désormais la première donnée enregistrée : il devient la "
        "contrainte de référence pour tout le traitement, avant même le dépôt de l'EVP."
    )

    if st.session_state.dossier_id:
        _banniere(
            f"Un dossier est déjà enregistré (id {st.session_state.dossier_id}). "
            "Utilisez « Nouveau dossier » dans la barre latérale pour en enregistrer un autre.",
            "info",
        )
        return

    ok, sante = api_get(f"{ORCHESTRATEUR_URL}/health")
    if not ok:
        _banniere(f"Orchestrateur injoignable : {sante}", "erreur")
        return
    _banniere("Orchestrateur joignable.", "succes")

    mode = st.radio("Salarié", ["Salarié déjà connu", "Nouveau salarié"], horizontal=True)

    if mode == "Salarié déjà connu":
        _ecran_salarie_connu()
    else:
        _ecran_nouveau_salarie()


# --------------------------------------------------------------------------
# ÉCRAN 1 — Dépôt du fichier EVP (sur le dossier déjà créé à l'écran 0)
# --------------------------------------------------------------------------
#
# Choix technique retenu (pas de nouvel endpoint orchestrateur) : le
# fichier EVP uploadé ici est conservé côté client (st.session_state,
# jamais envoyé au serveur à ce stade) et n'est transmis QUE lors du clic
# sur le trigger "Extraire l'EVP" (écran 2), directement dans le corps de
# POST /dossiers/{id}/transition (champ evp_fichier_base64, déjà présent
# dans TransitionRequest — cf. orchestrateur/app/schemas.py). Cet écran
# n'a donc besoin d'aucun appel API : il se contente de préparer les
# octets réellement uploadés (ou reconstruits depuis un cas de test) pour
# ce clic ultérieur. C'est bien le fichier réellement déposé ici qui
# transite vers extracteur-evp, jamais un fichier fixe côté serveur.


def ecran_depot_evp():
    st.header("1. Dépôt de l'EVP")

    if not st.session_state.dossier_id:
        _banniere("Enregistrez d'abord un salarié (écran « 0. Enregistrement du salarié »).", "attention")
        return

    ok, dossier = dossier_actuel()
    if not ok:
        _banniere(str(dossier), "erreur")
        return
    st.caption(f"Dossier `{dossier['id']}` — {dossier['prenom']} (matricule {dossier['matricule'] or 'n/a'})")

    mode = st.radio(
        "Origine du fichier EVP", ["Upload d'un fichier réel (.xlsx)", "Cas de test (démo rapide)"], horizontal=True
    )

    if mode == "Upload d'un fichier réel (.xlsx)":
        upload = st.file_uploader("Fichier EVP mensuel (.xlsx)", type=["xlsx"])
        if upload is not None and st.button("Utiliser ce fichier", type="primary"):
            st.session_state.evp_bytes = upload.getvalue()
            st.session_state.evp_nom_fichier = upload.name
            _banniere(f"Fichier « {upload.name} » prêt pour l'extraction (écran 2).", "succes")
    else:
        fixtures = lister_fixtures()
        if not fixtures:
            _banniere("Aucun cas de test trouvé dans tests/fixtures/.", "attention")
            return
        labels = [f"{'[Cas réel] ' if '_reel' in f.stem else ''}{f.stem}" for f in fixtures]
        choix = st.selectbox("Cas de test (EVP)", options=range(len(fixtures)), format_func=lambda i: labels[i])
        fixture_path = fixtures[choix]
        cas = charger_fixture(fixture_path)
        with st.expander("Voir l'EVP de ce cas"):
            st.json(cas["evp"])
        if st.button("Utiliser ce cas de test", type="primary"):
            st.session_state.evp_bytes = construire_xlsx_depuis_evp(cas["evp"])
            st.session_state.evp_nom_fichier = f"{fixture_path.stem}.xlsx (reconstruit depuis le cas de test)"
            _banniere("Fichier EVP du cas de test prêt pour l'extraction (écran 2).", "succes")

    if st.session_state.evp_bytes:
        st.caption(f"Fichier actuellement prêt : {st.session_state.evp_nom_fichier}")


# --------------------------------------------------------------------------
# ÉCRAN 2 — Suivi du pipeline (+ fenêtres de décision contextuelles)
# --------------------------------------------------------------------------


def barre_progression(etat: str):
    if etat == "TERMINE":
        index_affiche = len(ETAPES_PRINCIPALES)
    elif etat == "REJETE":
        index_affiche = None
    elif etat in ETAPES_PRINCIPALES:
        index_affiche = ETAPES_PRINCIPALES.index(etat)
    else:  # boucle A2_3 / A3_3 / A4_3 : rattachée à l'étape principale correspondante
        parent = etat.split("_")[0]
        index_affiche = ETAPES_PRINCIPALES.index(parent) if parent in ETAPES_PRINCIPALES else 0

    if etat == "REJETE":
        st.progress(1.0, text="Dossier rejeté")
    else:
        fraction = (index_affiche + (1 if etat == "TERMINE" else 0)) / len(ETAPES_PRINCIPALES)
        st.progress(min(fraction, 1.0), text=LIBELLE_ETAPE.get(etat, etat))

    cols = st.columns(len(ETAPES_PRINCIPALES))
    for i, (col, code) in enumerate(zip(cols, ETAPES_PRINCIPALES)):
        if etat == "TERMINE" or (index_affiche is not None and i < index_affiche):
            col.markdown(f'<span style="color:#1A7F37; font-weight:700;">{code}</span>', unsafe_allow_html=True)
        elif index_affiche is not None and i == index_affiche:
            col.markdown(
                f'<span style="color:#1B2A4A; font-weight:700; text-decoration:underline;">{code}</span>',
                unsafe_allow_html=True,
            )
        else:
            col.markdown(f'<span style="color:#9AA0A6;">{code}</span>', unsafe_allow_html=True)


def afficher_extraction(dossier_id: str):
    ok, lignes = api_get(f"{ORCHESTRATEUR_URL}/dossiers/{dossier_id}/evp")
    if not ok:
        _banniere(str(lignes), "erreur")
        return
    if not lignes:
        return
    st.subheader("Extraction EVP (extracteur-evp)")
    for ligne in lignes:
        score = ligne.get("score_confiance")
        evp = ligne.get("evp", {})
        label = f"Score de confiance : {score:.2f}" if score is not None else "Score de confiance : n/a"
        tonalite = "succes" if (score is not None and score > 0.7) else "attention"
        _banniere(f"{label} — {evp.get('prenom', '?')} {evp.get('nom') or ''}".strip(), tonalite)
        with st.expander("Détail de la ligne EVP extraite"):
            st.json(evp)


def afficher_controles(dossier_id: str):
    ok, controles = api_get(f"{ORCHESTRATEUR_URL}/dossiers/{dossier_id}/controles")
    if not ok:
        _banniere(str(controles), "erreur")
        return
    if not controles:
        return
    st.subheader("Résultats du Rule Engine (compliance-validation)")
    st.caption(
        "Décision déterministe, jamais portée par un LLM ou le RAG : chaque ligne cite "
        "précisément l'article de la CCN SYNTEC ou l'accord Soft IT qui la fonde."
    )
    for phase in sorted({c["phase"] for c in controles}):
        lignes_phase = [c for c in controles if c["phase"] == phase]
        non_conformes = [c for c in lignes_phase if c["resultat"] != "conforme"]
        titre_phase = "A2 (pré-calcul)" if phase == "A2" else "A4 (post-calcul)" if phase == "A4" else phase
        st.markdown(f"**Contrôle {titre_phase}**")
        if non_conformes:
            _banniere(
                f"{len(non_conformes)} règle(s) non conforme(s) détectée(s) — décision humaine requise, "
                "l'avancement n'est pas bloqué automatiquement.",
                "attention",
            )
        st.dataframe(_tableau_controles(lignes_phase), use_container_width=True, hide_index=True)


def afficher_bulletin(dossier_id: str):
    ok, bulletins = api_get(f"{ORCHESTRATEUR_URL}/dossiers/{dossier_id}/bulletins")
    if not ok:
        _banniere(str(bulletins), "erreur")
        return
    if not bulletins:
        return
    st.subheader("Bulletin simulé (integration-sage)")
    _banniere(
        "<strong>CALCUL DE DÉMONSTRATION — en attente d'intégration Sage réelle.</strong> "
        "Ces montants sont produits par une formule factice (voir integration-sage/README.md), "
        "aucune valeur réglementaire.",
        "attention",
    )
    dernier = bulletins[-1]["bulletin"]
    col1, col2, col3 = st.columns(3)
    col1.metric("Rémunération brute", f"{dernier.get('total_remuneration_brute', 0):,.2f} €")
    col2.metric("Cotisations salariales", f"{dernier.get('total_cotisations_salariales', 0):,.2f} €")
    col3.metric("Net à payer (mock)", f"{dernier.get('net_a_payer', 0):,.2f} €")
    with st.expander("Détail complet du bulletin simulé"):
        st.json(dernier)


ACTEURS_POSSIBLES = ["gestionnaire", "responsable_validation", "orchestrateur"]


def _contenu_decision(dossier: dict, phase: str):
    """Contenu commun aux deux fenêtres de décision (A2/A4) : récapitulatif
    déjà en base (cf. commentaire dans _executer_controle_conformite côté
    orchestrateur — le contrôle est déclenché à l'ENTRÉE de l'état, jamais
    par cette décision elle-même), puis acteur/commentaire/boutons."""
    st.caption(f"État actuel : {LIBELLE_ETAPE.get(dossier['etat'], dossier['etat'])}")

    ok_c, controles = api_get(f"{ORCHESTRATEUR_URL}/dossiers/{dossier['id']}/controles", params={"phase": phase})
    if ok_c and controles:
        non_conformes = [c for c in controles if c["resultat"] != "conforme"]
        st.markdown(f"**Récapitulatif du contrôle {phase}** ({len(controles)} règle(s) évaluée(s))")
        if non_conformes:
            _banniere(f"{len(non_conformes)} écart(s) détecté(s).", "attention")
        else:
            _banniere("Aucun écart détecté par le Rule Engine.", "succes")
        st.dataframe(_tableau_controles(controles), use_container_width=True, hide_index=True)
    else:
        _banniere(
            f"Aucun résultat de contrôle {phase} trouvé en base pour ce dossier — anomalie, "
            "vérifier le journal d'audit.",
            "erreur",
        )

    if phase == "A4":
        ok_b, bulletins = api_get(f"{ORCHESTRATEUR_URL}/dossiers/{dossier['id']}/bulletins")
        if ok_b and bulletins:
            _banniere("<strong>CALCUL DE DÉMONSTRATION</strong> — en attente d'intégration Sage réelle.", "attention")
            with st.expander("Détail du bulletin"):
                st.json(bulletins[-1]["bulletin"])

    st.divider()
    acteur = st.selectbox("Acteur (qui prend la décision)", ACTEURS_POSSIBLES, key=f"acteur_{dossier['id']}_{phase}")
    commentaire = st.text_area("Commentaire (optionnel)", "", key=f"commentaire_{dossier['id']}_{phase}")

    triggers = dossier["triggers_disponibles"]
    cols = st.columns(len(triggers)) if triggers else []
    for col, trig in zip(cols, triggers):
        with col:
            if st.button(
                LIBELLE_TRANSITION.get(trig, trig),
                key=f"decision_{dossier['id']}_{trig}",
                use_container_width=True,
            ):
                ok2, resultat = transitionner(trig, acteur=acteur, commentaire=commentaire or None)
                if ok2:
                    st.session_state["_derniere_decision"] = f"{dossier['etat']} → {resultat['etat']}"
                    st.rerun()
                else:
                    _banniere(str(resultat), "erreur")


@st.dialog("Contrôle de conformité avant calcul")
def _popup_decision_a2(dossier: dict):
    _contenu_decision(dossier, phase="A2")


@st.dialog("Contrôle de conformité avant paiement")
def _popup_decision_a4(dossier: dict):
    _contenu_decision(dossier, phase="A4")


def ecran_pipeline():
    st.header("2. Suivi du pipeline")

    ok, dossier = dossier_actuel()
    if not ok:
        _banniere(str(dossier) if isinstance(dossier, str) else "Enregistrez d'abord un salarié (écran 0).", "info")
        return

    if st.session_state.get("_derniere_decision"):
        _banniere(f"Décision enregistrée : {st.session_state.pop('_derniere_decision')}", "succes")

    st.caption(f"Dossier `{dossier['id']}` — {dossier['prenom']} (matricule {dossier['matricule'] or 'n/a'})")
    barre_progression(dossier["etat"])
    st.divider()

    if dossier["etat"] in ETATS_DECISION_HUMAINE:
        _banniere(
            "Décision humaine requise avant de poursuivre — la fenêtre de décision s'ouvre "
            "automatiquement ci-dessous.",
            "attention",
        )
        if dossier["etat"] in ("A2", "A2_3"):
            _popup_decision_a2(dossier)
        else:
            _popup_decision_a4(dossier)
    elif dossier["etat"] in ("TERMINE", "REJETE"):
        _banniere("Dossier clôturé." if dossier["etat"] == "TERMINE" else "Dossier rejeté.", "succes")
    else:
        # États "pipeline" (pas de décision réglementaire) : les triggers
        # disponibles depuis ces états ne sont jamais des triggers de
        # décision (cf. state_machine.py), affichés tels quels.
        for trig in dossier["triggers_disponibles"]:
            label = LIBELLE_TRANSITION.get(trig, trig)
            if st.button(label, key=f"pipeline_{trig}"):
                ok2, resultat = transitionner(trig, acteur="orchestrateur")
                if ok2:
                    st.session_state["_derniere_decision"] = f"{dossier['etat']} → {resultat['etat']}"
                    st.rerun()
                else:
                    _banniere(str(resultat), "erreur")

    st.divider()
    afficher_extraction(dossier["id"])
    afficher_controles(dossier["id"])
    afficher_bulletin(dossier["id"])

    with st.expander("Journal d'audit de ce dossier (accès rapide, voir aussi écran 4)"):
        afficher_audit_log(dossier["id"])


# --------------------------------------------------------------------------
# ÉCRAN 3 — Recherche réglementaire (RAG)
# --------------------------------------------------------------------------


def ecran_rag():
    st.header("3. Recherche réglementaire (RAG)")
    _banniere(
        "<strong>Recherche documentaire</strong> — fournit du contexte, ne prend jamais de décision "
        "réglementaire. Les décisions de conformité viennent exclusivement du Rule Engine "
        "(écran de suivi), jamais de cette recherche.",
        "info",
    )

    question = st.text_input("Question libre sur la CCN SYNTEC", placeholder="Ex : Quel est le préavis pour un cadre ?")
    if st.button("Rechercher", type="primary") and question.strip():
        ok, resultat = api_post(f"{RAG_URL}/rag/query", json={"question": question})
        if not ok:
            _banniere(str(resultat), "erreur")
            return
        passages = resultat.get("passages", [])
        if not passages:
            _banniere("Aucun passage trouvé.", "attention")
            return
        for p in passages:
            with st.container(border=True):
                st.markdown(f"**Article {p['article']} — {p['titre']}** (score {p['score']:.2f})")
                st.write(p["texte"])
                st.caption(f"Source : {p['source']}, page {p['page']}")


# --------------------------------------------------------------------------
# ÉCRAN 4 — Journal d'audit
# --------------------------------------------------------------------------


def afficher_audit_log(dossier_id: str):
    ok, entries = api_get(f"{ORCHESTRATEUR_URL}/dossiers/{dossier_id}/audit")
    if not ok:
        _banniere(str(entries), "erreur")
        return
    if not entries:
        _banniere("Aucune entrée d'audit pour l'instant.", "info")
        return
    df = pd.DataFrame(
        [
            {
                "Horodatage": e["horodatage"],
                "Acteur": e["acteur"],
                "Action": e["action"],
                "Résultat": e["resultat"],
            }
            for e in entries
        ]
    )
    st.dataframe(df, use_container_width=True, hide_index=True)


def ecran_audit():
    st.header("4. Journal d'audit")
    st.caption(
        "Preuve de traçabilité complète : chaque transition d'état ET chaque appel "
        "inter-service (extracteur-evp, compliance-validation, integration-sage) est "
        "journalisé ici, pas seulement les changements de statut."
    )
    ok, dossier = dossier_actuel()
    if not ok:
        _banniere(str(dossier) if isinstance(dossier, str) else "Enregistrez d'abord un salarié (écran 0).", "info")
        return
    if st.button("Rafraîchir"):
        st.rerun()
    afficher_audit_log(dossier["id"])


# --------------------------------------------------------------------------
# Navigation
# --------------------------------------------------------------------------

st.title("Exeiguard — Pilotage du pipeline paie A1 → A6")

onglets = st.tabs(
    [
        "0. Enregistrement salarié",
        "1. Dépôt EVP",
        "2. Suivi du pipeline",
        "3. Recherche RAG",
        "4. Journal d'audit",
    ]
)

with onglets[0]:
    ecran_enregistrement()
with onglets[1]:
    ecran_depot_evp()
with onglets[2]:
    ecran_pipeline()
with onglets[3]:
    ecran_rag()
with onglets[4]:
    ecran_audit()

# Rendue APRÈS les onglets (pas avant) : Streamlit exécute tout le script à
# chaque interaction, y compris le contenu de tous les onglets (leur
# visibilité est un simple toggle côté client). Si la barre latérale était
# rendue avant les onglets, elle refléterait l'état AVANT une action de
# cette même exécution — bug réel observé en test manuel le 10/09.
with st.sidebar:
    st.markdown("### Dossier en cours")
    if st.session_state.dossier_id:
        st.code(st.session_state.dossier_id, language=None)
        if st.session_state.evp_nom_fichier:
            st.caption(f"Fichier EVP : {st.session_state.evp_nom_fichier}")
        if st.button("Nouveau dossier"):
            st.session_state.dossier_id = None
            st.session_state.evp_bytes = None
            st.session_state.evp_nom_fichier = None
            st.rerun()
    else:
        st.caption("Aucun dossier sélectionné — commencez par l'écran 0.")
    st.divider()
    st.caption(f"Orchestrateur : {ORCHESTRATEUR_URL}")
    st.caption(f"RAG : {RAG_URL}")
