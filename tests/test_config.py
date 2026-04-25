from __future__ import annotations

from pathlib import Path

import pytest

from kleinanzeigen_watcher.config import Config, Profile, load_config


def _write(tmp_path: Path, content: str) -> Path:
    cfg = tmp_path / "config.yaml"
    cfg.write_text(content, encoding="utf-8")
    return cfg


VALID_ENV = {"TELEGRAM_BOT_TOKEN": "123:abc", "TELEGRAM_CHAT_ID": "456"}


def test_loads_minimal_config(tmp_path: Path) -> None:
    cfg = _write(tmp_path, """
defaults:
  poll_interval_minutes: 10
profiles:
  - name: monitors
    query: office monitor
""")
    result = load_config(cfg, env=VALID_ENV)
    assert isinstance(result, Config)
    assert len(result.profiles) == 1
    p = result.profiles[0]
    assert p.name == "monitors"
    assert p.query == "office monitor"
    assert p.enabled is True
    assert p.poll_interval_minutes == 10


def test_defaults_inherited_into_profile(tmp_path: Path) -> None:
    cfg = _write(tmp_path, """
defaults:
  poll_interval_minutes: 30
profiles:
  - name: a
    query: x
  - name: b
    query: y
    poll_interval_minutes: 5
""")
    result = load_config(cfg, env=VALID_ENV)
    assert result.profiles[0].poll_interval_minutes == 30
    assert result.profiles[1].poll_interval_minutes == 5


def test_default_user_agents_present_when_absent_in_config(tmp_path: Path) -> None:
    cfg = _write(tmp_path, """
profiles:
  - name: a
    query: x
""")
    result = load_config(cfg, env=VALID_ENV)
    assert len(result.user_agents) >= 1


def test_user_agents_from_config_override_defaults(tmp_path: Path) -> None:
    cfg = _write(tmp_path, """
defaults:
  user_agents:
    - "Mozilla/5.0 custom"
profiles:
  - name: a
    query: x
""")
    result = load_config(cfg, env=VALID_ENV)
    assert result.user_agents == ["Mozilla/5.0 custom"]


def test_profile_with_no_name_raises(tmp_path: Path) -> None:
    cfg = _write(tmp_path, """
profiles:
  - query: x
""")
    with pytest.raises(ValueError, match="name"):
        load_config(cfg, env=VALID_ENV)


def test_profile_without_query_or_category_raises(tmp_path: Path) -> None:
    cfg = _write(tmp_path, """
profiles:
  - name: a
    enabled: true
""")
    with pytest.raises(ValueError, match="query"):
        load_config(cfg, env=VALID_ENV)


def test_profile_radius_without_plz_raises(tmp_path: Path) -> None:
    cfg = _write(tmp_path, """
profiles:
  - name: a
    query: x
    radius_km: 20
""")
    with pytest.raises(ValueError, match="plz"):
        load_config(cfg, env=VALID_ENV)


def test_disabled_profile_loads_without_filter(tmp_path: Path) -> None:
    cfg = _write(tmp_path, """
profiles:
  - name: a
    query: x
  - name: b
    enabled: false
    query: y
""")
    result = load_config(cfg, env=VALID_ENV)
    assert {p.name for p in result.profiles} == {"a", "b"}
    assert next(p for p in result.profiles if p.name == "b").enabled is False


def test_active_profiles_helper_filters_disabled(tmp_path: Path) -> None:
    cfg = _write(tmp_path, """
profiles:
  - name: a
    query: x
  - name: b
    enabled: false
    query: y
""")
    result = load_config(cfg, env=VALID_ENV)
    assert [p.name for p in result.active_profiles()] == ["a"]


def test_missing_telegram_env_raises(tmp_path: Path) -> None:
    cfg = _write(tmp_path, """
profiles:
  - name: a
    query: x
""")
    with pytest.raises(ValueError, match="TELEGRAM_BOT_TOKEN"):
        load_config(cfg, env={"TELEGRAM_CHAT_ID": "1"})
    with pytest.raises(ValueError, match="TELEGRAM_CHAT_ID"):
        load_config(cfg, env={"TELEGRAM_BOT_TOKEN": "1"})


def test_loads_example_config_from_repo() -> None:
    repo_root = Path(__file__).parent.parent
    result = load_config(repo_root / "config.example.yaml", env=VALID_ENV)
    assert len(result.profiles) >= 2
    assert all(isinstance(p, Profile) for p in result.profiles)


def test_db_path_default(tmp_path: Path) -> None:
    cfg = _write(tmp_path, """
profiles:
  - name: a
    query: x
""")
    result = load_config(cfg, env=VALID_ENV)
    assert result.db_path.name == "kleinanzeigen.db"


def test_db_path_overridable(tmp_path: Path) -> None:
    cfg = _write(tmp_path, """
defaults:
  db_path: /tmp/foo.db
profiles:
  - name: a
    query: x
""")
    result = load_config(cfg, env=VALID_ENV)
    assert str(result.db_path) == "/tmp/foo.db"


def test_ai_filter_default_false(tmp_path: Path) -> None:
    cfg = _write(tmp_path, """
profiles:
  - name: a
    query: x
""")
    result = load_config(cfg, env=VALID_ENV)
    assert result.profiles[0].ai_filter is False
    assert result.anthropic_api_key is None


def test_ai_filter_true_with_anthropic_key_loads(tmp_path: Path) -> None:
    cfg = _write(tmp_path, """
profiles:
  - name: a
    query: x
    ai_filter: true
""")
    env = {**VALID_ENV, "ANTHROPIC_API_KEY": "sk-ant-test"}
    result = load_config(cfg, env=env)
    assert result.profiles[0].ai_filter is True
    assert result.anthropic_api_key == "sk-ant-test"


def test_ai_filter_true_without_anthropic_key_raises(tmp_path: Path) -> None:
    cfg = _write(tmp_path, """
profiles:
  - name: a
    query: x
    ai_filter: true
""")
    with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
        load_config(cfg, env=VALID_ENV)


def test_evaluator_prompt_overridable_per_profile(tmp_path: Path) -> None:
    cfg = _write(tmp_path, """
profiles:
  - name: a
    query: x
    ai_filter: true
    evaluator_prompt: "Bewerte nur Stehlampen."
""")
    env = {**VALID_ENV, "ANTHROPIC_API_KEY": "k"}
    result = load_config(cfg, env=env)
    assert result.profiles[0].evaluator_prompt == "Bewerte nur Stehlampen."
