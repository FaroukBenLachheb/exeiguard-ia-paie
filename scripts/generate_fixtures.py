"""
scripts/generate_fixtures.py

Génère le jeu de 10-15 cas de test du PoC (Phase 0 / D.1), en combinant :
- les 2 cas RÉELS déjà validés en D.0 (Didier, Sindhuja)
- des cas SYNTHÉTIQUES construits pour couvrir les scénarios volontaires
  attendus par le guide (absence, prime, cas conventionnel rare, heures
  sup, congé sans solde, absence injustifiée, PDF scanné dégradé...).

Chaque cas est validé via les schémas Pydantic de shared/schemas AVANT
d'être écrit sur disque : un cas qui ne passe pas la validation n'est
jamais exporté, ce qui garantit que tout ce qui atterrit dans
tests/fixtures/ et db/seeds/ est déjà conforme au contrat de données.

Sorties :
  tests/fixtures/cas_XX_<slug>.json   -> un fichier par cas (contrat + evp)
  db/seeds/seed_dossiers.json         -> agrégat de tous les cas

Usage :
    python scripts/generate_fixtures.py
    python scripts/generate_fixtures.py --nb-synthetiques 10 --seed 42
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

# Permet d'exécuter le script depuis la racine du projet sans installer
# le package shared/ en mode editable.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "shared"))

from faker import Faker  # noqa: E402  (import après sys.path.insert)
from pydantic import ValidationError  # noqa: E402

from schemas import (  # noqa: E402
    AbsencePeriode,
    ContratTravail,
    EVPMensuel,
    StatutSalarie,
    TypeAbsence,
    TypeContrat,
)

FIXTURES_DIR = ROOT / "tests" / "fixtures"
SEEDS_DIR = ROOT / "db" / "seeds"

# Grille de classification SYNTEC observée sur les contrats réels
# (position -> coefficient). A affiner si vous avez d'autres grades réels.
GRILLE_SYNTEC = {
    "1.1": 95,
    "1.2": 100,
    "2.1": 115,
    "2.2": 130,
    "2.3": 150,
    "3.1": 170,
    "3.2": 210,
    "3.3": 270,
}

# Paramètres de l'accord d'entreprise Soft IT (cf. structure_donnees_soft_it.md §5.2)
ACCORD_SOFT_IT = dict(
    rtt_par_an=10,
    periode_reference_conges="01/06 au 31/05",
    delai_justification_absence_heures=24,
    organisme_justification_absence="H Cube",
    indemnite_non_concurrence_mois_salaire=6,
    duree_non_concurrence_mois=12,
    duree_engagement_formation_mois=12,
)


def _contrat_de_base(**overrides) -> dict:
    base = dict(
        type_contrat="CDI",
        convention_collective="SYNTEC",
        statut=StatutSalarie.CADRE,
        heures_mensuelles=151.67,
        lieu_travail="au sein de la société ou en télétravail",
        clause_non_concurrence=True,
        clause_formation=False,
        **ACCORD_SOFT_IT,
    )
    base.update(overrides)
    return base


def cas_reels() -> list[dict]:
    """Les 2 cas réels déjà validés dans shared/tests/test_schemas.py."""
    return [
        {
            "id": "cas_01_didier_reel",
            "description": "Cas réel - nominal avec absence RTT, sans clause formation",
            "contrat": ContratTravail(
                **_contrat_de_base(
                    prenom="Didier",
                    nationalite="Française",
                    poste="Ingénieur Système Windows",
                    date_effet=date(2025, 7, 1),
                    position="2.2",
                    coefficient=130,
                    remuneration_annuelle_brute=53000,
                    remuneration_mensuelle_brute=4417,
                    periode_essai_mois=None,
                    duree_non_concurrence_mois=12,
                    date_signature=date(2025, 6, 30),
                    lieu_signature="Paris",
                )
            ).model_dump(mode="json"),
            "evp": EVPMensuel(
                periode=date(2026, 6, 1),
                prenom="Didier",
                poste="Administrateur Système",
                type_contrat=TypeContrat.CDI,
                debut_contrat=date(2025, 7, 1),
                salaire_an=53000,
                mutuelle="Seul",
                nb_ticket_restaurant=16,
                pass_navigo=False,
                absences=[
                    AbsencePeriode(type=TypeAbsence.RTT, nb_jours=2, dates_brutes="15 et 25/05")
                ],
            ).model_dump(mode="json"),
        },
        {
            "id": "cas_02_sindhuja_reel",
            "description": "Cas réel - période d'essai + clause formation + remarque libre (changement d'adresse)",
            "contrat": ContratTravail(
                **_contrat_de_base(
                    prenom="Sindhuja",
                    nationalite="Indienne",
                    poste="Consultante GRC",
                    date_effet=date(2025, 11, 3),
                    position="3.2",
                    coefficient=210,
                    remuneration_annuelle_brute=70000,
                    remuneration_mensuelle_brute=5833,
                    periode_essai_mois=4,
                    periode_essai_renouvelable=True,
                    clause_formation=True,
                    date_signature=date(2025, 10, 23),
                    lieu_signature="Paris",
                )
            ).model_dump(mode="json"),
            "evp": EVPMensuel(
                periode=date(2026, 6, 1),
                prenom="Sindhuja",
                poste="Consultante GRC",
                type_contrat=TypeContrat.CDI,
                debut_contrat=date(2025, 11, 3),
                salaire_an=70000,
                mutuelle="Avec enfants",
                nb_ticket_restaurant=16,
                pass_navigo=True,
                absences=[
                    AbsencePeriode(type=TypeAbsence.RTT, nb_jours=1, dates_brutes="07/05/2026"),
                    AbsencePeriode(type=TypeAbsence.RTT, nb_jours=1, dates_brutes="15/05/2026"),
                ],
                remarques="Changement d'adresse",
            ).model_dump(mode="json"),
        },
    ]


# ---------------------------------------------------------------------------
# Cas synthétiques : chacun couvre un scénario volontaire du guide (Phase 0)
# ---------------------------------------------------------------------------

def cas_synthetiques(fake: Faker) -> list[dict]:
    cas = []

    def ajoute(id_, description, contrat_kwargs, evp_kwargs):
        contrat = ContratTravail(**_contrat_de_base(**contrat_kwargs))
        evp = EVPMensuel(**evp_kwargs)
        cas.append(
            {
                "id": id_,
                "description": description,
                "contrat": contrat.model_dump(mode="json"),
                "evp": evp.model_dump(mode="json"),
            }
        )

    # --- Cas 03 : nominal simple, sans absence ---
    prenom = fake.first_name()
    ajoute(
        "cas_03_nominal_sans_absence",
        "Cas nominal - aucune absence, aucune clause particulière",
        dict(
            prenom=prenom,
            nationalite="Française",
            poste="Développeur Backend",
            date_effet=date(2025, 3, 1),
            position="2.1",
            coefficient=GRILLE_SYNTEC["2.1"],
            remuneration_annuelle_brute=42000,
            remuneration_mensuelle_brute=3500,
            periode_essai_mois=3,
            clause_non_concurrence=False,
            date_signature=date(2025, 2, 20),
            lieu_signature="Paris",
        ),
        dict(
            periode=date(2026, 6, 1),
            prenom=prenom,
            poste="Développeur Backend",
            type_contrat=TypeContrat.CDI,
            debut_contrat=date(2025, 3, 1),
            salaire_an=42000,
            mutuelle="Seul",
            nb_ticket_restaurant=16,
            pass_navigo=False,
        ),
    )

    # --- Cas 04 : prime exceptionnelle ---
    prenom = fake.first_name()
    ajoute(
        "cas_04_prime_exceptionnelle",
        "Cas avec prime exceptionnelle sur le mois",
        dict(
            prenom=prenom,
            nationalite="Française",
            poste="Chef de Projet",
            date_effet=date(2024, 9, 1),
            position="3.1",
            coefficient=GRILLE_SYNTEC["3.1"],
            remuneration_annuelle_brute=58000,
            remuneration_mensuelle_brute=4833.33,
            periode_essai_mois=None,
            date_signature=date(2024, 8, 20),
            lieu_signature="Paris",
        ),
        dict(
            periode=date(2026, 6, 1),
            prenom=prenom,
            poste="Chef de Projet",
            type_contrat=TypeContrat.CDI,
            debut_contrat=date(2024, 9, 1),
            salaire_an=58000,
            mutuelle="Avec conjoint",
            nb_ticket_restaurant=16,
            pass_navigo=True,
            prime=1500.0,
            remarques="Prime exceptionnelle - livraison projet client X",
        ),
    )

    # --- Cas 05 : congé maladie ---
    prenom = fake.first_name()
    ajoute(
        "cas_05_absence_maladie",
        "Cas avec absence maladie sur une partie du mois",
        dict(
            prenom=prenom,
            nationalite="Française",
            poste="Testeur QA",
            date_effet=date(2023, 6, 1),
            position="1.2",
            coefficient=GRILLE_SYNTEC["1.2"],
            remuneration_annuelle_brute=34000,
            remuneration_mensuelle_brute=2833.33,
            periode_essai_mois=None,
            date_signature=date(2023, 5, 20),
            lieu_signature="Paris",
        ),
        dict(
            periode=date(2026, 6, 1),
            prenom=prenom,
            poste="Testeur QA",
            type_contrat=TypeContrat.CDI,
            debut_contrat=date(2023, 6, 1),
            salaire_an=34000,
            mutuelle="Seul",
            nb_ticket_restaurant=10,
            pass_navigo=True,
            absences=[
                AbsencePeriode(
                    type=TypeAbsence.MALADIE, nb_jours=5, dates_brutes="10/06 au 14/06/2026"
                )
            ],
        ),
    )

    # --- Cas 06 : cas conventionnel rare - statut ETAM (non-cadre) ---
    prenom = fake.first_name()
    ajoute(
        "cas_06_etam_non_cadre",
        "Cas conventionnel rare - statut ETAM (non-cadre), grille SYNTEC différente",
        dict(
            prenom=prenom,
            nationalite="Française",
            poste="Assistant Administratif",
            date_effet=date(2025, 1, 6),
            statut=StatutSalarie.ETAM,
            position="1.1",
            coefficient=GRILLE_SYNTEC["1.1"],
            remuneration_annuelle_brute=28000,
            remuneration_mensuelle_brute=2333.33,
            periode_essai_mois=2,
            clause_non_concurrence=False,
            date_signature=date(2024, 12, 20),
            lieu_signature="Paris",
        ),
        dict(
            periode=date(2026, 6, 1),
            prenom=prenom,
            poste="Assistant Administratif",
            type_contrat=TypeContrat.CDI,
            debut_contrat=date(2025, 1, 6),
            salaire_an=28000,
            mutuelle="Seul",
            nb_ticket_restaurant=16,
            pass_navigo=True,
        ),
    )

    # --- Cas 07 : heures supplémentaires ---
    prenom = fake.first_name()
    ajoute(
        "cas_07_heures_sup",
        "Cas avec heures supplémentaires déclarées",
        dict(
            prenom=prenom,
            nationalite="Française",
            poste="Administrateur Réseau",
            date_effet=date(2024, 4, 1),
            position="2.2",
            coefficient=GRILLE_SYNTEC["2.2"],
            remuneration_annuelle_brute=45000,
            remuneration_mensuelle_brute=3750,
            periode_essai_mois=None,
            date_signature=date(2024, 3, 20),
            lieu_signature="Paris",
        ),
        dict(
            periode=date(2026, 6, 1),
            prenom=prenom,
            poste="Administrateur Réseau",
            type_contrat=TypeContrat.CDI,
            debut_contrat=date(2024, 4, 1),
            salaire_an=45000,
            mutuelle="Avec enfants",
            nb_ticket_restaurant=16,
            pass_navigo=False,
            heures_sup=8.0,
        ),
    )

    # --- Cas 08 : congé sans solde ---
    prenom = fake.first_name()
    ajoute(
        "cas_08_conge_sans_solde",
        "Cas avec congé sans solde",
        dict(
            prenom=prenom,
            nationalite="Française",
            poste="Consultant Fonctionnel",
            date_effet=date(2022, 9, 1),
            position="2.3",
            coefficient=GRILLE_SYNTEC["2.3"],
            remuneration_annuelle_brute=48000,
            remuneration_mensuelle_brute=4000,
            periode_essai_mois=None,
            date_signature=date(2022, 8, 20),
            lieu_signature="Paris",
        ),
        dict(
            periode=date(2026, 6, 1),
            prenom=prenom,
            poste="Consultant Fonctionnel",
            type_contrat=TypeContrat.CDI,
            debut_contrat=date(2022, 9, 1),
            salaire_an=48000,
            mutuelle="Seul",
            nb_ticket_restaurant=8,
            pass_navigo=True,
            absences=[
                AbsencePeriode(
                    type=TypeAbsence.CONGE_SANS_SOLDE,
                    nb_jours=10,
                    dates_brutes="01/06 au 10/06/2026",
                )
            ],
        ),
    )

    # --- Cas 09 : absence injustifiée (cas limite pour le Rule Engine) ---
    prenom = fake.first_name()
    ajoute(
        "cas_09_absence_injustifiee",
        "Cas limite - absence injustifiée, doit déclencher une alerte Compliance",
        dict(
            prenom=prenom,
            nationalite="Française",
            poste="Technicien Support",
            date_effet=date(2025, 5, 12),
            position="1.2",
            coefficient=GRILLE_SYNTEC["1.2"],
            remuneration_annuelle_brute=32000,
            remuneration_mensuelle_brute=2666.67,
            periode_essai_mois=2,
            date_signature=date(2025, 5, 1),
            lieu_signature="Paris",
        ),
        dict(
            periode=date(2026, 6, 1),
            prenom=prenom,
            poste="Technicien Support",
            type_contrat=TypeContrat.CDI,
            debut_contrat=date(2025, 5, 12),
            salaire_an=32000,
            mutuelle="Seul",
            nb_ticket_restaurant=16,
            pass_navigo=False,
            absences=[
                AbsencePeriode(
                    type=TypeAbsence.INJUSTIFIEE, nb_jours=1, dates_brutes="20/06/2026"
                )
            ],
        ),
    )

    # --- Cas 10 : acompte sur salaire ---
    prenom = fake.first_name()
    ajoute(
        "cas_10_acompte",
        "Cas avec acompte sur salaire demandé dans le mois",
        dict(
            prenom=prenom,
            nationalite="Française",
            poste="Ingénieur Cloud",
            date_effet=date(2023, 11, 1),
            position="2.2",
            coefficient=GRILLE_SYNTEC["2.2"],
            remuneration_annuelle_brute=50000,
            remuneration_mensuelle_brute=4166.67,
            periode_essai_mois=None,
            date_signature=date(2023, 10, 20),
            lieu_signature="Paris",
        ),
        dict(
            periode=date(2026, 6, 1),
            prenom=prenom,
            poste="Ingénieur Cloud",
            type_contrat=TypeContrat.CDI,
            debut_contrat=date(2023, 11, 1),
            salaire_an=50000,
            mutuelle="Avec famille",
            nb_ticket_restaurant=16,
            pass_navigo=True,
            acompte=800.0,
        ),
    )

    # --- Cas 11 : CDD (type de contrat différent, avec date de fin) ---
    prenom = fake.first_name()
    ajoute(
        "cas_11_cdd",
        "Cas CDD - type de contrat différent, avec date de fin renseignée",
        dict(
            prenom=prenom,
            nationalite="Française",
            poste="Développeur Frontend (remplacement)",
            date_effet=date(2026, 3, 1),
            type_contrat="CDD",
            position="1.2",
            coefficient=GRILLE_SYNTEC["1.2"],
            remuneration_annuelle_brute=36000,
            remuneration_mensuelle_brute=3000,
            periode_essai_mois=None,
            clause_non_concurrence=False,
            date_signature=date(2026, 2, 20),
            lieu_signature="Paris",
        ),
        dict(
            periode=date(2026, 6, 1),
            prenom=prenom,
            poste="Développeur Frontend (remplacement)",
            type_contrat=TypeContrat.CDD,
            debut_contrat=date(2026, 3, 1),
            fin_contrat=date(2026, 8, 31),
            salaire_an=36000,
            mutuelle="Seul",
            nb_ticket_restaurant=16,
            pass_navigo=False,
        ),
    )

    # --- Cas 12 : nouvel entrant, premier mois (pas d'historique) ---
    prenom = fake.first_name()
    ajoute(
        "cas_12_nouvel_entrant",
        "Cas limite - nouvel entrant, premier bulletin, pas d'historique disponible",
        dict(
            prenom=prenom,
            nationalite="Française",
            poste="Data Analyst",
            date_effet=date(2026, 6, 1),
            position="2.1",
            coefficient=GRILLE_SYNTEC["2.1"],
            remuneration_annuelle_brute=40000,
            remuneration_mensuelle_brute=3333.33,
            periode_essai_mois=3,
            date_signature=date(2026, 5, 20),
            lieu_signature="Paris",
        ),
        dict(
            periode=date(2026, 6, 1),
            prenom=prenom,
            poste="Data Analyst",
            type_contrat=TypeContrat.CDI,
            debut_contrat=date(2026, 6, 1),
            salaire_an=40000,
            mutuelle="Seul",
            nb_ticket_restaurant=16,
            pass_navigo=True,
        ),
    )

    return cas


# ---------------------------------------------------------------------------
# NOTE - cas non généré par ce script : "PDF scanné dégradé"
#
# Le guide (Phase 0/4) demande aussi un cas de PDF scanné volontairement
# dégradé pour tester l'OCR/fallback LLM de l'Extracteur EVP. Ce n'est pas
# une donnée structurée (donc hors périmètre Pydantic) : à préparer à part,
# par ex. en scannant/floutant un des contrats PDF réels fournis, et en le
# déposant dans tests/fixtures/cas_13_pdf_degrade.pdf lors de la Phase 4.
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=42, help="Graine aléatoire (reproductibilité)")
    args = parser.parse_args()

    fake = Faker("fr_FR")
    Faker.seed(args.seed)

    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
    SEEDS_DIR.mkdir(parents=True, exist_ok=True)

    tous_les_cas = []
    erreurs = []

    for cas in cas_reels() + cas_synthetiques(fake):
        tous_les_cas.append(cas)

    for cas in tous_les_cas:
        chemin = FIXTURES_DIR / f"{cas['id']}.json"
        chemin.write_text(json.dumps(cas, indent=2, ensure_ascii=False), encoding="utf-8")

    seed_path = SEEDS_DIR / "seed_dossiers.json"
    seed_path.write_text(
        json.dumps(tous_les_cas, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    print(f"{len(tous_les_cas)} cas générés et validés avec succès.")
    print(f"  -> {FIXTURES_DIR} (un fichier par cas)")
    print(f"  -> {seed_path} (agrégat)")
    if erreurs:
        print(f"\n{len(erreurs)} cas rejetés par la validation Pydantic :")
        for e in erreurs:
            print(f"  - {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
