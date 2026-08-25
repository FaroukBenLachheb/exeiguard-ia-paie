"""
compliance-validation/app/rule_engine/rules/rg08_rtt.py

RG-08 - Nombre de jours RTT par an (accord d'entreprise Soft IT).

Source : accord d'entreprise Soft IT (cf.
scripts/generate_fixtures.py::ACCORD_SOFT_IT, rtt_par_an=10 ; voir aussi
structure_donnees_soft_it.md §5.2).

TODO : ce paramètre est en dur ici faute de fichier de configuration
externalisé (config/settings/ ne contient qu'un .gitkeep à ce stade,
aucun accord_entreprise_soft_it.yaml n'existe encore). A externaliser dès
que ce fichier existera, pour éviter que ce Rule Engine et
scripts/generate_fixtures.py ne dérivent chacun sur leur propre valeur.

Vérifié contre docs/architecture/references/convention_collective_syntec.pdf
(texte intégral, avenant n°46 du 16 juillet 2021) : aucun enrichissement
trouvé. L'Art. 6.1 renvoie à un accord de branche distinct (22 juin 1999,
modifié 1er avril 2014) pour l'aménagement du temps de travail sur
l'année, sans donner de nombre de jours RTT dans ce document - le
sourcing reste donc accord d'entreprise Soft IT seul.
"""

from shared.schemas import DossierSalarie

from .base import ResultatRegle

REGLE_ID = "RG-08"
SOURCE = "Accord d'entreprise Soft IT"

RTT_PAR_AN_SOFT_IT = 10  # TODO : externaliser (cf. docstring)


def evaluer(dossier: DossierSalarie) -> ResultatRegle:
    contrat = dossier.contrat
    conforme = contrat.rtt_par_an == RTT_PAR_AN_SOFT_IT

    if conforme:
        message = (
            f"rtt_par_an ({contrat.rtt_par_an}) conforme à l'accord Soft IT "
            f"({RTT_PAR_AN_SOFT_IT})."
        )
    else:
        message = (
            f"rtt_par_an ({contrat.rtt_par_an}) différent de l'accord Soft IT "
            f"({RTT_PAR_AN_SOFT_IT})."
        )

    return ResultatRegle(regle_id=REGLE_ID, conforme=conforme, message=message, source=SOURCE)
