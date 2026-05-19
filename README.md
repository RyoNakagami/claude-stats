# claude-stats

Claude Code のコスト分析ツールです．`~/.claude/projects/` の JSONL ファイルを解析し，モデル別・プロジェクト別・セッション別のコストとキャッシュ効果をターミナルに表示します．

## インストール

### uv tool install（推奨）

```bash
uv tool install claude-stats
```

### 開発用インストール

```bash
git clone <リポジトリURL>
cd claude-stats
uv sync
uv run claude-stats --help
```

## 使い方

```bash
claude-stats [コマンド] [オプション]
```

### コマンド一覧

| コマンド | 説明 |
| ------- | ---- |
| `summary` | モデル別・日別コストサマリー |
| `projects` | プロジェクト別コスト |
| `sessions` | セッション別コスト（上位 N 件） |
| `cache` | キャッシュ効果の詳細分析 |
| `prompt` | プロンプト単位のコスト（上位 N 件） |

### 共通オプション

| オプション | 省略形 | 説明 |
| --------- | ------ | ---- |
| `--days N` | `-d N` | 直近 N 日間を対象にする |
| `--since YYYY-MM-DD` | | 集計開始日を指定 |
| `--until YYYY-MM-DD` | | 集計終了日を指定 |
| `--project NAME` | `-p NAME` | プロジェクト名でフィルタ（部分一致） |
| `--top N` | `-n N` | 上位 N 件を表示（sessions / prompt コマンド） |
| `--dir PATH` | | `~/.claude/projects` の代替パスを指定 |
| `--pricing-file PATH` | | カスタム pricing YAML のパスを指定 |
| `--version` | `-v` | バージョンを表示して終了 |

## 使用例

```bash
# 全期間のモデル別コストサマリー
claude-stats summary

# 直近 7 日間のサマリー
claude-stats summary --days 7

# 期間指定（2026-05-01 〜 2026-05-31）
claude-stats summary --since 2026-05-01 --until 2026-05-31

# プロジェクト別コスト（直近 30 日間）
claude-stats projects --days 30

# 特定プロジェクトのセッション別コスト上位 10 件
claude-stats sessions --project myproject --top 10

# キャッシュ効果の詳細分析
claude-stats cache --days 7

# 高コストのプロンプト上位 30 件
claude-stats prompt --days 7
```

## pricing.yml のカスタマイズ

デフォルトの料金表はパッケージに同梱された `pricing.yml` を使用します．`--pricing-file` オプションで独自の料金表に差し替えられます．

```bash
claude-stats summary --pricing-file /path/to/custom.yml
```

### pricing.yml の形式

```yaml
# USD per 1M tokens
defaults:
  input: 3.0
  output: 15.0
  cache_write_5m: 3.75
  cache_write_1h: 6.0
  cache_read: 0.30

models:
  claude-sonnet-4-6:
    input: 3.0
    output: 15.0
    cache_write_5m: 3.75
    cache_write_1h: 6.0
    cache_read: 0.30
  claude-opus-4-7:
    input: 15.0
    output: 75.0
    cache_write_5m: 18.75
    cache_write_1h: 30.0
    cache_read: 1.50
```

- `models` に一致するモデルがない場合は `defaults` の値が使用されます．
- モデル名は前方一致でもマッチします（例: `claude-sonnet-4-6-something` → `claude-sonnet-4-6` にマッチ）．
- 全コマンドで `--pricing-file` オプションが使用可能です．

## ライセンス

MIT
