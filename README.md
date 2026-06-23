# iterm2-cli

iTerm2 をスクリプト / AI エージェントから操作する CLI。ペインの列挙・テキスト送信・画面読み取り・
分割・状態待ち（完了検知）などを、機械可読（`--json` / exit code）で提供する。

複数ペイン（並列に動く AI エージェント等）のオーケストレーションに必要な、ペインの一意識別・
高レベル操作・状態報告を、ライブラリ＋CLI＋任意デーモンとして単体で完結させることを狙う。

---

## セットアップ

前提: iTerm2 が起動し、**Python API が有効**（Settings → General → Magic → Enable Python API）。
依存 `iterm2` は optional extra（`uv` で隔離管理、グローバル汚染なし）。

短い `iterm2` コマンドで使えるようにする方法は 2 つ。どちらでも本書の例の `iterm2 …` がそのまま動く。

```sh
# A) ツールとして PATH に入れる（推奨・永続）
uv tool install --with iterm2 .          # `iterm2` と `iterm2-cli` が PATH に入る

# B) リポジトリ同梱ラッパーを symlink（インストール不要・常に最新コードを使う）
ln -s "$(pwd)/bin/iterm2" ~/.local/bin/iterm2
```

インストールせず素の `uv` で呼ぶ場合（上の `iterm2 …` と等価）:

```sh
uv run --extra iterm2 iterm2-cli <subcommand> …
```

## クイックスタート

```sh
iterm2 list --json            # ペイン一覧（JSON）
iterm2 send "echo hi" -e      # current ペインに送信＋Enter
iterm2 read --tail 20         # current ペインの末尾20行
iterm2 wait                   # current が idle になるまで待つ
```

高頻度に使うならデーモンを起動（接続を保持し **1コマンド ~5ms**、後述）。

---

## コマンドリファレンス

`<target>`（対象ペイン）の指定は次の規則:

- **ペイロードを持つコマンド**（send / send-key / var / set-status / set-progress）→ `-t/--target`
- **対象のみのコマンド**（read / busy / wait / split / focus / close）→ 位置引数
- いずれも **省略時は current**（`$ITERM_SESSION_ID`）。`-s/--session <id>` で session_id を直接指定。
- `<target>` 解決順: `-s <id>` → ラベル → current。

| コマンド | 説明 | 例 |
|---|---|---|
| `list [--json]` | ペイン階層を列挙（session_id / name / 行列 / is_active） | `iterm2 list --json` |
| `identify [-t T] [--json]` | 呼び出し元（current）の session を特定して出力（割当 label も）。cmux `identify` 相当 | `iterm2 identify --json` |
| `send <text> [-t T] [-e]` | 本文を送信。`-e/--enter` で確定キーも送る | `iterm2 send "ls" -t worker -e` |
| `send-key <keys...> [-t T]` | 特殊キー送出（enter/tab/esc/up/down/left/right/ctrl-c …） | `iterm2 send-key ctrl-c -t worker` |
| `read [T] [--tail N] [--json]` | 画面内容を読む（末尾の空行は除去してから `--tail` を適用） | `iterm2 read --tail 40 --json` |
| `busy [T] [--json]` | 状態判定。**busy のとき exit 1** | `iterm2 busy worker && echo idle` |
| `wait [T] [--timeout S] [--until S] [--until-text M]` | 指定状態（既定 idle）まで、または `--until-text M` で画面に文字列 M が出るまで待つ | `iterm2 wait -s <id> --until-text "Remote Control active"` |
| `new-split [DIR] [-t T] [--profile P]` | ペインを分割し新 session_id を出力。方向は `right`(既定)/`left`/`down`/`up`（左右=垂直、上下=水平、left/up=前側） | `iterm2 new-split down -t worker` |
| `new-tab [-t T] [--cmd C] [--in-window W] [--profile P]` | タブを作り新 session_id を出力（既定は呼び出し元=current の窓、`--in-window W` で指定窓内）。デーモン起動中でも current 窓はクライアント側で解決する | `iterm2 new-tab --in-window <wid> --cmd claude` |
| `new-window [--cmd C] [--profile P]` | 新規ウィンドウを作り新 session_id を出力 | `iterm2 new-window --cmd claude` |
| `focus [T]` | フォーカス移動 | `iterm2 focus worker` |
| `rename <name> [-t T] [--json]` | ペインの表示名を変更 | `iterm2 rename "🟢 worker" -t worker` |
| `close [T] [--force]` | ペイン/タブを閉じる | `iterm2 close -s <id> --force` |
| `var get <name> [-t T]` / `var set <name> <value> [-t T]` | セッション変数 | `iterm2 var get user.x -t worker` |
| `set-status <key> <value> [-t T]` | 状態を `user.<key>` に書く（後述） | `iterm2 set-status itermcli_state running` |
| `set-progress <n> [-t T]` | 進捗を `user.itermcli_progress` に書く | `iterm2 set-progress 42` |
| `label set <name> <id>` / `label ls [--json]` / `label rm <name>` | ラベル↔session_id（iTerm2 不要） | `iterm2 label set worker <id>` |
| `daemon start [--socket P]` / `daemon stop` | 常駐デーモンの起動／停止 | `iterm2 daemon start` |
| `ping` | 接続確認（`ok` を出力） | `iterm2 ping` |

