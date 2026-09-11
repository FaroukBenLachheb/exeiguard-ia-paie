"""
extracteur-evp/app/parsers/contrat_parser.py

Extraction déterministe des champs d'un contrat de travail (PDF, upload
réel) par LIBELLÉ DE SECTION, jamais par numéro d'article fixe : la
numérotation varie d'un contrat à l'autre selon les clauses présentes
(cf. docstring de shared/schemas/contrat.py - ex. la clause de formation,
quand elle existe, décale l'article suivant). Chaque section est donc
localisée en cherchant son TITRE (normalisé : accents retirés, casse
ignorée), puis la valeur est extraite dans la fenêtre de texte qui suit.

Score de confiance par champ (0-1), documenté ici car réutilisé
partout dans ce module :
  1.0  libellé de section trouvé ET valeur conforme au motif précis
       attendu pour ce champ (date, montant, "2.2", etc.)
  0.5-0.75  libellé trouvé mais valeur ambiguë (motif de repli plus
       large, ou plusieurs candidats), OU absence d'une clause
       optionnelle déduite de l'absence de son libellé (déduction
       raisonnable, pas une vraie lecture)
  0.0  champ non localisé du tout, valeur=None

Champs volontairement HORS scope (non listés dans le besoin, non
extraits ici) : matricule (n'existe pas sur un contrat, relié plus tard
via l'EVP/Sage), nationalite, adresse, date_naissance, nir - tous
Optional côté ContratTravail, donc l'absence ne bloque pas la
validation Pydantic en aval.
"""

from __future__ import annotations

import re
import sys
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional

import pdfplumber

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from shared.schemas import StatutSalarie  # noqa: E402

SCORE_NON_TROUVE = 0.0
SCORE_DEDUCTION = 0.5
SCORE_AMBIGU = 0.7
SCORE_EXACT = 1.0

MOIS_FR = {
    "JANVIER": 1,
    "FEVRIER": 2,
    "MARS": 3,
    "AVRIL": 4,
    "MAI": 5,
    "JUIN": 6,
    "JUILLET": 7,
    "AOUT": 8,
    "SEPTEMBRE": 9,
    "OCTOBRE": 10,
    "NOVEMBRE": 11,
    "DECEMBRE": 12,
}


@dataclass
class ChampExtrait:
    valeur: Any
    confiance: float
    raison: str


def contrat_et_confiances(champs: dict[str, ChampExtrait]) -> tuple[dict[str, Any], dict[str, float]]:
    """Sépare un dict de ChampExtrait en (valeurs brutes, scores), pour la
    réponse API (POST /extraire-contrat) et pour la fusion avec le
    fallback LLM (contrat_llm_fallback.py)."""
    return (
        {nom: c.valeur for nom, c in champs.items()},
        {nom: c.confiance for nom, c in champs.items()},
    )


# --------------------------------------------------------------------------
# Extraction du texte brut (pdfplumber, une page à la fois puis jointes)
# --------------------------------------------------------------------------


_MOTIF_COUPURE_MOT = re.compile(r"(?<=[a-zà-ÿ])-\n(?=[a-zà-ÿ])")


def extraire_texte_pdf(chemin: str | Path) -> str:
    with pdfplumber.open(Path(chemin)) as pdf:
        pages = [page.extract_text() or "" for page in pdf.pages]
    texte = "\n".join(pages)
    # Recolle les mots coupés en fin de ligne par la mise en page PDF
    # (ex. "bruts men-\nsuels" -> "bruts mensuels") : sans ce recollage,
    # un mot-clé recherché comme "MENSUEL" ne matche jamais un mot coupé
    # en deux à cet endroit précis du texte extrait - observé sur un
    # contrat réel. Restreint aux coupures minuscule-minuscule pour ne
    # pas recoller à tort un vrai tiret de mot composé (ex.
    # "non-concurrence") qui tomberait en fin de ligne.
    return _MOTIF_COUPURE_MOT.sub("", texte)


# Apostrophes typographiques (guillemet-9 ’, accent grave/aigu isolés
# parfois utilisés comme apostrophe) observées dans les PDF réels
# (pdfplumber restitue l'apostrophe telle qu'encodée dans le PDF, jamais
# l'apostrophe droite ' utilisée dans les libellés ci-dessous) : sans
# cette normalisation, "DATE D'EFFET"/"PERIODE D'ESSAI" ne matchent
# jamais "DATE D’EFFET"/"PÉRIODE D’ESSAI" tels qu'extraits du PDF.
_APOSTROPHES = "’‘`´"


def _normaliser_char(c: str) -> str:
    if c in _APOSTROPHES:
        return "'"
    d = unicodedata.normalize("NFKD", c)
    d = "".join(ch for ch in d if not unicodedata.combining(ch))
    # Repli sur le caractère original si la décomposition ne donne rien
    # (ou plus d'un caractère, ex. "œ" -> "OE") : on ne garde que le
    # premier caractère pour préserver la longueur (et donc les indices)
    # du texte d'origine, condition nécessaire pour que les offsets
    # trouvés dans le texte normalisé restent valides sur le texte brut.
    return (d[:1] or c).upper()


def _texte_normalise(texte: str) -> str:
    return "".join(_normaliser_char(c) for c in texte)


