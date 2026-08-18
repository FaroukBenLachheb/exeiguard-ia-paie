# Onboarding technique — exeiguard-ia-paie

Ce document explique **ce qui existe dans le dépôt de code aujourd'hui, pourquoi, et comment le faire tourner**. Il suppose que vous connaissez déjà l'idée métier du projet (automatiser le contrôle de conformité de la paie chez Soft IT) et l'architecture cible décrite dans les documents de référence (schéma d'architecture, diagramme de séquence) : les concepts fonctionnels comme l'EVP, le dossier salarié, le pipeline A1→A6, le Rule Engine, le RAG ou l'intégration Sage ne sont donc pas redéfinis depuis zéro ici — seulement rattachés au code qui les implémente (ou pas encore).

Chaque notion propre au code (nom de fichier, de classe, de champ, de convention) est définie la première fois qu'elle apparaît, et reprise dans le glossaire (§9) pour référence rapide.

---

## 1. Vue d'ensemble de l'avancement

### Deux numérotations coexistent dans le dépôt

Le code cite les jalons du guide de développement de deux façons différentes selon l'endroit :

- **`D.0`, `D.1`, `D.2`, `D.4`, `D.5+`** : utilisé dans les messages de commit Git.
- **`Phase 0`, `Phase 2`, `Phase 3`, `Phase 4`, `Phase 6`, `Phase 9`** : utilisé dans les docstrings du code (`db/models.py`, `scripts/generate_fixtures.py`, `docker-compose.yml`...).

Les deux semblent désigner le même guide, mais aucun fichier du dépôt ne fournit de table de correspondance officielle entre les deux (le guide lui-même n'est pas versionné ici). Ce document présente donc ce qui est **certain** (ce que le code fait, avec sa référence), pas une reconstruction inventée de la numérotation complète. Notez en particulier qu'aucun commit ni commentaire ne mentionne "D.3" — la conteneurisation et l'infra LLM, qui se situent chronologiquement entre D.2 et D.4, n'ont pas reçu de label D.x.

### Ce qui est fait

| Jalon | Contenu livré | Où | Commit(s) |
|---|---|---|---|
| **D.0** | Contrat de données Pydantic (EVP, contrat de travail, bulletin, dossier) + tests sur les 2 premiers documents réels (Didier, Sindhuja) | `shared/schemas/`, `shared/tests/` | `4618ec6` |
| **D.1** (= "Phase 0" côté docstring) | Générateur de 15 cas de test (2 puis 5 réels + 10 synthétiques), validés par les schémas Pydantic avant export | `scripts/generate_fixtures.py`, `tests/fixtures/`, `db/seeds/` | `032d0ff`, `3b0ef52` |
| **D.2** (= "Phase 2") | Socle transactionnel PostgreSQL : 5 tables SQLAlchemy, migration Alembic initiale, test d'insertion/lecture avec vérification de l'audit log | `db/` | `2722e43` |
| *(sans label D.x)* | Conteneurisation des 4 services (Dockerfiles + healthchecks), puis infra LLM (Ollama sur VM GPU cible) | `*/Dockerfile`, `docker-compose*.yml`, `llm/` | `adee48e`, `8168473` |
| **D.4** (= "Phase 4", partiel) | Extracteur EVP : parsing direct du fichier Excel réel + score de confiance par ligne. **Pas encore fait dans ce même jalon** : l'OCR/parsing PDF (contrats, bulletins), le fallback LLM, et l'exposition en API (le service n'expose encore que `GET /health`) | `extracteur-evp/app/` | `11bb025`, `b76ea79`, `e637a4d` |

### Ce qui reste à faire (D.5+)

Concrètement, aujourd'hui, **seul le contrat de données (shared/schemas/) et le parsing Excel de l'EVP produisent un résultat exploitable** ; les 4 autres services **FastAPI** (framework Python utilisé pour exposer chaque service comme une API HTTP — les 5 services applicatifs du projet en sont chacun une instance) n'exposent que `GET /health` (une route de test standard qui répond juste "je suis en vie", sans logique métier). Reste à implémenter, dans cet ordre logique (chaque étape dépend de la précédente) :

1. **Extracteur EVP — compléter** : OCR/parsing des contrats et bulletins PDF (aujourd'hui seul l'EVP Excel est parsé), fallback LLM sur les lignes à faible score de confiance.
2. **Orchestrateur — logique métier** : la machine à états A1→A6 elle-même (aujourd'hui `orchestrateur/app/main.py` initialise juste la base et répond `/health`, il n'y a aucune transition d'état implémentée en dehors de l'exemple manuel de `db/test_insertion.py`).
3. **Compliance & Validation — Rule Engine + RAG** : `compliance-validation/app/rule_engine/` est un dossier vide à ce jour. C'est ici que vivront les futures règles comme celle évoquée pour l'incohérence heures contrat/bulletin (voir §8).
4. **Intégration Sage** : `integration-sage/mock/` existe mais est vide — le mock de l'API Sage (nécessaire avant l'intégration réelle) n'a pas encore été écrit.
5. **RAG** : `rag/` est une coquille (dossiers `api/`, `ingestion/` avec juste des `__init__.py`, `Dockerfile` non écrit).

**Pourquoi cet ordre ?** Chaque service en aval a besoin d'une sortie fiable du service en amont pour être développé/testé utilement : le Rule Engine ne peut pas être validé sérieusement sans EVP extraits, l'orchestrateur ne peut pas piloter un pipeline dont les étapes n'existent pas encore, et l'intégration Sage/le RAG sont les dernières briques consommées par les étapes de contrôle post-calcul. C'est aussi pour cette raison que le fix Docker documenté dans `docs/architecture/dependances-partagees.md` (voir §7) a été traité maintenant plutôt que découvert au moment d'écrire le premier de ces 4 services : `shared/schemas` sera importé par les quatre.

---

## 2. Arborescence du projet

Seuls les dossiers non vides sont détaillés ici. Structure générale : un dossier par service (`orchestrateur/`, `extracteur-evp/`, `compliance-validation/`, `integration-sage/`, `rag/`), chacun avec le même squelette interne (`app/`, `tests/`, `Dockerfile`, `requirements.txt`), plus des dossiers transverses (`shared/`, `db/`, `scripts/`, `tests/`).

### `shared/` — le contrat de données commun

Rôle : définit les modèles **Pydantic** (bibliothèque Python de validation de données par schéma typé — un modèle Pydantic est une classe dont chaque attribut a un type déclaré ; instancier la classe avec des données invalides lève une erreur) partagés par tous les services. C'est la fondation du projet — développée en détail au §4.

Contenu actuel : `shared/schemas/` (4 modèles + leurs enums), `shared/tests/` (9 tests), `shared/requirements.txt`. `shared/venv/` existe aussi sur disque (environnement virtuel Python local) mais n'est ni versionné (`.gitignore`) ni copié dans les images Docker (`.dockerignore`, voir §7).

### `db/` — le socle transactionnel

Rôle : persistance PostgreSQL des dossiers en cours de traitement, via **SQLAlchemy** (ORM Python — Object-Relational Mapper, fait correspondre des classes Python à des tables SQL) et **Alembic** (outil de migrations de schéma associé à SQLAlchemy, génère et applique des scripts SQL versionnés pour faire évoluer une base sans perte de données).

Contenu actuel : `database.py` (connexion), `models.py` (5 tables), `migrations/` (une migration initiale), `seeds/seed_dossiers.json` (généré par `scripts/generate_fixtures.py`), `test_insertion.py`, `alembic.ini`.

### `scripts/` — outils de génération de données

Rôle : scripts one-shot exécutés manuellement par un développeur (pas appelés par un service). Contenu actuel : `generate_fixtures.py`, seul script existant, qui produit les fichiers dans `tests/fixtures/` et `db/seeds/`.

### `tests/` — fixtures et emplacements de tests transverses

Rôle : données de test partagées entre services (pas de logique ici, que des données), plus les emplacements réservés pour les tests d'intégration et de bout en bout à venir.

Contenu actuel : `tests/fixtures/` contient 15 fichiers JSON (`cas_01_didier_reel.json` à `cas_15_karim_reel.json`), chacun une paire `{contrat, evp}` conforme aux schémas Pydantic. `tests/integration/` et `tests/e2e/` existent (`.gitkeep`) mais sont vides — aucun test d'intégration inter-services n'existe encore, ce qui est cohérent avec le fait qu'aucun service (hormis l'extracteur EVP) n'a de logique à tester au-delà de son `/health`.

