# Changelog

本プロジェクトの主要な変更を記録します。書式は [Keep a Changelog](https://keepachangelog.com/ja/1.1.0/) に、
バージョニングは [Semantic Versioning](https://semver.org/lang/ja/) に従います。

## [Unreleased]

### Fixed

- `set-name --json` がデーモン経由で `session_id: null` を返していた契約破れを修正（クライアント側で解決した session_id を返す）。
- 既定の `tab`（current 窓）がデーモンプロセス視点の current 窓に作られうる D5 違反を修正。呼び出し元の窓をクライアント側で解決し、デーモンには具体的 session_id（`from_session`）を渡すようにした。`tab` に `-t/--target` `-s/--session` を追加。

### Changed

- コマンド命名を cmux / tmux 準拠の「動詞-名詞」に統一（D11）: `window`→`new-window`、`tab`→`new-tab`、`split`→`new-split`、`set-name`→`rename`。操作系（send/read 等）は素の動詞のまま。
- `new-split` の方向指定を cmux 風の位置引数 `right`/`left`/`down`/`up` に変更（旧 `-h`/`-b` フラグを置換。left/right=垂直、down/up=水平、left/up=前側）。
- 新規ウィンドウ作成を `tab --window` から独立コマンド（socket `window.new`）に分離（D10）。タブ作成は「タブを作る」一操作に専念し、`--in-window` は行き先指定として存続。1 コマンド 1 操作・不変条件 #2（CLI↔socket 1:1）に整合。
- `daemon --stop` フラグを `daemon start` / `daemon stop` サブコマンドに分離（起動と停止は別操作・1 コマンド 1 操作）。
- バージョンを `pyproject.toml` の単一ソース化（`__version__` は `importlib.metadata` から取得し二重定義を解消）。
- デーモンの socket を bind 時点から 0600 相当で作成（`umask` で `bind`→`chmod` 間の窓を解消）。
- デーモンの接続に受信タイムアウトを追加（改行を送らない stuck client がスレッドを占有しないように）。
- `RealAdapter.list_sessions` の name 取得を `asyncio.gather` で並行化（N+1 解消）。
- 不変条件「全コマンドに `--json`」を実態（構造化出力コマンドのみ）に整合。

### Removed

- `ITerm2Adapter.get_screen_contents` の未使用引数 `max_lines` を削除（trim/tail は Controller 側で実施）。
- `tab --window` フラグを削除（後方互換エイリアスは残さない。新規ウィンドウは `window` コマンド。D10）。

### Added

- `identify` コマンド（cmux 相当）: 呼び出し元（current）の session を特定して出力（`--json` で全フィールド＋割当 label）。current 解決はクライアント側（D5）、情報は `session.list` を再利用し専用 socket method を持たない。
- `MIGRATION.md`: 0.0.1 からの破壊的変更（コマンド改名）の移行ガイド。
- CI（GitHub Actions）で `pytest` + `ruff` を push/PR 時に実行。
- 結合スモークに `set_name` / `create_tab`（既存窓・from_session）を追加。
- `CONTRIBUTING.md` / `CHANGELOG.md`、`pyproject` の urls / classifiers / keywords。

## [0.0.1]

### Added

- iTerm2 を操作する CLI の初期実装（list / send / send-key / read / busy / wait / split / tab / focus / close / var / label / set-status / set-progress / ping / daemon）。
- 都度接続（RealAdapter）と常駐デーモン（Unix socket）の 2 経路を透過的に切り替える `Backend` 構成。
- `set-name` / `wait --until-text` / `tab --in-window` の 3 コマンドを追加。
- MIT ライセンス。
