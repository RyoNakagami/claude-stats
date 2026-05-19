"""Tests for claude_stats._cli"""

import json
import textwrap
from pathlib import Path
from unittest import mock

import pytest

from claude_stats._cli import (
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