# État technique du projet ExeiGuard IA Paie — réunion du 26/08/2026

Document préparé le 25/08/2026 sur la VM cible (VM OVH, GPU NVIDIA A10, Ollama natif + conteneurs Docker). **Tout ce qui suit a été vérifié en exécutant réellement les commandes indiquées à cet instant** — aucune commande "censée marcher" n'est présentée sans son résultat réel. Quand un résultat diffère de ce qu'on pourrait attendre (échec, fonctionnalité absente, environnement à relancer), c'est dit explicitement plutôt que masqué.

**Version régénérée le 25/08/2026 en fin de journée**, après la découverte (racontée en Partie 2) que l'orchestrateur ne contenait en réalité qu'un placeholder `/health` malgré des validations antérieures qui le décrivaient comme fonctionnel. La machine à états A1→A6 a depuis été récupérée, intégrée et corrigée (commit `791747c`), puis un healthcheck manquant a été ajouté (commit `3244584`). Toute la Partie 3 a été rejouée intégralement à partir de zéro pour cette version — y compris les 5 composants qui n'avaient pas changé — plutôt que de recopier les résultats de la version précédente.

Méthodologie de vérification : un environnement virtuel Python dédié a été recréé dans le scratchpad de la session (`shared/requirements.txt` + `compliance-validation/requirements.txt` + `extracteur-evp/requirements.txt` + `orchestrateur/requirements.txt`) pour exécuter les tests hors conteneur ; les conteneurs `postgres` et `orchestrateur` tournaient déjà (`docker compose -f docker-compose.dev.yml ps` — voir Partie 3, point 3, pour le détail) ; `qdrant` et le service `rag` (lancé directement via `python -m uvicorn`, hors Docker — voir Partie 1) tournaient également déjà sur la VM.

---

## Partie 1 — Arborescence du projet, dossier par dossier

Racine du dépôt (fichiers significatifs hors dossiers) : `README.md`, `.env` / `.env.example`, `.dockerignore`, `docker-compose.dev.yml` (stack de dev locale), `docker-compose.yml` (stack VM cible — `llm-server` + `qdrant`, GPU actif), `pytest.ini` (`--import-mode=importlib`, nécessaire — voir Partie 3, point de vigilance).

### `shared/` — le contrat de données commun (fondation de tous les composants)

Rôle architecture : socle transverse consommé par **Orchestrateur, Extracteur EVP, Rule Engine (Compliance & Validation), RAG** — chacun importe ces modèles plutôt que d'en redéfinir des équivalents locaux.

- `shared/schemas/evp.py` — `EVPMensuel` (une ligne EVP = un salarié pour un mois) + `AbsencePeriode`. Deux validateurs Pydantic durs : un CDI ne peut pas avoir de date de fin ; une ligne doit porter au moins un identifiant exploitable (matricule OU nom/prénom).
- `shared/schemas/contrat.py` — `ContratTravail` (référentiel contractuel statique). Porte la tolérance de 2€ sur la cohérence rémunération annuelle/mensuelle (justifiée par un écart réel de 1,33€ observé sur le contrat de Karim).
- `shared/schemas/bulletin.py` — `BulletinSalaire` + `LigneCotisation`, sans liste de lignes figée (certaines lignes de bulletin sont conditionnelles, ex. Pass Navigo).
- `shared/schemas/dossier.py` — `DossierSalarie`, le modèle pivot (contrat + historiques EVP/bulletins), point d'entrée documenté des deux invocations du Moteur Compliance & Validation (A2 pré-calcul, A4 post-calcul).
- `shared/schemas/rupture.py` — `RuptureContrat` (type de rupture, dates de notification/fin effective), ajouté pour alimenter RG-04/06/07.
- `shared/schemas/__init__.py` — réexporte les classes ci-dessus.
- `shared/reference_data/grilles_syntec.py` — `GRILLE_SYNTEC_CADRES` / `GRILLE_SYNTEC_ETAM` (grilles position→coefficient), déplacées ici depuis `scripts/` car `scripts/` n'est jamais copié dans les images Docker.
- `shared/tests/test_schemas.py` — **11 tests** (9 dans la version onboarding, +2 avec `RuptureContrat`) sur données réelles (Didier, Sindhuja) + rejets attendus.
- `shared/requirements.txt`.

### `db/` — le socle transactionnel

Rôle : persistance PostgreSQL des dossiers en cours de traitement.

- `db/database.py` — `engine`/`SessionLocal` (SQLAlchemy), `init_db()`.
- `db/models.py` — 5 tables : `Dossier`, `EVPEnregistrement`, `Controle`, `Decision`, `AuditLog`.
- `db/alembic.ini`, `db/migrations/env.py`, `db/migrations/script.py.mako`, `db/migrations/versions/bcb3dbf7d6d9_initial_schema.py` (migration initiale, seule existante).
- `db/seeds/seed_dossiers.json` — généré par `scripts/generate_fixtures.py`.
- `db/test_insertion.py` — insertion/lecture bout en bout (dossier + EVP + audit_log), exécutable en script ou en test pytest.

### `orchestrateur/` — le service pivot du pipeline (Orchestrateur)

Rôle cible : piloter la machine à états A1→A6. **État réel aujourd'hui : fonctionnel et vérifié** (voir Partie 2 pour la découverte du 26/08 et le correctif, et Partie 3 point 3 pour la vérification en direct).

