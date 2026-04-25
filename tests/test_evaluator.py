from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock

import anthropic
import pytest

from kleinanzeigen_watcher.evaluator import DEFAULT_SYSTEM_PROMPT, Evaluator, Verdict
from kleinanzeigen_watcher.parser import Listing


def _listing(title: str = "Dell U2412M 24 Zoll Office", price: str = "40 € VB", description: str = "Sehr guter Zustand, FullHD") -> Listing:
    return Listing(
        id="1", title=title, url="https://example.com/x/1",
        price=price, location="01067 Dresden", description=description,
        image_url=None, posted_at=datetime(2026, 4, 25),
        is_topad=False, is_pro=False, distance="5 km",
    )


def _ok_response(verdict: Verdict) -> MagicMock:
    response = MagicMock()
    response.parsed_output = verdict
    return response


def test_evaluate_returns_verdict_from_parsed_output() -> None:
    expected = Verdict(recommended=True, reason="Dell-Marke, 24 Zoll, FullHD, im Budget")
    client = MagicMock()
    client.messages.parse.return_value = _ok_response(expected)

    evaluator = Evaluator(api_key="x", client=client)
    result = evaluator.evaluate(_listing())

    assert result == expected


def test_evaluate_uses_haiku_45_by_default() -> None:
    client = MagicMock()
    client.messages.parse.return_value = _ok_response(Verdict(recommended=False, reason="x"))
    evaluator = Evaluator(api_key="x", client=client)

    evaluator.evaluate(_listing())

    call_kwargs = client.messages.parse.call_args.kwargs
    assert call_kwargs["model"] == "claude-haiku-4-5"


def test_evaluate_passes_listing_fields_in_user_message() -> None:
    client = MagicMock()
    client.messages.parse.return_value = _ok_response(Verdict(recommended=True, reason="y"))
    evaluator = Evaluator(api_key="x", client=client)

    evaluator.evaluate(_listing(title="HP EliteDisplay E243", price="35 €", description="Funktioniert einwandfrei"))

    user_msg = client.messages.parse.call_args.kwargs["messages"][0]["content"]
    assert "HP EliteDisplay E243" in user_msg
    assert "35 €" in user_msg
    assert "Funktioniert einwandfrei" in user_msg


def test_evaluate_uses_default_system_prompt() -> None:
    client = MagicMock()
    client.messages.parse.return_value = _ok_response(Verdict(recommended=True, reason="z"))
    evaluator = Evaluator(api_key="x", client=client)

    evaluator.evaluate(_listing())

    assert client.messages.parse.call_args.kwargs["system"] == DEFAULT_SYSTEM_PROMPT


def test_evaluate_supports_custom_system_prompt() -> None:
    client = MagicMock()
    client.messages.parse.return_value = _ok_response(Verdict(recommended=False, reason="."))
    custom = "Du bewertest nur Stehlampen. Antwort: JA/NEIN."

    evaluator = Evaluator(api_key="x", client=client, system_prompt=custom)
    evaluator.evaluate(_listing())

    assert client.messages.parse.call_args.kwargs["system"] == custom


def test_evaluate_uses_output_format_with_verdict_pydantic() -> None:
    client = MagicMock()
    client.messages.parse.return_value = _ok_response(Verdict(recommended=True, reason="ok"))
    evaluator = Evaluator(api_key="x", client=client)

    evaluator.evaluate(_listing())

    assert client.messages.parse.call_args.kwargs["output_format"] is Verdict


def test_api_error_yields_safe_default_not_recommended() -> None:
    client = MagicMock()
    client.messages.parse.side_effect = anthropic.APIError(
        message="boom", request=MagicMock(), body=None,
    )
    evaluator = Evaluator(api_key="x", client=client)

    result = evaluator.evaluate(_listing())

    assert result.recommended is False
    assert "Bewertung" in result.reason or "Fehler" in result.reason


def test_evaluate_max_tokens_kept_small() -> None:
    client = MagicMock()
    client.messages.parse.return_value = _ok_response(Verdict(recommended=True, reason="ok"))
    evaluator = Evaluator(api_key="x", client=client)

    evaluator.evaluate(_listing())

    assert client.messages.parse.call_args.kwargs["max_tokens"] <= 512


def test_verdict_pydantic_model_has_required_fields() -> None:
    v = Verdict(recommended=True, reason="weil")
    assert v.recommended is True
    assert v.reason == "weil"
