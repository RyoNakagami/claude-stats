"""Tests for claude_stats._cli"""

import json
import textwrap
from pathlib import Path
from unittest import mock

import pytest
from typer.testing import CliRunner

from claude_stats._cli import (
    _human_text,
    app,
    bar_chart,
    cache_savings,
    calc_cost,
    fmt_cost,
    fmt_tokens,
    get_price,
    get_projects_dir,
    load_pricing,
    load_records,
)
from claude_stats._version import get_version

runner = CliRunner()

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def default_pricing():
    return load_pricing()  # bundled pricing.yml


@pytest.fixture()
def custom_pricing(tmp_path):
    yml = tmp_path / "custom.yml"
    yml.write_text(textwrap.dedent("""\
        defaults:
          input: 1.0
          output: 5.0
          cache_write_5m: 1.25
          cache_write_1h: 2.0
          cache_read: 0.10
        models:
          my-model:
            input: 2.0
            output: 10.0
            cache_write_5m: 2.5
            cache_write_1h: 4.0
            cache_read: 0.20
    """))
    return load_pricing(str(yml))


# ---------------------------------------------------------------------------
# load_pricing
# ---------------------------------------------------------------------------

def test_load_pricing_bundled(default_pricing):
    assert "defaults" in default_pricing
    assert "models" in default_pricing


def test_load_pricing_custom(tmp_path):
    yml = tmp_path / "p.yml"
    yml.write_text("defaults:\n  input: 9.9\nmodels: {}\n")
    pricing = load_pricing(str(yml))
    assert pricing["defaults"]["input"] == 9.9


# ---------------------------------------------------------------------------
# get_price
# ---------------------------------------------------------------------------

def test_get_price_exact_match(default_pricing):
    p = get_price("claude-sonnet-4-6", default_pricing)
    assert p["input"] == 3.0
    assert p["output"] == 15.0


def test_get_price_prefix_match(default_pricing):
    p = get_price("claude-sonnet-4-6-something-extra", default_pricing)
    assert p["input"] == 3.0


def test_get_price_unknown_falls_back_to_defaults(default_pricing):
    p = get_price("totally-unknown-model", default_pricing)
    defaults = default_pricing["defaults"]
    assert p == defaults


def test_get_price_custom(custom_pricing):
    p = get_price("my-model", custom_pricing)
    assert p["input"] == 2.0
    unknown = get_price("other", custom_pricing)
    assert unknown["input"] == 1.0


# ---------------------------------------------------------------------------
# calc_cost
# ---------------------------------------------------------------------------

def test_calc_cost_basic(default_pricing):
    usage = {"input_tokens": 1_000_000, "output_tokens": 0}
    cost = calc_cost(usage, "claude-sonnet-4-6", default_pricing)
    assert cost == pytest.approx(3.0)


def test_calc_cost_output(default_pricing):
    usage = {"input_tokens": 0, "output_tokens": 1_000_000}
    cost = calc_cost(usage, "claude-sonnet-4-6", default_pricing)
    assert cost == pytest.approx(15.0)


def test_calc_cost_cache_read(default_pricing):
    usage = {"input_tokens": 0, "cache_read_input_tokens": 1_000_000}
    cost = calc_cost(usage, "claude-sonnet-4-6", default_pricing)
    assert cost == pytest.approx(0.30)


def test_calc_cost_cache_creation_legacy(default_pricing):
    # Old format: flat cache_creation_input_tokens field
    usage = {"input_tokens": 0, "cache_creation_input_tokens": 1_000_000}
    cost = calc_cost(usage, "claude-sonnet-4-6", default_pricing)
    assert cost == pytest.approx(3.75)


def test_calc_cost_cache_creation_nested(default_pricing):
    usage = {
        "input_tokens": 0,
        "cache_creation": {"ephemeral_5m_input_tokens": 1_000_000},
    }
    cost = calc_cost(usage, "claude-sonnet-4-6", default_pricing)
    assert cost == pytest.approx(3.75)


# ---------------------------------------------------------------------------
# cache_savings
# ---------------------------------------------------------------------------

def test_cache_savings_zero_when_no_reads(default_pricing):
    assert cache_savings({}, "claude-sonnet-4-6", default_pricing) == 0.0