def _fenetre(
    texte: str, texte_norm: str, libelles: list[str], taille: int = 700, apres: int = 0, avant: int = 0
) -> Optional[str]:
    """Retourne la fenêtre de texte (casse/accents d'origine préservés)
    qui entoure la première occurrence d'un des libellés donnés (cherchés
    en MAJUSCULES SANS ACCENT sur texte_norm), ou None si aucun n'est
    trouvé. `apres` décale le début de la fenêtre après le libellé lui
    même (pour sauter la ponctuation ":"/"-"). `avant` inclut du texte
    AVANT le libellé (nécessaire quand la valeur précède le mot-clé, ex.
    "de 10 RTT" : le nombre est avant "RTT", pas après)."""
    for libelle in libelles:
        m = re.search(re.escape(libelle), texte_norm)
        if m:
            fin_libelle = m.end() + apres
            debut = max(0, fin_libelle - avant)
            return texte[debut : fin_libelle + taille]
    return None


def _trouve_libelle(texte_norm: str, libelles: list[str]) -> bool:
    return any(libelle in texte_norm for libelle in libelles)


# --------------------------------------------------------------------------
# Utilitaires de parsing de valeur
# --------------------------------------------------------------------------

_MOTIF_MONTANT = re.compile(r"(\d{1,3}(?:[  ]\d{3})*(?:[.,]\d{1,2})?)\s*(?:€|EUR|EUROS)", re.IGNORECASE)
_MOTIF_DATE_NUM = re.compile(r"(\d{1,2})/(\d{1,2})/(\d{2,4})")
_MOTIF_DATE_TEXTE = re.compile(
    r"(\d{1,2})(?:ER)?\s+(" + "|".join(MOIS_FR) + r")\s+(\d{4})"
)


def _montant(fenetre: Optional[str]) -> Optional[float]:
    if not fenetre:
        return None
    m = _MOTIF_MONTANT.search(fenetre)
    if not m:
        return None
    brut = m.group(1).replace(" ", "").replace(" ", "").replace(",", ".")
    try:
        return float(brut)
    except ValueError:
        return None


def _parse_date(fenetre: Optional[str]) -> Optional[date]:
    if not fenetre:
        return None
    fenetre_norm = _texte_normalise(fenetre)
    m = _MOTIF_DATE_NUM.search(fenetre_norm)
    if m:
        jour, mois, annee = (int(g) for g in m.groups())
        if annee < 100:
            annee += 2000
        try:
            return date(annee, mois, jour)
        except ValueError:
            return None
    m = _MOTIF_DATE_TEXTE.search(fenetre_norm)
    if m:
        jour = int(m.group(1))
        mois = MOIS_FR.get(m.group(2))
        annee = int(m.group(3))
        if mois:
            try:
                return date(annee, mois, jour)
            except ValueError:
                return None
    return None


def _entier(fenetre: Optional[str], motif: re.Pattern) -> Optional[int]:
    if not fenetre:
        return None
    m = motif.search(_texte_normalise(fenetre))
    return int(m.group(1)) if m else None


def _aplatir(texte: str) -> str:
    """Recolle un texte extrait sur plusieurs lignes (retour à la ligne
    de mise en page PDF, pas un vrai saut de paragraphe) en une seule
    ligne, espaces compactés."""
    return " ".join(texte.split())


# --------------------------------------------------------------------------
# Identité (prénom / nom) — pas une "section" à proprement parler : cherché
# dans le préambule ("Entre les soussignés..."), sur le texte BRUT (la
# casse porte l'information : nom de famille conventionnellement en
# MAJUSCULES, prénom en casse normale). Le contrat nomme généralement le
# représentant de l'employeur PUIS le salarié, séparés par un "Et,"
# isolé sur sa propre ligne ("...Monsieur Tarik KARABAG\nEt,\n<salarié>"
# - structure identique sur les deux contrats réels observés) : ce
# marqueur structurel, pas une civilité, sert d'ancre pour isoler le bloc
# du salarié, la civilité (Madame/Monsieur) n'étant elle-même PAS
# systématique (cas réel observé : "Et,\nSindhuja" sans civilité, alors
# que "Et,\nMonsieur Didier" en a une).
# --------------------------------------------------------------------------

_MOTIF_BLOC_SALARIE = re.compile(r"\nET,\s*\n([^\n]+)")
_MOTIF_PRENOM_NOM = re.compile(
    r"^(?:(?:Madame|Monsieur|M\.|Mme\.?)[ \t]+)?([A-ZÀ-Ý][a-zà-ÿ\-]+)(?:[ \t]+([A-ZÀ-Ý][A-ZÀ-Ý\-]{1,}))?[ \t]*$"
)


