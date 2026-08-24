"""
shared/reference_data/grilles_syntec.py

Grilles de classification SYNTEC (CCN SYNTEC, IDCC 1486), utilisées pour
valider la cohérence position/coefficient d'un salarié selon son statut
(Cadre ou ETAM).

Déplacé depuis scripts/generate_fixtures.py : scripts/ n'est jamais copié
dans les images Docker des services applicatifs (voir
docs/architecture/dependances-partagees.md), alors que shared/ l'est
systématiquement. Un service comme compliance-validation qui a besoin de
ces grilles pour son Rule Engine doit les importer depuis shared/, pas
depuis scripts/.
"""

# Grille de classification SYNTEC - Ingénieurs et Cadres uniquement
# (positions 1.1 à 3.3, coefficients 95-270). Ne pas utiliser pour un
# salarié statut=ETAM, cf. grille séparée GRILLE_SYNTEC_ETAM.
GRILLE_SYNTEC_CADRES = {
    "1.1": 95,
    "1.2": 100,
    "2.1": 115,
    "2.2": 130,
    "2.3": 150,
    "3.1": 170,
    "3.2": 210,
    "3.3": 270,
}

# Grille de classification SYNTEC - ETAM uniquement (CCN SYNTEC, IDCC 1486,
# avenant classifications). Positions/coefficients distincts de la grille
# Ingénieurs et Cadres (GRILLE_SYNTEC_CADRES) : ne pas confondre les deux
# échelles, cf. bugs cas_06 et cas_18 (positions cadres appliquées à tort
# à des salariés ETAM). Dict volontairement limité aux entrées vérifiées
# via deux sources indépendantes (salerya.fr, mapaye.fr) ; ne pas
# compléter les échelons manquants sans la même vérification.
GRILLE_SYNTEC_ETAM = {
    "1.1": 240,
    "1.2": 250,
}
