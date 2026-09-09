#!/usr/bin/env bash
#
# scripts/reprise_apres_reactivation_vm.sh
#
# A executer sur la VM OVH GPU une fois l'instance re-disponible (capacite
# GPU OVH insuffisante au moment de la redaction de ce script -> corrections
# preparees en local, non testees en direct, cf. commit associe).
#
# Corrige/valide dans l'ordre :
#   - reseau Docker explicite "exeiguard_net" (docker-compose.yml et
#     docker-compose.dev.yml) au lieu du reseau implicite par defaut, pour
#     eliminer l'echec DNS "llm-server" observe depuis le conteneur rag ;
#   - suppression du mapping de port host sur llm-server (11434) pour
#     eliminer le conflit avec l'Ollama natif installe sur l'hote ;
#   - healthcheck llm-server ("ollama list") + depends_on condition:
#     service_healthy sur rag, pour ne demarrer rag qu'une fois Ollama pret.
#
# Utilise docker-compose.dev.yml (comme demande) : c'est le fichier qui
# construit rag/ via son Dockerfile. Si le besoin d'acceleration GPU
# reelle pour llm-server se confirme, remplacer par docker-compose.yml
# (seul fichier avec la reservation GPU active) - cf. point non tranche
# en fin de script / rapport d'accompagnement.
#
# Usage : bash scripts/reprise_apres_reactivation_vm.sh
# Variable optionnelle : PULL_OPTIONAL_MODELS=1 pour aussi tirer les gros
# modeles LLM (mistral, qwen) en plus de l'embedding (voir etape 6).

set -uo pipefail

COMPOSE_FILE="docker-compose.dev.yml"
COMPOSE="docker compose -f ${COMPOSE_FILE}"
RAG_QDRANT_URL="http://127.0.0.1:6333"
EXPECTED_POINTS_COUNT=68

echo "=== [1/8] git pull ==="
git pull
if [ $? -ne 0 ]; then
  echo "ECHEC git pull - arret du script." >&2
  exit 1
fi

echo "=== [2/8] docker compose down --remove-orphans (etat propre avant reconstruction) ==="
${COMPOSE} down --remove-orphans
if [ $? -ne 0 ]; then
  echo "ECHEC docker compose down - arret du script." >&2
  exit 1
fi

echo "=== [3/8] docker compose up -d --build (reconstruit les images avec le code + compose corriges) ==="
${COMPOSE} up -d --build
if [ $? -ne 0 ]; then
  echo "ECHEC docker compose up - arret du script." >&2
  exit 1
fi

echo "=== [4/8] Attente que llm-server soit 'healthy' (healthcheck 'ollama list', max 60s) ==="
LLM_HEALTHY=0
for i in $(seq 1 12); do
  STATUS=$(${COMPOSE} ps llm-server 2>/dev/null)
  if echo "${STATUS}" | grep -qi "healthy"; then
    echo "llm-server est healthy (apres ~$((i * 5))s)."
    LLM_HEALTHY=1
    break
  fi
  echo "  ... pas encore healthy, nouvel essai dans 5s (${i}/12)"
  sleep 5
done
if [ "${LLM_HEALTHY}" -ne 1 ]; then
  echo "ATTENTION : llm-server n'est pas passe 'healthy' apres 60s." >&2
  echo "Diagnostic avant d'aller plus loin : '${COMPOSE} logs llm-server' et '${COMPOSE} ps'." >&2
  echo "Le script continue quand meme (les etapes suivantes peuvent echouer en cascade si llm-server n'est vraiment pas pret)." >&2
fi

echo "=== [5/8] Pull du modele d'embedding nomic-embed-text (obligatoire pour le RAG) ==="
${COMPOSE} exec -T llm-server ollama pull nomic-embed-text
if [ $? -ne 0 ]; then
  echo "ECHEC pull nomic-embed-text - le RAG ne pourra pas generer d'embeddings. Verifier avant de continuer." >&2
fi