### `orchestrateur/` — le service pivot du pipeline

Rôle cible (architecture) : piloter la machine à états A1→A6 de chaque dossier. Contenu actuel : un `main.py` FastAPI qui initialise la base de données au démarrage (`init_db()`) et expose `GET /health` — aucune route ni logique de transition d'état n'est encore implémentée. `app/api/` existe mais est un squelette vide.

### `extracteur-evp/` — le seul service avec de la logique métier à ce jour

Rôle cible : extraire les données structurées des EVP (Excel), contrats et bulletins (PDF, OCR). Contenu actuel : `app/parsers/excel_parser.py` (parsing Excel EVP, fonctionnel), `app/confidence_scoring.py` (scoring, fonctionnel), 16 tests dans `tests/test_excel_parser.py`. `app/ocr/` existe mais est vide — aucun parsing PDF n'est implémenté. `app/main.py` reste un squelette `GET /health`, la logique de `excel_parser.py`/`confidence_scoring.py` n'est pas encore branchée sur une route API.

### `compliance-validation/` — coquille en attente du Rule Engine

Rôle cible : exécuter les règles de conformité (Rule Engine) et le RAG réglementaire, invoqués en A2 (pré-calcul) et A4 (post-calcul — voir §3 "shared/schemas/dossier.py" et le glossaire §9 pour comment ces deux invocations se retrouvent dans le code). Contenu actuel : uniquement `app/main.py` (`GET /health`) et des dossiers vides `app/rule_engine/`, `app/rule_engine/rules/`, `app/api/`.

### `integration-sage/` — coquille en attente du mock

Rôle cible : interfacer avec Sage (mock en PoC — proof of concept, le périmètre actuel du projet avant un déploiement en production — réel ensuite) pour récupérer/envoyer les bulletins. Contenu actuel : uniquement `app/main.py` (`GET /health`). `mock/` existe mais est vide — pas encore de mock Sage.

---

## 3. Fichiers de code significatifs

Seuls les fichiers avec une vraie logique sont détaillés (les `main.py` squelettes de `compliance-validation` et `integration-sage`, ainsi que les `__init__.py` vides marqués `# squelette du module (contenu à venir)`, ne le sont pas — voir §2 pour leur rôle).

### `shared/schemas/evp.py`

Définit `EVPMensuel` (une ligne EVP = un salarié pour un mois donné) et son sous-modèle `AbsencePeriode`, plus les enums `TypeAbsence` (CP/RTT/MALADIE/CONGE_SANS_SOLDE/INJUSTIFIEE) et `TypeContrat`. Deux validateurs Pydantic (`@model_validator`) y sont encodés en dur : un CDI ne peut pas avoir de date de fin, et une ligne doit avoir au moins un identifiant exploitable (matricule OU nom/prénom). C'est ce modèle que produit `extracteur-evp/app/parsers/excel_parser.py` en sortie, et que consomme `DossierSalarie.evp_historique` (`shared/schemas/dossier.py`). Le champ `matricule` y est `Optional` à dessein — voir §7, décision "matricule EVP jamais fiable".

