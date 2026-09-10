# integration-sage

## Statut actuel : mock de démonstration, sans accès à l'API Sage réelle

Ce service expose aujourd'hui `POST /calculer`, qui **simule** le calcul
d'un bulletin de paie (`mock/calcul_simule.py`) : formule volontairement
factice et grossière (`net_a_payer = remuneration_mensuelle_brute * 0.78`,
cotisations à taux plats arbitraires), **sans aucune valeur
réglementaire**. Ce mock permet de valider le pipeline de bout en bout
(A1 → A6) sans accès à l'API Sage réelle : le format de sortie
(`BulletinSalaire`, `shared/schemas/bulletin.py`) est en revanche le même
que celui attendu de Sage, ce qui signifie que le câblage entre
l'orchestrateur et ce service n'aura pas à changer le jour où le mock est
remplacé par un vrai appel Sage — seul le contenu de `mock/calcul_simule.py`
sera remplacé par un client HTTP vers l'API Sage.

## Points d'intégration réels prévus côté Sage

Une fois l'accès à l'API Sage obtenu, `POST /calculer` de ce service
appellera vraisemblablement les endpoints Sage suivants (à confirmer avec
la documentation Sage/l'éditeur au moment de l'intégration) :

- **`POST /calcul-paie`** — soumettre les données d'un salarié pour une
  période donnée (contrat + variables de paie du mois) et déclencher le
  calcul du bulletin côté Sage.
- **`GET /bulletin/{id}`** — récupérer le bulletin calculé (le calcul
  Sage réel n'est probablement pas synchrone ; ce endpoint permettrait de
  poller/récupérer le résultat une fois prêt).
- **`GET /salarie/{matricule}`** (ou équivalent) — vérifier/synchroniser
  le référentiel salarié Sage avant calcul, pour détecter un écart entre
  le contrat connu d'Exeiguard et la fiche salarié Sage.

## Ce que ce mock prouve, et ce qu'il ne prouve pas

Prouve : que l'orchestrateur peut déclencher un appel HTTP réel à ce
service à la transition `calcul_termine` (A3→A4), recevoir un
`BulletinSalaire` structurellement valide, et le persister — le pipeline
complet A1→A6 peut donc être démontré de bout en bout dès aujourd'hui.

Ne prouve pas : la conformité réglementaire des montants produits (aucune
règle de cotisation réelle n'est appliquée), ni la compatibilité avec le
format d'échange Sage réel (celui-ci n'a pas encore été consulté).