def _extraire_identite(texte: str, texte_norm: str) -> tuple[ChampExtrait, ChampExtrait]:
    """Isole le bloc du salarié via le marqueur structurel "Et,\\n" qui le
    sépare du représentant de l'employeur cité juste avant (cf.
    commentaire ci-dessus), puis lit sur la ligne suivante (texte BRUT :
    la casse porte l'information, nom de famille conventionnellement en
    MAJUSCULES) une civilité optionnelle, un prénom, et un nom de famille
    optionnel (absent sur les deux contrats réels observés, le champ du
    gabarit étant resté vide)."""
    m_bloc = _MOTIF_BLOC_SALARIE.search(texte_norm)
    if not m_bloc:
        raison = "Aucun marqueur « Et, » isolé sur sa ligne trouvé pour délimiter le bloc du salarié"
        return ChampExtrait(None, SCORE_NON_TROUVE, raison), ChampExtrait(None, SCORE_NON_TROUVE, raison)

    ligne = texte[m_bloc.start(1) : m_bloc.end(1)]
    m = _MOTIF_PRENOM_NOM.match(ligne)
    if not m:
        raison = "Bloc du salarié localisé mais la ligne suivante ne ressemble pas à un nom de personne"
        return ChampExtrait(None, SCORE_NON_TROUVE, raison), ChampExtrait(None, SCORE_NON_TROUVE, raison)

    prenom = m.group(1).strip()
    nom = m.group(2).strip() if m.group(2) else None
    champ_prenom = ChampExtrait(prenom, SCORE_EXACT, "Prénom trouvé juste après le marqueur « Et, » du bloc salarié")
    champ_nom = (
        ChampExtrait(nom, SCORE_EXACT, "Nom de famille en MAJUSCULES trouvé sur la même ligne que le prénom")
        if nom
        else ChampExtrait(None, SCORE_NON_TROUVE, "Prénom trouvé mais aucun nom de famille sur la même ligne (champ probablement resté vide sur le contrat)")
    )
    return champ_prenom, champ_nom


# --------------------------------------------------------------------------
# Poste / fonction
# --------------------------------------------------------------------------

LIBELLES_FONCTION = ["FONCTION DU CONTRACTANT", "FONCTION DU SALARIE", "FONCTION", "POSTE"]


# Capture restreinte à une seule ligne ([^\n.], pas [^.]) : l'intitulé de
# poste tient sur sa propre ligne, contrairement à "lieu de travail" qui
# peut être coupé par un retour à la ligne de mise en page en plein
# milieu de la phrase.
_MOTIF_QUALITE_DE = re.compile(r"QUALITE DE\s*[:\-]?\s*([^\n.][^\n.]{1,120})")


def _extraire_poste(texte: str, texte_norm: str) -> ChampExtrait:
    fen = _fenetre(texte, texte_norm, LIBELLES_FONCTION, taille=250, apres=0)
    if fen is None:
        return ChampExtrait(None, SCORE_NON_TROUVE, f"Aucun des libellés {LIBELLES_FONCTION} trouvé")
    # Motif précis : le contrat introduit le poste par "engagé(e) en
    # qualité de : <poste>" - isole le poste seul, sans le boilerplate.
    m = _MOTIF_QUALITE_DE.search(_texte_normalise(fen))
    if m:
        return ChampExtrait(
            _aplatir(fen[m.start(1) : m.end(1)]), SCORE_EXACT, "« en qualité de : » trouvé, poste isolé du boilerplate"
        )
    # Repli : première phrase après le libellé, sans distinguer le
    # boilerplate éventuel — confiance réduite car le texte capturé peut
    # contenir plus que le seul intitulé du poste.
    m = re.search(r"[:\-]?\s*([^.]{2,150})\.", fen)
    if not m:
        return ChampExtrait(None, SCORE_NON_TROUVE, "Libellé de fonction trouvé mais aucun texte exploitable après")
    return ChampExtrait(_aplatir(m.group(1)), SCORE_AMBIGU, "Libellé de fonction trouvé, première phrase capturée telle quelle")


# --------------------------------------------------------------------------
# Type de contrat (CDI/CDD) — cherché dans le titre du document, pas dans
# une "section" nommée.
# --------------------------------------------------------------------------


def _extraire_type_contrat(texte_norm: str) -> ChampExtrait:
    debut = texte_norm[:1500]
    if re.search(r"A\s+DUREE\s+INDETERMINEE", debut):
        return ChampExtrait("CDI", SCORE_EXACT, "« à durée indéterminée » trouvé dans le titre/préambule")
    if re.search(r"A\s+DUREE\s+DETERMINEE", debut):
        return ChampExtrait("CDD", SCORE_EXACT, "« à durée déterminée » trouvé dans le titre/préambule")
    return ChampExtrait(None, SCORE_NON_TROUVE, "Ni « durée indéterminée » ni « durée déterminée » trouvé")


# --------------------------------------------------------------------------
# Convention collective
# --------------------------------------------------------------------------

LIBELLES_CONVENTION = ["CONVENTION COLLECTIVE"]


def _extraire_convention(texte: str, texte_norm: str) -> ChampExtrait:
    fen = _fenetre(texte, texte_norm, LIBELLES_CONVENTION, taille=300)
    if fen is not None and "SYNTEC" in _texte_normalise(fen):
        return ChampExtrait("SYNTEC", SCORE_EXACT, "« Convention collective » suivi de « SYNTEC »")
    if "SYNTEC" in texte_norm or "IDCC 1486" in texte_norm:
        return ChampExtrait(
            "SYNTEC", SCORE_AMBIGU, "« SYNTEC »/« IDCC 1486 » trouvé dans le document, hors section dédiée"
        )
    return ChampExtrait(None, SCORE_NON_TROUVE, "Ni libellé « Convention collective » ni « SYNTEC » trouvés")


# --------------------------------------------------------------------------
# Statut / position / coefficient (classification)
# --------------------------------------------------------------------------

LIBELLES_CLASSIFICATION = ["CLASSIFICATION", "STATUT"]
_MOTIF_POSITION = re.compile(r"POSITION\s*[:\-]?\s*(\d\.\d)")
_MOTIF_COEFFICIENT = re.compile(r"COEFFICIENT\s*[:\-]?\s*(\d{2,3})")