### `shared/schemas/contrat.py`

Définit `ContratTravail` (référentiel contractuel statique d'un salarié) et l'enum `StatutSalarie` (CADRE/NON_CADRE/ETAM). Porte trois validateurs de cohérence : rémunération mensuelle vs annuelle/12 (tolérance 2€, voir §7), clause de non-concurrence nécessite une durée, clause de formation nécessite une durée d'engagement. Ce modèle est produit manuellement dans les fixtures aujourd'hui (`scripts/generate_fixtures.py`) — aucun parseur de contrat PDF n'existe encore côté `extracteur-evp/`.

### `shared/schemas/bulletin.py`

Définit `BulletinSalaire` (sortie du mock Sage en PoC, sortie Sage réelle en prod) et `LigneCotisation` (une ligne générique du tableau de cotisations ou d'éléments de rémunération, réutilisée pour les cotisations comme pour les absences du bulletin). Aucun champ n'y est marqué obligatoire par convention rigide : le docstring du fichier explique que certaines lignes de bulletin sont conditionnelles (ex: Pass Navigo absent chez un salarié, présent chez un autre) et que le schéma ne doit donc pas figer une liste fixe de lignes attendues.

### `shared/schemas/dossier.py`

Définit `DossierSalarie`, le modèle pivot qui combine `ContratTravail` (statique) et l'historique `evp_historique`/`bulletins_historique` (mensuel, listes de `EVPMensuel`/`BulletinSalaire`). Expose trois méthodes utilitaires : `dernier_evp()`, `dernier_bulletin()`, et `bulletin_precedent()` (l'avant-dernier bulletin, utile pour calculer un delta M-1, voir glossaire §9). Le docstring précise explicitement que c'est ce modèle qui alimente les deux invocations du Moteur Compliance & Validation (A2 pré-calcul, A4 post-calcul) — c'est donc le point d'entrée de données attendu par le futur `compliance-validation/`.

### `shared/schemas/__init__.py`

Réexporte les classes des quatre modules ci-dessus (`from .bulletin import ...`, etc.) pour permettre `from schemas import EVPMensuel` (ou `from shared.schemas import EVPMensuel` selon le contexte d'import, voir §5) plutôt que d'obliger chaque appelant à connaître le fichier exact où vit chaque classe.

### `shared/tests/test_schemas.py`

9 tests qui valident les 4 schémas ci-dessus contre des **données réelles** (contrats et EVP de Didier et Sindhuja, transcrits à la main depuis les PDF/Excel fournis par Soft IT) plutôt que des données inventées, plus quelques tests négatifs (`pytest.raises(ValidationError)`) qui prouvent que les validateurs de cohérence rejettent bien des incohérences volontaires. C'est la première suite de tests du projet (D.0) et la référence pour la structure attendue de chaque schéma.

### `scripts/generate_fixtures.py`

Génère les 15 cas de `tests/fixtures/` et `db/seeds/seed_dossiers.json` : 5 cas réels (Didier, Sindhuja, Jordan, Julien, Karim — construits à la main à partir des documents PDF/Excel Soft IT, non versionnés eux-mêmes) et 10 cas synthétiques (générés avec **Faker**, bibliothèque de données factices réalistes) couvrant chacun un scénario métier volontaire (prime, absence maladie, CDD, heures sup, etc.). Chaque cas est instancié via les classes Pydantic de `shared/schemas` **avant** d'être écrit sur disque : un cas qui échoue la validation n'est jamais exporté, ce qui garantit que tout fichier dans `tests/fixtures/` est déjà conforme au contrat de données. Ce script est appelé par un développeur (`python scripts/generate_fixtures.py`), jamais par un service.

### `db/database.py`

Fournit `engine` et `SessionLocal` (objets SQLAlchemy de connexion) à partir de la variable d'environnement `DATABASE_URL`, avec une valeur par défaut construite depuis `POSTGRES_USER`/`POSTGRES_PASSWORD`/`POSTGRES_HOST`/`POSTGRES_PORT`/`POSTGRES_DB` si absente. Expose `get_session()` et `init_db()` (crée les tables si absentes — pratique en dev/tests, mais `alembic upgrade head` reste la voie recommandée en PoC/prod, voir §5). Importé aujourd'hui par `orchestrateur/app/main.py` et `db/test_insertion.py`.

### `db/models.py`

Définit les 5 tables SQLAlchemy du socle transactionnel : `Dossier`, `EVPEnregistrement`, `Controle`, `Decision`, `AuditLog` (détaillées au §9, glossaire). Principe explicite dans le docstring : ces tables ne redéfinissent pas les schémas Pydantic de `shared/schemas/` — elles les **persistent**, en gardant les champs structurants (matricule, période, état...) comme colonnes indexables et le détail complet de l'objet (ex: `contrat_json`) en colonne `JSON` générique. Ce choix de type `JSON` générique (portable SQLite/PostgreSQL sans changement de code) plutôt que `postgresql.JSONB` explicite (une variante du type JSON propre à PostgreSQL, indexable et donc plus rapide à interroger, mais qui ne fonctionnerait pas sur SQLite) est documenté comme un compromis dev/prod, voir §7.

### `db/test_insertion.py`

Sert de test de bout en bout minimal du socle transactionnel : insère un `Dossier` + un `EVPEnregistrement` + un `AuditLog` à partir du cas réel `cas_01_didier_reel.json`, puis relit et vérifie chaque champ (y compris l'horodatage de l'audit log). Exécutable en script (`python db/test_insertion.py`, fonction `main()`) ou sous pytest (fonction `test_insertion()`, qui appelle `main()` — voir §6 pour un point d'attention sur ce fichier).

### `db/migrations/env.py` et `db/migrations/versions/bcb3dbf7d6d9_initial_schema.py`

`env.py` est le point d'entrée Alembic : il lit `DATABASE_URL` de la même façon que `db/database.py` plutôt que de dupliquer la config dans `alembic.ini`. Le fichier de version `bcb3dbf7d6d9_initial_schema.py` est la migration initiale, générée automatiquement par Alembic à partir de `db/models.py` : elle crée les 5 tables et leurs index. C'est la seule migration existante à ce jour (`down_revision = None`).

### `extracteur-evp/app/parsers/excel_parser.py`

Le fichier le plus dense du dépôt à ce jour. Parse un fichier EVP `.xlsx` avec **openpyxl** (bibliothèque de lecture/écriture de fichiers Excel) et retourne une liste de `ParsedEVPLigne` (une dataclass, pas un modèle Pydantic — elle porte le résultat du parsing *avant* validation : `evp` peut être `None` si la ligne est invalide, plus `erreurs`/`avertissements`). Fonction d'entrée : `parse_evp_file(path)`. Point clé d'implémentation : les blocs d'absence (CP/RTT/MALADIE/...) ne sont **jamais** repérés par une position de colonne fixe, mais par le libellé de la ligne d'en-tête groupée du fichier (fonction `_detecter_colonnes_absence`) — ce choix est le sujet du commit `e637a4d` et est testé explicitement par plusieurs tests de "généralisation" dans `test_excel_parser.py`. Consomme `shared.schemas` (construit des `EVPMensuel`/`AbsencePeriode`), sera à terme appelé par une route API de `extracteur-evp/app/main.py` (pas encore branché).

### `extracteur-evp/app/confidence_scoring.py`

Calcule un score de confiance (0 à 1) par ligne EVP déjà parsée (`ParsedEVPLigne` venant de `excel_parser.py`), pour signaler les lignes qui méritent une relecture humaine ou un futur fallback LLM (pas encore implémenté). Le score ne mesure pas la validité Pydantic (déjà garantie en amont) mais la fiabilité probable de l'*extraction* : il baisse si `REMARQUES` contient probablement un montant non structuré (regex `MOTIF_REMARQUE_SUSPECTE`, ex: "Prime Astreintes : 450 €" vu sur un cas réel), s'il y a incohérence de salaire avec un `ContratTravail` de référence fourni en paramètre optionnel, ou si le parsing a émis des avertissements. Fonction d'entrée : `score_ligne_evp(ligne, contrat_reference=None)`, retourne un `ScoreConfiance(valeur, raisons)`.

### `extracteur-evp/tests/test_excel_parser.py` et `extracteur-evp/tests/conftest.py`

16 tests qui construisent des classeurs Excel synthétiques **en mémoire** (jamais les fichiers réels non versionnés) reproduisant la structure du fichier réel, organisés autour de 3 anomalies réelles documentées : matricule EVP non fiable, colonne dates hétérogène (texte libre vs datetime Excel natif), 0 explicite vs cellule vide. Trois tests supplémentaires ("généralisation") prouvent que le parser retrouve les bons blocs d'absence même quand leur ordre, leur position ou leur présence changent — preuve que le parser ne mémorise pas la disposition du fichier de test actuel. `conftest.py` ajoute `extracteur-evp/` et la racine du dépôt à `sys.path` (la liste, tenue en mémoire par Python à l'exécution, des dossiers où chercher un module lors d'un `import` — `PYTHONPATH`, voir glossaire §9, ne fait que pré-remplir cette liste au démarrage) pour rendre `app` et `shared` importables : nécessaire car `extracteur-evp` contient un tiret, donc n'est pas un nom de package Python valide.

### `orchestrateur/app/main.py`

Point d'entrée FastAPI du service. Aujourd'hui : ajoute `db/` à `sys.path` (avec deux chemins candidats selon qu'on est en conteneur ou en exécution locale, voir §5), appelle `init_db()` au démarrage via le `lifespan` FastAPI (le hook FastAPI exécuté une fois au démarrage du service, avant d'accepter des requêtes), et expose `GET /health`. Aucune route métier n'existe encore — c'est le point d'entrée qui accueillera la machine à états A1→A6 une fois développée.

### `docker-compose.dev.yml` et `docker-compose.yml`

`docker-compose.dev.yml` est l'environnement de développement local : PostgreSQL + les 4 services applicatifs + `llm-server` (Ollama), sans réservation GPU (commentée, pas de GPU en local). `docker-compose.yml` est le squelette de déploiement sur la VM cible OVH (GPU NVIDIA L4 24 Go) — seul `llm-server` y est défini pour l'instant, avec la réservation GPU active cette fois ; les autres services y seront ajoutés phase par phase, "sur le même modèle" (commentaire en tête de fichier).

### `.env.example`

Modèle de fichier `.env` (à copier, jamais commité tel quel — voir §5) : variables PostgreSQL, et variables Ollama (`OLLAMA_HOST`/`PORT`, `OLLAMA_MODEL_FALLBACK` pour l'extraction, `OLLAMA_MODEL_COMPLIANCE` pour le raisonnement compliance/RAG).

---

## 4. Le contrat de données central (`shared/schemas/`)

`shared/schemas/` est la fondation du projet parce que **tout le reste en dépend, dans les deux sens du terme** :

- **En amont** : ce sont les seuls modèles qui encodent, à partir des documents réels Soft IT, ce à quoi ressemblent vraiment un EVP, un contrat, un bulletin — y compris leurs irrégularités (champs conditionnels, formulations non standard, matricule EVP peu fiable). Ces modèles ont été écrits et validés **avant** tout code applicatif (D.0, avant même D.1), précisément pour que chaque service développé ensuite parte d'un contrat de données déjà éprouvé sur du réel plutôt que d'une hypothèse.
- **En aval** : `db/models.py` les persiste sans les redéfinir (`contrat_json`, `evp_json` sont des dumps de ces modèles), `scripts/generate_fixtures.py` les utilise pour garantir que toute fixture générée est valide, `extracteur-evp/app/parsers/excel_parser.py` construit directement des `EVPMensuel`, et `shared/schemas/dossier.py` (`DossierSalarie`) est explicitement documenté comme le modèle qui alimentera les deux invocations du Moteur Compliance & Validation.

### Comment un nouveau service doit s'y raccrocher

Tout nouveau service qui manipule des données métier (compliance-validation, integration-sage, rag) doit **importer ces modèles plutôt que d'en redéfinir des équivalents locaux**. Concrètement, dans le conteneur d'un service :

```python
from schemas import EVPMensuel, ContratTravail, DossierSalarie
```

Ceci fonctionne parce que le Dockerfile du service copie `shared/` dans l'image et positionne `PYTHONPATH=/app/shared` (voir §5 et §7) — mécanisme mis en place justement pour que ce raccrochement soit immédiat, sans redécouverte service par service. Si un service a besoin d'un champ que le contrat actuel ne porte pas (ex: `BulletinSalaire.date_premiere_entree` n'a pas d'équivalent dans `ContratTravail`/`EVPMensuel` à ce jour, voir §8), la bonne pratique observée dans l'historique est d'**étendre le schéma partagé** plutôt que de faire porter cette donnée par un champ ad hoc côté service.

---

## 5. Lancer le projet en local

### Pré-requis

- Python 3.11 (les Dockerfiles utilisent `python:3.11-slim`)
- Docker Desktop (avec Docker Compose v2, `docker compose ...` sans tiret)
- Pas de GPU nécessaire en local (la réservation GPU est commentée dans `docker-compose.dev.yml`)

### Option A — Toute la stack via Docker Compose (recommandé pour un premier tour)

```bash
cp .env.example .env
docker compose -f docker-compose.dev.yml up -d --build
```

Démarre PostgreSQL + les 4 services applicatifs (orchestrateur sur `:8000`, extracteur-evp sur `:8001`, compliance-validation sur `:8002`, integration-sage sur `:8003`) + `llm-server` (Ollama, port `11434` interne uniquement, pas exposé sur l'hôte). Vérifier que tout est démarré :

```bash
docker compose -f docker-compose.dev.yml ps
curl http://localhost:8000/health
```

Pour utiliser réellement le LLM (pas nécessaire tant qu'aucun service ne l'appelle) :

```bash
docker compose -f docker-compose.dev.yml exec llm-server ollama pull mistral:7b-instruct-q4_K_M
docker compose -f docker-compose.dev.yml exec llm-server ollama pull qwen2.5:14b-instruct-q4_K_M
```

### Option B — Un seul service en local, hors Docker (pour développer/déboguer)

Chaque service se lance avec **uvicorn** (le serveur qui fait réellement tourner une application FastAPI — FastAPI décrit les routes, uvicorn les sert sur un port réseau ; `--reload` redémarre automatiquement à chaque modification de fichier). Exemple avec l'extracteur-evp (le service avec le plus de logique actuellement) :

```bash
cd extracteur-evp
python -m venv venv && venv\Scripts\activate   # (Linux/Mac : source venv/bin/activate)
pip install -r requirements.txt -r ../shared/requirements.txt
uvicorn app.main:app --reload --port 8001
```

Pour l'orchestrateur, qui a en plus besoin de `db/` et d'une base :

```bash
cd orchestrateur
python -m venv venv && venv\Scripts\activate
pip install -r requirements.txt -r ../shared/requirements.txt
set DATABASE_URL=sqlite:///./dev.db          # PowerShell : $env:DATABASE_URL="sqlite:///./dev.db"
uvicorn app.main:app --reload --port 8000
```

`main.py` détecte lui-même s'il tourne en conteneur ou en dépôt local pour retrouver `db/` (deux chemins candidats testés dans l'ordre) — pas de variable supplémentaire à positionner pour ça.

### Générer/régénérer les fixtures

```bash
python -m venv shared/venv && shared\venv\Scripts\activate
pip install -r shared/requirements.txt
python scripts/generate_fixtures.py --seed 42
```

Réécrit tous les fichiers de `tests/fixtures/` et `db/seeds/seed_dossiers.json`. `--seed` contrôle la génération Faker (déterministe à graine fixée, `--seed 42` est la valeur utilisée dans tout l'historique du projet).

### Appliquer les migrations Alembic (au lieu de `init_db()`)

```bash
cd db
set DATABASE_URL=postgresql+psycopg2://exeiguard:changeme_local@localhost:5432/exeiguard_poc
alembic upgrade head
```

---

## 6. Lancer les tests

### Tout le dépôt en une commande

```bash
python -m pytest
```

Aucun fichier `pytest.ini`/`pyproject.toml` ne restreint la découverte des tests : lancée depuis la racine, cette commande découvre et exécute **tous** les tests du dépôt (26 à ce jour). Un point d'attention : `db/test_insertion.py::test_insertion` insère réellement des lignes dans la base pointée par `DATABASE_URL` au moment de l'exécution (pas de rollback, pas de base isolée par test — documenté explicitement dans le fichier). Pour ne pas accumuler de lignes dans une base partagée (ex: le PostgreSQL de `docker-compose.dev.yml`), pointez vers une base SQLite jetable :

```bash
DATABASE_URL="sqlite:///./test.db" python -m pytest
# PowerShell : $env:DATABASE_URL="sqlite:///./test.db"; python -m pytest
```

### Détail des 3 suites existantes

| Suite | Emplacement | Nb tests | Couvre |
|---|---|---|---|
| Schémas Pydantic | `shared/tests/test_schemas.py` | 9 | Validité des 4 modèles sur données réelles (Didier, Sindhuja) + rejets attendus (incohérence rémunération, CDI avec date de fin, ligne EVP sans identifiant, clause sans durée) |
| Parser Excel EVP | `extracteur-evp/tests/test_excel_parser.py` | 16 | Parsing nominal, les 3 anomalies réelles (matricule non fiable, dates hétérogènes, 0 vs vide), et 3 tests de généralisation de la détection des blocs d'absence par libellé |
| Socle transactionnel | `db/test_insertion.py` | 1 | Insertion + lecture d'un dossier/EVP/audit_log de bout en bout, vérifie horodatage + acteur + action + résultat (critère explicite de la Phase 2 du guide) |

`tests/integration/` et `tests/e2e/` (racine du dépôt) sont réservés pour plus tard — vides à ce jour, cohérent avec l'absence de logique inter-services à tester pour l'instant (voir §1).

Il n'y a pas de pipeline CI configuré dans le dépôt (pas de `.github/workflows/`) : les tests sont exécutés manuellement par les développeurs avant chaque commit, comme en attestent les mentions "Validé : ..." dans plusieurs messages de commit.

---

## 7. Décisions d'architecture et justification

### Machine à états (A1→A6) plutôt qu'un moteur BPMN complet

`db/models.py` modélise l'avancement d'un dossier avec un simple champ `Dossier.etat` (chaîne de caractères, ex: `"A1"`), pas un moteur de workflow générique de type **BPMN** (Business Process Model and Notation — un standard et une catégorie d'outils pour modéliser et exécuter des processus métier complexes, généralement reconfigurables sans redéploiement du code). Aucun fichier du dépôt ne documente explicitement un arbitrage écrit contre BPMN — cette section présente donc l'interprétation la plus probable au vu du code, pas une décision sourcée verbatim : le pipeline cible est une séquence d'états connue et fixe (A1 à A6, définie dans l'architecture de référence), pas un ensemble de processus métier à composer dynamiquement. Un champ `etat` + une table `audit_log` qui trace chaque transition (`action: "transition_etat:A1->A2"`, voir `db/test_insertion.py`) couvre ce besoin sans ajouter la dépendance et la complexité opérationnelle d'un moteur BPMN — complexité qui se justifie surtout quand les processus doivent être reconfigurables sans redéploiement, ce qui n'est pas un besoin exprimé ici pour un PoC (proof of concept) à 6 états fixes.

### Ollama plutôt que vLLM

Décision actée et documentée : `llm/README.md` et le commit `8168473` ("adaptation infra LLM pour GPU (Ollama remplace llama.cpp CPU-only, cf. changement de VM cible)"). Le plan initial était `llama.cpp` en CPU-only ; au changement de cible d'infrastructure (VM OVH avec GPU NVIDIA L4 24 Go), Ollama a été retenu et vLLM explicitement écarté. Le dépôt ne détaille pas le comparatif Ollama/vLLM lui-même, seulement le résultat : Ollama sert deux modèles (`mistral:7b-instruct-q4_K_M` en fallback d'extraction, `qwen2.5:14b-instruct-q4_K_M` pour le raisonnement compliance/RAG) via un endpoint compatible OpenAI, plus simple à opérer pour deux modèles avec chargement/déchargement à la demande qu'un serveur vLLM taillé pour du throughput élevé multi-requêtes.

### `shared/` copié dans chaque image Docker plutôt que packagé différemment

Chaque Dockerfile applicatif (orchestrateur, extracteur-evp, compliance-validation, integration-sage) fait `COPY shared/ ./shared/` et installe `shared/requirements.txt`, plutôt que de publier `shared/` comme un package pip installable (ex: `pip install -e shared/` avec un `setup.py`/`pyproject.toml`). Voir `docs/architecture/dependances-partagees.md` et le commit `0af3508`. C'est le même choix, pour la même raison, que celui déjà fait pour `db/` (voir le docstring de `orchestrateur/app/main.py` : "`db/` n'est pas encore package comme un module Python installable partagé entre services (prévu pour une phase ultérieure)") : au stade actuel du PoC, packager proprement `shared/` ajouterait de la cérémonie (fichier de build, versionning interne, republication à chaque changement de schéma) pour un bénéfice qui ne se matérialise que si `shared/` est consommé en dehors de ce monorepo. Le coût de la solution retenue est documenté et assumé : sans `.dockerignore`, `COPY shared/` aurait aussi embarqué `shared/venv/` (des milliers de fichiers) dans chaque image — corrigé par un `.dockerignore` racine dans le même commit.

### Le matricule EVP n'est jamais utilisé comme identifiant fiable

Documenté à trois endroits cohérents : le docstring de `shared/schemas/evp.py` ("le champ MATRICULE est souvent vide côté EVP -> la jointure avec le référentiel salarié doit prévoir un fallback sur (nom, prenom)"), le docstring de `extracteur-evp/app/parsers/excel_parser.py` ("c'est un simple numéro de ligne (1, 2, 3...), jamais le matricule Sage réel"), et le test `extracteur-evp/tests/test_excel_parser.py::test_matricule_evp_jamais_transmis_au_modele`. En pratique : `excel_parser.py` construit toujours `EVPMensuel(matricule=None, ...)`, quelle que soit la valeur brute lue dans la colonne MATRICULE du fichier Excel — cette valeur brute est conservée à part (`ParsedEVPLigne.raw_matricule`) uniquement pour audit, jamais transmise au modèle métier. `EVPMensuel.identifiant_minimal_present` (validateur Pydantic) impose en échange qu'au moins nom ou prénom soit renseigné, pour garantir qu'une ligne reste malgré tout identifiable.

### Autres décisions notables (bonus)

- **Détection des blocs d'absence par libellé d'en-tête, jamais par position de colonne fixe** (`excel_parser.py`, commit `e637a4d`) : une confusion CP/RTT avait été introduite dans les fixtures D.1 par transcription manuelle, détectée a posteriori par validation croisée avec le parser automatisé D.4 (commit `b76ea79`). Prouvé par 3 tests de généralisation qui font varier ordre/position/présence des blocs.
- **Tolérance à 2€ (pas 1€) sur la cohérence rémunération annuelle/mensuelle** (`shared/schemas/contrat.py`, commit `3afe2b0`) : le contrat réel de Karim porte un écart de 1.33€ dû à un arrondi mensuel appliqué par Soft IT. Plutôt que de "corriger" une donnée réelle pour satisfaire le validateur, la tolérance du validateur a été ajustée, avec le cas réel cité en commentaire comme justification.
- **Type `JSON` générique** plutôt que `postgresql.JSONB` explicite dans `db/models.py` (voir définition de JSONB au §3) : fonctionne identiquement sur SQLite (tests locaux) et PostgreSQL (dev/PoC), au prix de ne pas bénéficier de l'indexation JSONB native — un `TypeDecorator` dédié (mécanisme SQLAlchemy permettant de personnaliser comment un type de colonne est stocké/lu, ici pour basculer vers `JSONB` sans changer le reste du code) est explicitement envisagé "si besoin de perf sur les requêtes JSON" une fois sur la VM cible.

---

## 8. Points d'attention et dette technique connue

- **Format de dates hétérogène dans les EVP réels** : la colonne DATES d'un bloc d'absence contient tantôt du texte libre (`"22, 25 et 26/05"`), tantôt un datetime Excel natif. `excel_parser.py` normalise les deux vers une chaîne `JJ/MM/AAAA` avant validation Pydantic (`AbsencePeriode.dates_brutes` est typé `str`), mais le texte libre n'est jamais reparsé en dates structurées (liste de `date`) — le docstring du module le signale comme un point "à normaliser en liste de `date` lors du parsing, mais on garde le texte brut ici pour ne rien perdre à l'extraction", jamais fait à ce jour.
- **Faute de frappe "ABSCENCES" dans les libellés réels** (au lieu de "ABSENCES", sur 4 des 5 blocs) : gérée par un matching sur sous-motif (`"RTT"`, `"MALADIE"`, etc.) qui ne porte pas sur la partie fautive, donc insensible à cette coquille précise. Reste fragile si Soft IT modifie un jour plus radicalement l'intitulé d'un bloc.
- **Incohérence heures contrat/bulletin (139h vs 151,67h) sur 3 cas réels** (Jordan, Julien, Karim) : le contrat mentionne 139h/mois (38h30/semaine) mais le bulletin réel utilise 151,67h comme tous les autres salariés. Préservée telle quelle dans les fixtures (non "corrigée"), en attente d'une future règle du Rule Engine (mentionnée en commentaire sous l'identifiant provisoire `RG-0X`) — qui n'existe pas encore (`compliance-validation/app/rule_engine/` est vide).
- **Primes en texte libre non extraites en structuré** (ex: `"Prime Astreintes : 450 €"` chez Jordan, `"Prime Durée de mission 1500 € Brut"` chez Karim) : volontairement non reconstruites dans le champ `prime` par `excel_parser.py` — c'est le signal que `confidence_scoring.py` fait baisser le score de confiance de la ligne, en vue d'un futur fallback LLM (Phase D.5+, pas implémenté).
- **Qualification bulletin sans coefficient affiché** chez Julien (contrairement aux autres bulletins qui affichent `"Position X.X / Coeff - YYY"`), alors que le contrat porte bien un coefficient (275) : incohérence d'affichage contrat/bulletin non modélisable à ce jour faute de fixture `BulletinSalaire` pour ce cas — bon candidat de test Compliance futur.
- **`date_premiere_entree`** (reprise d'ancienneté, différente de `date_entree`/`date_effet` chez Didier, Julien, Karim) n'est portée que par `BulletinSalaire`, pas encore par `ContratTravail`/`EVPMensuel` — à reporter le jour où des fixtures `BulletinSalaire` réelles seront créées pour ces cas.
- **`db/test_insertion.py::test_insertion` n'est pas isolé** : chaque exécution insère réellement dans la base pointée par `DATABASE_URL`, sans transaction annulée en fin de test. Convention actuelle pour éviter d'accumuler des lignes dans une base partagée : toujours pointer `DATABASE_URL` vers un SQLite jetable pour lancer les tests (voir §6).
- **`.gitignore` a déjà eu un incident d'encodage** : la ligne excluant `data-confidentielles/` (dossier contenant les PDF/Excel réels des salariés) s'est retrouvée un temps encodée en UTF-16 au milieu d'un fichier UTF-8, donc jamais reconnue comme règle valide par Git — corrigé dans le commit `3b0ef52`, mais bon rappel de vérifier `git status` avant de commiter si ce fichier est retouché.
- **Pas de CI configurée** (`.github/workflows/` absent) : les tests sont lancés manuellement par les développeurs, pas automatiquement à chaque push/PR.
- **`integration-sage/mock/` et `rag/` sont des coquilles vides** malgré leurs dossiers déjà créés — rien à tester ni à lancer pour ces deux services au-delà de `GET /health` (et même pas de `Dockerfile` réel pour `rag/`, qui contient encore juste un commentaire placeholder).

---

## 9. Glossaire

### Vocabulaire métier → où il vit dans le code

| Terme | Ce qu'il signifie dans le code |
|---|---|
| **EVP** | Instancié en code sous `EVPMensuel` (`shared/schemas/evp.py`) : une ligne = un salarié pour un mois. Persisté en base via `EVPEnregistrement` (`db/models.py`, table `evp`). |
| **Dossier** | `DossierSalarie` (`shared/schemas/dossier.py`) côté contrat de données pur (contrat + historiques EVP/bulletins) ; `Dossier` (`db/models.py`, table `dossiers`) côté persistance, centré sur `etat` (état courant dans la machine à états) plutôt que sur l'historique complet. |
| **Matricule** | Deux sens à ne pas confondre dans le code : le matricule *Sage* (fiable, porté par `BulletinSalaire.matricule`, obligatoire) et le matricule *EVP brut* (numéro de ligne du fichier Excel, jamais fiable, jamais transmis à `EVPMensuel.matricule` — voir §7). `ContratTravail.matricule` est absent du contrat lui-même, "relié via bulletin/EVP" selon son commentaire. |
| **Bulletin** | `BulletinSalaire` (`shared/schemas/bulletin.py`). Aujourd'hui, aucune fixture réelle n'en instancie une complète hormis `bulletin_didier()` dans `shared/tests/test_schemas.py` (donnée de test, pas un fichier de fixtures partagé comme les EVP/contrats). |
| **audit_log** | Table SQLAlchemy `AuditLog` (`db/models.py`). Trace immuable (jamais modifiée ni supprimée) de chaque événement du pipeline : `horodatage`, `acteur` (humain, ex: `"gestionnaire"`, ou système, ex: `"orchestrateur"`), `action` (ex: `"transition_etat:A1->A2"`), `resultat`, `details_json`. |
| **A1→A6** | États du pipeline (définis dans l'architecture de référence). Dans le code, une simple valeur du champ `Dossier.etat` (`String(20)`), sans validation programmatique des transitions autorisées à ce jour — c'est l'orchestrateur (pas encore écrit) qui portera cette logique. |
| **A2 (pré-calcul) / A4 (post-calcul)** | Les deux invocations du Moteur Compliance & Validation, distinguées dans le code par `Controle.phase` (`"A2"` ou `"A4"`, `db/models.py`). Le docstring de `shared/schemas/dossier.py` précise : A2 compare le dernier EVP au contrat, A4 compare le dernier bulletin au bulletin M-1 et au contrat. |
| **Delta M-1** | Comparaison entre le bulletin du mois courant et celui du mois précédent, utilisée en A4. Côté code : `DossierSalarie.bulletin_precedent()` retourne l'avant-dernier élément de `bulletins_historique` (ou `None` s'il y en a moins de deux) — c'est la méthode conçue précisément pour ce calcul. |
| **Rule Engine** | Composant cible de `compliance-validation/app/rule_engine/` (vide à ce jour). Dans `db/models.py`, `Controle.regle_id` (ex: `"RG-03"`) est le champ prévu pour tracer quelle règle a produit un résultat — matérialise le principe "jamais une décision réglementaire portée par un LLM seul" cité dans le docstring de `Controle`. |
| **RG-0X** | Convention de nommage d'une règle du Rule Engine (ex: `RG-03`) observée dans `Controle.regle_id`. `RG-0X` (littéralement, avec le X) est utilisé en commentaire comme identifiant provisoire pour une règle pas encore écrite (ex: la future règle sur l'incohérence heures contrat/bulletin, voir §8) — ce n'est pas un identifiant réel, juste une convention d'attente. |
| **source_extraction** | Champ de `EVPEnregistrement` (`db/models.py`), valeurs attendues `"parsing_direct"` ou (plus tard) un identifiant de fallback LLM — reflète comment la ligne EVP a été obtenue. |
| **score_confiance** | Champ de `EVPEnregistrement` (`db/models.py`), alimenté par `score_ligne_evp()` (`extracteur-evp/app/confidence_scoring.py`) : un flottant entre 0 et 1 qui reflète la fiabilité de l'extraction (pas la validité Pydantic, déjà garantie). |
| **Décision** | Table `Decision` (`db/models.py`) : une action humaine explicite (`acteur`, `action` ex: `"valider"`/`"corriger"`/`"rejeter"`, `commentaire`) sur un dossier — jamais une décision automatique. |
| **Convention collective / SYNTEC** | Convention collective applicable chez Soft IT, portée par `ContratTravail.convention_collective`. `position` (ex: `"2.2"`) et `coefficient` (ex: `130`) sont les deux axes de la grille de classification SYNTEC ; `scripts/generate_fixtures.py` encode la correspondance observée entre les deux dans `GRILLE_SYNTEC`. |

### Vocabulaire technique (outillage)

| Terme | Signification dans ce projet |
|---|---|
| **Pydantic** | Bibliothèque Python de modèles de données validés par type (utilisée pour tout `shared/schemas/`). Une instanciation avec des données invalides lève `pydantic.ValidationError`. |
| **SQLAlchemy** | ORM (Object-Relational Mapper) utilisé par `db/models.py` pour mapper les classes Python aux tables PostgreSQL/SQLite. |
| **Alembic** | Outil de migrations de schéma associé à SQLAlchemy (`db/migrations/`) : génère et applique des scripts SQL versionnés. |
| **openpyxl** | Bibliothèque de lecture/écriture de fichiers Excel, utilisée par `excel_parser.py` pour lire les fichiers EVP `.xlsx`. |
| **Faker** | Bibliothèque de génération de données factices réalistes (noms, etc.), utilisée par `scripts/generate_fixtures.py` pour les 10 cas synthétiques. |
| **PYTHONPATH** | Variable d'environnement listant les dossiers où Python cherche les modules importables. Positionnée à `/app/shared` dans chaque Dockerfile applicatif pour permettre `from schemas import ...` sans `sys.path.insert` répété dans le code (voir §4, §7). |
| **fixture (pytest)** vs **fixture (métier)** | Deux sens différents à ne pas confondre : une fixture *pytest* est une fonction de préparation de données pour un test (ex: `contrat_didier()` dans `shared/tests/test_schemas.py`) ; une fixture *métier* est un cas de test JSON dans `tests/fixtures/` (ex: `cas_01_didier_reel.json`), généré par `scripts/generate_fixtures.py`. |