def test_cache_savings_correct(default_pricing):
    usage = {"cache_read_input_tokens": 1_000_000}
    savings = cache_savings(usage, "claude-sonnet-4-6", default_pricing)
    # input(3.0) - cache_read(0.30) = 2.70 per 1M
    assert savings == pytest.approx(2.70)


# ---------------------------------------------------------------------------
# fmt_cost / fmt_tokens
# ---------------------------------------------------------------------------

def test_fmt_cost():
    assert fmt_cost(1.23456) == "$1.2346"
    assert fmt_cost(0.0) == "$0.0000"


def test_fmt_tokens_large():
    assert fmt_tokens(2_500_000) == "2.5M"


def test_fmt_tokens_kilo():
    assert fmt_tokens(1_500) == "1.5k"


def test_fmt_tokens_small():
    assert fmt_tokens(42) == "42"


# ---------------------------------------------------------------------------
# bar_chart
# ---------------------------------------------------------------------------

def test_bar_chart_full():
    result = bar_chart(10.0, 10.0, width=4)
    assert result == "████"


def test_bar_chart_half():
    result = bar_chart(5.0, 10.0, width=4)
    assert result == "██░░"


def test_bar_chart_zero_max():
    assert bar_chart(1.0, 0.0) == ""


# ---------------------------------------------------------------------------
# load_records
# ---------------------------------------------------------------------------

def _make_record(model: str = "claude-sonnet-4-6", ts: str = "2026-01-01T00:00:00Z") -> dict:
    return {
        "type": "assistant",
        "timestamp": ts,
        "uuid": "test-uuid",
        "message": {
            "model": model,
            "usage": {
                "input_tokens": 100,
                "output_tokens": 50,
                "cache_read_input_tokens": 0,
                "cache_creation_input_tokens": 0,
            },
        },
    }


@pytest.fixture()
def projects_dir(tmp_path, default_pricing):
    proj = tmp_path / "my-project"
    proj.mkdir()
    session = proj / "session-abc.jsonl"
    session.write_text(json.dumps(_make_record()) + "\n")
    return tmp_path


def test_load_records_basic(projects_dir, default_pricing):
    records = load_records(projects_dir, default_pricing)
    assert len(records) == 1
    r = records[0]
    assert r["project"] == "my-project"
    assert r["model"] == "claude-sonnet-4-6"
    assert r["cost"] > 0


def test_load_records_project_filter(projects_dir, default_pricing):
    # Non-matching filter returns empty
    records = load_records(projects_dir, default_pricing, project_filter="other")
    assert records == []

    # Matching filter returns records
    records = load_records(projects_dir, default_pricing, project_filter="my")
    assert len(records) == 1


def test_load_records_skips_non_assistant(tmp_path, default_pricing):
    proj = tmp_path / "p"
    proj.mkdir()
    session = proj / "s.jsonl"
    user_rec = {"type": "user", "message": {"usage": {"input_tokens": 100}}}
    session.write_text(json.dumps(user_rec) + "\n")
    records = load_records(tmp_path, default_pricing)
    assert records == []


def test_load_records_days_filter(tmp_path, default_pricing):
    proj = tmp_path / "p"
    proj.mkdir()
    session = proj / "s.jsonl"
    old_rec = _make_record(ts="2020-01-01T00:00:00Z")
    session.write_text(json.dumps(old_rec) + "\n")
    records = load_records(tmp_path, default_pricing, days=7)
    assert records == []


# ---------------------------------------------------------------------------
# get_version
# ---------------------------------------------------------------------------

def test_get_version_returns_string():
    v = get_version()
    assert isinstance(v, str)
    assert len(v) > 0


# ---------------------------------------------------------------------------
# get_projects_dir
# ---------------------------------------------------------------------------

def test_get_projects_dir_override():
    assert get_projects_dir("/custom/path") == Path("/custom/path")


def test_get_projects_dir_linux_default():
    with mock.patch("platform.system", return_value="Linux"):
        path = get_projects_dir(None)
    assert path == Path.home() / ".claude" / "projects"


def test_get_projects_dir_mac_default():
    with mock.patch("platform.system", return_value="Darwin"):
        path = get_projects_dir(None)
    assert path == Path.home() / ".claude" / "projects"