def _extraire_statut(texte: str, texte_norm: str) -> ChampExtrait:
    fen = _fenetre(texte, texte_norm, LIBELLES_CLASSIFICATION, taille=400)
    zone = _texte_normalise(fen) if fen is not None else texte_norm
    trouve_dans_section = fen is not None
    if re.search(r"NON[\s\-]CADRE", zone):
        valeur = StatutSalarie.NON_CADRE.value
    elif "ETAM" in zone:
        valeur = StatutSalarie.ETAM.value
    elif "CADRE" in zone:
        valeur = StatutSalarie.CADRE.value
    else:
        return ChampExtrait(None, SCORE_NON_TROUVE, "Aucun des statuts CADRE/NON_CADRE/ETAM trouvé")
    score = SCORE_EXACT if trouve_dans_section else SCORE_AMBIGU
    raison = "Statut trouvé " + ("dans la section classification" if trouve_dans_section else "hors section dédiée")
    return ChampExtrait(valeur, score, raison)


def _extraire_position(texte: str, texte_norm: str) -> ChampExtrait:
    fen = _fenetre(texte, texte_norm, LIBELLES_CLASSIFICATION, taille=400)
    if fen is not None:
        m = _MOTIF_POSITION.search(_texte_normalise(fen))
        if m:
            return ChampExtrait(m.group(1), SCORE_EXACT, "« Position : X.X » trouvé dans la section classification")
    m = _MOTIF_POSITION.search(texte_norm)
    if m:
        return ChampExtrait(m.group(1), SCORE_AMBIGU, "« Position : X.X » trouvé hors section dédiée")
    return ChampExtrait(None, SCORE_NON_TROUVE, "Aucun motif « Position : X.X » trouvé")


def _extraire_coefficient(texte: str, texte_norm: str) -> ChampExtrait:
    fen = _fenetre(texte, texte_norm, LIBELLES_CLASSIFICATION, taille=400)
    if fen is not None:
        val = _entier(fen, _MOTIF_COEFFICIENT)
        if val is not None:
            return ChampExtrait(val, SCORE_EXACT, "« Coefficient : NNN » trouvé dans la section classification")
    val = _entier(texte, _MOTIF_COEFFICIENT)
    if val is not None:
        return ChampExtrait(val, SCORE_AMBIGU, "« Coefficient : NNN » trouvé hors section dédiée")
    return ChampExtrait(None, SCORE_NON_TROUVE, "Aucun motif « Coefficient : NNN » trouvé")


# --------------------------------------------------------------------------
# Date d'effet
# --------------------------------------------------------------------------

LIBELLES_DATE_EFFET = ["PRISE D'EFFET", "PRISE D EFFET", "PREND EFFET", "DATE D'EFFET", "A COMPTER DU"]


def _extraire_date_effet(texte: str, texte_norm: str) -> ChampExtrait:
    fen = _fenetre(texte, texte_norm, LIBELLES_DATE_EFFET, taille=100)
    if fen is not None:
        d = _parse_date(fen)
        if d is not None:
            return ChampExtrait(d, SCORE_EXACT, "Date trouvée juste après un libellé de prise d'effet")
    return ChampExtrait(None, SCORE_NON_TROUVE, f"Aucun des libellés {LIBELLES_DATE_EFFET} suivi d'une date valide")


# --------------------------------------------------------------------------
# Rémunération
# --------------------------------------------------------------------------

LIBELLES_REMUNERATION = ["REMUNERATION"]