- `app/main.py` — initialise la base au démarrage (`init_db()` via `@app.on_event("startup")`), et expose désormais les vraies routes métier : `POST /dossiers`, `GET /dossiers/{id}/etat`, `POST /dossiers/{id}/transition`, en plus de `GET /health` (ajouté en dernier, commit `3244584`, healthcheck Docker à nouveau vert). Chaque transition (réussie ou refusée en 409) est journalisée dans `audit_log`.
- `app/state_machine.py` — `DossierStateMachine`, machine à états `transitions` sur 11 états (A1, A2, A2_3, A3, A3_3, A4, A4_3, A5, A6, TERMINE, REJETE) et 14 transitions nommées, dont les 3 boucles de retour A2.3/A3.3/A4.3 déclarées comme de vraies transitions (pas des cas particuliers codés à côté).
- `app/schemas.py` — schémas API Pydantic (`CreationDossierRequest`, `DossierResponse`, `TransitionRequest`, `TransitionResponse`), nommé volontairement à part de `db/models.py` pour éviter toute collision d'import.
- `app/api/` — squelette vide (`__init__.py` seul) : les routes vivent directement dans `main.py`, même pattern que `rag/`.
- `tests/test_e2e_a1_a6.py` — **3 tests** via `TestClient` (appels HTTP réels sur l'app FastAPI, pas des appels Python directs), sur le cas réel Didier : parcours nominal complet A1→TERMINE avec vérification des 7 entrées `audit_log`, transition invalide rejetée en 409 et journalisée, boucle A2.3→A1.
- `Dockerfile`, `requirements.txt`.

### `extracteur-evp/` — extraction des documents salariés (Extracteur EVP)

Rôle cible : extraire les données structurées des EVP (Excel), contrats et bulletins (PDF/OCR). **Seul le parsing Excel EVP est fonctionnel.**

- `app/parsers/excel_parser.py` — fichier le plus dense du dépôt. `parse_evp_file(path)` retourne des `ParsedEVPLigne`. Détecte les blocs d'absence (CP/RTT/MALADIE/...) par le **libellé** de l'en-tête groupée, jamais par position de colonne fixe (commit `e637a4d`, suite à la découverte d'une confusion CP/RTT dans les fixtures — voir Partie 2).
- `app/confidence_scoring.py` — `score_ligne_evp()` : score 0–1 par ligne, pénalise les remarques suspectes en texte libre (ex. "Prime Astreintes : 450 €") et les incohérences salaire/contrat.
- `app/ocr/` — vide (`__init__.py` seul) : aucun parsing PDF/OCR à ce jour.
- `app/main.py` — squelette `GET /health` uniquement ; `excel_parser.py`/`confidence_scoring.py` ne sont pas encore branchés sur une route API.
- `tests/test_excel_parser.py` + `tests/conftest.py` — **16 tests**, classeurs Excel synthétiques en mémoire (jamais les fichiers réels), incluant 3 tests de généralisation de la détection des blocs d'absence.
- `Dockerfile`, `requirements.txt`.

### `compliance-validation/` — Rule Engine + RAG (Compliance & Validation)

Rôle cible : exécuter les règles de conformité (Rule Engine) et le RAG réglementaire (A2 pré-calcul / A4 post-calcul). **Le Rule Engine est complet et testé, mais n'est pas encore exposé en API.**

- `app/rule_engine/engine.py` — `evaluer_toutes_les_regles(dossier)` : exécute les 10 règles indépendamment (une règle qui échoue n'interrompt pas les autres).
- `app/rule_engine/rules/base.py` — `ResultatRegle` (regle_id, conforme, message, source).
- `app/rule_engine/rules/rg01_heures_mensuelles.py` à `rg10_coherence_contrat.py` — 10 règles, chacune sourcée sur un article précis de la CCN SYNTEC (`docs/architecture/references/convention_collective_syntec.pdf`) ou un accord d'entreprise Soft IT explicite :
  - **RG-01** cohérence heures hebdo/mensuelles (Code du travail L3121-27) · **RG-02** cohérence rémunération mensuelle/annuelle (Article 7.1 CCN SYNTEC) · **RG-03** cohérence position/coefficient (Article 7.2, grilles SYNTEC) · **RG-04** durée période d'essai (Article 3.4) · **RG-05** contrepartie non-concurrence (jurisprudence Cass. soc. + accord Soft IT) · **RG-06** durée de préavis (Article 4.2) · **RG-07** congés d'ancienneté, informative (Article 5.1 point 2) · **RG-08** RTT (accord Soft IT) · **RG-09** délai/organisme de justification d'absence (Article 9.1 + accord Soft IT) · **RG-10** cohérence contrat/dossier (Code du travail L1221-2 + Article 7.4).
- `app/api/` — squelette vide.
- `app/main.py` — squelette `GET /health` uniquement (le Rule Engine tourne aujourd'hui via les tests/scripts Python, pas via une route HTTP — voir Partie 3, point 5).
- `tests/test_rule_engine.py` — **28 tests** sur les 29 cas de `tests/fixtures/`, avec une analyse de couverture documentée branche par branche en fin de fichier.
- `tests/conftest.py`, `Dockerfile`, `requirements.txt`.

### `integration-sage/` — coquille en attente (Intégration Sage)

Rôle cible : interfacer avec Sage (mock en PoC, réel ensuite). **Rien d'implémenté au-delà du squelette.**

- `app/main.py` — `GET /health` uniquement.
- `app/api/` — squelette vide.
- `mock/` — **VIDE** (`.gitkeep`) : le mock Sage n'est pas écrit.
- `tests/` — **VIDE** (`__init__.py` seul, aucun test).
- `Dockerfile`, `requirements.txt`.

### `rag/` — recherche sémantique sur la CCN SYNTEC (RAG)

Rôle cible : RAG réglementaire consommé par Compliance & Validation. **Sprint réalisé le 25/08 (commit `20eac05`) : l'endpoint de recherche fonctionne, mais le périmètre est volontairement réduit.**

- `app/main.py` — `POST /rag/query {"question": ...}` : recherche les 3 passages les plus proches dans Qdrant (collection `syntec_convention`) et les retourne avec leur référence d'article exacte. Bonus optionnel `?synthese=true` (appel LLM Ollama qwen2.5:14b), volontairement non prioritaire.
- `app/config.py` — configuration Ollama/Qdrant ; sur cette VM, le service tourne **en Python natif sur l'hôte** (pas de Dockerfile réel), donc `OLLAMA_HOST`/`QDRANT_HOST` sont surchargés en `localhost`.
- `app/embeddings.py` — client `POST /api/embeddings` vers Ollama (modèle `nomic-embed-text`).
- `app/ingestion/chunking.py` — découpe le PDF de la CCN SYNTEC en un chunk par article (regex sur `"Article X.X — Titre"`, distinct du format abrégé du sommaire), avec suivi de la page d'origine.
- `app/ingestion/ingest.py` — script manuel d'indexation : génère un embedding par chunk, upsert dans Qdrant.
- `app/api/` — squelette vide, non utilisé (les routes vivent directement dans `main.py`).
- `corpus/` — **VIDE** (`.gitkeep`) : le corpus réellement utilisé est `docs/architecture/references/convention_collective_syntec.pdf`, pas ce dossier.
- `tests/` — **VIDE** (`__init__.py` seul) : **aucun test automatisé pytest pour le RAG à ce jour** — la vérification se fait par appels manuels (voir Partie 3, point 6).
- `Dockerfile` — **placeholder, pas de contenu réel** ("Contenu à définir phase par phase") : le service ne tourne pas en conteneur sur cette VM.
- `requirements.txt`, `.venv/` (environnement local non versionné, utilisé pour lancer le service).

### `scripts/` — outils de génération de données

- `generate_fixtures.py` — génère les 29 cas de `tests/fixtures/` et `db/seeds/seed_dossiers.json` (5 cas réels + 24 synthétiques), chaque cas validé par les schémas Pydantic avant export.

### `tests/` — fixtures et emplacements transverses

- `fixtures/` — **29 fichiers JSON** (`cas_01_didier_reel.json` à `cas_29_delai_justification_non_conforme.json`), conformes aux schémas Pydantic.
- `integration/` — **VIDE** (`.gitkeep`).
- `e2e/` — **VIDE** (`.gitkeep`).

### `docs/` — documentation

- `architecture/onboarding-technique.md` — document d'onboarding détaillé (rédigé autour de D.4/D.5, donc partiellement daté).
- `architecture/etat_technique_20260826.md` — le présent document, mis à jour au fil des découvertes (voir Partie 2).
- `architecture/dependances-partagees.md` — pattern Docker pour consommer `shared/`/`db/` depuis un nouveau service.
- `architecture/references/convention_collective_syntec.pdf` — CCN SYNTEC (IDCC 1486), texte de base réglementaire, source de toutes les règles RG-0X qui la citent.
- `architecture/references/README.md` — avertissement explicite : ce PDF ne contient **pas** les Annexes I/II (grilles de classification complètes) ; les grilles utilisées par RG-03 restent sourcées ailleurs (salerya.fr, mapaye.fr), à vérifier le jour où les annexes seront disponibles.
- `kpi/`, `poc-report/`, `risques/` — **VIDES** (`.gitkeep`), réservés, pas encore attaqués.

### `config/` — configuration d'infrastructure future

- `logging/`, `settings/`, `traefik/` — **tous VIDES** (`.gitkeep`). `traefik/` est réservé pour la Phase 9 (reverse proxy, seul point d'exposition publique prévu) ; rien n'existe encore.

### `llm/` — service LLM (Ollama)

- `README.md` — documente la décision Ollama vs vLLM (vLLM écarté), les deux modèles utilisés (`mistral:7b-instruct-q4_K_M` fallback extraction, `qwen2.5:14b-instruct-q4_K_M` compliance/RAG).
- `modelfiles/` — **VIDE** (`.gitkeep`) : les modèles utilisés sont les modèles Ollama standard, aucun Modelfile personnalisé écrit à ce jour.

### `vector_db/` — base vectorielle

- `qdrant-config/` — **VIDE** (`.gitkeep`) : Qdrant tourne avec sa configuration par défaut (image `qdrant/qdrant:latest`), aucune configuration personnalisée committée.

### `frontend/` — **VIDE, phase non attaquée**

- `public/`, `src/` — tous deux **VIDES** (`.gitkeep`). Aucune ligne de frontend écrite à ce jour ; composant non représenté dans l'architecture de référence listée pour cette réunion (Orchestrateur/Extracteur EVP/Rule Engine/RAG/Compliance & Validation/Intégration Sage), cohérent avec le fait que ce n'est pas encore une phase engagée.

### `.claude/`

- `settings.local.json` — configuration d'outillage (assistant de développement), hors périmètre applicatif.

**Récapitulatif des dossiers vides à ce jour (squelette non encore attaqué, pas un oubli) :** `config/logging/`, `config/settings/`, `config/traefik/`, `docs/kpi/`, `docs/poc-report/`, `docs/risques/`, `frontend/public/`, `frontend/src/`, `integration-sage/mock/`, `llm/modelfiles/`, `rag/corpus/`, `tests/e2e/`, `tests/integration/`, `vector_db/qdrant-config/` — plus les squelettes de package réduits à un `__init__.py` : `orchestrateur/app/api/` (l'orchestrateur, lui, n'est plus dans cette liste : `tests/` y contient désormais 3 tests réels), `integration-sage/app/api/`, `integration-sage/tests/`, `compliance-validation/app/api/`, `rag/app/api/`, `rag/tests/`, `extracteur-evp/app/ocr/`.

---

## Partie 2 — Chronologie de la démarche suivie

Reconstruite depuis `git log --oneline --all` (ordre chronologique), à partir du commit `1978521` ("chore: squelette initial du projet").

### D.0 — Contrat de données (`4618ec6`)
Écriture des schémas Pydantic (`EVPMensuel`, `ContratTravail`, `BulletinSalaire`, `DossierSalarie`) **avant tout code applicatif**, validés directement sur les deux premiers documents réels Soft IT (Didier, Sindhuja). Objectif : que chaque service développé ensuite parte d'un contrat de données déjà éprouvé sur du réel plutôt que d'une hypothèse.

### D.1 — Fixtures (`032d0ff`, `3b0ef52`, `3afe2b0`)
Générateur de cas de test (`scripts/generate_fixtures.py`) : d'abord 2 cas réels + 10 synthétiques, puis extension à 5 cas réels (ajout de Jordan, Julien, Karim, avec deux anomalies réelles précieuses documentées : incohérence heures contrat/bulletin, coefficient manquant sur bulletin). **Itération notable** : le contrat réel de Karim portait un écart de 1,33€ entre `remuneration_annuelle_brute/12` et `remuneration_mensuelle_brute` (arrondi Soft IT) — plutôt que de modifier la donnée réelle pour satisfaire le validateur, la tolérance du validateur a été portée de 1€ à 2€, avec le cas réel cité en commentaire comme justification (`3afe2b0`).

### D.2 — Socle PostgreSQL (`2722e43`)
5 tables SQLAlchemy, migration Alembic initiale, test d'insertion/lecture bout en bout avec vérification explicite de l'audit log (horodatage, acteur, action, résultat).

### Conteneurisation puis adaptation GPU/Ollama (`adee48e`, `8168473`)
D'abord Dockerfiles + healthchecks squelettes pour les 4 services, en préparation du déploiement sur la VM cible. **Itération** : le plan initial (`llama.cpp` CPU-only) a été abandonné au profit d'Ollama suite à un changement de cible d'infrastructure (VM OVH avec GPU) ; vLLM a été explicitement écarté (endpoint compatible OpenAI plus simple à opérer pour deux modèles avec chargement à la demande).

### D.4 — Extracteur EVP (`11bb025`, `b76ea79`, `e637a4d`)
Parser Excel EVP + score de confiance, validé sur les fichiers réels (hors dépôt, non versionnés) et testé sur fixtures synthétiques. **Itération notable et documentée dans la consigne** : la validation croisée entre les fixtures transcrites à la main (D.1) et le parser automatisé (D.4) a révélé une **erreur de classification CP/RTT** dans `cas_01`/`cas_02` — corrigée en `b76ea79`. Cause racine traitée ensuite en `e637a4d` : le parser détectait initialement les blocs d'absence par **position de colonne fixe**, ce qui est fragile ; passage à une détection par **libellé de l'en-tête groupée**, avec ajout de tests adversariaux ("généralisation") qui font varier ordre/position/présence des blocs pour prouver que le parser ne mémorise pas la disposition du fichier de test actuel.

### Correctifs d'infrastructure partagée (`312423f`, `0af3508`)
L'exécution complète de la suite de tests a révélé des dépendances manquantes (corrigées en `312423f`). Puis découverte que **`shared/` n'était pas copié dans les Dockerfiles** des 4 services applicatifs — corrigé une fois pour toutes (`0af3508`) plutôt que découvert service par service au moment d'écrire Compliance & Validation, Intégration Sage ou RAG (`shared/schemas` étant importé par les quatre).

### Documentation d'onboarding (`4eef10f`)
Document technique pour l'équipe, formalisant l'état du dépôt à ce stade (D.0 à D.4).

### Itérations sur l'exposition réseau (`bf786e7`, `bde2a93`, `d7333c7`, `f11c00a`, `9a69ddb`)
**Le port PostgreSQL était initialement publié publiquement** (`5432:5432` dans `docker-compose.dev.yml`) — corrigé en `bf786e7` (passage à un port éphémère non prévisible), puis en `bde2a93` (passage de `ports` à `expose` pour Postgres, extracteur-evp et compliance-validation : plus aucune exposition, même éphémère, hors réseau interne Docker). Seul l'orchestrateur restait publié sur `8000` pour le développement actif sur la VM ; ce caractère temporaire a été documenté explicitement en commentaire (`d7333c7`). Deux allers-retours supplémentaires (`f11c00a`, `9a69ddb`) ont fait osciller ce port entre `expose` et `ports` avant de se stabiliser sur `ports: 8000:8000` (état actuel, confirmé en Partie 3).

### D.5 — Rule Engine (`1c9b2f1`, `7db3e19`, `edd620e`, `3a355fc`, `5e7cf02`, `edbd9f6`, `ebaabe3`, `f42ee1e`)
1. **Extension du schéma** : ajout de `RuptureContrat` + 5 fixtures couvrant RG-04/RG-06/RG-07 (`1c9b2f1`), dont des cas volontairement non conformes pour tester la détection de violation, pas seulement la confirmation.
2. **Bug de grille SYNTEC découvert et corrigé** : `cas_18` puis `cas_06` portaient une position ETAM (`2.3` puis `1.1`) qui appartenait en réalité à la grille Cadres, pas à la grille ETAM (`7db3e19`, `edd620e`) — confirmé par un audit dédié qui a établi que seuls ces deux cas étaient concernés. **Cause racine traitée** : séparation de `GRILLE_SYNTEC` en `GRILLE_SYNTEC_CADRES` et `GRILLE_SYNTEC_ETAM` distinctes (`3a355fc`), pour empêcher toute récidive sur un futur cas ETAM.
3. **Problème d'emplacement Docker, même famille que `shared/`** : les grilles vivaient dans `scripts/`, qui n'est jamais copié dans les images Docker — déplacées vers `shared/reference_data/` avant même d'écrire le conteneur `compliance-validation` (`5e7cf02`), pour éviter un crash au démarrage déjà anticipé plutôt que découvert en prod.
4. **Rule Engine complet** : RG-01 à RG-10 (`edbd9f6`), testé sur les 20 cas de fixtures alors disponibles, avec analyse de couverture. Puis sourcing enrichi sur le texte intégral de la CCN SYNTEC réelle (`ebaabe3`) : chaque règle cite désormais un article précis plutôt qu'une référence générale à "la CCN SYNTEC", conformément à la consigne de `docs/architecture/references/README.md`.
5. **Test de généralisation du Rule Engine** (préparation de `f42ee1e`) : après avoir écrit les 10 règles, un test manuel a été construit avec un **profil ETAM au coefficient 400** — une valeur **absente de toutes les fixtures existantes** (qui utilisaient 245, 300 puis 450). L'objectif : prouver que RG-03/RG-04/RG-06 reposent sur une **logique de bornes/plages** (ex. RG-06 : `coefficient in (400, 450, 500)` déclenche un préavis fixe de 2 mois "quelle que soit l'ancienneté", indépendamment de toute valeur observée en fixture) et non sur une correspondance figée aux seuls cas déjà vus. Ce test a mis en évidence des trous de couverture réels (branches jamais exercées par aucune fixture : RG-06 ETAM <2 ans à coefficient élevé, RG-07 palier 15 ans, RG-08/RG-09 non conformes) — comblés par l'ajout des cas `cas_25` à `cas_29` et documentés branche par branche dans `f42ee1e`. **Ce test a été rejoué à l'identique en Partie 3, point 5, avec un résultat reproductible.**

### Collaboration et régression mineure (`6765ed5`, `676311c`, `4438b1e`)
Modification de `shared/schemas/bulletin.py` par un second contributeur (`6765ed5`) ayant introduit une `IndentationError` — détectée et corrigée dans la foulée (`676311c`), puis fusion des deux branches de travail (`4438b1e`).

### Fiabilisation de la suite de tests (`0ef058d`)
**Collision de module pytest** découverte en lançant la suite complète depuis la racine : `extracteur-evp/tests/conftest.py` et `compliance-validation/tests/conftest.py` (deux dossiers nommés `tests` sous des services dont le nom contient un tiret, donc non-packages) se résolvaient tous deux vers le même nom de module `tests.conftest`, provoquant un rejet de collecte. Corrigé en ajoutant `--import-mode=importlib` à `pytest.ini`.

### Sprint RAG (`20eac05`)
Sur quelques heures le 25/08 : découpage du PDF de la CCN SYNTEC en un chunk par article (`chunking.py`), script d'ingestion Qdrant (`ingest.py`), endpoint `POST /rag/query` avec recherche sémantique par embeddings Ollama (`main.py`). Priorité donnée à la fiabilité de la recherche citée (top-3 passages avec référence d'article exacte) plutôt qu'à la synthèse LLM, reléguée en option (`?synthese=true`). Pas de Dockerfile réel pour ce service à ce stade — tourne directement en Python sur l'hôte de la VM (voir Partie 1 et Partie 3, point 6).

### Découverte du 26/08 : l'orchestrateur n'avait jamais réellement été intégré (`791747c`)

**Ce qui s'est passé.** En préparant un audit systématique avant la réunion du 26/08 (rejouer, composant par composant, un test réel plutôt que de se fier aux comptes-rendus précédents), l'orchestrateur a été le seul des six composants à échouer : `orchestrateur/app/main.py` n'exposait qu'un `GET /health` placeholder, sans aucune route métier (`POST /dossiers`, `/transition`, `/etat`). Ni `state_machine.py`, ni `schemas.py`, ni `orchestrateur/tests/test_e2e_a1_a6.py` n'existaient dans le dépôt — alors que des échanges antérieurs décrivaient la machine à états A1→A6 comme implémentée et validée (le critère de la Phase 3 : "un dossier fictif traverse A1→A6 via appels API manuels, chaque transition apparaît dans audit_log").

**Cause probable.** Le code de la machine à états (D.3) avait été produit et discuté au cours d'une session de travail antérieure, mais rien n'indique qu'il ait été réellement exécuté ou committé à ce moment-là — aucune trace d'exécution vérifiable (pas de sortie de test, pas de commit correspondant dans `git log`) n'accompagne cette étape. Le plus probable est qu'un résultat "attendu" (le code fourni, censé fonctionner) a été acté comme "vérifié" sans qu'un test réel n'ait jamais été rejoué contre le dépôt tel qu'il existait effectivement — le placeholder `/health` de la conteneurisation initiale (`adee48e`) n'a donc jamais été remplacé.

**Comment ça a été détecté.** Par l'audit systématique lui-même : plutôt que de recopier l'état décrit dans les échanges précédents, chaque composant a été retesté un par un contre le dépôt réel (`git log`, arborescence, exécution effective des tests). L'écart entre "décrit comme fait" et "présent dans le dépôt" est apparu uniquement à ce moment, sur l'orchestrateur.

**Comment ça a été corrigé (`791747c`, puis `3244584`).** Le code de la machine à états a été récupéré et intégré au dépôt : `state_machine.py` (14 transitions dont les 3 boucles A2.3/A3.3/A4.3), `schemas.py`, et le remplacement du `main.py` placeholder par les vraies routes, avec journalisation systématique dans `audit_log` (succès et refus). Deux bugs de résolution de chemin propres à l'exécution en conteneur ont été découverts et corrigés au passage — le code n'avait jusque-là été exécuté qu'en local hors conteneur, jamais dans l'image Docker réelle :
1. La résolution de `db/` ne testait qu'un seul chemin candidat (`parents[2]`), qui pointait vers `/db` (inexistant) dans le conteneur au lieu de `/app/db` → `ModuleNotFoundError` au démarrage. Corrigé en testant deux chemins candidats (conteneur puis local).
2. Les imports `from state_machine import ...` / `from schemas import ...` sont des imports bare qui supposent que le répertoire de `main.py` est sur `sys.path` — faux par défaut en conteneur (`uvicorn app.main:app` charge le fichier comme sous-module du package `app`, seul `/app` est sur `sys.path`) → `ModuleNotFoundError` sur `state_machine`. Corrigé en insérant explicitement `_HERE.parent` dans `sys.path`.

Cette réintégration a cependant fait disparaître le `GET /health` de l'ancien placeholder, sans qu'un équivalent soit réécrit dans le nouveau `main.py` — cassant le healthcheck Docker (conteneur "unhealthy" malgré un service pleinement fonctionnel). Restauré dans la foulée en toute fin de journée (`3244584`) : `GET /health` retourne `{"status": "ok"}`, rebuild + redémarrage effectués, `docker compose ps` confirmé "healthy" (voir Partie 3, point 3).

**Ce que ça change pour cette réunion.** Sur les six composants couverts par ce document, l'orchestrateur est donc passé en quelques heures de "seul `/health` présent" à "machine à états A1→A6 fonctionnelle et testée" — c'est le changement le plus important depuis la version précédente de ce document, et la raison de sa régénération intégrale plutôt que d'une simple mise à jour ponctuelle.

---

## Partie 3 — Un exemple de test réel par composant, vérifié en direct

Les six sous-parties ci-dessous ont toutes été rejouées en direct pour cette version du document (pas seulement l'orchestrateur), afin de garantir que la Partie 3 dans son ensemble reste un instantané réel et non un mélange de résultats d'âges différents.

### 1. Schémas Pydantic (`shared/`)

Instanciation directe d'un `EVPMensuel` valide (données réelles de Didier, juin 2026) puis invalide (CDI avec date de fin, rejeté par le validateur `cdi_sans_date_fin`) :

```bash
cd /home/farouk/exeiguard-ia-paie
source <chemin_venv>/bin/activate   # environnement avec shared/requirements.txt installé
python3 - <<'EOF'
from datetime import date
from shared.schemas import EVPMensuel
from pydantic import ValidationError

evp_valide = EVPMensuel(
    periode=date(2026, 6, 1), prenom="Didier",
    poste="Ingénieur Système Windows", type_contrat="CDI",
    debut_contrat=date(2025, 7, 1), salaire_an=53000,
    mutuelle="Seul", nb_ticket_restaurant=18, pass_navigo=True,
)
print("VALIDE :", evp_valide.prenom, evp_valide.salaire_an)

try:
    EVPMensuel(periode=date(2026, 6, 1), prenom="Didier", poste="Ingénieur Système Windows",
               type_contrat="CDI", debut_contrat=date(2025, 7, 1),
               fin_contrat=date(2026, 12, 31), salaire_an=53000)
except ValidationError as e:
    print("REJETÉ COMME ATTENDU :", e)
EOF
```

**Résultat réel obtenu (25/08/2026) :**
```
VALIDE : Didier 53000.0
REJETÉ COMME ATTENDU : 1 validation error for EVPMensuel
  Value error, Un CDI ne doit pas avoir de date de fin de contrat [type=value_error, ...]
```

Suite complète associée, également exécutée en direct : `python -m pytest shared/tests/test_schemas.py -v` → **11 passed** (0,12s).

### 2. Base PostgreSQL (`db/`)

Conteneurs `postgres` et `orchestrateur` déjà démarrés (`docker compose -f docker-compose.dev.yml ps` — tous les deux "healthy", voir point 3). `db/test_insertion.py` exécuté contre ce PostgreSQL réel (port hôte éphémère `32768`, `DATABASE_URL` positionnée en conséquence) pour produire une nouvelle donnée réelle, puis interrogée directement :

```bash
export DATABASE_URL="postgresql+psycopg2://exeiguard:changeme_local@localhost:32768/exeiguard_poc"
python db/test_insertion.py
docker exec exeiguard-ia-paie-postgres-1 psql -U exeiguard -d exeiguard_poc \
  -c "SELECT id, prenom, nom, etat, created_at FROM dossiers ORDER BY created_at DESC LIMIT 1;"
```

**Résultat réel obtenu :**
```
Insertion/lecture réussie.
  Dossier      : id=1f6e34c7-5709-41f5-be78-5e524c2b548d prenom=Didier etat=A1
  EVP lié      : 1 entrée(s)
  Audit log    : horodatage=2026-08-25 21:09:20.714361 acteur=orchestrateur action=transition_etat:A1->A2 resultat=succes

                  id                  | prenom | nom | etat |         created_at
--------------------------------------+--------+-----+------+----------------------------
 1f6e34c7-5709-41f5-be78-5e524c2b548d | Didier |     | A1   | 2026-08-25 21:09:20.706699
(1 row)
```

### 3. Orchestrateur (machine à états A1→A6) — **fonctionnel, vérifié en direct**

**a) `docker compose ps` — le conteneur affiche bien "healthy" (pas juste "up") :**

```bash
docker compose -f docker-compose.dev.yml ps
```
```
NAME                                IMAGE                             STATUS                    PORTS
exeiguard-ia-paie-orchestrateur-1   exeiguard-ia-paie-orchestrateur   Up 5 minutes (healthy)    0.0.0.0:8000->8000/tcp
exeiguard-ia-paie-postgres-1        postgres:16-alpine                Up 48 minutes (healthy)   0.0.0.0:32768->5432/tcp
exeiguard-ia-paie-qdrant-1          qdrant/qdrant:latest              Up 2 hours                127.0.0.1:6333-6334->6333-6334/tcp
```

**b) Démo curl complète — POST /dossiers, les 6 transitions nominales A1→TERMINE, GET /etat :**

```bash
BASE=http://localhost:8000
curl -s $BASE/health
curl -s -X POST $BASE/dossiers -H "Content-Type: application/json" \
  -d '{"matricule":"0004","contrat":{"prenom":"Didier","nom":"","poste":"Ingénieur Système Windows","type_contrat":"CDI"},"evp":{"periode":"2026-06-01"}}'
# puis, pour chaque action de la séquence nominale extraire_evp / valider_transmission /
# calcul_termine / valider_bulletin / autoriser_paiement / cloturer :
curl -s -X POST $BASE/dossiers/$ID/transition -H "Content-Type: application/json" \
  -d "{\"action\":\"$ACTION\",\"acteur\":\"demo\"}"
curl -s $BASE/dossiers/$ID/etat
```

**Résultat réel obtenu :**
```
GET /health                    -> {"status":"ok"}
POST /dossiers                 -> {"id":"73933adf-...","etat":"A1","triggers_disponibles":["extraire_evp"]}
transition extraire_evp        -> A1 -> A2
transition valider_transmission -> A2 -> A3
transition calcul_termine      -> A3 -> A4
transition valider_bulletin    -> A4 -> A5
transition autoriser_paiement  -> A5 -> A6
transition cloturer            -> A6 -> TERMINE
GET /etat                      -> {"etat":"TERMINE","triggers_disponibles":[]}
```

**c) Vérification directe en base — les 7 entrées `audit_log` (1 création + 6 transitions), toutes `succes` :**
```
           action            | resultat
-----------------------------+----------
 creation_dossier            | succes
 transition_etat:A1->A2      | succes
 transition_etat:A2->A3      | succes
 transition_etat:A3->A4      | succes
 transition_etat:A4->A5      | succes
 transition_etat:A5->A6      | succes
 transition_etat:A6->TERMINE | succes
```

**d) Suite de tests associée**, avec un vrai PostgreSQL comme backend (`DATABASE_URL` pointée sur le port éphémère du conteneur) :
```bash
python -m pytest orchestrateur/tests/ -v
```
```
orchestrateur/tests/test_e2e_a1_a6.py::test_parcours_complet_a1_a6 PASSED
orchestrateur/tests/test_e2e_a1_a6.py::test_transition_invalide_rejetee_et_journalisee PASSED
orchestrateur/tests/test_e2e_a1_a6.py::test_boucle_a2_3_puis_retour_a1 PASSED
3 passed in 0.77s
```

**Point de vigilance découvert pendant cette vérification (nouveau)** : `orchestrateur/tests/test_e2e_a1_a6.py` se connecte désormais à un vrai PostgreSQL (ce n'était pas le cas quand l'orchestrateur n'avait pas de logique métier). Lancer `python -m pytest` depuis la racine **sans** `DATABASE_URL` positionnée échoue en collecte (`OperationalError: connection to server at "localhost", port 5432 failed` — le conteneur `postgres` publie son port sur un hôte éphémère, pas `5432`). À la démo : toujours exporter `DATABASE_URL` vers le port réellement publié (`docker compose port postgres 5432`) avant de lancer la suite complète.

### 4. Extracteur EVP

Le score de confiance a été rejoué directement contre `app/confidence_scoring.py`, sur une ligne EVP construite à partir du contrat réel de Jordan (`tests/fixtures/cas_13_jordan_reel.json`), avec la remarque suspecte réellement observée sur ce cas ("Prime Astreintes : 450 €") :

```bash
python3 - <<'EOF'
# ligne 1 : EVP sans remarque suspecte
# ligne 2 : EVP avec remarques="Prime Astreintes : 450 €", contrat_reference=contrat Jordan
EOF
```

**Résultat réel obtenu :**
```
Ligne 1 (sans remarque suspecte) : score = 0.6
  - Matricule EVP présent en complément du nom/prénom (identification renforcée)

Ligne 2 (remarque suspecte 'Prime Astreintes : 450 €') : score = 0.35
  - Matricule EVP présent en complément du nom/prénom (identification renforcée)
  - REMARQUES contient probablement un montant/une donnée non reportée dans les colonnes structurées (candidat fallback LLM) : 'Prime Astreintes : 450 €'
  - salaire_an cohérent avec le contrat de référence
```

Le score chute de 0,6 à 0,35 exactement pour la raison documentée dans le code (montant en texte libre non structuré). Suite complète associée : `python -m pytest extracteur-evp/tests/ -v` → **16 passed** (0,29s), incluant les 3 tests de généralisation de la détection des blocs d'absence (`test_ordre_blocs_absence_inverse_toujours_bien_classe`, `test_colonne_supplementaire_inseree_avant_blocs_absence_retrouve_les_bons_blocs`, `test_bloc_absence_manquant_est_ignore_sans_planter`).

### 5. Rule Engine — test de généralisation (coefficient ETAM 400)

Rejoué à l'identique : profil ETAM (contrat réel de Jordan modifié), position `3.1` (absente de la grille ETAM vérifiée), coefficient **400** (absent de toutes les 29 fixtures — les cas les plus proches utilisent 245, 300 et 450), période d'essai de 3 mois (plafond exact de la plage `[275,500]`), préavis effectif réduit à 1 mois pour vérifier si le moteur applique la clause spéciale "coefficient 400/450/500 : 2 mois quelle que soit l'ancienneté" plutôt que le seuil générique ETAM <2 ans (qui se contenterait de 1 mois) :

```bash
python3 - <<'EOF'
# DossierSalarie(contrat=ContratTravail(position="3.1", coefficient=400, statut="ETAM",
#                periode_essai_mois=3, ...),
#                rupture=RuptureContrat(type_rupture="demission",
#                date_notification=2026-01-01, date_fin_contrat_effective=2026-02-01))
# evaluer_toutes_les_regles(dossier)
EOF
```

**Résultat réel obtenu (25/08/2026, identique à la précédente exécution documentée dans `f42ee1e`) :**
```
[RG-03] CONFORME - position '3.1' absente de la grille SYNTEC ETAM vérifiée. Coefficient 400 dans des bornes ETAM confirmées (240-500).
[RG-04] CONFORME - Période d'essai de 3 mois conforme au maximum de 3 mois pour le coefficient 400 (statut ETAM), Article 3.4 de la CCN SYNTEC (IDCC 1486).
[RG-06] NON CONFORME - Préavis de 1 mois inférieur au minimum requis : 2 mois (ETAM coefficient 400, quelle que soit l'ancienneté).
```

Ce que ce test prouve : le Rule Engine ne "mémorise" pas les valeurs de coefficient déjà vues en fixture — RG-04 applique correctement le plafond de 3 mois de la plage `[275, 500]` et RG-06 applique correctement la clause fixe à 2 mois des coefficients `(400, 450, 500)`, pour une valeur (400) jamais rencontrée jusqu'ici. C'est ce test qui avait révélé, lors de sa première exécution, les trous de couverture comblés par `cas_25`-`cas_29` (commit `f42ee1e`, voir Partie 2). Suite complète associée : `python -m pytest compliance-validation/tests/ -v` → **28 passed** (0,13s).

**Point de vigilance confirmé pendant cette vérification** (toujours d'actualité) : lancer `python -m pytest extracteur-evp/tests/ compliance-validation/tests/` en donnant les deux chemins explicitement en arguments casse la collecte (`ModuleNotFoundError: No module named 'app.parsers'`) — alors que `python -m pytest` seul depuis la racine (découverte par défaut) fonctionne de façon fiable et reproductible. Rejoué aujourd'hui avec, en plus, `DATABASE_URL` exportée (nécessaire depuis que l'orchestrateur a de vrais tests, point 3 ci-dessus) : **59 passed** pour l'ensemble du dépôt (11 shared + 1 db + 16 extracteur-evp + 3 orchestrateur + 28 compliance-validation).

### 6. RAG

Service déjà démarré sur la VM (`python -m uvicorn app.main:app --host 0.0.0.0 --port 8003`, `OLLAMA_HOST=localhost QDRANT_HOST=localhost`), Qdrant conteneurisé avec 68 points indexés (`curl http://localhost:6333/collections/syntec_convention` → `"points_count":68`). Les 3 questions validées, rejouées :

```bash
curl -s -X POST http://localhost:8003/rag/query -H "Content-Type: application/json" \
  -d '{"question": "Quelle est la durée de la période d'\''essai pour un cadre ?"}'
```
**Résultat réel :** top-1 = Article 12.5 (score 0,6928, hors sujet — clause expatriation), **top-2 = Article 3.4 "Période d'essai"** (score 0,6678, la bonne réponse : 4 mois pour un cadre).

```bash
curl -s -X POST http://localhost:8003/rag/query -H "Content-Type: application/json" \
  -d '{"question": "Combien de jours de congés supplémentaires après 10 ans d'\''ancienneté ?"}'
```
**Résultat réel :** top-1 = Article 5.2 (score 0,6802, hors sujet), **top-2 = Article 5.1 "Durée des congés payés"** (score 0,6513, contient le barème d'ancienneté au point 2), top-3 = Article 5.3.

```bash
curl -s -X POST http://localhost:8003/rag/query -H "Content-Type: application/json" \
  -d '{"question": "Quel est le préavis pour un ETAM en cas de démission ?"}'
```
**Résultat réel :** top-1 = Article 12.8 (score 0,6356, hors sujet), top-2 = Article 12.7 (hors sujet), **top-3 = Article 4.2 "Durée du préavis"** (score 0,6118, la bonne réponse — en dernière position du top-3 cette fois).

**Confirmation du point de calibration déjà identifié** : sur les 3 questions, le bon article figure systématiquement dans le top-3 mais n'est jamais en 1ère position (2e, 2e, puis 3e position), avec des scores quasi identiques à la dernière vérification (embeddings déterministes, aucune donnée modifiée depuis) — état stable, connu, à mentionner tel quel en réunion plutôt qu'à présenter comme résolu.