def test_get_projects_dir_windows_default():
    with mock.patch("platform.system", return_value="Windows"), \
         mock.patch.dict("os.environ", {"APPDATA": "C:\\Users\\test\\AppData\\Roaming"}):
        path = get_projects_dir(None)
    assert path == Path("C:\\Users\\test\\AppData\\Roaming") / "Claude" / "projects"


def test_get_projects_dir_windows_no_appdata_fallback():
    env = {k: v for k, v in __import__("os").environ.items() if k != "APPDATA"}
    with mock.patch("platform.system", return_value="Windows"), \
         mock.patch.dict("os.environ", env, clear=True):
        path = get_projects_dir(None)
    assert path == Path.home() / ".claude" / "projects"


# ---------------------------------------------------------------------------
# _human_text
# ---------------------------------------------------------------------------

def _user_record(text: str) -> dict:
    return {"type": "user", "message": {"role": "user", "content": [{"type": "text", "text": text}]}}


def test_human_text_plain():
    assert _human_text(_user_record("hello world")) == "hello world"


def test_human_text_strips_paired_system_tag():
    rec = _user_record("<ide_opened_file>secret path</ide_opened_file>\nreal prompt")
    assert _human_text(rec) == "real prompt"


def test_human_text_strips_orphaned_closing_tag():
    rec = _user_record("before</ide_selection>\nreal prompt")
    assert _human_text(rec) == "before\nreal prompt"


def test_human_text_skips_tool_result_content():
    rec = {
        "type": "user",
        "message": {"role": "user", "content": [{"type": "tool_result", "content": "output"}]},
    }
    assert _human_text(rec) == ""


def test_human_text_filters_interrupted():
    rec = _user_record("[Request interrupted by user]")
    assert _human_text(rec) == ""


def test_human_text_joins_multiple_blocks():
    rec = {
        "type": "user",
        "message": {"role": "user", "content": [
            {"type": "text", "text": "first"},
            {"type": "text", "text": "second"},
        ]},
    }
    assert _human_text(rec) == "first\nsecond"


def _user_record_str(text: str) -> dict:
    return {"type": "user", "message": {"role": "user", "content": text}}


def test_human_text_string_content_plain():
    assert _human_text(_user_record_str("実装してください")) == "実装してください"


def test_human_text_string_content_with_code():
    text = "#!/bin/bash\necho hi\n実装してください"
    assert _human_text(_user_record_str(text)) == text


def test_human_text_string_local_command_caveat():
    rec = _user_record_str("<local-command-caveat>ignored</local-command-caveat>")
    assert _human_text(rec) == ""


def test_human_text_string_command_name():
    rec = _user_record_str("<command-name>/model</command-name>\n<command-message>x</command-message>")
    assert _human_text(rec) == ""


def test_human_text_string_local_command_stdout():
    rec = _user_record_str("<local-command-stdout>output</local-command-stdout>")
    assert _human_text(rec) == ""


# ---------------------------------------------------------------------------
# show command fixtures
# ---------------------------------------------------------------------------

SESSION_ID = "abcd1234-0000-0000-0000-000000000000"


def _make_session_records():
    return [
        {
            "type": "user", "uuid": "u1", "parentUuid": None,
            "timestamp": "2026-01-01T00:00:00Z",
            "message": {"role": "user", "content": [{"type": "text", "text": "hello"}]},
        },
        {
            "type": "assistant", "uuid": "a1", "parentUuid": "u1",
            "timestamp": "2026-01-01T00:01:00Z",
            "message": {
                "model": "claude-sonnet-4-6",
                "usage": {
                    "input_tokens": 1_000_000, "output_tokens": 0,
                    "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0,
                },
            },
        },
        {
            "type": "user", "uuid": "u2", "parentUuid": "a1",
            "timestamp": "2026-01-01T00:02:00Z",
            "message": {"role": "user", "content": [{"type": "text", "text": "world"}]},
        },
        {
            "type": "assistant", "uuid": "a2", "parentUuid": "u2",
            "timestamp": "2026-01-01T00:03:00Z",
            "message": {
                "model": "claude-sonnet-4-6",
                "usage": {
                    "input_tokens": 0, "output_tokens": 1_000_000,
                    "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0,
                },
            },
        },
    ]