def _extraire_remuneration(texte: str, texte_norm: str) -> tuple[ChampExtrait, ChampExtrait]:
    fen = _fenetre(texte, texte_norm, LIBELLES_REMUNERATION, taille=1000)
    if fen is None:
        raison = f"Aucun des libellés {LIBELLES_REMUNERATION} trouvé"
        return (ChampExtrait(None, SCORE_NON_TROUVE, raison), ChampExtrait(None, SCORE_NON_TROUVE, raison))

    fen_norm = _texte_normalise(fen)

    def _montant_proche(mot_cle_prefixe: str, distance_max: int = 80) -> Optional[float]:
        # Recherche par PROXIMITE (pas seulement "mot-cle PUIS montant") :
        # un contrat reel formule "remuneration annuelle de 53 000 e...
        # correspondant a 4 417e ... bruts MENSUELS" - le montant mensuel
        # est cite AVANT l'adjectif "mensuels", pas apres. `mot_cle_prefixe`
        # matche l'adjectif complet ou tronque (ANNUEL couvre ANNUELLE,
        # MENSUEL couvre MENSUELLE/MENSUELS).
        positions_mot = [m.start() for m in re.finditer(mot_cle_prefixe, fen_norm)]
        if not positions_mot:
            return None
        meilleur, meilleure_distance = None, None
        for m in _MOTIF_MONTANT.finditer(fen_norm):
            centre = (m.start() + m.end()) // 2
            distance = min(abs(centre - p) for p in positions_mot)
            if distance <= distance_max and (meilleure_distance is None or distance < meilleure_distance):
                meilleur, meilleure_distance = m.group(1), distance
        if meilleur is None:
            return None
        try:
            return float(meilleur.replace(" ", "").replace(" ", "").replace(",", "."))
        except ValueError:
            return None

    annuel = _montant_proche("ANNUEL")
    mensuel = _montant_proche("MENSUEL")

    if annuel is not None:
        champ_annuel = ChampExtrait(annuel, SCORE_EXACT, "Montant trouvé à proximité de « annuelle » dans la section rémunération")
    else:
        champ_annuel = ChampExtrait(None, SCORE_NON_TROUVE, "Aucun montant associé à « annuelle » dans la section rémunération")

    if mensuel is not None:
        champ_mensuel = ChampExtrait(mensuel, SCORE_EXACT, "Montant trouvé à proximité de « mensuelle » dans la section rémunération")
    else:
        champ_mensuel = ChampExtrait(None, SCORE_NON_TROUVE, "Aucun montant associé à « mensuelle » dans la section rémunération")

    # Repli : si un seul des deux manque, et qu'au moins deux montants en €
    # apparaissent dans la section, on prend les deux premiers montants
    # trouvés dans l'ordre du texte (annuel généralement cité avant mensuel)
    # — confiance réduite car l'association au libellé n'est plus garantie.
    if annuel is None or mensuel is None:
        montants = _MOTIF_MONTANT.findall(fen)
        valeurs = []
        for brut in montants:
            try:
                valeurs.append(float(brut.replace(" ", "").replace(" ", "").replace(",", ".")))
            except ValueError:
                continue
        if annuel is None and len(valeurs) >= 1:
            champ_annuel = ChampExtrait(
                valeurs[0], SCORE_DEDUCTION, "Repli : premier montant en € de la section rémunération (position, pas libellé)"
            )
        if mensuel is None and len(valeurs) >= 2:
            champ_mensuel = ChampExtrait(
                valeurs[1], SCORE_DEDUCTION, "Repli : deuxième montant en € de la section rémunération (position, pas libellé)"
            )

    return champ_annuel, champ_mensuel


# --------------------------------------------------------------------------
# Heures mensuelles
# --------------------------------------------------------------------------

_MOTIF_HEURES_MENSUELLES = re.compile(r"(\d{2,3}[.,]\d{1,2})\s*HEURES")
HEURES_MENSUELLES_DEFAUT = 151.67


def _extraire_heures_mensuelles(texte: str, texte_norm: str) -> ChampExtrait:
    m = _MOTIF_HEURES_MENSUELLES.search(texte_norm)
    if m:
        try:
            return ChampExtrait(
                float(m.group(1).replace(",", ".")), SCORE_EXACT, "Motif « NNN,NN heures » trouvé dans le document"
            )
        except ValueError:
            pass
    return ChampExtrait(
        HEURES_MENSUELLES_DEFAUT,
        SCORE_DEDUCTION,
        "Aucun motif « NNN,NN heures » trouvé — valeur légale standard (35h/semaine) utilisée par défaut",
    )


# --------------------------------------------------------------------------
# Période d'essai
# --------------------------------------------------------------------------

LIBELLES_PERIODE_ESSAI = ["PERIODE D'ESSAI", "PERIODE D ESSAI"]
_MOTIFS_PAS_DE_PERIODE_ESSAI = ["NE COMPREND PAS DE PERIODE D'ESSAI", "NE COMPORTE PAS DE PERIODE D'ESSAI", "PAS DE PERIODE D'ESSAI"]
# Une durée en mois peut être écrite en chiffres seuls ("12 MOIS"), entre
# parenthèses suivie du mot en toutes lettres ("(12) DOUZE MOIS" - cas réel
# observé, cf. clause de non-concurrence), ou l'inverse ("6 (SIX) MOIS DE
# SALAIRES" - cas réel observé, indemnité de non-concurrence) : le motif
# tolère jusqu'à une parenthèse et jusqu'à deux mots intercalés avant "MOIS".
_MOTIF_MOIS = re.compile(r"(\d{1,2})\)?\s*(?:\([^)]*\))?\s*(?:[A-ZÀ-Ÿ\-]+\s+){0,2}MOIS")


def _extraire_periode_essai(texte: str, texte_norm: str) -> tuple[ChampExtrait, ChampExtrait]:
    fen = _fenetre(texte, texte_norm, LIBELLES_PERIODE_ESSAI, taille=400)
    if fen is None:
        raison = f"Aucun des libellés {LIBELLES_PERIODE_ESSAI} trouvé"
        return ChampExtrait(None, SCORE_NON_TROUVE, raison), ChampExtrait(False, SCORE_NON_TROUVE, raison)

    fen_norm = _texte_normalise(fen)
    if any(_texte_normalise(motif) in fen_norm for motif in _MOTIFS_PAS_DE_PERIODE_ESSAI):
        return (
            ChampExtrait(None, SCORE_EXACT, "« ne comprend pas de période d'essai » détecté explicitement"),
            ChampExtrait(False, SCORE_EXACT, "Pas de période d'essai : non renouvelable par construction"),
        )

    mois = _entier(fen, _MOTIF_MOIS)
    renouvelable = "RENOUVELABLE" in fen_norm and "NON RENOUVELABLE" not in fen_norm
    champ_mois = (
        ChampExtrait(mois, SCORE_EXACT, "Durée en mois trouvée dans la section période d'essai")
        if mois is not None
        else ChampExtrait(None, SCORE_NON_TROUVE, "Section période d'essai trouvée mais aucune durée en mois lisible")
    )
    champ_renouv = ChampExtrait(
        renouvelable,
        SCORE_EXACT if mois is not None else SCORE_DEDUCTION,
        "« renouvelable » " + ("trouvé" if renouvelable else "absent") + " dans la section période d'essai",
    )
    return champ_mois, champ_renouv