### exit code

| code | 意味 |
|---|---|
| 0 | 成功 |
| 1 | `busy`=busy のとき / `label rm`=該当なし / `daemon start`=既に起動中 |
| 2 | エラー（対象解決不可・セッション不在・未知キー・`wait` タイムアウト・デーモンエラー・接続失敗）。stderr に 1 行 |

### `--json` 出力の形

`--json` は**複数フィールドの構造化出力を返すコマンド**にだけ用意する。単一値しか返さないコマンド（`new-split`/`new-tab`/`new-window` の新 session_id、`wait` の最終状態）は **stdout に素の値を 1 行**で出すのでそのままパイプで受けられる（`--json` は無い）。

| コマンド | 形 |
|---|---|
| `list --json` | `[{"session_id","name","rows","cols","tab_id","window_id","is_active"}, …]` |
| `read --json` | `{"lines": ["…", …]}` |
| `set-name --json` | `{"session_id","name"}`（デーモン経由でも `session_id` は解決済み id） |
| `busy --json` | `{"state": "busy" \| "idle" \| "needs-input" \| "unknown"}` |
| `label ls --json` | `{"<label>": "<session_id>", …}` |

---

## 状態報告と完了検知（エージェント向け）

`busy` / `wait` はセッション変数 **`user.itermcli_state`** を最優先で読み、無ければ画面マーカー
（"esc to interrupt" 等）にフォールバックする。エージェントは自分の状態をこの変数に書けば、
オーケストレータが確実に完了検知できる。書き方は 2 通り:

```sh
# 1) CLI から（外部 / hook）
iterm2 set-status itermcli_state running   # busy 扱い
iterm2 set-status itermcli_state idle       # idle 扱い

# 2) ペイン内から OSC 1337（シェル/プログラムが直接）
printf '\033]1337;SetUserVar=itermcli_state=%s\a' "$(printf running | base64)"
```

語彙: `running`/`busy`→busy、`needs_input`/`needs-input`→needs-input、`idle`/`done`→idle。

変数が無いときの画面マーカー（フォールバック）の既定は `"esc to interrupt"`。別の TUI に合わせるには
環境変数 `ITERM2_CLI_BUSY_MARKERS` / `ITERM2_CLI_NEEDS_INPUT_MARKERS`（改行/カンマ区切り）で上書きする。

---

## デーモン（低レイテンシ）

都度接続は 1 コマンド ~0.6〜1.6s（websocket 接続+認証）。高頻度操作はデーモンを起動すると
接続を保持し、各コマンドは Unix socket 経由になる（**実測 list ≈ 5ms**）。

```sh
iterm2 daemon start  # 常駐起動（Ctrl-C で停止）
iterm2 daemon stop   # 停止
```

- デーモン起動中は**クライアントに iterm2 パッケージ不要**（socket 経由なので `--extra iterm2` すら要らない）。
- CLI はデーモンの有無を自動判定し、未起動なら都度接続にフォールバック（**同一コマンド表面**）。
- `<target>` の current 解決はクライアント側で行うため、デーモンが別プロセスでも各ペインの current を正しく解決。
- 接続ごとにスレッド処理するため、長い `wait` が他コマンドを塞がない。
- socket パスは `ITERM2_CLI_SOCKET`（既定 `${XDG_RUNTIME_DIR:-/tmp}/iterm2-cli.sock`、パーミッション 0600）。

---

## アーキテクチャ（俯瞰）

