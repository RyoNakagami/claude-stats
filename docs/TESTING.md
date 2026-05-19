---
author: "RyoNak"
date-modified: "2026-05-20"
project: claude-stats
---

# テストスイート詳細

`tests/test_cli.py` に定義された 30 件のテストケースを説明します．

## テスト実行方法

```bash
# 全テスト実行
uv run pytest

# 詳細出力
uv run pytest -v

# 特定のテストグループのみ実行
uv run pytest -k "load_pricing"
```

## テストの構成

| グループ | テスト数 | 対象関数 |
| ------- | ------- | ------- |
| `load_pricing` | 2 | `load_pricing()` |
| `get_price` | 4 | `get_price()` |
| `calc_cost` | 5 | `calc_cost()` |
| `cache_savings` | 2 | `cache_savings()` |
| `fmt_cost / fmt_tokens` | 4 | `fmt_cost()`, `fmt_tokens()` |
| `bar_chart` | 3 | `bar_chart()` |
| `load_records` | 4 | `load_records()` |
| `get_version` | 1 | `get_version()` |
| `get_projects_dir` | 5 | `get_projects_dir()` |

---

## フィクスチャ

### `default_pricing`

バンドル済みの `pricing.yml` を読み込んだ pricing dict を返します．

### `custom_pricing(tmp_path)`

`tmp_path` に一時的なカスタム YAML を生成し読み込みます．`defaults` と `models.my-model` の 2 エントリを持ちます．

### `projects_dir(tmp_path, default_pricing)`

`tmp_path/my-project/session-abc.jsonl` に `_make_record()` の 1 レコードを
書き込み，`tmp_path` を返します．`load_records` 系テストで使用します．

---

## load_pricing

### `test_load_pricing_bundled`

**目的**: バンドル済み `pricing.yml` が正しく読み込まれること．

**前提条件**: `path` 引数なしで `load_pricing()` を呼ぶ．

**期待値**: 返り値の dict に `"defaults"` キーと `"models"` キーが存在する．

---

### `test_load_pricing_custom`

**目的**: 任意パスの YAML ファイルを読み込めること．

**前提条件**: `tmp_path` に `defaults.input: 9.9` を含む YAML を生成し
`load_pricing(path)` を呼ぶ．

**期待値**: `pricing["defaults"]["input"] == 9.9`．

---

## get_price

### `test_get_price_exact_match`

**目的**: モデル名が完全一致する場合に正しい料金を返すこと．

**前提条件**: `get_price("claude-sonnet-4-6", default_pricing)` を呼ぶ．

**期待値**: `input == 3.0`，`output == 15.0`．

---

### `test_get_price_prefix_match`

**目的**: モデル名が前方一致する場合にも正しい料金を返すこと．

**前提条件**: `get_price("claude-sonnet-4-6-something-extra", default_pricing)` を呼ぶ．

**期待値**: `input == 3.0`（`claude-sonnet-4-6` にマッチ）．

---

### `test_get_price_unknown_falls_back_to_defaults`

**目的**: 一致するモデルがない場合に `defaults` の値を返すこと．

**前提条件**: `get_price("totally-unknown-model", default_pricing)` を呼ぶ．

**期待値**: `pricing["defaults"]` と同一の dict が返る．

---

### `test_get_price_custom`

**目的**: カスタム pricing でも exact match と fallback が機能すること．

**前提条件**: `custom_pricing` フィクスチャを使用．`my-model` と未知のモデル `other` を取得．

**期待値**: `my-model` は `input == 2.0`，`other` は `defaults.input == 1.0`．

---

## calc_cost

### `test_calc_cost_basic`

**目的**: input トークンのみのコスト計算が正しいこと．

**前提条件**: `usage = {"input_tokens": 1_000_000}`，モデル `claude-sonnet-4-6`
（input 単価 3.0 USD/1M）．

**期待値**: コスト ≈ 3.0 USD．

---

### `test_calc_cost_output`

**目的**: output トークンのみのコスト計算が正しいこと．

**前提条件**: `usage = {"output_tokens": 1_000_000}`，output 単価 15.0 USD/1M．

**期待値**: コスト ≈ 15.0 USD．

---

### `test_calc_cost_cache_read`

**目的**: cache_read トークンのコスト計算が正しいこと．

**前提条件**: `usage = {"cache_read_input_tokens": 1_000_000}`，cache_read 単価 0.30 USD/1M．

**期待値**: コスト ≈ 0.30 USD．

---

### `test_calc_cost_cache_creation_legacy`

**目的**: 旧形式（フラットな `cache_creation_input_tokens` フィールド）のコスト計算が正しいこと．

**前提条件**: `usage = {"cache_creation_input_tokens": 1_000_000}`，
cache_write_5m 単価 3.75 USD/1M．

**期待値**: コスト ≈ 3.75 USD．

---

### `test_calc_cost_cache_creation_nested`

**目的**: 新形式（ネストされた `cache_creation.ephemeral_5m_input_tokens`）のコスト計算が正しいこと．

**前提条件**: `usage = {"cache_creation": {"ephemeral_5m_input_tokens": 1_000_000}}`．

**期待値**: コスト ≈ 3.75 USD．旧形式と同じ単価で計算されること．

---

## cache_savings

### `test_cache_savings_zero_when_no_reads`

**目的**: cache_read トークンがない場合に節約額が 0 になること．

