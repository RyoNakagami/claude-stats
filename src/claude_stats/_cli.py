"""Claude Code Cost Analyzer — analyzes ~/.claude/projects/ JSONL files."""

from __future__ import annotations

import json
import os
import platform
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from importlib.resources import files
from pathlib import Path
from typing import Optional

import typer
import yaml
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from claude_stats._version import get_version

app = typer.Typer(help="Claude Code cost analyzer", add_completion=False)
console = Console()


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(get_version())
        raise typer.Exit()


@app.callback()
def _main(
    version: Optional[bool] = typer.Option(
        None, "--version", "-v", callback=_version_callback, is_eager=True, help="Show version and exit"
    ),
) -> None:
    pass

# ---------------------------------------------------------------------------
# Pricing helpers
# ---------------------------------------------------------------------------

_BUNDLED_PRICING_PATH = files("claude_stats").joinpath("pricing.yml")


def load_pricing(path: Optional[str] = None) -> dict:
    src = Path(path) if path else Path(str(_BUNDLED_PRICING_PATH))
    with open(src, encoding="utf-8") as f:
        return yaml.safe_load(f)


def get_price(model: str, pricing: dict) -> dict:
    models = pricing.get("models", {})
    if model in models:
        return models[model]
    for key in models:
        if model.startswith(key) or key.startswith(model):
            return models[key]
    return pricing.get("defaults", {})


# ---------------------------------------------------------------------------
# Cost calculation
# ---------------------------------------------------------------------------

def calc_cost(usage: dict, model: str, pricing: dict) -> float:
    p = get_price(model, pricing)
    M = 1_000_000
    cost = 0.0
    cost += usage.get("input_tokens", 0) / M * p.get("input", 0)
    cost += usage.get("output_tokens", 0) / M * p.get("output", 0)
    cost += usage.get("cache_read_input_tokens", 0) / M * p.get("cache_read", 0)
    cache_c = usage.get("cache_creation", {})
    cost += cache_c.get("ephemeral_5m_input_tokens", 0) / M * p.get("cache_write_5m", 0)
    cost += cache_c.get("ephemeral_1h_input_tokens", 0) / M * p.get("cache_write_1h", 0)
    if not cache_c:
        cost += usage.get("cache_creation_input_tokens", 0) / M * p.get("cache_write_5m", 0)
    return cost


def cache_savings(usage: dict, model: str, pricing: dict) -> float:
    p = get_price(model, pricing)
    M = 1_000_000
    reads = usage.get("cache_read_input_tokens", 0)
    return reads / M * (p.get("input", 0) - p.get("cache_read", 0))


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def parse_jsonl(path: Path) -> list:
    records = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    except Exception:
        pass
    return records


def get_projects_dir(dir_override: Optional[str]) -> Path:
    if dir_override:
        return Path(dir_override)
    if platform.system() == "Windows":
        appdata = os.environ.get("APPDATA")
        if appdata:
            return Path(appdata) / "Claude" / "projects"
    return Path.home() / ".claude" / "projects"


def load_records(
    projects_dir: Path,
    pricing: dict,
    days: Optional[int] = None,
    project_filter: Optional[str] = None,
    since: Optional[str] = None,
    until: Optional[str] = None,
) -> list:
    cutoff_from = None
    cutoff_to = None
    if days:
        cutoff_from = datetime.now(timezone.utc) - timedelta(days=days)
    if since:
        cutoff_from = datetime.fromisoformat(since).replace(tzinfo=timezone.utc)
    if until:
        cutoff_to = datetime.fromisoformat(until).replace(tzinfo=timezone.utc)

    results = []
    for project_dir in sorted(projects_dir.iterdir()):
        if not project_dir.is_dir():
            continue
        proj_name = project_dir.name
        if project_filter and project_filter.lower() not in proj_name.lower():
            continue

        for jsonl_path in project_dir.rglob("*.jsonl"):
            session_id = jsonl_path.stem
            for rec in parse_jsonl(jsonl_path):
                if rec.get("type") != "assistant":
                    continue
                msg = rec.get("message", {})
                usage = msg.get("usage")
                if not usage:
                    continue

                ts_str = rec.get("timestamp", "")
                ts = None
                if ts_str:
                    try:
                        ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                    except Exception:
                        pass

                if cutoff_from and ts and ts < cutoff_from:
                    continue
                if cutoff_to and ts and ts > cutoff_to:
                    continue

                model = msg.get("model", "unknown")
                results.append({
                    "project":    proj_name,
                    "session_id": session_id,
                    "uuid":       rec.get("uuid", ""),
                    "timestamp":  ts,
                    "model":      model,
                    "usage":      usage,
                    "cost":       calc_cost(usage, model, pricing),
                    "savings":    cache_savings(usage, model, pricing),
                    "entrypoint": rec.get("entrypoint", ""),
                })

    return results


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def fmt_cost(c: float) -> str:
    return f"${c:.4f}"


