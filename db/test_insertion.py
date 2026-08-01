"""
db/test_insertion.py

Valide le critère de la Phase 2 du guide :
"insertion/lecture de test réussie, audit_log capture bien horodatage +
acteur + action + résultat sur un événement fictif."

Utilise le cas réel "Didier" (cas_01_didier_reel.json) comme donnée
d'insertion, pour rester cohérent avec D.0/D.1.
"""

import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from database import SessionLocal, engine, init_db  # noqa: E402
from models import AuditLog, Dossier, EVPEnregistrement  # noqa: E402

FIXTURE = Path(__file__).parent.parent / "tests" / "fixtures" / "cas_01_didier_reel.json"


def main():
    init_db()
    session = SessionLocal()

    cas = json.loads(FIXTURE.read_text(encoding="utf-8"))
    contrat = cas["contrat"]
    evp = cas["evp"]

    # --- Insertion d'un dossier ---
    dossier = Dossier(
        matricule="0004",
        prenom=contrat["prenom"],
        nom=contrat.get("nom"),
        periode=date.fromisoformat(evp["periode"]),
        etat="A1",
        contrat_json=contrat,
    )
    session.add(dossier)
    session.commit()
    session.refresh(dossier)

    # --- Insertion de l'EVP associé ---
    evp_row = EVPEnregistrement(
        dossier_id=dossier.id,
        evp_json=evp,
        source_extraction="parsing_direct",
        score_confiance=0.97,
    )
    session.add(evp_row)

    # --- Insertion d'un événement d'audit fictif (transition A1 -> A2) ---
    audit = AuditLog(
        dossier_id=dossier.id,
        acteur="orchestrateur",
        action="transition_etat:A1->A2",
        resultat="succes",
        details_json={"regle_declenchee": "score_confiance>=0.75"},
    )
    session.add(audit)
    session.commit()

    # --- Lecture de vérification ---
    dossier_relu = session.get(Dossier, dossier.id)
    assert dossier_relu is not None, "Dossier introuvable après insertion"
    assert dossier_relu.prenom == "Didier"
    assert len(dossier_relu.evp_entries) == 1
    assert dossier_relu.evp_entries[0].evp_json["prenom"] == "Didier"

    audit_relu = (
        session.query(AuditLog).filter_by(dossier_id=dossier.id).one()
    )
    assert audit_relu.horodatage is not None, "horodatage manquant"
    assert audit_relu.acteur == "orchestrateur"
    assert audit_relu.action == "transition_etat:A1->A2"
    assert audit_relu.resultat == "succes"

    print("Insertion/lecture réussie.")
    print(f"  Dossier      : id={dossier_relu.id} prenom={dossier_relu.prenom} etat={dossier_relu.etat}")
    print(f"  EVP lié      : {len(dossier_relu.evp_entries)} entrée(s)")
    print(f"  Audit log    : horodatage={audit_relu.horodatage} "
          f"acteur={audit_relu.acteur} action={audit_relu.action} resultat={audit_relu.resultat}")

    session.close()


if __name__ == "__main__":
    main()