# --------------------------------------------------------------------------
# RTT / période de référence congés
# --------------------------------------------------------------------------

LIBELLES_RTT = ["RTT"]
# "JOURS" n'est pas toujours présent (cas réel observé : "de 10 RTT par
# an", sans le mot "jours") : le motif le rend optionnel, dans les deux
# sens (nombre avant ou après "RTT").
_MOTIF_RTT_JOURS = re.compile(r"(\d{1,2})\s*(?:JOURS?\s*(?:DE\s*)?)?RTT|RTT[^\d]{0,40}?(\d{1,2})\s*JOURS?")


def _extraire_rtt(texte: str, texte_norm: str) -> ChampExtrait:
    # avant=30 : le nombre précède souvent "RTT" dans la même phrase
    # ("de 10 RTT par an" - cas réel observé), donc hors de la fenêtre
    # qui ne suivrait que le libellé.
    fen = _fenetre(texte, texte_norm, LIBELLES_RTT, taille=400, avant=30)
    zone_norm = _texte_normalise(fen) if fen is not None else texte_norm
    m = _MOTIF_RTT_JOURS.search(zone_norm)
    if m:
        valeur = int(m.group(1) or m.group(2))
        score = SCORE_EXACT if fen is not None else SCORE_AMBIGU
        return ChampExtrait(valeur, score, "Motif « N jours de RTT » trouvé")
    return ChampExtrait(None, SCORE_NON_TROUVE, "Aucun motif « N jours de RTT » trouvé")


LIBELLES_CONGES = ["PERIODE DE REFERENCE", "CONGES PAYES", "CONGES"]
# Couvre aussi bien un format numérique ("01/06 au 31/05") qu'un format en
# toutes lettres ("1er juin au 31 mai" - cas réel observé) : chaque borne
# est un nombre (avec "ER" optionnel) suivi d'au plus un mot (le mois),
# ce qui exclut naturellement la suite de phrase ("de l'année suivante").
_MOTIF_PERIODE_REF = re.compile(
    r"DU\s+(\d{1,2}(?:ER)?(?:/\d{1,2})?(?:\s+[A-ZÀ-Ÿ]+)?)\s+AU\s+(\d{1,2}(?:ER)?(?:/\d{1,2})?(?:\s+[A-ZÀ-Ÿ]+)?)"
)


def _extraire_periode_reference_conges(texte: str, texte_norm: str) -> ChampExtrait:
    fen = _fenetre(texte, texte_norm, LIBELLES_CONGES, taille=300)
    if fen is not None:
        m = _MOTIF_PERIODE_REF.search(_texte_normalise(fen))
        if m:
            # Capture depuis `fen` (casse d'origine) aux mêmes indices que
            # le match sur le texte normalisé (longueur préservée).
            borne1 = fen[m.start(1) : m.end(1)].lower()
            borne2 = fen[m.start(2) : m.end(2)].lower()
            return ChampExtrait(
                f"{borne1} au {borne2}", SCORE_EXACT, "Motif « du X au Y » trouvé dans la section congés"
            )
    return ChampExtrait(None, SCORE_NON_TROUVE, "Aucune période de référence congés (« du X au Y ») trouvée")


# --------------------------------------------------------------------------
# Clause de non-concurrence
# --------------------------------------------------------------------------

LIBELLES_NON_CONCURRENCE = ["NON-CONCURRENCE", "NON CONCURRENCE"]
_MOTIFS_CLAUSE_ABSENTE = ["NE COMPORTE PAS", "NE PREVOIT PAS", "NE COMPREND PAS", "SANS CLAUSE"]
# Même tolérance que _MOTIF_MOIS (parenthèse/mot en toutes lettres avant
# "MOIS"), plus la proximité d'un des deux mots "SALAIRE"/"REMUNERATION"
# qui distingue l'indemnité de la simple durée de la clause.
_MOTIF_INDEMNITE_MOIS = re.compile(
    r"(\d{1,2})\)?\s*(?:\([^)]*\))?\s*(?:[A-ZÀ-Ÿ\-]+\s+){0,2}MOIS[^.]{0,25}(?:SALAIRE|REMUNERATION)"
)


