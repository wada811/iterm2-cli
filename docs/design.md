# 設計 — iterm2-cli

作成日: 2026-06-15

要件（[requirements.md](./requirements.md)）を満たす実装設計。言語選定・アーキテクチャ・コマンド表面・socket プロトコル・送信作法・完了検知・オーケストレータ 統合を定める。調査根拠は [research.md](./research.md)。

> 本書の「コマンド表面」「socket API」はユーザーが「深く検討する余地がある」と指摘した重点項目。第一版を確定仕様として示し、実装フェーズで個別に精査する余地を各所に明記する。

---

## 1. 言語選定（Python に確定）

| 観点 | Python（採用） | TypeScript/Node | Go / Rust |
|---|---|---|---|
| iTerm2 API アクセス | `iterm2` pip を直接利用（公式・最短） | ネイティブ手段なし。Python 橋渡し or websocket+protobuf 自前実装 | protobuf+認証を全自前実装 |
| オーケストレータ 統合 | 既存資産が全部 Python。ライブラリ共有・置換が容易 | 言語境界が増える | 言語境界が増える |
| 起動速度 | やや遅い（import）。デーモンで解決 | 速い（が Python 橋渡しで相殺） | 最速・単一バイナリ |
| CLI UX | `typer`/`click` で十分 | `commander`/`oclif` | cobra/clap |
| 配布 | `uv`（PEP 723）で自己完結 | npm | 単一バイナリ（API 自前実装が壁） |
| 保守リスク | 低（公式 API 追従） | 中〜高（protobuf 追従） | 高 |

**決定: Python。** iTerm2 の実用 API は Python のみで、Node/Go は「API への到達コスト」が本質的に高く、結局 Python へ橋渡しするとレイテンシ・複雑性で勝てない。CLI UX は `typer`（型ヒント駆動）。依存は `uv`（PEP 723 インラインメタデータ）で自己完結し、グローバル pip 汚染を避ける。

---

## 2. アーキテクチャ（3 層）

```
┌─────────────────────────────────────────────┐
│  CLI 層 (typer)   iterm2-cli <subcommand>     │  ← 人間向けエイリアス。薄い
├─────────────────────────────────────────────┤
│  ライブラリ層（中核ロジック）iterm2_cli         │  ← オーケストレータ が import 可能
│   - SessionResolver (<target> 解決)           │
│   - 各操作 (send/read/split/...)              │     ※ Adapter インターフェースにのみ依存
│   - 送信作法・完了検知（状態機械）              │     （iterm2 pip を直接触らない）
├─────────────────────────────────────────────┤
│  Adapter 層（port）  ITerm2Adapter (interface) │  ← テスタビリティの継ぎ目
│   ├ RealAdapter  : iterm2 pip (websocket/async)│
│   └ FakeAdapter  : テスト用インメモリ実装       │
├─────────────────────────────────────────────┤
│  接続層: 都度接続(フェーズ1) / デーモン+socket(2) │
└─────────────────────────────────────────────┘
        │                          │
   RealAdapter 経由 ←──────────→ iTerm2 Python API
```

- **CLI サブコマンドは socket method と 1:1 対応**（cmux 踏襲）。CLI はライブラリ/デーモンへの薄いクライアント。
- **中核ロジックは `ITerm2Adapter` インターフェースにのみ依存**し、`iterm2` pip を直接触らない。本番は `RealAdapter`、テストは `FakeAdapter` を差す（ports & adapters / humble object）。→ §2.2。
- **デーモン未起動なら CLI が自前で都度接続にフォールバック。** フェーズ1（都度接続）とフェーズ2（デーモン）を**同一コマンド表面**で両立。
- **ライブラリ層を オーケストレータ が import** することで、`オーケストレータ.py`/`(利用側スクリプト)` のアドホック制御を段階的に置換。

