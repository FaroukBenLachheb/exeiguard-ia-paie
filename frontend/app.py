"""
frontend/app.py

Interface Streamlit pilotant le pipeline réel A1->A6 (JOUR 2). Destinée à
être montrée au CEO : AUCUNE donnée n'est simulée ou codée en dur ici.
Chaque écran appelle les vraies API HTTP (orchestrateur, extracteur-evp
via l'orchestrateur, compliance-validation via l'orchestrateur,
integration-sage via l'orchestrateur, rag directement) et n'affiche que
ce que ces services renvoient réellement.

Trois principes non négociables du projet, rappelés à l'écran à chaque
endroit pertinent :
  1. Traçabilité complète -> écran 5 (journal d'audit), toujours accessible.
  2. Validation humaine obligatoire -> écran 3 : aucune transition qui
     engage une décision réglementaire n'est déclenchée ailleurs que par
     un clic explicite sur ce écran dédié.
  3. Rule Engine (déterministe, décisionnel) vs RAG (documentaire,
     jamais décisionnel) -> bandeau explicite sur l'écran 4, et les
     résultats du Rule Engine (écran 2) sont toujours présentés comme
     LA source de la décision de conformité, jamais le RAG.

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
from datetime import date, datetime
from pathlib import Path

import httpx
import openpyxl
import pandas as pd
import streamlit as st

# --------------------------------------------------------------------------
# Configuration — URLs des vraies API (ports publiés par docker-compose.dev.yml)
# --------------------------------------------------------------------------

ORCHESTRATEUR_URL = os.environ.get("ORCHESTRATEUR_URL", "http://localhost:8000")
RAG_URL = os.environ.get("RAG_URL", "http://localhost:8001")
HTTP_TIMEOUT = 15.0

_ROOT = Path(__file__).resolve().parents[1]
_FIXTURES_DIR = _ROOT / "tests" / "fixtures"

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
    "extraire_evp": "📄 Extraire l'EVP",
    "valider_transmission": "✅ Valider la transmission",
    "detecter_ecart": "⚠️ Signaler un écart",
    "corriger_evp": "🔁 Corriger et revenir à la collecte (A1)",
    "calcul_termine": "🧮 Lancer le calcul de paie (mock Sage)",
    "echec_calcul": "❌ Signaler un échec de calcul",
    "relancer_calcul": "🔁 Relancer le calcul",
    "valider_bulletin": "✅ Valider le bulletin",
    "demander_correction": "⚠️ Demander une correction",
    "rejeter": "❌ Rejeter le dossier",
    "retour_calcul": "🔁 Retour au calcul (A3)",
    "retour_controle": "🔁 Retour au contrôle (A2.3)",
    "autoriser_paiement": "💶 Autoriser le paiement",
    "cloturer": "🏁 Clôturer le dossier",
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
# ÉCRAN 1 — Dépôt et démarrage d'un dossier
# --------------------------------------------------------------------------


def ecran_depot():
    st.header("1. Dépôt et démarrage d'un dossier")

    ok, sante = api_get(f"{ORCHESTRATEUR_URL}/health")
    if not ok:
        st.error(f"Orchestrateur injoignable : {sante}")
        return
    st.success("Orchestrateur joignable.")

    fixtures = lister_fixtures()
    if not fixtures:
        st.warning("Aucun cas de test trouvé dans tests/fixtures/.")
        return

    labels = [f"{'⭐ ' if '_reel' in f.stem else ''}{f.stem}" for f in fixtures]
    choix = st.selectbox(
        "Cas de test (⭐ = cas réel Soft IT)", options=range(len(fixtures)), format_func=lambda i: labels[i]
    )
    fixture_path = fixtures[choix]
    cas = charger_fixture(fixture_path)
    st.caption(cas.get("description", ""))

    with st.expander("Voir le contrat et l'EVP de ce cas"):
        col1, col2 = st.columns(2)
        col1.json(cas["contrat"])
        col2.json(cas["evp"])

    st.markdown("**Fichier EVP à utiliser pour l'extraction (écran 2)**")
    upload = st.file_uploader(
        "Optionnel : déposez votre propre fichier EVP réel (.xlsx) — remplace le fichier "
        "reconstruit automatiquement depuis le cas de test choisi ci-dessus",
        type=["xlsx"],
    )

    matricule = st.text_input("Matricule", value=cas.get("id", ""))

    if st.button("Créer le dossier", type="primary"):
        payload = {"matricule": matricule, "contrat": cas["contrat"], "evp": cas["evp"]}
        ok, resultat = api_post(f"{ORCHESTRATEUR_URL}/dossiers", json=payload)
        if not ok:
            st.error(resultat)
            return

        if upload is not None:
            st.session_state.evp_bytes = upload.getvalue()
            st.session_state.evp_nom_fichier = upload.name
        else:
            st.session_state.evp_bytes = construire_xlsx_depuis_evp(cas["evp"])
            st.session_state.evp_nom_fichier = f"{fixture_path.stem}.xlsx (reconstruit depuis le cas de test)"

        st.session_state.dossier_id = resultat["id"]
        st.success(
            f"Dossier créé — id={resultat['id']} — état initial : {resultat['etat']} "
            f"(salarié : {resultat['prenom']})"
        )
        st.info("Rendez-vous sur l'écran 2 pour suivre le pipeline.")


# --------------------------------------------------------------------------
# ÉCRAN 2 — Suivi du pipeline
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
            col.markdown(f"✅ **{code}**")
        elif index_affiche is not None and i == index_affiche:
            col.markdown(f"🔵 **{code}**")
        else:
            col.markdown(f"⚪ {code}")


def afficher_extraction(dossier_id: str):
    ok, lignes = api_get(f"{ORCHESTRATEUR_URL}/dossiers/{dossier_id}/evp")
    if not ok:
        st.error(lignes)
        return
    if not lignes:
        return
    st.subheader("Extraction EVP (extracteur-evp)")
    for ligne in lignes:
        score = ligne.get("score_confiance")
        evp = ligne.get("evp", {})
        label = f"Score de confiance : {score:.2f}" if score is not None else "Score de confiance : n/a"
        if score is not None and score > 0.7:
            st.success(f"{label} — {evp.get('prenom', '?')} {evp.get('nom') or ''}".strip())
        else:
            st.warning(f"{label} — {evp.get('prenom', '?')} {evp.get('nom') or ''}".strip())
        with st.expander("Détail de la ligne EVP extraite"):
            st.json(evp)


def afficher_controles(dossier_id: str):
    ok, controles = api_get(f"{ORCHESTRATEUR_URL}/dossiers/{dossier_id}/controles")
    if not ok:
        st.error(controles)
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
            st.warning(
                f"{len(non_conformes)} règle(s) non conforme(s) détectée(s) — signalé pour décision "
                "humaine (écran 3), l'avancement n'est PAS bloqué automatiquement."
            )
        df = pd.DataFrame(
            [
                {
                    "Règle": c["regle_id"],
                    "Conforme": "✅" if c["resultat"] == "conforme" else "⚠️",
                    "Explication complète": c["explication"],
                }
                for c in lignes_phase
            ]
        )
        st.dataframe(df, use_container_width=True, hide_index=True)


def afficher_bulletin(dossier_id: str):
    ok, bulletins = api_get(f"{ORCHESTRATEUR_URL}/dossiers/{dossier_id}/bulletins")
    if not ok:
        st.error(bulletins)
        return
    if not bulletins:
        return
    st.subheader("Bulletin simulé (integration-sage)")
    st.warning(
        "⚠️ **CALCUL DE DÉMONSTRATION — en attente d'intégration Sage réelle.** "
        "Ces montants sont produits par une formule factice (voir integration-sage/README.md), "
        "aucune valeur réglementaire."
    )
    dernier = bulletins[-1]["bulletin"]
    col1, col2, col3 = st.columns(3)
    col1.metric("Rémunération brute", f"{dernier.get('total_remuneration_brute', 0):,.2f} €")
    col2.metric("Cotisations salariales", f"{dernier.get('total_cotisations_salariales', 0):,.2f} €")
    col3.metric("Net à payer (mock)", f"{dernier.get('net_a_payer', 0):,.2f} €")
    with st.expander("Détail complet du bulletin simulé"):
        st.json(dernier)


def ecran_pipeline():
    st.header("2. Suivi du pipeline")

    ok, dossier = dossier_actuel()
    if not ok:
        st.info(dossier if isinstance(dossier, str) else "Créez d'abord un dossier (écran 1).")
        return

    st.caption(f"Dossier `{dossier['id']}` — {dossier['prenom']} (matricule {dossier['matricule'] or 'n/a'})")
    barre_progression(dossier["etat"])
    st.divider()

    if dossier["etat"] in ETATS_DECISION_HUMAINE:
        st.warning(
            "⚠️ **Décision humaine requise avant de poursuivre** — rendez-vous sur "
            "l'écran **3. Validation humaine**. Aucune transition n'est déclenchée depuis cet écran "
            "tant qu'une décision explicite n'a pas été prise."
        )
    elif dossier["etat"] in ("TERMINE", "REJETE"):
        st.success("Dossier clôturé." if dossier["etat"] == "TERMINE" else "Dossier rejeté.")
    else:
        # États "pipeline" (pas de décision réglementaire) : les triggers
        # disponibles depuis ces états ne sont jamais des triggers de
        # décision (cf. state_machine.py), affichés tels quels.
        for trig in dossier["triggers_disponibles"]:
            label = LIBELLE_TRANSITION.get(trig, trig)
            if st.button(label, key=f"pipeline_{trig}"):
                ok2, resultat = transitionner(trig, acteur="orchestrateur")
                if ok2:
                    st.success(f"{dossier['etat']} → {resultat['etat']}")
                    st.rerun()
                else:
                    st.error(resultat)

    st.divider()
    afficher_extraction(dossier["id"])
    afficher_controles(dossier["id"])
    afficher_bulletin(dossier["id"])

    with st.expander("📋 Journal d'audit de ce dossier (accès rapide, voir aussi écran 5)"):
        afficher_audit_log(dossier["id"])


# --------------------------------------------------------------------------
# ÉCRAN 3 — Validation humaine
# --------------------------------------------------------------------------

ACTEURS_POSSIBLES = ["gestionnaire", "responsable_validation", "orchestrateur"]


def ecran_validation_humaine():
    st.header("3. Validation humaine")
    st.caption(
        "Principe non négociable du projet : aucune décision réglementaire n'est jamais prise "
        "automatiquement. Une action explicite, ici, est obligatoire pour que le dossier avance."
    )

    ok, dossier = dossier_actuel()
    if not ok:
        st.info(dossier if isinstance(dossier, str) else "Créez d'abord un dossier (écran 1).")
        return

    if dossier["etat"] not in ETATS_DECISION_HUMAINE:
        st.info(
            f"Le dossier est actuellement en état **{LIBELLE_ETAPE.get(dossier['etat'], dossier['etat'])}** "
            "— aucune décision humaine n'est requise à ce stade (voir écran 2)."
        )
        return

    st.subheader(f"Décision requise — état {LIBELLE_ETAPE.get(dossier['etat'], dossier['etat'])}")

    phase = "A2" if dossier["etat"] in ("A2", "A2_3") else "A4"
    # Depuis la correction du 10/09/2026 (défaut architectural trouvé lors
    # du test UI), le contrôle de conformité {phase} est déclenché à
    # l'ENTRÉE de cet état (extraire_evp pour A2, calcul_termine pour A4),
    # pas par le clic de décision lui-même : les résultats doivent donc
    # TOUJOURS être déjà en base ici, avant tout bouton Valider/Corriger/
    # Rejeter — jamais après.
    ok_c, controles = api_get(f"{ORCHESTRATEUR_URL}/dossiers/{dossier['id']}/controles", params={"phase": phase})
    if ok_c and controles:
        non_conformes = [c for c in controles if c["resultat"] != "conforme"]
        st.markdown(f"**Récapitulatif du contrôle {phase}** ({len(controles)} règle(s) évaluée(s))")
        if non_conformes:
            st.error(f"{len(non_conformes)} écart(s) détecté(s) :")
            for c in non_conformes:
                st.markdown(f"- **{c['regle_id']}** — {c['explication']}")
        else:
            st.success("Aucun écart détecté par le Rule Engine.")
        with st.expander("Voir le détail complet des 10 règles"):
            df = pd.DataFrame(
                [
                    {"Règle": c["regle_id"], "Conforme": "✅" if c["resultat"] == "conforme" else "⚠️", "Explication": c["explication"]}
                    for c in controles
                ]
            )
            st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        # Ne devrait plus arriver en fonctionnement normal (cf. commentaire
        # ci-dessus) : signalé comme anomalie, pas comme un état attendu.
        st.error(
            f"⚠️ Aucun résultat de contrôle {phase} trouvé en base pour ce dossier alors que l'état "
            f"{dossier['etat']} devrait toujours en contenir un — vérifier audit_log (écran 5)."
        )

    if phase == "A4":
        ok_b, bulletins = api_get(f"{ORCHESTRATEUR_URL}/dossiers/{dossier['id']}/bulletins")
        if ok_b and bulletins:
            st.warning("⚠️ CALCUL DE DÉMONSTRATION — en attente d'intégration Sage réelle.")
            st.json(bulletins[-1]["bulletin"])

    st.divider()
    acteur = st.selectbox("Acteur (qui prend la décision)", ACTEURS_POSSIBLES)
    commentaire = st.text_area("Commentaire (optionnel)", "")

    triggers = dossier["triggers_disponibles"]
    cols = st.columns(len(triggers)) if triggers else []
    for col, trig in zip(cols, triggers):
        with col:
            if st.button(LIBELLE_TRANSITION.get(trig, trig), key=f"decision_{trig}", use_container_width=True):
                ok2, resultat = transitionner(trig, acteur=acteur, commentaire=commentaire or None)
                if ok2:
                    st.success(f"Décision enregistrée : {dossier['etat']} → {resultat['etat']}")
                    st.rerun()
                else:
                    st.error(resultat)


# --------------------------------------------------------------------------
# ÉCRAN 4 — Recherche réglementaire (RAG)
# --------------------------------------------------------------------------


def ecran_rag():
    st.header("4. Recherche réglementaire (RAG)")
    st.info(
        "📚 **Recherche documentaire — fournit du contexte, ne prend jamais de décision "
        "réglementaire.** Les décisions de conformité viennent exclusivement du Rule Engine "
        "(écran 2/3), jamais de cette recherche."
    )

    question = st.text_input("Question libre sur la CCN SYNTEC", placeholder="Ex : Quel est le préavis pour un cadre ?")
    if st.button("Rechercher", type="primary") and question.strip():
        ok, resultat = api_post(f"{RAG_URL}/rag/query", json={"question": question})
        if not ok:
            st.error(resultat)
            return
        passages = resultat.get("passages", [])
        if not passages:
            st.warning("Aucun passage trouvé.")
            return
        for p in passages:
            with st.container(border=True):
                st.markdown(f"**Article {p['article']} — {p['titre']}** (score {p['score']:.2f})")
                st.write(p["texte"])
                st.caption(f"Source : {p['source']}, page {p['page']}")


# --------------------------------------------------------------------------
# ÉCRAN 5 — Journal d'audit
# --------------------------------------------------------------------------


def afficher_audit_log(dossier_id: str):
    ok, entries = api_get(f"{ORCHESTRATEUR_URL}/dossiers/{dossier_id}/audit")
    if not ok:
        st.error(entries)
        return
    if not entries:
        st.info("Aucune entrée d'audit pour l'instant.")
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
    st.header("5. Journal d'audit")
    st.caption(
        "Preuve de traçabilité complète : chaque transition d'état ET chaque appel "
        "inter-service (extracteur-evp, compliance-validation, integration-sage) est "
        "journalisé ici, pas seulement les changements de statut."
    )
    ok, dossier = dossier_actuel()
    if not ok:
        st.info(dossier if isinstance(dossier, str) else "Créez d'abord un dossier (écran 1).")
        return
    if st.button("🔄 Rafraîchir"):
        st.rerun()
    afficher_audit_log(dossier["id"])


# --------------------------------------------------------------------------
# Navigation
# --------------------------------------------------------------------------

st.title("Exeiguard — Pilotage du pipeline paie A1 → A6")

onglets = st.tabs(
    [
        "1. Dépôt",
        "2. Suivi du pipeline",
        "3. Validation humaine",
        "4. Recherche RAG",
        "5. Journal d'audit",
    ]
)

with onglets[0]:
    ecran_depot()
with onglets[1]:
    ecran_pipeline()
with onglets[2]:
    ecran_validation_humaine()
with onglets[3]:
    ecran_rag()
with onglets[4]:
    ecran_audit()

# Rendue APRÈS les onglets (pas avant) : Streamlit exécute tout le script à
# chaque interaction, y compris le contenu de tous les onglets (leur
# visibilité est un simple toggle côté client). Si la barre latérale était
# rendue avant les onglets, elle refléterait l'état AVANT une action de
# cette même exécution (ex: juste après "Créer le dossier" sur l'écran 1) —
# bug réel observé en test manuel le 10/09 : la barre latérale affichait
# encore "Aucun dossier sélectionné" juste après la création réussie d'un
# dossier, alors que l'écran 2 affichait déjà le bon id.
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
        st.caption("Aucun dossier sélectionné — commencez par l'écran 1.")
    st.divider()
    st.caption(f"Orchestrateur : {ORCHESTRATEUR_URL}")
    st.caption(f"RAG : {RAG_URL}")