def fmt_tokens(n: int) -> str:
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}k"
    return str(n)


def bar_chart(value: float, max_value: float, width: int = 25) -> str:
    if max_value == 0:
        return ""
    filled = int(value / max_value * width)
    return "█" * filled + "░" * (width - filled)


def period_label(days: Optional[int], since: Optional[str], until: Optional[str]) -> str:
    if days:
        return f"直近 {days} 日間"
    if since or until:
        return f"{since or '開始'} 〜 {until or '現在'}"
    return "全期間"


def model_short(model: str) -> str:
    return model.replace("claude-", "").replace("-20250514", "")


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

@app.command()
def summary(
    days:         Optional[int] = typer.Option(None, "--days",         "-d", help="直近N日間"),
    since:        Optional[str] = typer.Option(None, "--since",               help="開始日 YYYY-MM-DD"),
    until:        Optional[str] = typer.Option(None, "--until",               help="終了日 YYYY-MM-DD"),
    project:      Optional[str] = typer.Option(None, "--project",      "-p", help="プロジェクト名フィルタ"),
    dir:          Optional[str] = typer.Option(None, "--dir",                 help="~/.claude/projects パス"),
    pricing_file: Optional[str] = typer.Option(None, "--pricing-file",        help="pricing YAML ファイルパス"),
):
    """モデル別・日別コストサマリー"""
    pricing = load_pricing(pricing_file)
    records = load_records(get_projects_dir(dir), pricing, days=days, project_filter=project, since=since, until=until)
    if not records:
        console.print("[yellow]対象レコードが見つかりませんでした[/yellow]")
        raise typer.Exit()

    by_model: dict = defaultdict(lambda: {"cost": 0.0, "savings": 0.0, "input": 0, "output": 0, "cache_read": 0, "cache_write": 0, "count": 0})
    by_date: dict  = defaultdict(float)

    for r in records:
        m = by_model[r["model"]]
        m["cost"]    += r["cost"]
        m["savings"] += r["savings"]
        m["count"]   += 1
        u = r["usage"]
        m["input"]      += u.get("input_tokens", 0)
        m["output"]     += u.get("output_tokens", 0)
        m["cache_read"] += u.get("cache_read_input_tokens", 0)
        cache_c = u.get("cache_creation", {})
        m["cache_write"] += (
            cache_c.get("ephemeral_5m_input_tokens", 0)
            + cache_c.get("ephemeral_1h_input_tokens", 0)
            + u.get("cache_creation_input_tokens", 0)
        )
        if r["timestamp"]:
            by_date[r["timestamp"].strftime("%Y-%m-%d")] += r["cost"]

    grand_total   = sum(m["cost"]    for m in by_model.values())
    grand_savings = sum(m["savings"] for m in by_model.values())

    console.print()
    console.print(Panel(f"[bold]Claude Code コスト分析[/bold]   {period_label(days, since, until)}", style="bold blue"))

    tbl = Table(title="モデル別コスト", box=box.ROUNDED, show_lines=True)
    tbl.add_column("モデル",         style="cyan", no_wrap=True)
    tbl.add_column("コスト",         style="green", justify="right")
    tbl.add_column("%",              justify="right")
    tbl.add_column("Input",          justify="right")
    tbl.add_column("Output",         justify="right")
    tbl.add_column("Cache Read",     justify="right")
    tbl.add_column("Cache Write",    justify="right")
    tbl.add_column("キャッシュ節約", style="yellow", justify="right")
    tbl.add_column("Req数",          justify="right")

    for mdl, m in sorted(by_model.items(), key=lambda x: -x[1]["cost"]):
        pct = m["cost"] / grand_total * 100 if grand_total else 0
        tbl.add_row(
            mdl,
            fmt_cost(m["cost"]),
            f"{pct:.1f}%",
            fmt_tokens(m["input"]),
            fmt_tokens(m["output"]),
            fmt_tokens(m["cache_read"]),
            fmt_tokens(m["cache_write"]),
            fmt_cost(m["savings"]),
            str(m["count"]),
        )
    tbl.add_section()
    tbl.add_row(
        "[bold]合計[/bold]",
        f"[bold]{fmt_cost(grand_total)}[/bold]", "100%",
        "", "", "", "",
        f"[bold yellow]{fmt_cost(grand_savings)}[/bold yellow]",
        str(len(records)),
    )
    console.print(tbl)

    if by_date:
        console.print("\n[bold]日別コスト (最新14日)[/bold]")
        recent = sorted(by_date.keys())[-14:]
        max_c = max(by_date[d] for d in recent)
        dt = Table(box=box.SIMPLE, show_header=False)
        dt.add_column("日付",   style="dim")
        dt.add_column("コスト", justify="right", style="green")
        dt.add_column("グラフ")
        for date in recent:
            dt.add_row(date, fmt_cost(by_date[date]), bar_chart(by_date[date], max_c))
        console.print(dt)

    console.print(f"\n[dim]※ Max/Proプランは参考値（実際の課金額ではありません）[/dim]\n")