### 2.1 レイテンシ対策（段階導入）
> 実測（2026-06-15, [research.md](./research.md) §3.1）: it2api 都度接続は **cold 1.57s / warm 0.58s**。単発なら許容、高頻度バッチでは無視できず、デーモン化を裏付ける。

- **フェーズ1（既定）**: it2api 同様コマンド毎に websocket 接続+認証。実装単純で正しさを担保。対話用途では実用範囲（warm ~0.6s）。
- **フェーズ2（必要時）**: 接続を保持する常駐 `iterm2-cli daemon` を Unix socket で待受け、CLI は軽量クライアント。高頻度バッチ向け。
  - **重要**: オーケストレータ の `オーケストレータ.py` は既に「接続を保持する常駐 Python」。**デーモンの実体を オーケストレータ に寄せる**（CLI がライブラリを提供、オーケストレータ がホスト）構成で二重管理を回避。`daemon` サブコマンドは単独利用時の選択肢として用意。

### 2.2 テスタビリティ（adapter seam）
iTerm2 は状態を持つ外部アプリで、実接続は遅く（cold 1.57s）不安定になりがち。これを**設計で吸収**する:

- **`ITerm2Adapter`（port）**: `send_text` / `send_key` / `get_screen_contents` / `split_pane` / `create_tab` / `activate` / `close` / `get|set_variable` / `list_sessions` 等の最小インターフェース。中核ロジックはこれにのみ依存。
- **`RealAdapter`**: `iterm2` pip を実装に持つ。ここだけが websocket/async と認証を扱う。
- **`FakeAdapter`**: インメモリのセッション木を持つテスト用実装。送信・画面内容・分割を模擬し、**iTerm2 無しでユニットテストを高速に回す**。
- **テストの線引き**: 純ロジック（resolver / label / プロトコル encode-decode / send-key 符号化 / 完了検知の状態機械 / `--json` 整形）は `FakeAdapter` でユニット TDD。実 iTerm2 は split→send→read を 1 往復する**少数の結合テスト**に限定。
- 開発手順は Canon TDD に従う（[CLAUDE.md](../CLAUDE.md) のテスト戦略、出典 [t-wada 解説](https://t-wada.hatenablog.jp/entry/canon-tdd-by-kent-beck)）。テストリストは §5 のコマンド表面＋「検討余地」を起点にする。

---

## 3. socket プロトコル（cmux 踏襲）

| 項目 | 仕様 |
|---|---|
| 接続先 | Unix domain socket。既定 `${XDG_RUNTIME_DIR:-/tmp}/iterm2-cli.sock`、`ITERM2_CLI_SOCKET` で上書き |
| リクエスト | `{"id":"req-1","method":"session.send_text","params":{...}}` |
| 成功レスポンス | `{"id":"req-1","ok":true,"result":{...}}` |
| エラーレスポンス | `{"id":"req-1","ok":false,"error":{"code":"...","message":"..."}}` |
| method 名前空間 | `session.*` / `pane.*` / `window.*` / `notify.*` / `system.*` |

> 検討余地: 接続認可モード（cmux の `CMUX_SOCKET_MODE` 相当）を設けるか、ローカル socket のパーミッションのみで足りるか。実装時に決定。

---

## 4. アドレッシング `<target>`（cmux の env 注入を踏襲）

- **解決順**: 明示 `--session <id>` → ラベル（状態ファイル登録名）→ 環境変数 `$ITERM_SESSION_ID`（current pane）。省略時は current。
- デーモンは各ペインに解決済み ID を環境変数で注入（cmux の `CMUX_SURFACE_ID` 相当 = `ITERM2_CLI_SESSION`）。
- **永続状態は session_id↔label の最小マッピングのみ**（craigsc cmux の最小主義）。保存先 `${XDG_STATE_HOME:-~/.local/state}/iterm2-cli/labels.json`。branch・cwd 等は iTerm2 変数や FS から都度引く。
- ラベル正規化（`/`→`-` 等）は craigsc に倣う。

---

## 5. コマンド表面 × socket method（完全仕様・第一版）

> **完全代替方針**: 各操作は `iterm2` Python API（下表「役割 / 実装」の `async_*` メソッド）を**直接呼ぶ**。it2api へのシェルアウトはしない（実行時依存ゼロ）。it2api は移植元リファレンスに留める。

| CLI | socket method | 主な params | 役割 / 実装（Python API） |
|---|---|---|---|
| `list [--json]` | `session.list` | — | window/tab/session 階層列挙（`terminal_windows`） |
| `send <target> <text> [--literal]` | `session.send_text` | target,text | 本文送信（`async_send_text`）。既定で bracket-paste 安全に送る。`--literal` で生送出 |
| `send-key <target> <key>...` | `session.send_key` | target,keys | enter/tab/escape/backspace/delete/up/down/left/right/ctrl-c 等のキー送出 |
| `read <target> [--tail N] [--json]` | `session.read` | target,tail | 画面内容読取（`async_get_screen_contents`） |
| `busy <target> [--json]` | `session.busy` | target | busy/idle/needs-input 判定（exit code + JSON）。OSC/hook 駆動を第一、画面マーカーをフォールバック |
| `wait <target> [--timeout S] [--for STATE]` | `session.wait` | target,timeout,state | 指定状態（既定 idle）まで待機 |
| `split <target> [-h\|-v] [--profile P] [--cmd C]` | `pane.split` | target,vertical,profile,command | ペイン分割し新 session_id を返す（`async_split_pane`） |
| `tab [--profile P] [--cmd C] [--window]` | `window.new_tab` | profile,command | タブ（or `--window` で新窓）作成（`async_create_tab` / `Window.async_create`） |
| `focus <target>` | `session.focus` | target | フォーカス移動（`async_activate`） |
| `close <target> [--force]` | `session.close` | target,force | ペイン/タブ閉鎖（`async_close`） |
| `var get <target> <name>` | `session.get_var` | target,name | 変数取得（`async_get_variable`） |
| `var set <target> <name> <value>` | `session.set_var` | target,name,value | 変数設定（`async_set_variable`） |
| `set-status <target> <key> <value> [--icon I --color C]` | `session.set_status` | target,key,value,icon,color | 状態 pill → セッション名/バッジ/ユーザー変数に反映 |
| `set-progress <target> <n>` | `session.set_progress` | target,n | 進捗 → 同上 |
| `notify [--title T --body B] [--target t]` | `notify.create` | title,body,target | 通知（OSC9 / osascript フォールバック） |
| `label set <target> <name>` / `label ls` / `label rm <name>` | `session.label.*` | — | ラベル↔session_id マッピング管理 |
| `daemon [--socket PATH]` | — | — | 常駐起動 |
| `ping` | `system.ping` | — | 疎通確認 |

> 検討余地（実装フェーズで精査）:
> - `send` と `send-key` の境界（複合送信 `send --enter` を糖衣として許すか）。
> - `busy` の状態語彙（busy/idle/needs-input/done）の確定と hook イベントとの対応表。
> - `set-status`/`set-progress` の iTerm2 UI への具体的写像（名前 vs バッジ vs ユーザー変数）。
> - 階層操作（cmux の move/reorder 相当）や arrangement 保存/復元を本フェーズで含めるか、後続フェーズで Python API（`Arrangement.async_save/restore` 等）に直接実装するか。

---

## 6. 送信作法（G6 / オーケストレータ 知見の内蔵）

オーケストレータ が `(利用側スクリプト)` で苦労した送信ノウハウをライブラリに内蔵:
- **本文と確定キーの分離**: `send`（本文）→ `send-key enter`（確定）。bracket-paste 中の早期 Enter を避ける。
- **`/remote-control` 等パレット系**: 本文送出後にパレット表示を待つ遅延を入れてから確定（実測値は実装時に `(利用側スクリプト)` から転記）。
- **UTF-8**: Python API は文字列を直接扱うため AppleScript のエスケープ問題（オーケストレータ の既知ハック）は発生しない。

---

## 7. 完了/busy 検知（G2 / cmux 知見）

優先順位:
1. **hook イベント駆動（第一候補）**: Claude Code の hook（オーケストレータ の `notify_state.sh` が `.state/<id>.json` に running/needs_input/idle/done を記録）を状態源にする。最も正確。
2. **OSC 9/99/777**: ターミナル通知シーケンスを完了シグナルに使う（cmux 方式）。iTerm2 は OSC9 / OSC1337 RequestAttention に対応。
3. **画面マーカー走査（フォールバック）**: "esc to interrupt" 等のマーカー検知（オーケストレータ 現行方式）。脆いので最後段。

`busy`/`wait` はこの優先順で状態を決定する。状態語彙と hook イベントの対応は実装時に確定。

---

## 8. オーケストレータ 統合方針

| 既存（オーケストレータ） | 統合後 |
|---|---|
| `(利用側スクリプト)`（busy 検知＋送信） | `iterm2_cli` の `send`/`send-key`/`busy`/`wait` を呼ぶ薄いラッパに |
| `focus_pane.py` / `close_pane.py` | `iterm2_cli` の `focus`/`close` に置換 |
| `オーケストレータ.py` のペイン制御 | ライブラリ層を import。`オーケストレータ.py` がデーモン実体をホスト |
| `.state/window.json` の session_id↔task_id | label マッピング機構に寄せる（task_id をラベルとして登録） |
| `notify_state.sh` | 状態源として busy/wait 検知に接続 |

段階的置換: まずライブラリを切り出し、オーケストレータ の各スクリプトを 1 つずつ委譲に書き換える。一度に全置換しない。

---

## 9. リポジトリ構成（実装フェーズの想定）

```
iterm2-cli/
├── docs/                 requirements.md / design.md / research.md（本フェーズ成果物）
├── src/iterm2_cli/
│   ├── __init__.py
│   ├── cli.py            typer エントリ（薄い）
│   ├── core.py           中核ロジック（Adapter にのみ依存）
│   ├── adapter.py        ITerm2Adapter(port) / RealAdapter(iterm2 pip)
│   ├── resolver.py       <target> 解決・label 管理
│   ├── detect.py         busy/完了検知（hook/OSC/マーカー）
│   ├── daemon.py         Unix socket サーバ（フェーズ2）
│   └── client.py         socket クライアント
├── tests/
│   ├── fakes.py          FakeAdapter（インメモリ）
│   ├── test_*.py         ユニット（FakeAdapter・高速）
│   └── integration/      実 iTerm2 結合テスト（少数・要 iTerm2）
├── pyproject.toml        uv プロジェクト（typer, iterm2 依存）
└── README.md
```

> 構成は実装フェーズで確定。単一スクリプト（PEP 723）から始め、規模に応じてパッケージ化する選択肢もある。core と adapter の分離（§2.2）は規模に関わらず維持する。

---

## 10. 検証計画（設計の妥当性）

[requirements.md](./requirements.md) の受け入れ基準に対し、実装フェーズで:
1. `uv run --with iterm2 -- it2api list-sessions` でレイテンシ実測（[research.md](./research.md) §3.1 に転記）→ G4/デーモンの優先度を数値で裏付け。
2. `async_get_screen_contents` で他ペイン画面が読めるか・API 許可ダイアログ挙動。
3. OSC 9/99/777 と `notify_state.sh` を組み合わせた完了検知の実証。
4. `send`/`send-key` 分離で bracket-paste 問題が解消するか。

いずれも可逆（2-way door）。不可逆操作（push/名前変更/credential/API 許可設定改変）は実行せず 管理者 に報告（オーケストレータ 不可逆操作 規約）。
