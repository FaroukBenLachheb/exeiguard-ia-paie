"""
orchestrateur/app/main.py

API de l'Orchestrateur (Phase 3). Expose :
  POST /dossiers                    -> créer un dossier, état initial A1
  GET  /dossiers/{id}/etat          -> état courant + triggers disponibles
  POST /dossiers/{id}/transition    -> déclencher une transition

Chaque transition (réussie ou refusée) est journalisée dans audit_log —
c'est le principe directeur "traçabilité complète" du guide, appliqué au
niveau le plus bas du pipeline.

Point d'attention pour la Phase 9 (assemblage Docker) : ce service importe
directement les modèles SQLAlchemy du dossier top-level `db/`. En
conteneurisation, prévoir soit un contexte de build incluant `db/` dans
l'image orchestrateur, soit l'extraction de models.py/database.py dans un
package partagé (sur le même principe que shared/schemas). Pour le
développement local (D.3), l'import direct suffit.
"""

from __future__ import annotations

import base64
import binascii
import os
import sys
from pathlib import Path

# Rend db/models.py et db/database.py importables. Deux chemins candidats
# testés dans l'ordre : cas conteneur (WORKDIR /app, app/ et db/ copiés
# côte à côte -> /app/app/main.py, db/ à parents[1]) puis cas dépôt local
# (<repo>/orchestrateur/app/main.py, db/ à parents[2]). Bug corrigé le
# 26/08/2026 : la version initiale ne testait que parents[2], ce qui
# résolvait en "/db" (inexistant) dans le conteneur et faisait planter le
# service au démarrage (ModuleNotFoundError: No module named 'database').
_HERE = Path(__file__).resolve()
# Bug #2 corrigé le 26/08/2026 : "from state_machine import ..." / "from
# schemas import ..." ci-dessous sont des imports bare (pas relatifs), qui
# supposent que le répertoire contenant main.py lui-même est sur
# sys.path. Faux par défaut en conteneur (uvicorn app.main:app charge ce
# fichier comme sous-module du package "app" ; seul /app est sur
# sys.path, pas /app/app) -> ModuleNotFoundError: No module named
# 'state_machine'. Confirmé par exécution réelle du conteneur reconstruit.
sys.path.insert(0, str(_HERE.parent))
for _candidate in (_HERE.parents[1] / "db", _HERE.parents[2] / "db"):
    if _candidate.is_dir():
        sys.path.insert(0, str(_candidate))
        break

import httpx  # noqa: E402
from fastapi import FastAPI, HTTPException  # noqa: E402
from transitions import MachineError  # noqa: E402

from database import SessionLocal, init_db  # noqa: E402
from models import AuditLog, Bulletin, Controle, Dossier, EVPEnregistrement  # noqa: E402

from state_machine import DossierStateMachine  # noqa: E402
from schemas import (  # noqa: E402  (schémas API, distincts de db/models.py)
    CreationDossierRequest,
    DossierResponse,
    TransitionRequest,
    TransitionResponse,
)

app = FastAPI(title="Exeiguard - Orchestrateur", version="0.1.0")

# Noms d'hôtes = noms de service Docker Compose (docker-compose.dev.yml et
# docker-compose.yml), résolus via le réseau "exeiguard_net". Surchargeables
# par variable d'environnement pour les tests (cf. orchestrateur/tests/).
EXTRACTEUR_EVP_URL = os.getenv("EXTRACTEUR_EVP_URL", "http://extracteur-evp:8000")
COMPLIANCE_VALIDATION_URL = os.getenv("COMPLIANCE_VALIDATION_URL", "http://compliance-validation:8000")
INTEGRATION_SAGE_URL = os.getenv("INTEGRATION_SAGE_URL", "http://integration-sage:8000")
HTTP_TIMEOUT = float(os.getenv("ORCHESTRATEUR_HTTP_TIMEOUT", "10.0"))


@app.on_event("startup")
def _startup():
    init_db()


@app.get("/health")
def health():
    return {"status": "ok"}


def _audit(session, dossier_id: str, acteur: str, action: str, resultat: str, details: dict | None = None):
    session.add(
        AuditLog(
            dossier_id=dossier_id,
            acteur=acteur,
            action=action,
            resultat=resultat,
            details_json=details,
        )
    )
    session.commit()


