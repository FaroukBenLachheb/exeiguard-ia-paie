# docs/architecture/references/

Référentiels réglementaires officiels utilisés par le projet. À partir de
ce jour, **toute règle réglementaire du Rule Engine
(`compliance-validation/app/rule_engine/`) doit citer un article précis
d'un document de ce dossier**, jamais une référence générale.

## convention_collective_syntec.pdf

Convention collective nationale des bureaux d'études techniques, cabinets
d'ingénieurs-conseils et sociétés de conseils (IDCC 1486), convention du
15 décembre 1987, mise à jour par l'avenant n°46 du 16 juillet 2021.

Ce n'est **pas** une donnée personnelle de salarié (c'est un texte
réglementaire public), donc pas de restriction RGPD - il est commité
normalement dans ce dossier, contrairement à `data-confidentielles/` qui
n'est jamais versionné.

**Avertissement important** : ce PDF contient le **texte de base**
(Préambule et articles 1.1 à 13.6) mais **PAS les annexes I et II**
(grilles de classification complètes des coefficients ETAM et Cadres).
Confirmé par le glossaire du document lui-même, qui liste les annexes
comme des documents séparés du texte de base :
- Annexe I - Classification des employés, techniciens et agents de
  maîtrise (ETAM)
- Annexe II - Classification des ingénieurs et cadres

Les **bornes** de coefficients sont confirmées par le texte de base :
- ETAM : 240 à 500 (Article 2.1, composition des collèges électoraux du
  CSE : ouvriers/employés 240-250, techniciens 275-355, agents de
  maîtrise 400-500)
- Cadres : 95 à 270 (Article 3.4, période d'essai)

Mais le détail complet **position par position** utilisé par
`GRILLE_SYNTEC_CADRES`/`GRILLE_SYNTEC_ETAM`
(`shared/reference_data/grilles_syntec.py`) n'est **pas encore sourcé sur
ce document** (il vient d'autres sources vérifiées indépendamment,
salerya.fr et mapaye.fr) et reste à vérifier le jour où les Annexes I/II
seront disponibles.

## Utilisation dans le Rule Engine

Chaque règle `RG-XX` (`compliance-validation/app/rule_engine/rules/`)
doit citer, dans son docstring et dans le champ `source` de
`ResultatRegle`, l'article précis de ce document sur lequel elle repose
(ex : `"Article 3.4 de la CCN SYNTEC (IDCC 1486)"`), et non une référence
générale comme `"CCN SYNTEC"` seule. Si un article précis n'est pas
identifiable dans ce document pour une valeur donnée, la règle doit le
signaler explicitement (TODO en commentaire) plutôt que d'inventer un
chiffre.