@pytest.fixture()
def show_dir(tmp_path):
    proj = tmp_path / "test-project"
    proj.mkdir()
    session = proj / f"{SESSION_ID}.jsonl"
    session.write_text("\n".join(json.dumps(r) for r in _make_session_records()) + "\n")
    return tmp_path


# ---------------------------------------------------------------------------
# show command — error cases
# ---------------------------------------------------------------------------

def test_show_not_found(show_dir):
    result = runner.invoke(app, ["show", "ffffffff", "--dir", str(show_dir)])
    assert result.exit_code != 0


def test_show_ambiguous_prefix(tmp_path):
    for name in ("abcd1111-x.jsonl", "abcd2222-x.jsonl"):
        proj = tmp_path / "p"
        proj.mkdir(exist_ok=True)
        (proj / name).write_text(json.dumps(_make_session_records()[0]) + "\n")
    result = runner.invoke(app, ["show", "abcd", "--dir", str(tmp_path)])
    assert result.exit_code != 0


# ---------------------------------------------------------------------------
# show command — happy path
# ---------------------------------------------------------------------------

def test_show_returns_valid_json(show_dir):
    result = runner.invoke(app, ["show", SESSION_ID, "--dir", str(show_dir)])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["session_id"] == SESSION_ID
    assert data["project"] == "test-project"
    assert data["model"] == "claude-sonnet-4-6"


def test_show_prefix_match(show_dir):
    result = runner.invoke(app, ["show", "abcd1234", "--dir", str(show_dir)])
    assert result.exit_code == 0
    assert json.loads(result.output)["session_id"] == SESSION_ID


def test_show_turn_structure(show_dir):
    result = runner.invoke(app, ["show", SESSION_ID, "--dir", str(show_dir)])
    data = json.loads(result.output)
    assert data["human_turns"] == 2
    assert data["assistant_responses"] == 2
    turns = data["turns"]
    assert len(turns) == 2
    assert turns[0]["prompt"] == "hello"
    assert turns[1]["prompt"] == "world"


def test_show_turn_costs(show_dir):
    result = runner.invoke(app, ["show", SESSION_ID, "--dir", str(show_dir)])
    data = json.loads(result.output)
    turns = data["turns"]
    # turn 1: 1M input tokens @ claude-sonnet-4-6 = $3.00
    assert turns[0]["cost_usd"] == pytest.approx(3.0)
    # turn 2: 1M output tokens @ claude-sonnet-4-6 = $15.00
    assert turns[1]["cost_usd"] == pytest.approx(15.0)


def test_show_total_cost(show_dir):
    result = runner.invoke(app, ["show", SESSION_ID, "--dir", str(show_dir)])
    data = json.loads(result.output)
    assert data["total_cost_usd"] == pytest.approx(18.0)  # $3 + $15


def test_show_period(show_dir):
    result = runner.invoke(app, ["show", SESSION_ID, "--dir", str(show_dir)])
    data = json.loads(result.output)
    assert data["period"]["start"] == "2026-01-01T00:00:00Z"
    assert data["period"]["end"] == "2026-01-01T00:03:00Z"


def test_show_string_content_counts_as_human_turn(tmp_path):
    session_id = "str00001-0000-0000-0000-000000000000"
    prompt = "#!/bin/bash\necho hi\nを踏まえて実装してください"
    records = [
        {
            "type": "user", "uuid": "u1", "parentUuid": None,
            "timestamp": "2026-01-01T00:00:00Z",
            "message": {"role": "user", "content": prompt},
        },
        {
            "type": "assistant", "uuid": "a1", "parentUuid": "u1",
            "timestamp": "2026-01-01T00:01:00Z",
            "message": {
                "model": "claude-sonnet-4-6",
                "usage": {
                    "input_tokens": 1_000_000, "output_tokens": 0,
                    "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0,
                },
            },
        },
    ]
    proj = tmp_path / "test-project"
    proj.mkdir()
    (proj / f"{session_id}.jsonl").write_text("\n".join(json.dumps(r) for r in records) + "\n")

    result = runner.invoke(app, ["show", session_id, "--dir", str(tmp_path)])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["human_turns"] >= 1
    assert any(t["prompt"] == prompt for t in data["turns"])