@app.command()
def projects(
    days:         Optional[int] = typer.Option(None, "--days",         "-d", help="直近N日間"),
    since:        Optional[str] = typer.Option(None, "--since",               help="開始日 YYYY-MM-DD"),
    until:        Optional[str] = typer.Option(None, "--until",               help="終了日 YYYY-MM-DD"),
    top:          int            = typer.Option(20,  "--top",           "-n", help="上位N件"),
    dir:          Optional[str] = typer.Option(None, "--dir",                 help="~/.claude/projects パス"),
    pricing_file: Optional[str] = typer.Option(None, "--pricing-file",        help="pricing YAML ファイルパス"),
):
    """プロジェクト別コスト"""
    pricing = load_pricing(pricing_file)
    records = load_records(get_projects_dir(dir), pricing, days=days, since=since, until=until)
    if not records:
        console.print("[yellow]対象レコードが見つかりませんでした[/yellow]")
        raise typer.Exit()

    by_proj: dict = defaultdict(lambda: {"cost": 0.0, "savings": 0.0, "count": 0, "models": set()})
    for r in records:
        p = by_proj[r["project"]]
        p["cost"]    += r["cost"]
        p["savings"] += r["savings"]
        p["count"]   += 1
        p["models"].add(r["model"])

    grand_total = sum(p["cost"] for p in by_proj.values())
    sorted_proj = sorted(by_proj.items(), key=lambda x: -x[1]["cost"])[:top]
    max_cost    = sorted_proj[0][1]["cost"] if sorted_proj else 1

    console.print()
    console.print(Panel(f"[bold]プロジェクト別コスト[/bold]   {period_label(days, since, until)}", style="bold blue"))

    tbl = Table(box=box.ROUNDED, show_lines=True)
    tbl.add_column("プロジェクト", style="cyan")
    tbl.add_column("コスト",       style="green", justify="right")
    tbl.add_column("%",            justify="right")
    tbl.add_column("節約額",       style="yellow", justify="right")
    tbl.add_column("Req数",        justify="right")
    tbl.add_column("モデル",       style="dim")
    tbl.add_column("グラフ")

    for proj, p in sorted_proj:
        pct = p["cost"] / grand_total * 100 if grand_total else 0
        models_str = ", ".join(model_short(m) for m in sorted(p["models"]))
        tbl.add_row(
            proj[-50:] if len(proj) > 50 else proj,
            fmt_cost(p["cost"]),
            f"{pct:.1f}%",
            fmt_cost(p["savings"]),
            str(p["count"]),
            models_str,
            bar_chart(p["cost"], max_cost, 20),
        )

    console.print(tbl)
    console.print(f"\n[bold]合計: {fmt_cost(grand_total)}[/bold]  (全{len(by_proj)}プロジェクト)\n")


