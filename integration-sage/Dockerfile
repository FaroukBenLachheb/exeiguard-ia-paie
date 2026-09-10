# Dockerfile — service integration-sage
#
# Mock deterministe (mock/calcul_simule.py, phase JOUR 1) branche sur
# POST /calculer, en attendant l'acces a l'API Sage reelle (voir
# integration-sage/README.md).
#
# Dependances partagees (shared/) : voir
# docs/architecture/dependances-partagees.md pour le pattern commun aux
# Dockerfiles applicatifs. shared/ est copie a cote de app/,
# shared/requirements.txt est installe en plus du requirements.txt du
# service, et PYTHONPATH inclut /app/shared pour que
# `from schemas import ...` fonctionne sans sys.path.insert dans le code
# applicatif. mock/ est copie a cote de app/ egalement (import "from
# mock.calcul_simule import ..." dans app/main.py, package top-level au
# meme titre que "app" et "shared").

FROM python:3.11-slim

WORKDIR /app

COPY integration-sage/requirements.txt ./requirements.txt
COPY shared/requirements.txt ./shared-requirements.txt
RUN pip install --no-cache-dir -r requirements.txt -r shared-requirements.txt

COPY integration-sage/app/ ./app/
COPY integration-sage/mock/ ./mock/
COPY shared/ ./shared/

ENV PYTHONPATH=/app/shared

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health', timeout=2)" || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