def _extraire_non_concurrence(texte: str, texte_norm: str) -> tuple[ChampExtrait, ChampExtrait, ChampExtrait]:
    # taille=1500 (pas 600) : sur un contrat réel, la durée et l'indemnité
    # de non-concurrence sont citées à plusieurs paragraphes d'écart dans
    # le même article (la clause elle-même est longue).
    fen = _fenetre(texte, texte_norm, LIBELLES_NON_CONCURRENCE, taille=1500)
    if fen is None:
        raison = f"Aucun des libellés {LIBELLES_NON_CONCURRENCE} trouvé — absence de clause déduite"
        return (
            ChampExtrait(False, SCORE_DEDUCTION, raison),
            ChampExtrait(None, SCORE_NON_TROUVE, raison),
            ChampExtrait(None, SCORE_NON_TROUVE, raison),
        )
    fen_norm = _texte_normalise(fen)
    if any(motif in fen_norm for motif in _MOTIFS_CLAUSE_ABSENTE):
        raison = "Section non-concurrence trouvée mais indique explicitement l'absence de clause"
        return (
            ChampExtrait(False, SCORE_EXACT, raison),
            ChampExtrait(None, SCORE_EXACT, raison),
            ChampExtrait(None, SCORE_EXACT, raison),
        )

    champ_clause = ChampExtrait(True, SCORE_EXACT, "Section non-concurrence trouvée, sans mention d'absence de clause")

    mois_candidats = [int(x) for x in _MOTIF_MOIS.findall(fen_norm)]
    duree = mois_candidats[0] if mois_candidats else None
    champ_duree = (
        ChampExtrait(duree, SCORE_EXACT, "Première durée en mois trouvée dans la section non-concurrence")
        if duree is not None
        else ChampExtrait(None, SCORE_NON_TROUVE, "Section non-concurrence trouvée mais aucune durée en mois lisible")
    )

    m_indem = _MOTIF_INDEMNITE_MOIS.search(fen_norm)
    if m_indem:
        champ_indem = ChampExtrait(
            int(m_indem.group(1)), SCORE_EXACT, "Motif « N mois de salaire » trouvé dans la section non-concurrence"
        )
    else:
        champ_indem = ChampExtrait(
            None, SCORE_NON_TROUVE, "Aucun motif « N mois de salaire/rémunération » trouvé pour l'indemnité"
        )

    return champ_clause, champ_duree, champ_indem


# --------------------------------------------------------------------------
# Clause de formation / dédit-formation
# --------------------------------------------------------------------------

LIBELLES_FORMATION = ["DEDIT-FORMATION", "DEDIT FORMATION", "ENGAGEMENT DE FORMATION", "CLAUSE DE FORMATION", "FORMATION"]


def _extraire_formation(texte: str, texte_norm: str) -> tuple[ChampExtrait, ChampExtrait]:
    fen = _fenetre(texte, texte_norm, LIBELLES_FORMATION, taille=600)
    if fen is None:
        raison = f"Aucun des libellés {LIBELLES_FORMATION} trouvé — absence de clause déduite"
        return ChampExtrait(False, SCORE_DEDUCTION, raison), ChampExtrait(None, SCORE_NON_TROUVE, raison)
    fen_norm = _texte_normalise(fen)
    if any(motif in fen_norm for motif in _MOTIFS_CLAUSE_ABSENTE):
        raison = "Section formation trouvée mais indique explicitement l'absence de clause/engagement"
        return ChampExtrait(False, SCORE_EXACT, raison), ChampExtrait(None, SCORE_EXACT, raison)

    champ_clause = ChampExtrait(True, SCORE_EXACT, "Section formation/dédit-formation trouvée, sans mention d'absence de clause")
    duree = _entier(fen, _MOTIF_MOIS)
    champ_duree = (
        ChampExtrait(duree, SCORE_EXACT, "Durée en mois trouvée dans la section formation")
        if duree is not None
        else ChampExtrait(None, SCORE_NON_TROUVE, "Section formation trouvée mais aucune durée en mois lisible")
    )
    return champ_clause, champ_duree


# --------------------------------------------------------------------------
# Lieu de travail
# --------------------------------------------------------------------------

LIBELLES_LIEU_TRAVAIL = ["LIEU DE TRAVAIL"]


def _extraire_lieu_travail(texte: str, texte_norm: str) -> ChampExtrait:
    fen = _fenetre(texte, texte_norm, LIBELLES_LIEU_TRAVAIL, taille=300)
    if fen is None:
        return ChampExtrait(None, SCORE_NON_TROUVE, f"Aucun des libellés {LIBELLES_LIEU_TRAVAIL} trouvé")
    # [^.] (pas [^\n.]) : la phrase peut être coupée par un retour à la
    # ligne de mise en page PDF avant le point final (ex. "...au sein de
    # la société ou en\ntélétravail.") - _aplatir() recolle ensuite.
    m = re.search(r"[:\-]?\s*([^.]{2,200})\.", fen)
    if not m:
        return ChampExtrait(None, SCORE_NON_TROUVE, "Libellé lieu de travail trouvé mais aucun texte exploitable après")
    return ChampExtrait(_aplatir(m.group(1)), SCORE_EXACT, "Libellé lieu de travail trouvé, valeur capturée juste après")


# --------------------------------------------------------------------------
# Justification des absences
# --------------------------------------------------------------------------

LIBELLES_JUSTIFICATION_ABSENCE = ["JUSTIFICATION DES ABSENCES", "JUSTIFICATION D'ABSENCE", "JUSTIFICATION D ABSENCE", "ABSENCE"]
_MOTIF_DELAI_HEURES = re.compile(r"(\d{1,3})\s*HEURES")
_MOTIF_ORGANISME = re.compile(r"AUPRES DE\s+(?:LA SOCIETE\s+|LA STE\s+|L'ORGANISME\s+)?([A-Z0-9°\-][A-Z0-9°\- ]{1,30})")