@app.command()
def sessions(
    days:         Optional[int] = typer.Option(None, "--days",         "-d", help="直近N日間"),
    since:        Optional[str] = typer.Option(None, "--since",               help="開始日 YYYY-MM-DD"),
    until:        Optional[str] = typer.Option(None, "--until",               help="終了日 YYYY-MM-DD"),
    project:      Optional[str] = typer.Option(None, "--project",      "-p", help="プロジェクト名フィルタ"),
    top:          int            = typer.Option(20,  "--top",           "-n", help="上位N件"),
    dir:          Optional[str] = typer.Option(None, "--dir",                 help="~/.claude/projects パス"),
    pricing_file: Optional[str] = typer.Option(None, "--pricing-file",        help="pricing YAML ファイルパス"),
):
    """セッション別コスト"""
    pricing = load_pricing(pricing_file)
    records = load_records(get_projects_dir(dir), pricing, days=days, project_filter=project, since=since, until=until)
    if not records:
        console.print("[yellow]対象レコードが見つかりませんでした[/yellow]")
        raise typer.Exit()

    by_sess: dict = defaultdict(lambda: {"cost": 0.0, "savings": 0.0, "count": 0, "project": "", "first": None, "models": set()})
    for r in records:
        s = by_sess[r["session_id"]]
        s["cost"]    += r["cost"]
        s["savings"] += r["savings"]
        s["count"]   += 1
        s["project"]  = r["project"]
        s["models"].add(r["model"])
        if r["timestamp"] and (s["first"] is None or r["timestamp"] < s["first"]):
            s["first"] = r["timestamp"]

    sorted_sess = sorted(by_sess.items(), key=lambda x: -x[1]["cost"])[:top]

    console.print()
    console.print(Panel(f"[bold]セッション別コスト (上位{top})[/bold]   {period_label(days, since, until)}", style="bold blue"))

    tbl = Table(box=box.ROUNDED, show_lines=True)
    tbl.add_column("セッションID",  style="dim",    no_wrap=True)
    tbl.add_column("プロジェクト",  style="cyan")
    tbl.add_column("開始",          style="dim")
    tbl.add_column("コスト",        style="green",  justify="right")
    tbl.add_column("節約額",        style="yellow", justify="right")
    tbl.add_column("Req数",         justify="right")
    tbl.add_column("モデル",        style="dim")

    for sess_id, s in sorted_sess:
        first_str = s["first"].strftime("%m/%d %H:%M") if s["first"] else "-"
        proj_short = s["project"][-35:] if len(s["project"]) > 35 else s["project"]
        models_str = ", ".join(model_short(m) for m in sorted(s["models"]))
        tbl.add_row(
            sess_id[:8] + "…",
            proj_short,
            first_str,
            fmt_cost(s["cost"]),
            fmt_cost(s["savings"]),
            str(s["count"]),
            models_str,
        )
    console.print(tbl)


@app.command()
def cache(
    days:         Optional[int] = typer.Option(None, "--days",         "-d", help="直近N日間"),
    since:        Optional[str] = typer.Option(None, "--since",               help="開始日 YYYY-MM-DD"),
    until:        Optional[str] = typer.Option(None, "--until",               help="終了日 YYYY-MM-DD"),
    project:      Optional[str] = typer.Option(None, "--project",      "-p", help="プロジェクト名フィルタ"),
    dir:          Optional[str] = typer.Option(None, "--dir",                 help="~/.claude/projects パス"),
    pricing_file: Optional[str] = typer.Option(None, "--pricing-file",        help="pricing YAML ファイルパス"),
):
    """キャッシュ効果の詳細分析"""
    pricing = load_pricing(pricing_file)
    records = load_records(get_projects_dir(dir), pricing, days=days, project_filter=project, since=since, until=until)
    if not records:
        console.print("[yellow]対象レコードが見つかりませんでした[/yellow]")
        raise typer.Exit()

    total_cost    = sum(r["cost"]    for r in records)
    total_savings = sum(r["savings"] for r in records)
    total_input   = sum(r["usage"].get("input_tokens", 0) for r in records)
    total_cr      = sum(r["usage"].get("cache_read_input_tokens", 0) for r in records)
    total_cw      = sum(
        r["usage"].get("cache_creation", {}).get("ephemeral_5m_input_tokens", 0)
        + r["usage"].get("cache_creation", {}).get("ephemeral_1h_input_tokens", 0)
        + r["usage"].get("cache_creation_input_tokens", 0)
        for r in records
    )

    would_have   = total_cost + total_savings
    cache_rate   = total_cr / (total_input + total_cr) * 100 if (total_input + total_cr) else 0
    savings_rate = total_savings / would_have * 100 if would_have else 0

    console.print()
    console.print(Panel(f"[bold]キャッシュ効果分析[/bold]   {period_label(days, since, until)}", style="bold blue"))

    tbl = Table(box=box.ROUNDED, show_lines=True)
    tbl.add_column("項目",   style="cyan")
    tbl.add_column("値",     justify="right")
    tbl.add_column("補足",   style="dim")

    tbl.add_row("実際のコスト",           f"[green]{fmt_cost(total_cost)}[/green]", "")
    tbl.add_row("キャッシュなし仮定コスト", fmt_cost(would_have),                    "cache_read を input 料金で換算")
    tbl.add_row("キャッシュ節約額",       f"[bold yellow]{fmt_cost(total_savings)}[/bold yellow]", f"削減率 {savings_rate:.1f}%")
    tbl.add_section()
    tbl.add_row("Cache Read トークン",    fmt_tokens(total_cr),   f"ヒット率 {cache_rate:.1f}%")
    tbl.add_row("Cache Write トークン",   fmt_tokens(total_cw),   "")
    tbl.add_row("通常 Input トークン",    fmt_tokens(total_input), "")
    console.print(tbl)

    by_model: dict = defaultdict(lambda: {"cost": 0.0, "savings": 0.0, "cr": 0, "cw": 0})
    for r in records:
        m = by_model[r["model"]]
        m["cost"]    += r["cost"]
        m["savings"] += r["savings"]
        m["cr"]      += r["usage"].get("cache_read_input_tokens", 0)
        cache_c = r["usage"].get("cache_creation", {})
        m["cw"] += (
            cache_c.get("ephemeral_5m_input_tokens", 0)
            + cache_c.get("ephemeral_1h_input_tokens", 0)
            + r["usage"].get("cache_creation_input_tokens", 0)
        )

    mt = Table(title="モデル別キャッシュ効果", box=box.SIMPLE)
    mt.add_column("モデル",      style="cyan")
    mt.add_column("コスト",      style="green",  justify="right")
    mt.add_column("節約額",      style="yellow", justify="right")
    mt.add_column("Cache Read",  justify="right")
    mt.add_column("Cache Write", justify="right")

    for mdl, m in sorted(by_model.items(), key=lambda x: -x[1]["cost"]):
        mt.add_row(mdl, fmt_cost(m["cost"]), fmt_cost(m["savings"]), fmt_tokens(m["cr"]), fmt_tokens(m["cw"]))
    console.print(mt)


