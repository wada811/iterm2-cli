# 設計 — iterm2-cli

作成日: 2026-06-15

要件（[requirements.md](./requirements.md)）を満たす実装設計。言語選定・アーキテクチャ・コマンド表面・socket プロトコル・送信作法・完了検知・外部からの利用方法を定める。調査根拠は [research.md](./research.md)。

> 本書はアーキテクチャと socket 契約を定める。CLI の利用方法・フラグ・exit code・`--json` 形は
> 利用者向けの [README](../README.md) を正とし、ここでは重複させない。

---

## 1. 言語選定（Python に確定）

| 観点 | Python（採用） | TypeScript/Node | Go / Rust |
|---|---|---|---|
| iTerm2 API アクセス | `iterm2` pip を直接利用（公式・最短） | ネイティブ手段なし。Python 橋渡し or websocket+protobuf 自前実装 | protobuf+認証を全自前実装 |
| 利用側との統合 | Python 製の利用側とライブラリ共有が容易 | 言語境界が増える | 言語境界が増える |
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
│  ライブラリ層（中核ロジック）iterm2_cli         │  ← 外部から import 可能
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
- **`Backend` Protocol**（`backend.py`）が操作表面を定義し、`Controller`（都度接続）と `DaemonClient`（socket）が共に満たす。`make_controller()` は `Backend` を返し、両者を透過的に差し替える。runtime_checkable によりテストで両実装の表面一致を担保（ドリフト検出）。
- **中核ロジックは `ITerm2Adapter` インターフェースにのみ依存**し、`iterm2` pip を直接触らない。本番は `RealAdapter`、テストは `FakeAdapter` を差す（ports & adapters / humble object）。→ §2.2。
- **デーモン未起動なら CLI が自前で都度接続にフォールバック。** フェーズ1（都度接続）とフェーズ2（デーモン）を**同一コマンド表面**で両立。
- **デーモンは接続ごとにスレッド処理**（head-of-line 回避）。長い `wait` が走っても他コマンドは即応する。RealAdapter は単一イベントループ上で呼び出しを直列化するためスレッド安全。
- **ライブラリ層を外部の利用側が import** でき、各自のアドホックな iTerm2 制御を本 CLI に寄せられる。

### 2.1 レイテンシ対策（段階導入）
> 実測（2026-06-15, [research.md](./research.md) §3.1）: it2api 都度接続は **cold 1.57s / warm 0.58s**。単発なら許容、高頻度バッチでは無視できず、デーモン化を裏付ける。

- **フェーズ1（既定）**: it2api 同様コマンド毎に websocket 接続+認証。実装単純で正しさを担保。対話用途では実用範囲（warm ~0.6s）。
- **フェーズ2（必要時）**: 接続を保持する常駐 `iterm2-cli daemon` を Unix socket で待受け、CLI は軽量クライアント。高頻度バッチ向け。
  - 既に「接続を保持する常駐プロセス」を持つ利用側であれば、**デーモンの実体をその常駐プロセスに寄せ**（CLI がライブラリを提供、利用側がホスト）二重管理を避けられる。`daemon` サブコマンドは単独利用時の選択肢として用意。

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

> 認可（決定済）: ローカル単一ユーザー前提とし、**socket ファイルを 0600** にするのみ。cmux の `CMUX_SOCKET_MODE` 相当の認可モードは設けない（必要になれば追加）。

---

## 4. アドレッシング `<target>`（cmux の env 注入を踏襲）

- **解決順**: 明示 `--session <id>` → ラベル（状態ファイル登録名）→ 環境変数 `$ITERM_SESSION_ID`（current pane）。省略時は current。
- デーモンは各ペインに解決済み ID を環境変数で注入（cmux の `CMUX_SURFACE_ID` 相当 = `ITERM2_CLI_SESSION`）。
- **永続状態は session_id↔label の最小マッピングのみ**（craigsc cmux の最小主義）。保存先 `${XDG_STATE_HOME:-~/.local/state}/iterm2-cli/labels.json`。branch・cwd 等は iTerm2 変数や FS から都度引く。
- ラベル正規化（`/`→`-` 等）は craigsc に倣う。

---

## 5. コマンド表面 × socket method（完全仕様・第一版）

