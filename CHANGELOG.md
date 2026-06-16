# Changelog

本プロジェクトの主要な変更を記録します。書式は [Keep a Changelog](https://keepachangelog.com/ja/1.1.0/) に、
バージョニングは [Semantic Versioning](https://semver.org/lang/ja/) に従います。

## [Unreleased]

### Fixed

- `set-name --json` がデーモン経由で `session_id: null` を返していた契約破れを修正（クライアント側で解決した session_id を返す）。
- 既定の `tab`（current 窓）がデーモンプロセス視点の current 窓に作られうる D5 違反を修正。呼び出し元の窓をクライアント側で解決し、デーモンには具体的 session_id（`from_session`）を渡すようにした。`tab` に `-t/--target` `-s/--session` を追加。

### Changed

- バージョンを `pyproject.toml` の単一ソース化（`__version__` は `importlib.metadata` から取得し二重定義を解消）。
- デーモンの socket を bind 時点から 0600 相当で作成（`umask` で `bind`→`chmod` 間の窓を解消）。
- デーモンの接続に受信タイムアウトを追加（改行を送らない stuck client がスレッドを占有しないように）。
- `RealAdapter.list_sessions` の name 取得を `asyncio.gather` で並行化（N+1 解消）。
- 不変条件「全コマンドに `--json`」を実態（構造化出力コマンドのみ）に整合。

### Removed

- `ITerm2Adapter.get_screen_contents` の未使用引数 `max_lines` を削除（trim/tail は Controller 側で実施）。

### Added

- CI（GitHub Actions）で `pytest` + `ruff` を push/PR 時に実行。
- 結合スモークに `set_name` / `create_tab`（既存窓・from_session）を追加。
- `CONTRIBUTING.md` / `CHANGELOG.md`、`pyproject` の urls / classifiers / keywords。

## [0.0.1]

### Added

- iTerm2 を操作する CLI の初期実装（list / send / send-key / read / busy / wait / split / tab / focus / close / var / label / set-status / set-progress / ping / daemon）。
- 都度接続（RealAdapter）と常駐デーモン（Unix socket）の 2 経路を透過的に切り替える `Backend` 構成。
- `set-name` / `wait --until-text` / `tab --in-window` の 3 コマンドを追加。
- MIT ライセンス。