def _extraire_justification_absence(texte: str, texte_norm: str) -> tuple[ChampExtrait, ChampExtrait]:
    fen = _fenetre(texte, texte_norm, LIBELLES_JUSTIFICATION_ABSENCE, taille=400)
    if fen is None:
        raison = f"Aucun des libellés {LIBELLES_JUSTIFICATION_ABSENCE} trouvé"
        return ChampExtrait(None, SCORE_NON_TROUVE, raison), ChampExtrait(None, SCORE_NON_TROUVE, raison)

    delai = _entier(fen, _MOTIF_DELAI_HEURES)
    champ_delai = (
        ChampExtrait(delai, SCORE_EXACT, "Délai en heures trouvé dans la section justification des absences")
        if delai is not None
        else ChampExtrait(None, SCORE_NON_TROUVE, "Section justification des absences trouvée mais aucun délai en heures lisible")
    )

    fen_norm = _texte_normalise(fen)
    m_org = _MOTIF_ORGANISME.search(fen_norm)
    champ_org = (
        ChampExtrait(m_org.group(1).strip().title(), SCORE_AMBIGU, "Nom d'organisme trouvé après « auprès de »")
        if m_org
        else ChampExtrait(None, SCORE_NON_TROUVE, "Aucun nom d'organisme trouvé après « auprès de »")
    )
    return champ_delai, champ_org


# --------------------------------------------------------------------------
# Signature
# --------------------------------------------------------------------------

# "FAIT A ..." ou "FAIT EN DEUX EXEMPLAIRES A ..." (cas réel observé) :
# jusqu'à 4 mots tolérés entre "FAIT" et "A" avant le lieu.
_MOTIF_FAIT_A = re.compile(r"FAIT\s+(?:\S+\s+){0,4}?A\s+([A-Z][A-Z\-\s]{1,40}?),?\s+LE\s+(.{4,40}?)(?:\.|\n|$)")


def _extraire_signature(texte: str, texte_norm: str) -> tuple[ChampExtrait, ChampExtrait]:
    zone = texte[-1200:]
    zone_norm = _texte_normalise(zone)
    m = _MOTIF_FAIT_A.search(zone_norm)
    if not m:
        raison = "Aucun motif « Fait à ..., le ... » trouvé en fin de document"
        return ChampExtrait(None, SCORE_NON_TROUVE, raison), ChampExtrait(None, SCORE_NON_TROUVE, raison)

    lieu = zone[m.start(1) : m.end(1)].strip().title()
    date_texte = zone[m.start(2) : m.end(2)]
    d = _parse_date(date_texte)
    champ_date = (
        ChampExtrait(d, SCORE_EXACT, "Date trouvée dans le motif « Fait à ..., le ... »")
        if d is not None
        else ChampExtrait(None, SCORE_AMBIGU, "Motif « Fait à ..., le ... » trouvé mais date illisible")
    )
    champ_lieu = ChampExtrait(lieu, SCORE_EXACT, "Lieu trouvé dans le motif « Fait à ..., le ... »")
    return champ_date, champ_lieu


# --------------------------------------------------------------------------
# Point d'entrée
# --------------------------------------------------------------------------


def extraire_contrat(chemin_pdf: str | Path) -> dict[str, ChampExtrait]:
    """Extrait tous les champs de ContratTravail (shared/schemas/contrat.py)
    localisables dans le PDF donné, chacun avec son score de confiance."""
    texte = extraire_texte_pdf(chemin_pdf)
    texte_norm = _texte_normalise(texte)

    champs: dict[str, ChampExtrait] = {}

    prenom, nom = _extraire_identite(texte, texte_norm)
    champs["prenom"] = prenom
    champs["nom"] = nom

    champs["poste"] = _extraire_poste(texte, texte_norm)
    champs["date_effet"] = _extraire_date_effet(texte, texte_norm)
    champs["type_contrat"] = _extraire_type_contrat(texte_norm)
    champs["convention_collective"] = _extraire_convention(texte, texte_norm)
    champs["statut"] = _extraire_statut(texte, texte_norm)
    champs["position"] = _extraire_position(texte, texte_norm)
    champs["coefficient"] = _extraire_coefficient(texte, texte_norm)

    rem_an, rem_mens = _extraire_remuneration(texte, texte_norm)
    champs["remuneration_annuelle_brute"] = rem_an
    champs["remuneration_mensuelle_brute"] = rem_mens
    champs["heures_mensuelles"] = _extraire_heures_mensuelles(texte, texte_norm)

    pe_mois, pe_renouv = _extraire_periode_essai(texte, texte_norm)
    champs["periode_essai_mois"] = pe_mois
    champs["periode_essai_renouvelable"] = pe_renouv

    champs["rtt_par_an"] = _extraire_rtt(texte, texte_norm)
    champs["periode_reference_conges"] = _extraire_periode_reference_conges(texte, texte_norm)

    nc, nc_duree, nc_indem = _extraire_non_concurrence(texte, texte_norm)
    champs["clause_non_concurrence"] = nc
    champs["duree_non_concurrence_mois"] = nc_duree
    champs["indemnite_non_concurrence_mois_salaire"] = nc_indem

    fo, fo_duree = _extraire_formation(texte, texte_norm)
    champs["clause_formation"] = fo
    champs["duree_engagement_formation_mois"] = fo_duree

    champs["lieu_travail"] = _extraire_lieu_travail(texte, texte_norm)

    delai, organisme = _extraire_justification_absence(texte, texte_norm)
    champs["delai_justification_absence_heures"] = delai
    champs["organisme_justification_absence"] = organisme

    date_sig, lieu_sig = _extraire_signature(texte, texte_norm)
    champs["date_signature"] = date_sig
    champs["lieu_signature"] = lieu_sig

    return champs
