"""
rag/app/ingestion/chunking.py

Découpe le texte de la CCN SYNTEC
(docs/architecture/references/convention_collective_syntec.pdf) en un
chunk par article, en utilisant la structure réelle du document comme
délimiteur naturel (pas de découpage arbitraire par taille de texte).

Le document distingue deux usages du mot "article" :
- dans le Sommaire (pages 2-4) : "Art. X.X — Titre .......... N" (abrégé
  "Art.", suivi de points de suite et d'un numéro de page) ;
- dans le corps du texte : "Article X.X — Titre" (non abrégé, jamais
  suivi de points de suite).
Le regex ci-dessous cible volontairement la forme longue "Article X.X"
pour ignorer le Sommaire sans avoir à le découper explicitement -
vérifié empiriquement sur l'extraction pdfplumber du document réel (cf.
session de prototypage), pas supposé.

Le document se termine par une section "Glossaire" (sans numérotation
Article X.X) après le dernier article (13.6) : elle est explicitement
exclue du dernier chunk plutôt que d'être avalée dedans par erreur.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import pdfplumber

ARTICLE_PATTERN = re.compile(r"^Article (\d+\.\d+) — (.+)$", re.MULTILINE)

# Lignes répétées en en-tête/pied de chaque page, à retirer avant
# concaténation pour ne pas polluer un article qui s'étend sur plusieurs
# pages (observées sur toutes les pages du document réel).
_LIGNES_BRUIT = re.compile(
    r"^(Convention collective Syntec.*Bureaux d'études techniques|Page \d+ / \d+)$",
    re.MULTILINE,
)

# Marque la fin du texte de base exploitable (tout ce qui suit dans la
# même page que le dernier article n'est pas un article).
MARQUEUR_FIN_TEXTE_BASE = "Glossaire"


@dataclass
class ArticleChunk:
    article: str  # ex: "3.4"
    titre: str  # ex: "Période d'essai"
    texte: str  # corps complet de l'article
    source: str  # nom du fichier PDF
    page: int  # page (1-based) où débute l'article


def _extraire_texte_par_page(chemin_pdf: Path) -> list[str]:
    """Une entrée par page, en-têtes/pieds de page retirés."""
    pages = []
    with pdfplumber.open(chemin_pdf) as pdf:
        for page in pdf.pages:
            texte = page.extract_text() or ""
            texte = _LIGNES_BRUIT.sub("", texte)
            pages.append(texte)
    return pages


def chunker_convention_syntec(chemin_pdf: Path) -> list[ArticleChunk]:
    pages = _extraire_texte_par_page(chemin_pdf)

    # Concatène tout le document en gardant, pour chaque offset de
    # caractère, la page (1-based) à laquelle il appartient.
    texte_complet = ""
    offsets_pages: list[tuple[int, int]] = []  # (offset_debut, numero_page)
    for i, texte_page in enumerate(pages):
        offsets_pages.append((len(texte_complet), i + 1))
        texte_complet += texte_page + "\n"

    def page_pour_offset(offset: int) -> int:
        page_courante = offsets_pages[0][1]
        for debut, numero in offsets_pages:
            if debut > offset:
                break
            page_courante = numero
        return page_courante

    matches = list(ARTICLE_PATTERN.finditer(texte_complet))
    chunks: list[ArticleChunk] = []

    for i, match in enumerate(matches):
        article = match.group(1)
        titre = match.group(2).strip()
        debut_corps = match.end()
        fin_corps = matches[i + 1].start() if i + 1 < len(matches) else len(texte_complet)
        corps = texte_complet[debut_corps:fin_corps]

        # Dernier article : coupe avant le Glossaire (hors texte de base).
        idx_glossaire = corps.find(MARQUEUR_FIN_TEXTE_BASE)
        if idx_glossaire != -1:
            corps = corps[:idx_glossaire]

        corps = corps.strip()

        chunks.append(
            ArticleChunk(
                article=article,
                titre=titre,
                texte=corps,
                source=chemin_pdf.name,
                page=page_pour_offset(match.start()),
            )
        )

    return chunks


if __name__ == "__main__":
    # Usage manuel de vérification (pas un test formel) :
    #   python rag/app/ingestion/chunking.py
    _ROOT = Path(__file__).resolve().parents[3]
    _PDF = _ROOT / "docs" / "architecture" / "references" / "convention_collective_syntec.pdf"
    resultats = chunker_convention_syntec(_PDF)
    print(f"{len(resultats)} chunks extraits depuis {_PDF.name}")
    for c in resultats[:3]:
        print(f"\n--- Article {c.article} ({c.titre}) — page {c.page} ---")
        print(c.texte[:200], "...")