**前提条件**: `cache_savings({}, "claude-sonnet-4-6", pricing)` を呼ぶ．

**期待値**: `0.0`．

---

### `test_cache_savings_correct`

**目的**: cache_read トークンがある場合の節約額計算が正しいこと．

**前提条件**: `usage = {"cache_read_input_tokens": 1_000_000}`．
節約額 = (input 単価 3.0 - cache_read 単価 0.30) × 1M = 2.70 USD．

**期待値**: savings ≈ 2.70 USD．

---

## fmt_cost / fmt_tokens

### `test_fmt_cost`

**目的**: コスト値が `$X.XXXX` 形式（小数点以下 4 桁）でフォーマットされること．

**前提条件**: `fmt_cost(1.23456)`，`fmt_cost(0.0)`．

**期待値**: `"$1.2346"`，`"$0.0000"`．

---

### `test_fmt_tokens_large`

**目的**: 100 万以上のトークン数が `M` サフィックス付きでフォーマットされること．

**前提条件**: `fmt_tokens(2_500_000)`．

**期待値**: `"2.5M"`．

---

### `test_fmt_tokens_kilo`

**目的**: 1000 以上 100 万未満のトークン数が `k` サフィックス付きでフォーマットされること．

**前提条件**: `fmt_tokens(1_500)`．

**期待値**: `"1.5k"`．

---

### `test_fmt_tokens_small`

**目的**: 1000 未満のトークン数がそのまま文字列でフォーマットされること．

**前提条件**: `fmt_tokens(42)`．

**期待値**: `"42"`．

---

## bar_chart

### `test_bar_chart_full`

**目的**: value が max_value と等しい場合にすべて `█` で埋まること．

**前提条件**: `bar_chart(10.0, 10.0, width=4)`．

**期待値**: `"████"`（4 文字すべてが `█`）．

---

### `test_bar_chart_half`

**目的**: value が max_value の半分の場合に前半が `█`，後半が `░` になること．

**前提条件**: `bar_chart(5.0, 10.0, width=4)`．

**期待値**: `"██░░"`．

---

### `test_bar_chart_zero_max`

**目的**: max_value が 0 の場合に空文字列を返すこと（ゼロ除算の回避）．

**前提条件**: `bar_chart(1.0, 0.0)`．

**期待値**: `""`．

---

## load_records

### `test_load_records_basic`

**目的**: JSONL ファイルからレコードを正しく読み込めること．

**前提条件**: `projects_dir` フィクスチャ（`my-project/session-abc.jsonl` に 1 レコード）．

**期待値**: レコード数 1，`project == "my-project"`，
`model == "claude-sonnet-4-6"`，`cost > 0`．

---

### `test_load_records_project_filter`

**目的**: `project_filter` 引数で部分一致フィルタリングが機能すること．

**前提条件**: `project_filter="other"` と `project_filter="my"` の両方を試す．

**期待値**: `"other"` フィルタでは空リスト，`"my"` フィルタでは 1 件．

---

### `test_load_records_skips_non_assistant`

**目的**: `type != "assistant"` のレコードが無視されること．

**前提条件**: `type: "user"` のレコードのみを含む JSONL を生成．

**期待値**: 返り値が空リスト．

---

### `test_load_records_days_filter`

**目的**: `days` 引数による日時フィルタが機能すること．

**前提条件**: `timestamp: "2020-01-01"` の古いレコードのみを含む JSONL，`days=7` でフィルタ．

**期待値**: 返り値が空リスト（7 日以上前のレコードは除外）．

---

## get_version

### `test_get_version_returns_string`

**目的**: `get_version()` が空でない文字列を返すこと．

**前提条件**: `get_version()` を呼ぶ．

**期待値**: `isinstance(v, str)` かつ `len(v) > 0`．

---

## get_projects_dir

### `test_get_projects_dir_override`

**目的**: `dir_override` が指定された場合にそのパスをそのまま返すこと．

**前提条件**: `get_projects_dir("/custom/path")`．

**期待値**: `Path("/custom/path")`．

---

### `test_get_projects_dir_linux_default`

**目的**: Linux 環境でデフォルトパスが `~/.claude/projects` になること．

**前提条件**: `platform.system` を `"Linux"` にモック．

**期待値**: `Path.home() / ".claude" / "projects"`．

---

### `test_get_projects_dir_mac_default`

**目的**: macOS 環境でデフォルトパスが `~/.claude/projects` になること．

**前提条件**: `platform.system` を `"Darwin"` にモック．

**期待値**: `Path.home() / ".claude" / "projects"`．

---

### `test_get_projects_dir_windows_default`

**目的**: Windows 環境で `APPDATA` 環境変数がある場合に `%APPDATA%/Claude/projects` を返すこと．

**前提条件**: `platform.system` を `"Windows"`，`APPDATA` を
`"C:\\Users\\test\\AppData\\Roaming"` にモック．

**期待値**: `Path("C:\\Users\\test\\AppData\\Roaming") / "Claude" / "projects"`．

---

### `test_get_projects_dir_windows_no_appdata_fallback`

**目的**: Windows 環境で `APPDATA` 環境変数がない場合に `~/.claude/projects` にフォールバックすること．

**前提条件**: `platform.system` を `"Windows"` にモック，`APPDATA` を環境変数から除去．

**期待値**: `Path.home() / ".claude" / "projects"`．
