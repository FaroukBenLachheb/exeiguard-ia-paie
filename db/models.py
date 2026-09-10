"""
db/models.py

Modèles SQLAlchemy 2.0 pour les 5 tables du socle transactionnel
(Phase 2 du guide) : dossiers, evp, controles, decisions, audit_log.

Principe : ces tables ne réinventent pas les schémas Pydantic de
shared/schemas/ — elles les PERSISTENT. Les champs structurants
(matricule, période, phase, acteur...) sont des colonnes indexables ;
le detail complet de chaque objet (contrat, EVP, résultat de contrôle)
est stocké en JSON pour rester fidèle aux schémas Pydantic sans dupliquer
leur définition à deux endroits différents.

Portabilité : le type JSON générique de SQLAlchemy fonctionne aussi bien
sur SQLite (tests locaux, ce sandbox) que sur PostgreSQL (JSONB en prod/PoC
réel) sans changement de code. Un `Type Decorator` dédié pourra basculer
vers `postgresql.JSONB` explicitement une fois sur la VM si besoin de perf
sur les requêtes JSON.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    JSON,
    Date,
    DateTime,
    ForeignKey,
    String,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def _uuid() -> str:
    return str(uuid.uuid4())


class Dossier(Base):
    """
    Un dossier = un salarié suivi dans le pipeline A1->A6 pour une période
    donnée. Correspond au `DossierSalarie` de shared/schemas/dossier.py,
    mais ici centré sur l'état d'avancement dans la machine à états
    (Phase 3), pas sur l'historique complet (qui vit dans evp/controles).
    """

    __tablename__ = "dossiers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    matricule: Mapped[Optional[str]] = mapped_column(String(20), index=True, nullable=True)
    prenom: Mapped[str] = mapped_column(String(100))
    nom: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    periode: Mapped[date] = mapped_column(Date, index=True)

    # Etat courant de la machine à états A1->A6 (Phase 3)
    etat: Mapped[str] = mapped_column(String(20), default="A1", index=True)

    # Référentiel contractuel figé au moment du traitement (ContratTravail.model_dump())
    contrat_json: Mapped[dict] = mapped_column(JSON)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

    evp_entries: Mapped[list["EVPEnregistrement"]] = relationship(
        back_populates="dossier", cascade="all, delete-orphan"
    )
    controles: Mapped[list["Controle"]] = relationship(
        back_populates="dossier", cascade="all, delete-orphan"
    )
    bulletins: Mapped[list["Bulletin"]] = relationship(
        back_populates="dossier", cascade="all, delete-orphan"
    )
    decisions: Mapped[list["Decision"]] = relationship(
        back_populates="dossier", cascade="all, delete-orphan"
    )
    audit_entries: Mapped[list["AuditLog"]] = relationship(
        back_populates="dossier", cascade="all, delete-orphan"
    )


class EVPEnregistrement(Base):
    """Une ligne EVP reçue pour un dossier (correspond à EVPMensuel)."""

    __tablename__ = "evp"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    dossier_id: Mapped[str] = mapped_column(ForeignKey("dossiers.id"), index=True)

    evp_json: Mapped[dict] = mapped_column(JSON)  # EVPMensuel.model_dump()

    # Résultat de l'extraction (Phase 4) : parsing direct ou fallback LLM
    source_extraction: Mapped[str] = mapped_column(String(20), default="parsing_direct")
    score_confiance: Mapped[Optional[float]] = mapped_column(nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    dossier: Mapped["Dossier"] = relationship(back_populates="evp_entries")


class Controle(Base):
    """
    Un résultat du Moteur Compliance & Validation (Phase 6), qu'il soit
    invoqué en A2 (pré-calcul) ou A4 (post-calcul). C'est ici que la
    traçabilité "jamais une décision réglementaire portée par un LLM seul"
    se matérialise : `regle_id` pointe toujours vers le Rule Engine.
    """

    __tablename__ = "controles"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    dossier_id: Mapped[str] = mapped_column(ForeignKey("dossiers.id"), index=True)

    phase: Mapped[str] = mapped_column(String(10))  # "A2" ou "A4"
    regle_id: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)  # ex: "RG-03"
    resultat: Mapped[str] = mapped_column(String(20))  # "conforme" / "ecart" / "alerte"
    explication: Mapped[Optional[str]] = mapped_column(String(2000), nullable=True)
    source: Mapped[str] = mapped_column(String(20))  # "rule_engine" / "rag" / "delta_historique"

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    dossier: Mapped["Dossier"] = relationship(back_populates="controles")


class Bulletin(Base):
    """
    Un bulletin de paie calculé pour un dossier (Phase D.4+, JOUR 1 :
    calcul mock integration-sage, calcul Sage réel plus tard sans
    changement de schéma). Correspond à BulletinSalaire
    (shared/schemas/bulletin.py).
    """

    __tablename__ = "bulletins"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    dossier_id: Mapped[str] = mapped_column(ForeignKey("dossiers.id"), index=True)

    bulletin_json: Mapped[dict] = mapped_column(JSON)  # BulletinSalaire.model_dump()

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    dossier: Mapped["Dossier"] = relationship(back_populates="bulletins")


class Decision(Base):
    """Une décision humaine explicite (jamais automatique) prise sur un dossier."""

    __tablename__ = "decisions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    dossier_id: Mapped[str] = mapped_column(ForeignKey("dossiers.id"), index=True)

    acteur: Mapped[str] = mapped_column(String(100))  # ex: "gestionnaire", "responsable_validation"
    action: Mapped[str] = mapped_column(String(50))   # ex: "valider", "corriger", "rejeter"
    commentaire: Mapped[Optional[str]] = mapped_column(String(2000), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    dossier: Mapped["Dossier"] = relationship(back_populates="decisions")


class AuditLog(Base):
    """
    Trace immuable de CHAQUE événement du pipeline (principe directeur 3 du
    guide : traçabilité complète). Contrairement aux autres tables, celle-ci
    n'est jamais modifiée ni supprimée après écriture.
    """

    __tablename__ = "audit_log"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    dossier_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("dossiers.id"), index=True, nullable=True
    )

    horodatage: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), index=True)
    acteur: Mapped[str] = mapped_column(String(100))  # humain ("gestionnaire") ou système ("orchestrateur")
    action: Mapped[str] = mapped_column(String(100))  # ex: "transition_etat", "appel_llm_fallback"
    resultat: Mapped[str] = mapped_column(String(50))  # ex: "succes", "echec", "alerte"
    details_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)

    dossier: Mapped[Optional["Dossier"]] = relationship(back_populates="audit_entries")