echo "=== [6/8] (optionnel) Pull des modeles LLM de synthese/test, si PULL_OPTIONAL_MODELS=1 ==="
if [ "${PULL_OPTIONAL_MODELS:-0}" = "1" ]; then
  echo "PULL_OPTIONAL_MODELS=1 : pull de mistral:7b-instruct-q4_K_M et qwen2.5:14b-instruct-q4_K_M (peut prendre plusieurs minutes selon la bande passante)."
  ${COMPOSE} exec -T llm-server ollama pull mistral:7b-instruct-q4_K_M
  ${COMPOSE} exec -T llm-server ollama pull qwen2.5:14b-instruct-q4_K_M
else
  echo "PULL_OPTIONAL_MODELS non defini (ou != 1) : modeles mistral/qwen non tires (pas necessaires pour la recherche semantique elle-meme, cf. rag/app/main.py). Relancer avec PULL_OPTIONAL_MODELS=1 si besoin pour d'autres tests."
fi

echo "=== [7/8] Verification Qdrant : collection syntec_convention, points_count attendu = ${EXPECTED_POINTS_COUNT} ==="
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "${RAG_QDRANT_URL}/collections/syntec_convention")
QDRANT_BODY=$(curl -s "${RAG_QDRANT_URL}/collections/syntec_convention")
echo "Code HTTP : ${HTTP_CODE} - Reponse brute : ${QDRANT_BODY}"
ACTUAL_POINTS=$(echo "${QDRANT_BODY}" | python3 -c "
import json, sys
try:
    d = json.load(sys.stdin)
    print(d.get('result', {}).get('points_count', 'ERREUR_PARSING'))
except Exception:
    print('ERREUR_PARSING')
")
if [ "${ACTUAL_POINTS}" = "${EXPECTED_POINTS_COUNT}" ]; then
  echo "PASS - Qdrant : points_count = ${ACTUAL_POINTS} (attendu ${EXPECTED_POINTS_COUNT})"
else
  echo "FAIL - Qdrant : points_count = '${ACTUAL_POINTS}' (attendu ${EXPECTED_POINTS_COUNT})"
  echo "  -> Si la collection est vide/absente, relancer l'ingestion manuelle : voir rag/app/ingestion/ingest.py / rag/README.md."
fi

echo "=== [8/8] 3 questions de test du module RAG (reprises de docs/architecture/etat_technique_20260826.md, section 6) ==="
${COMPOSE} exec -T rag python3 <<'PY'
import json
import sys
import urllib.request

# Les 3 questions et l'article "bon" attendu (deja verifies manuellement,
# cf. docs/architecture/etat_technique_20260826.md section 6 RAG) : le bon
# article figure dans le top-3 renvoye par POST /rag/query, mais pas
# forcement en 1ere position (etat connu, pas un bug de ce correctif).
CAS_DE_TEST = [
    ("Quelle est la duree de la periode d'essai pour un cadre ?", "3.4"),
    ("Combien de jours de conges supplementaires apres 10 ans d'anciennete ?", "5.1"),
    ("Quel est le preavis pour un ETAM en cas de demission ?", "4.2"),
]

URL = "http://localhost:8000/rag/query"
nb_pass = 0

for question, article_attendu in CAS_DE_TEST:
    payload = json.dumps({"question": question}).encode("utf-8")
    req = urllib.request.Request(
        URL, data=payload, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        articles_trouves = [p["article"] for p in data.get("passages", [])]
        if article_attendu in articles_trouves:
            print(f"PASS - \"{question}\" -> article {article_attendu} trouve dans le top-3 {articles_trouves}")
            nb_pass += 1
        else:
            print(f"FAIL - \"{question}\" -> article {article_attendu} ABSENT du top-3 {articles_trouves}")
    except Exception as exc:
        print(f"FAIL - \"{question}\" -> erreur d'appel : {exc}")

print(f"\nResume RAG : {nb_pass}/{len(CAS_DE_TEST)} PASS")
sys.exit(0 if nb_pass == len(CAS_DE_TEST) else 1)
PY
RAG_TEST_EXIT=$?

echo ""
echo "=== Reprise terminee ==="
if [ "${RAG_TEST_EXIT}" -ne 0 ]; then
  echo "Au moins un des 3 tests RAG a echoue (voir PASS/FAIL ci-dessus) - a investiguer avant de considerer le service pret." >&2
fi
echo "Verifier manuellement '${COMPOSE} ps' et '${COMPOSE} logs' en cas de doute avant de poursuivre."
