from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import anthropic
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from .parser import Listing

log = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-haiku-4-5"
DEFAULT_MAX_TOKENS = 256

DEFAULT_SYSTEM_PROMPT = """Du bewertest Office-Monitor-Inserate auf Kleinanzeigen.de als Preis-Leistungs-Käufe für ein Budget bis 50€.

Antworte ausschließlich im JSON-Schema mit:
- recommended (bool): true nur wenn echter P/L-Kauf für ein Office-Setup
- reason (string, max 1 kurzer Satz auf Deutsch): warum ja oder nein

Kriterien für recommended=true (alle sollten erfüllt sein):
- Etablierte Office/Business-Marke (Dell, HP, Lenovo, Eizo, Fujitsu, Samsung Business/SyncMaster, BenQ, NEC, Iiyama)
- Mindestgröße 22 Zoll (24"+ bevorzugt)
- Auflösung mindestens FullHD (1920x1080), oder unklar aber Marke + Größe stimmen
- Preis im Budget (Beschreibung beachten - VB heißt verhandelbar)
- Kein Hinweis auf größere Defekte / Pixelfehler / kaputte Anschlüsse

Kriterien für recommended=false:
- Junk/No-Name-Marken oder unbekannte Hersteller
- Unter 22 Zoll
- Sub-FullHD (1280x1024, 1440x900 etc.) oder altes 4:3-Format ohne klaren Grund
- Defekt-/Schaden-Hinweise in der Beschreibung
- Reine Konsumer-Modelle (z.B. Acer/AOC Gamer-Reihen ohne Office-Eignung)
- Wenn aus Titel + Beschreibung das Modell überhaupt nicht identifizierbar ist

Sei eher streng - der Watcher soll nur klare P/L-Sieger melden, keine Maybes."""


class Verdict(BaseModel):
    recommended: bool
    reason: str = Field(default="", max_length=400)


class Evaluator:
    def __init__(
        self,
        *,
        api_key: str,
        model: str = DEFAULT_MODEL,
        system_prompt: str = DEFAULT_SYSTEM_PROMPT,
        client: anthropic.Anthropic | None = None,
    ) -> None:
        self._client = client or anthropic.Anthropic(api_key=api_key)
        self._model = model
        self._system = system_prompt

    def evaluate(self, listing: Listing, *, system_prompt: str | None = None) -> Verdict:
        user_msg = (
            f"Titel: {listing.title}\n"
            f"Preis: {listing.price}\n"
            f"Ort: {listing.location}"
            + (f" ({listing.distance})" if listing.distance else "")
            + "\n"
            f"Beschreibung: {listing.description or '(keine Beschreibung)'}"
        )
        try:
            response = self._client.messages.parse(
                model=self._model,
                max_tokens=DEFAULT_MAX_TOKENS,
                system=system_prompt or self._system,
                messages=[{"role": "user", "content": user_msg}],
                output_format=Verdict,
            )
        except (anthropic.APIError, anthropic.APIStatusError) as exc:
            log.warning("evaluator API error for listing %s: %s — defaulting to not-recommended", listing.id, exc)
            return Verdict(recommended=False, reason="(Bewertung fehlgeschlagen, Listing übersprungen)")

        parsed: Verdict = response.parsed_output
        return parsed