@app.command()
def prompt(
    days:         Optional[int] = typer.Option(None, "--days",         "-d", help="直近N日間"),
    since:        Optional[str] = typer.Option(None, "--since",               help="開始日 YYYY-MM-DD"),
    until:        Optional[str] = typer.Option(None, "--until",               help="終了日 YYYY-MM-DD"),
    project:      Optional[str] = typer.Option(None, "--project",      "-p", help="プロジェクト名フィルタ"),
    top:          int            = typer.Option(30,  "--top",           "-n", help="上位N件"),
    dir:          Optional[str] = typer.Option(None, "--dir",                 help="~/.claude/projects パス"),
    pricing_file: Optional[str] = typer.Option(None, "--pricing-file",        help="pricing YAML ファイルパス"),
):
    """プロンプト単位のコスト"""
    pricing = load_pricing(pricing_file)
    records = load_records(get_projects_dir(dir), pricing, days=days, project_filter=project, since=since, until=until)
    if not records:
        console.print("[yellow]対象レコードが見つかりませんでした[/yellow]")
        raise typer.Exit()

    sorted_records = sorted(records, key=lambda x: -x["cost"])[:top]

    console.print()
    console.print(Panel(f"[bold]プロンプト別コスト (上位{top})[/bold]   {period_label(days, since, until)}", style="bold blue"))

    tbl = Table(box=box.ROUNDED, show_lines=True)
    tbl.add_column("時刻",         style="dim",    no_wrap=True)
    tbl.add_column("プロジェクト", style="cyan")
    tbl.add_column("モデル",       style="dim")
    tbl.add_column("コスト",       style="green",  justify="right")
    tbl.add_column("節約額",       style="yellow", justify="right")
    tbl.add_column("Input",        justify="right")
    tbl.add_column("Output",       justify="right")
    tbl.add_column("CR",           justify="right", style="dim")
    tbl.add_column("CW",           justify="right", style="dim")

    for r in sorted_records:
        ts_str = r["timestamp"].strftime("%m/%d %H:%M") if r["timestamp"] else "-"
        u = r["usage"]
        cache_c = u.get("cache_creation", {})
        cw = (
            cache_c.get("ephemeral_5m_input_tokens", 0)
            + cache_c.get("ephemeral_1h_input_tokens", 0)
            + u.get("cache_creation_input_tokens", 0)
        )
        tbl.add_row(
            ts_str,
            (r["project"][-30:] if len(r["project"]) > 30 else r["project"]),
            model_short(r["model"]),
            fmt_cost(r["cost"]),
            fmt_cost(r["savings"]),
            fmt_tokens(u.get("input_tokens", 0)),
            fmt_tokens(u.get("output_tokens", 0)),
            fmt_tokens(u.get("cache_read_input_tokens", 0)),
            fmt_tokens(cw),
        )

    console.print(tbl)
    console.print("[dim]CR=Cache Read  CW=Cache Write[/dim]\n")