def _dossier_salarie_payload(session, dossier: Dossier) -> dict:
    """Reconstruit le corps DossierSalarie (shared/schemas/dossier.py)
    attendu par compliance-validation et integration-sage, à partir de
    l'état actuellement connu en base pour ce dossier (contrat figé à la
    création + tout l'historique EVP/bulletins déjà stocké)."""
    evp_rows = (
        session.query(EVPEnregistrement)
        .filter_by(dossier_id=dossier.id)
        .order_by(EVPEnregistrement.created_at)
        .all()
    )
    bulletin_rows = (
        session.query(Bulletin).filter_by(dossier_id=dossier.id).order_by(Bulletin.created_at).all()
    )
    return {
        "matricule": dossier.matricule,
        "contrat": dossier.contrat_json,
        "evp_historique": [row.evp_json for row in evp_rows],
        "bulletins_historique": [row.bulletin_json for row in bulletin_rows],
    }


def _executer_extraction_evp(session, dossier: Dossier, payload: TransitionRequest) -> None:
    """Appel réel à extracteur-evp (POST /extraire) AVANT la transition
    A1->A2. Décode le fichier EVP .xlsx transmis en base64, le pousse en
    upload multipart (même contrat que la route, cf. extracteur-evp/app/
    main.py), puis persiste chaque ligne exploitable dans EVPEnregistrement.
    Toute erreur (base64 invalide, appel HTTP en échec, réponse non-200)
    lève une HTTPException qui empêche l'appelant de faire avancer l'état.

    Enchaîne ensuite sur le contrôle de conformité A2 (cf.
    _executer_controle_conformite) : le dossier doit ATTERRIR en A2 avec
    ses 10 résultats de règles déjà disponibles, pour que l'écran de
    décision humaine (A2) affiche un vrai récapitulatif AVANT que le
    gestionnaire ne clique quoi que ce soit — pas après. Corrigé le
    10/09/2026 : cet appel était auparavant rattaché à la transition
    "valider_transmission" (A2->A3), donc déclenché PAR la décision
    humaine au lieu d'être disponible AVANT elle (défaut trouvé lors du
    test UI réel)."""
    if not payload.evp_fichier_base64:
        raise HTTPException(
            status_code=400,
            detail="evp_fichier_base64 requis pour l'action 'extraire_evp' "
            "(contenu du fichier EVP .xlsx encodé en base64)",
        )
    try:
        contenu = base64.b64decode(payload.evp_fichier_base64, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(status_code=400, detail=f"evp_fichier_base64 invalide : {exc}") from None

    try:
        reponse = httpx.post(
            f"{EXTRACTEUR_EVP_URL}/extraire",
            files={
                "fichier": (
                    "evp.xlsx",
                    contenu,
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            },
            timeout=HTTP_TIMEOUT,
        )
    except httpx.HTTPError as exc:
        _audit(session, dossier.id, "orchestrateur", "appel_extracteur_evp", "echec", {"erreur": str(exc)})
        raise HTTPException(status_code=502, detail=f"Appel à extracteur-evp échoué : {exc}") from None

    if reponse.status_code != 200:
        _audit(
            session,
            dossier.id,
            "orchestrateur",
            "appel_extracteur_evp",
            "echec",
            {"status_code": reponse.status_code, "corps": reponse.text[:500]},
        )
        raise HTTPException(
            status_code=502,
            detail=f"extracteur-evp a répondu {reponse.status_code} : {reponse.text[:300]}",
        )

    corps = reponse.json()
    nb_lignes_stockees = 0
    for ligne in corps.get("lignes", []):
        if not ligne.get("evp"):
            continue  # ligne non exploitable (erreurs déjà tracées côté extracteur-evp), non stockée
        score = (ligne.get("score_confiance") or {}).get("valeur")
        session.add(
            EVPEnregistrement(
                dossier_id=dossier.id,
                evp_json=ligne["evp"],
                source_extraction="parsing_direct",
                score_confiance=score,
            )
        )
        nb_lignes_stockees += 1
    session.commit()

    _audit(
        session,
        dossier.id,
        "orchestrateur",
        "appel_extracteur_evp",
        "succes",
        {"nb_lignes_extraites": corps.get("nb_lignes"), "nb_lignes_stockees": nb_lignes_stockees},
    )

    # Contrôle de conformité A2 déclenché ICI (entrée en A2), pas à la
    # sortie : si compliance-validation échoue, toute la transition
    # extraire_evp est refusée (l'exception se propage), cohérent avec
    # "pas d'avancement silencieux sur un échec".
    _executer_controle_conformite(session, dossier, phase="A2")


def _executer_controle_conformite(session, dossier: Dossier, phase: str) -> None:
    """Appel réel à compliance-validation (POST /evaluer), utilisé aussi
    bien en A2 (pré-calcul, déclenché depuis _executer_extraction_evp) qu'en
    A4 (post-calcul, déclenché depuis _executer_calcul_sage — phase
    distinguée par l'argument `phase`). Persiste les 10 résultats dans
    Controle. Un écart de conformité ne bloque JAMAIS la transition (la
    décision finale reste humaine, cf. guide) : il est journalisé comme
    anomalie dans audit_log pour affichage côté UI.

    Volontairement PAS rattaché à valider_transmission/valider_bulletin :
    ces deux transitions sont des décisions humaines pures (aucun appel
    HTTP), le contrôle doit déjà être disponible en base quand l'écran de
    décision s'affiche, pas déclenché par le clic de décision lui-même."""
    corps_requete = _dossier_salarie_payload(session, dossier)
    try:
        reponse = httpx.post(f"{COMPLIANCE_VALIDATION_URL}/evaluer", json=corps_requete, timeout=HTTP_TIMEOUT)
    except httpx.HTTPError as exc:
        _audit(
            session,
            dossier.id,
            "orchestrateur",
            f"appel_compliance_validation:{phase}",
            "echec",
            {"erreur": str(exc)},
        )
        raise HTTPException(status_code=502, detail=f"Appel à compliance-validation échoué : {exc}") from None

    if reponse.status_code != 200:
        _audit(
            session,
            dossier.id,
            "orchestrateur",
            f"appel_compliance_validation:{phase}",
            "echec",
            {"status_code": reponse.status_code, "corps": reponse.text[:500]},
        )
        raise HTTPException(
            status_code=502,
            detail=f"compliance-validation a répondu {reponse.status_code} : {reponse.text[:300]}",
        )

    corps = reponse.json()
    resultats = corps.get("resultats", [])
    non_conformes = []
    for resultat in resultats:
        conforme = resultat.get("conforme")
        message = resultat.get("message") or ""
        citation = resultat.get("source")  # citation légale précise (RG-XX), pas le sous-système
        explication = f"{message} (source : {citation})" if citation else message
        session.add(
            Controle(
                dossier_id=dossier.id,
                phase=phase,
                regle_id=resultat.get("regle_id"),
                resultat="conforme" if conforme else "ecart",
                # explication est Text (sans limite arbitraire, cf. db/models.py
                # et migration 6e43748f892b) : aucune troncature ici, la
                # citation réglementaire complète doit être conservée.
                explication=explication,
                # Colonne source = sous-système ayant produit le résultat (cf.
                # db/models.py : "rule_engine"/"rag"/"delta_historique"), PAS
                # la citation légale (portée par `explication` ci-dessus).
                source="rule_engine",
            )
        )
        if not conforme:
            non_conformes.append(resultat)
    session.commit()

    _audit(
        session,
        dossier.id,
        "orchestrateur",
        f"appel_compliance_validation:{phase}",
        "succes",
        {"nb_regles": len(resultats), "nb_non_conformes": len(non_conformes)},
    )

    if non_conformes:
        _audit(
            session,
            dossier.id,
            "orchestrateur",
            f"anomalie_conformite:{phase}",
            "alerte",
            {
                "regles_non_conformes": [
                    {"regle_id": r.get("regle_id"), "message": r.get("message")} for r in non_conformes
                ]
            },
        )


def _executer_calcul_sage(session, dossier: Dossier) -> None:
    """Appel réel à integration-sage (POST /calculer, mock déterministe
    tant que l'API Sage réelle n'est pas accessible). Persiste le
    BulletinSalaire obtenu dans la table Bulletin, puis enchaîne sur le
    contrôle de conformité A4 (cf. _executer_controle_conformite) : le
    dossier doit ATTERRIR en A4 avec le bulletin ET ses 10 résultats
    post-calcul déjà disponibles, pour que l'écran de décision humaine
    (A4) affiche un vrai récapitulatif AVANT le clic, pas après."""
    corps_requete = _dossier_salarie_payload(session, dossier)
    try:
        reponse = httpx.post(f"{INTEGRATION_SAGE_URL}/calculer", json=corps_requete, timeout=HTTP_TIMEOUT)
    except httpx.HTTPError as exc:
        _audit(session, dossier.id, "orchestrateur", "appel_integration_sage", "echec", {"erreur": str(exc)})
        raise HTTPException(status_code=502, detail=f"Appel à integration-sage échoué : {exc}") from None

    if reponse.status_code != 200:
        _audit(
            session,
            dossier.id,
            "orchestrateur",
            "appel_integration_sage",
            "echec",
            {"status_code": reponse.status_code, "corps": reponse.text[:500]},
        )
        raise HTTPException(
            status_code=502,
            detail=f"integration-sage a répondu {reponse.status_code} : {reponse.text[:300]}",
        )

    bulletin_json = reponse.json()
    session.add(Bulletin(dossier_id=dossier.id, bulletin_json=bulletin_json))
    session.commit()

    _audit(
        session,
        dossier.id,
        "orchestrateur",
        "appel_integration_sage",
        "succes",
        {"net_a_payer": bulletin_json.get("net_a_payer")},
    )

    # Contrôle de conformité A4 déclenché ICI (entrée en A4), pas à la
    # sortie : cf. commentaire équivalent dans _executer_extraction_evp.
    # _dossier_salarie_payload relit la base après le commit ci-dessus,
    # donc bulletins_historique inclut déjà ce bulletin pour l'évaluation.
    _executer_controle_conformite(session, dossier, phase="A4")


# Actions de transition qui déclenchent un appel inter-service réel avant de
# faire avancer l'état. Le mapping ne prend que dossier/session/payload en
# entrée : action -> callable(session, dossier, payload).
#
# valider_transmission (A2->A3) et valider_bulletin (A4->A5) sont
# volontairement ABSENTES de ce mapping : ce sont des décisions humaines
# pures (aucun appel HTTP), cf. commentaires de _executer_controle_conformite.
_APPELS_PAR_ACTION = {
    "extraire_evp": lambda session, dossier, payload: _executer_extraction_evp(session, dossier, payload),
    "calcul_termine": lambda session, dossier, payload: _executer_calcul_sage(session, dossier),
}


@app.post("/dossiers", response_model=DossierResponse, status_code=201)
def creer_dossier(payload: CreationDossierRequest):
    session = SessionLocal()
    try:
        import datetime as dt

        periode_str = (payload.evp or {}).get("periode")
        periode = (
            dt.date.fromisoformat(periode_str)
            if periode_str
            else dt.date.today().replace(day=1)
        )

        dossier = Dossier(
            matricule=payload.matricule,
            prenom=payload.contrat.get("prenom", "inconnu"),
            nom=payload.contrat.get("nom"),
            periode=periode,
            etat="A1",
            contrat_json=payload.contrat,
        )
        session.add(dossier)
        session.commit()
        session.refresh(dossier)

        _audit(session, dossier.id, "orchestrateur", "creation_dossier", "succes")

        sm = DossierStateMachine(etat_initial=dossier.etat)
        return DossierResponse(
            id=dossier.id,
            matricule=dossier.matricule,
            prenom=dossier.prenom,
            etat=dossier.etat,
            triggers_disponibles=sm.triggers_disponibles(),
        )
    finally:
        session.close()


@app.get("/dossiers/{dossier_id}/etat", response_model=DossierResponse)
def obtenir_etat(dossier_id: str):
    session = SessionLocal()
    try:
        dossier = session.get(Dossier, dossier_id)
        if dossier is None:
            raise HTTPException(status_code=404, detail="Dossier introuvable")
        sm = DossierStateMachine(etat_initial=dossier.etat)
        return DossierResponse(
            id=dossier.id,
            matricule=dossier.matricule,
            prenom=dossier.prenom,
            etat=dossier.etat,
            triggers_disponibles=sm.triggers_disponibles(),
        )
    finally:
        session.close()


# --- Endpoints de lecture (JOUR 2, frontend) -------------------------------
# Aucun n'existait avant JOUR 2 : le frontend (frontend/app.py) a besoin de
# lire les résultats déjà persistés par les transitions (extraction EVP,
# contrôles de conformité, bulletin simulé, journal d'audit) sans les
# recalculer ni les simuler côté UI.


@app.get("/dossiers/{dossier_id}/evp")
def obtenir_evp(dossier_id: str):
    session = SessionLocal()
    try:
        if session.get(Dossier, dossier_id) is None:
            raise HTTPException(status_code=404, detail="Dossier introuvable")
        rows = (
            session.query(EVPEnregistrement)
            .filter_by(dossier_id=dossier_id)
            .order_by(EVPEnregistrement.created_at)
            .all()
        )
        return [
            {
                "id": r.id,
                "evp": r.evp_json,
                "source_extraction": r.source_extraction,
                "score_confiance": r.score_confiance,
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ]
    finally:
        session.close()


@app.get("/dossiers/{dossier_id}/controles")
def obtenir_controles(dossier_id: str, phase: str | None = None):
    session = SessionLocal()
    try:
        if session.get(Dossier, dossier_id) is None:
            raise HTTPException(status_code=404, detail="Dossier introuvable")
        query = session.query(Controle).filter_by(dossier_id=dossier_id)
        if phase:
            query = query.filter_by(phase=phase)
        rows = query.order_by(Controle.phase, Controle.regle_id).all()
        return [
            {
                "id": r.id,
                "phase": r.phase,
                "regle_id": r.regle_id,
                "resultat": r.resultat,
                "explication": r.explication,
                "source": r.source,
                "created_at": r.created_at.isoformat(),
            }
            for r in rows
        ]
    finally:
        session.close()


@app.get("/dossiers/{dossier_id}/bulletins")
def obtenir_bulletins(dossier_id: str):
    session = SessionLocal()
    try:
        if session.get(Dossier, dossier_id) is None:
            raise HTTPException(status_code=404, detail="Dossier introuvable")
        rows = session.query(Bulletin).filter_by(dossier_id=dossier_id).order_by(Bulletin.created_at).all()
        return [{"id": r.id, "bulletin": r.bulletin_json, "created_at": r.created_at.isoformat()} for r in rows]
    finally:
        session.close()


@app.get("/dossiers/{dossier_id}/audit")
def obtenir_audit(dossier_id: str):
    session = SessionLocal()
    try:
        if session.get(Dossier, dossier_id) is None:
            raise HTTPException(status_code=404, detail="Dossier introuvable")
        rows = (
            session.query(AuditLog)
            .filter_by(dossier_id=dossier_id)
            .order_by(AuditLog.horodatage)
            .all()
        )
        return [
            {
                "horodatage": r.horodatage.isoformat(),
                "acteur": r.acteur,
                "action": r.action,
                "resultat": r.resultat,
                "details": r.details_json,
            }
            for r in rows
        ]
    finally:
        session.close()


@app.post("/dossiers/{dossier_id}/transition", response_model=TransitionResponse)
def transitionner(dossier_id: str, payload: TransitionRequest):
    session = SessionLocal()
    try:
        dossier = session.get(Dossier, dossier_id)
        if dossier is None:
            raise HTTPException(status_code=404, detail="Dossier introuvable")

        etat_precedent = dossier.etat
        sm = DossierStateMachine(etat_initial=etat_precedent)

        # Légalité de la transition vérifiée AVANT tout appel inter-service :
        # inutile (et risqué) d'appeler extracteur-evp/compliance-validation/
        # integration-sage pour une transition qui sera de toute façon
        # refusée par la machine à états.
        if payload.action not in sm.triggers_disponibles():
            _audit(
                session,
                dossier_id,
                payload.acteur,
                f"transition_refusee:{payload.action}",
                "echec",
                {"raison": f"Action inconnue ou impossible depuis {etat_precedent}", "etat_courant": etat_precedent},
            )
            raise HTTPException(
                status_code=409,
                detail=f"Transition '{payload.action}' impossible depuis l'état {etat_precedent}",
            )

        # Appel réel au service concerné, AVANT de faire avancer l'état : si
        # l'appel échoue, la fonction lève une HTTPException et la
        # transition n'est jamais déclenchée (pas d'avancement silencieux
        # sur un échec).
        appel = _APPELS_PAR_ACTION.get(payload.action)
        if appel is not None:
            appel(session, dossier, payload)

        try:
            nouvel_etat = sm.declencher(payload.action)
        except MachineError as exc:
            _audit(
                session,
                dossier_id,
                payload.acteur,
                f"transition_refusee:{payload.action}",
                "echec",
                {"raison": str(exc), "etat_courant": etat_precedent},
            )
            raise HTTPException(
                status_code=409,
                detail=f"Transition '{payload.action}' impossible depuis l'état {etat_precedent}",
            )

        dossier.etat = nouvel_etat
        session.commit()

        _audit(
            session,
            dossier_id,
            payload.acteur,
            f"transition_etat:{etat_precedent}->{nouvel_etat}",
            "succes",
            {"action": payload.action, "commentaire": payload.commentaire},
        )

        sm2 = DossierStateMachine(etat_initial=nouvel_etat)
        return TransitionResponse(
            id=dossier_id,
            etat_precedent=etat_precedent,
            etat=nouvel_etat,
            triggers_disponibles=sm2.triggers_disponibles(),
        )
    finally:
        session.close()
