"""
orchestrateur/app/state_machine.py

Machine à états A1->A6 avec les boucles de retour prévues par le guide :
- A2.3 : écart détecté en contrôle pré-calcul -> remontée au client -> A1
- A3.3 : échec du calcul (mock Sage) -> nouvelle tentative -> A3
- A4.3 : correction demandée en post-calcul -> retour A3 (recalcul) OU
         retour A2.3 (le problème vient en fait des données amont)

Principe du guide (erreur fréquente à éviter en Phase 3) : ces boucles
sont de VRAIES transitions de la machine à états, pas des cas particuliers
codés à côté. Elles sont donc déclarées ici au même titre que les autres.

100% déterministe : aucune IA n'intervient dans le choix de transition,
c'est toujours un appel explicite (API) qui déclenche un trigger nommé.
"""

from __future__ import annotations

from typing import Callable, Optional

from transitions import Machine, MachineError

ETATS = [
    "A1",  # Collecte
    "A2",  # Contrôle de conformité (pré-calcul)
    "A2_3",  # Boucle : écart détecté, remontée au client
    "A3",  # Calcul (Sage / mock Sage)
    "A3_3",  # Boucle : échec du calcul
    "A4",  # Validation (post-calcul)
    "A4_3",  # Boucle : correction demandée
    "A5",  # Paiement
    "A6",  # DSN et obligations légales
    "TERMINE",
    "REJETE",
]

# (trigger, source, destination) — définit le graphe complet du pipeline
TRANSITIONS = [
    ("extraire_evp", "A1", "A2"),
    ("detecter_ecart", "A2", "A2_3"),
    ("corriger_evp", "A2_3", "A1"),
    ("valider_transmission", "A2", "A3"),  # inclut la transmission Sage
    ("echec_calcul", "A3", "A3_3"),
    ("relancer_calcul", "A3_3", "A3"),
    ("calcul_termine", "A3", "A4"),
    ("demander_correction", "A4", "A4_3"),
    ("retour_calcul", "A4_3", "A3"),
    ("retour_controle", "A4_3", "A2_3"),
    ("valider_bulletin", "A4", "A5"),
    ("rejeter", "A4", "REJETE"),
    ("autoriser_paiement", "A5", "A6"),
    ("cloturer", "A6", "TERMINE"),
]


class DossierStateMachine:
    """Enveloppe légère autour de `transitions.Machine` pour un dossier."""

    def __init__(self, etat_initial: str = "A1", on_transition: Optional[Callable] = None):
        self._on_transition_callback = on_transition
        self.machine = Machine(
            model=self,
            states=ETATS,
            initial=etat_initial,
            auto_transitions=False,
            send_event=True,
        )
        for trigger, source, dest in TRANSITIONS:
            self.machine.add_transition(
                trigger=trigger, source=source, dest=dest, after="_log"
            )

    def _log(self, event):
        if self._on_transition_callback:
            self._on_transition_callback(event)

    def declencher(self, action: str) -> str:
        """Déclenche un trigger par son nom. Lève MachineError si invalide
        depuis l'état courant (capturé par l'API en 409)."""
        if not hasattr(self, action):
            raise MachineError(f"Action inconnue: {action!r}")
        getattr(self, action)()
        return self.state

    def triggers_disponibles(self) -> list[str]:
        return self.machine.get_triggers(self.state)