> **完全代替方針**: 各操作は `iterm2` Python API（下表「役割 / 実装」の `async_*` メソッド）を**直接呼ぶ**。it2api へのシェルアウトはしない（実行時依存ゼロ）。it2api は移植元リファレンスに留める。

本節は **socket method ↔ Controller / Python API の契約**を定める（CLI のフラグ・target 指定規則・
exit code・`--json` 形は利用者向けの [README](../README.md) を正とし、ここでは重複させない）。
`params` は socket リクエストの `params` キー（`session` は具体的な session_id。current 解決はクライアント側）。

| socket method | params | 対応 CLI | 実装（Controller / Python API） |
|---|---|---|---|
| `session.list` | — | `list` | `terminal_windows` 走査 |
| `session.send_text` | session, text | `send` | `async_send_text` |
| `session.send_key` | session, keys | `send-key` | keys を符号化 → `async_send_text` |
| `session.read` | session, tail | `read` | `async_get_screen_contents` |
| `session.busy` | session | `busy` | `_state`（`user.itermcli_state` 優先 → 画面マーカー、§7）|
| `session.wait` | session, until, timeout, poll_interval | `wait` | `wait_until`（既定 until=idle）|
| `pane.split` | session, vertical, profile | `split` | `async_split_pane` → 新 session_id |
| `window.new_tab` | profile, command, new_window | `tab` | `async_create_tab` / `Window.async_create` → 新 session_id |
| `session.focus` | session | `focus` | `async_activate` |
| `session.close` | session, force | `close` | `async_close` |
| `session.get_var` | session, name | `var get` | `async_get_variable` |
| `session.set_var` | session, name, value | `var set` / `set-status` / `set-progress` | `async_set_variable` |
| `system.ping` | — | `ping` | 疎通確認 |
| `system.stop` | — | `daemon --stop` | デーモン停止（HANDLERS 外の特別扱い）|

- `set-status <key> <value>` は `session.set_var` で `user.<key>` を書く糖衣（状態は `itermcli_state`）。`set-progress` は `user.itermcli_progress`。
- `label set/ls/rm` は session_id↔ラベルのローカル永続化で、**socket を経由しない**（iTerm2 不要）。
- **notify は将来**: design 初版から外す。必要時に追加。

> 検討余地（決定済）:
> - **send/send-key の境界**: `send` に `--enter/-e` 糖衣を追加（本文送出→確定キーを順に送る）。send-key は維持。
> - **busy の状態語彙**: `busy`/`needs-input`/`idle`/`unknown`。hook の語彙 `running/needs_input/idle/done` は変数値として吸収（running→busy, idle/done→idle）。
> - **set-status/set-progress の写像**: **user 変数に書く（非破壊）**。`set-status <k> <v>`→`user.<k>`、状態は `user.itermcli_state`、進捗は `user.itermcli_progress`。セッション名は既存の命名（状態絵文字など）を壊さないため既定で触らない（バッジ反映は将来オプション）。
> - **階層操作（move/reorder）・arrangement**: 初版スコープ外。必要時に Python API（`Arrangement.async_save/restore` 等）で追加。

---

## 6. 送信作法（G6）

ペイン送信で踏みやすい落とし穴をライブラリに内蔵:
- **本文と確定キーの分離**: `send`（本文）→ `send-key enter`（確定）。bracket-paste 中の早期 Enter を避ける。
- **コマンドパレット系の TUI**: 本文送出後にパレット表示を待つ遅延を入れてから確定（遅延は対象 TUI に合わせる）。
- **UTF-8**: Python API は文字列を直接扱うため AppleScript のエスケープ問題は発生しない。

---

## 7. 完了/busy 検知（G2 / cmux 知見）

**実装方針（決定済）**: 状態を**セッション user 変数 `user.itermcli_state` に集約**して読む。書き手は複数あってよい:
- エージェント/hook が `iterm2-cli set-status itermcli_state running|needs-input|idle` で書く（最も正確）。
- ペイン内から **OSC 1337 SetUserVar=itermcli_state=...** で書く（OSC 9/99/777 通知を直接購読する代わりに、変数へ集約できる）。

`busy`/`wait` の判定優先順（`Controller._state`）:
1. **`user.itermcli_state`**（あれば最優先。`running/busy`→busy, `needs_input`→needs-input, `idle/done`→idle）。
2. **画面マーカー走査（フォールバック）**: "esc to interrupt" 等。脆いので最後段。