3 層 + テスタビリティの継ぎ目。詳細は [docs/design.md](./docs/design.md)。

```
CLI (typer)  ─┐
              ├─►  Backend（共通表面: Controller / DaemonClient）
ライブラリ ────┘         │ 中核ロジックは ITerm2Adapter にのみ依存
                         ▼
              ITerm2Adapter(port) ─┬─ RealAdapter (iterm2 pip, async を単一ループに隔離)
                                   └─ FakeAdapter (テスト用インメモリ)
```

- **CLI は薄いクライアント**。操作の実体はライブラリ（`Controller`）。
- **`Backend` Protocol** を `Controller`（都度接続）と `DaemonClient`（socket）が共に満たす。
- **`ITerm2Adapter` port** が iTerm2 接続を抽象化。本番=`RealAdapter`、テスト=`FakeAdapter`。
  → iTerm2 無しでユニットテストが回り、async/websocket は RealAdapter 内に閉じる。

### ライブラリとして使う

```python
from iterm2_cli import Controller, RealAdapter, SessionResolver, State

c = Controller(RealAdapter.connect(), SessionResolver())
try:
    for s in c.list():
        print(s.session_id, s.name)
    c.send(None, "echo hi", session="<id>")
finally:
    c.shutdown()
```

### 他ツールから組み込む / ラッパー

本 CLI は特定の上位ツールを前提としない汎用基盤。特定ツール（AI コーディングエージェント等）固有の
お作法（起動コマンド・状態 hook 配線・TUI 固有の送信・命名/オーケストレーション）は、CLI / ライブラリ /
socket のプリミティブの上に**薄いラッパーとして外側に**載せられる（本リポジトリには含めない）。
依拠すべき契約と統合経路は [docs/design.md §8](./docs/design.md) を参照。

---

## リポジトリ構成

| パス | 役割 |
|---|---|
| `bin/iterm2` | 短縮ラッパー（`uv run … iterm2-cli` への委譲） |
| `src/iterm2_cli/cli.py` | typer エントリ（薄い） |
| `src/iterm2_cli/core.py` | `Controller`（中核操作） |
| `src/iterm2_cli/backend.py` | `Backend` Protocol（共通表面） |
| `src/iterm2_cli/adapter.py` / `adapter_real.py` | port と RealAdapter（iterm2 pip） |
| `src/iterm2_cli/resolver.py` / `labels.py` | `<target>` 解決 / ラベル永続化 |
| `src/iterm2_cli/detect.py` | busy/完了検知 |
| `src/iterm2_cli/keys.py` | send-key 符号化 |
| `src/iterm2_cli/daemon.py` / `client.py` / `protocol.py` | デーモン / クライアント / socket プロトコル |
| `tests/` | ユニット（FakeAdapter）／`tests/integration/`（実 iTerm2・オプトイン） |
| `docs/` | [requirements](./docs/requirements.md) / [design](./docs/design.md) / [decisions](./docs/decisions.md)（設計思想・なぜ）/ [research](./docs/research.md) |
| [CLAUDE.md](./CLAUDE.md) | 開発ガイド（手順・設計不変条件・テスト戦略） |

---

## 開発

```sh
uv run pytest                                                          # ユニット（iTerm2 不要）
uv run ruff check src tests                                            # lint（F/B/I）
ITERM2_CLI_INTEGRATION=1 uv run --extra iterm2 pytest tests/integration  # 実 iTerm2 結合（オプトイン）
```

開発の進め方・設計不変条件・テスト戦略（Canon TDD / adapter seam）は [CLAUDE.md](./CLAUDE.md) を参照。

---

## 位置付け（it2api との関係）

iTerm2 同梱の `it2api` も `iterm2` Python API のほぼ全操作を CLI 化している。it2api はその API の
薄いラッパに過ぎず特権機能を持たないため、**本 CLI は同じ Python API を直接叩いて it2api を完全代替する**
ことを目標とする（it2api へのシェルアウト＝実行時依存はゼロ。移植元リファレンスとして残す）。

it2api で埋まらないギャップ — 永続的なペイン識別（ラベル）、高レベル操作（`wait`/busy 検知）、
構造化出力（`--json`）、送信作法（send / send-key 分離・bracket-paste 安全）、状態報告
（`set-status`）、低レイテンシ（デーモン）— に価値を集中する。設計は先行ツール cmux
（manaflow-ai / craigsc）の知見を取り入れている。