> 実機確認済: 変数 running→busy / idle→idle を判定（[research](./research.md) 同様の手順で検証）。

`busy`/`wait` はこの優先順で状態を決定する。状態語彙と hook イベントの対応は実装時に確定。

---

## 8. 外部からの利用方法

本 CLI は単体で完結し、外部の利用側は次の 3 経路のいずれでも統合できる:

| 経路 | 使い方 | 向く場面 |
|---|---|---|
| **CLI** | `iterm2-cli <cmd>` をサブプロセス実行、`--json`/exit code で結果取得 | 言語非依存・単発 |
| **ライブラリ** | `from iterm2_cli import Controller, RealAdapter` を import | Python の利用側・接続を使い回したい |
| **デーモン + socket** | `iterm2-cli daemon` を常駐させ、CLI/独自クライアントが socket 経由 | 高頻度・低レイテンシ。利用側が常駐プロセスを持つなら実体をそこにホスト可 |

状態報告（`set-status` / OSC 1337 SetUserVar で `user.itermcli_state` を書く）とラベル登録
（`label set`）を使えば、利用側はペインを名前で識別し完了を待てる。

---

## 9. リポジトリ構成

```
iterm2-cli/
├── docs/                 requirements.md / design.md / research.md
├── src/iterm2_cli/
│   ├── cli.py            typer エントリ（薄い）
│   ├── core.py           Controller（中核ロジック・Adapter にのみ依存）
│   ├── backend.py        Backend Protocol（Controller / DaemonClient の共通表面）
│   ├── adapter.py        ITerm2Adapter(port) + SessionInfo
│   ├── adapter_real.py   RealAdapter（iterm2 pip、async を単一ループに隔離）
│   ├── resolver.py       <target> 解決      labels.py  ラベル永続化
│   ├── detect.py         busy/完了検知       keys.py    send-key 符号化
│   └── daemon.py / client.py / protocol.py  デーモン / クライアント / socket プロトコル
├── tests/                ユニット（FakeAdapter）+ integration/（実 iTerm2・オプトイン）
└── pyproject.toml        uv プロジェクト（typer 依存、iterm2 は optional extra）
```

> core と adapter の分離（§2.2）は維持する。

---

## 10. 検証

- **ユニット**: `uv run pytest`（`FakeAdapter` ベース・iTerm2 不要）。resolver / keys / labels / detect /
  Controller / CLI / protocol / daemon（実 Unix socket 越し）/ Backend 整合 / 全操作のデーモン往復契約。
- **lint**: `uv run ruff check src tests`（F / B / I）。
- **結合（実 iTerm2・オプトイン）**: `ITERM2_CLI_INTEGRATION=1 uv run --extra iterm2 pytest tests/integration`。
  create→send→read→close と var/split/activate/list を使い捨てウィンドウで実機確認。
- **レイテンシ**: 都度接続 cold 1.57s / warm 0.58s、デーモン経由 list ≈ 5ms（[research.md](./research.md) §3.1）。
- **並行性**: デーモンへ 8 スレッド×並行 RPC を 0 errors で実機確認。

---

## 11. 既知の制限・将来の改善

実害が小さく据え置いている項目。実運用で必要になったら着手する（鮮度を保つため最小限に記す）。

- **デーモン経由 `wait` のクライアント無タイムアウト**: デーモンが応答も切断もせず固まると無限待ち（kill 時は接続断で即整形済みエラー）。必要なら socket に wait+余裕のタイムアウトを設定。
- **デーモンの可観測性**: ログ／PID ファイルが無くデバッグしづらい。`--log` 任意・PID 出力で改善可。
- **socket cleanup の TOCTOU**: 同一パスへ複数デーモンを並走起動すると稀に socket ファイルを取り違える（is_alive ガードはあるが非アトミック）。
- **結合テストの穴**: `tab`（現ウィンドウ版）・`wait`（実 busy→idle 遷移）は実機未被覆。
- **it2api 全操作の網羅**: profile / arrangement / tmux / 各種 monitor は未実装（完全代替は段階的）。階層操作（move/reorder）も未実装。
- **公開時の整備**: LICENSE・`pyproject` メタデータ（authors / urls / classifiers）。
