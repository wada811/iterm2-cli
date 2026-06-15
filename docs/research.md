# 調査記録 — iTerm2 制御手段と先行ツール

作成日: 2026-06-15

iterm2-cli の要件定義・設計の根拠となる調査記録。一次情報（ローカル環境・iTerm2 同梱コード）と二次情報（公式ドキュメント・先行 OSS）を分けて記す。

---

## 1. 実行環境（一次情報）

| 項目 | 値 | 確認方法 |
|---|---|---|
| iTerm2 | 3.6.7beta2 | `defaults read /Applications/iTerm.app/Contents/Info.plist CFBundleShortVersionString` |
| Python API サーバ | 有効（`EnableAPIServer=1`） | `defaults read com.googlecode.iterm2 EnableAPIServer` |
| Python | 3.14.5（`/usr/local/bin/python3`） | `python3 --version` |
| Node | 25.9.0（mise 管理） | `node --version` |
| uv | 0.11.19 | `uv --version` |
| `iterm2` pip パッケージ | 未導入（システム Python に無い） | `python3 -c "import iterm2"` が失敗 |
| it2 ユーティリティ | `/Applications/iTerm.app/Contents/Resources/utilities/` に存在（it2api, it2getvar, it2setcolor, it2attention, imgcat 等） | `ls` |
| 実行コンテキスト | CLI 自体が iTerm2 内で動作（`ITERM_SESSION_ID` あり, `TERM_PROGRAM=iTerm.app`） | 環境変数 |

---

## 2. iTerm2 の外部制御手段（能力比較）

| 手段 | セッションID取得 | 画面内容読取 | ペイン作成/分割 | テキスト送信 | 変数 | CLI 適性 |
|---|---|---|---|---|---|---|
| Python API（iterm2 pip, websocket, async） | ○ | ○ | ○ | ○ | ○ | △（async/永続接続前提） |
| AppleScript（osascript） | ✗ | ✗ | ○ | ○ | ✗ | ○（だが機能不足・公式 deprecated） |
| OSC エスケープシーケンス | ✗ | △（ReportVariable のみ） | ✗ | ✗（自セッションのみ） | ○（自セッション） | ○（自セッション内限定） |
| it2* ユーティリティ | — | — | — | — | — | 既製の薄いラッパ群 |

**結論**: 「任意のペインを ID で識別 → 後からテキスト送信・画面読取」という中核ユースケースを満たせるのは **Python API のみ**。AppleScript は session_id 取得も画面読取も不可、公式に deprecated。OSC は自セッション内限定で他ペイン制御不可。

### 2.1 Python API の要点
- WebSocket（`ws://localhost:1912`, サブプロトコル `api.iterm2.com`）上の非同期 RPC。`async/await` 前提。
- 認証: `ITERM2_COOKIE`/`ITERM2_KEY` 環境変数、無ければ AppleScript で cookie 要求 → 初回は API 許可ダイアログ。
- 主要操作: セッション列挙 `app.terminal_windows[].tabs[].sessions[]`、`session.session_id`(UUID)、`app.get_session_by_id(id)`、`async_send_text`、`async_get_screen_contents`、`async_split_pane`、`async_create_tab`、`async_activate`、`async_set/get_variable`、各種 monitor（変数/フォーカス/画面/キーストローク）。
- 公式: https://iterm2.com/python-api/ , ソース https://github.com/gnachman/iTerm2/tree/master/api/library/python/iterm2

### 2.2 OSC エスケープシーケンス（自セッション）
- `OSC 1337` 系: SetUserVar / ReportVariable / SetMark / StealFocus / ClearScrollback / SetProfile / RequestAttention。
- `OSC 9`: 通知。`OSC 99` / `OSC 777`: 通知系（後述 cmux が完了検知に利用）。
- tmux 配下では `\033Ptmux;...\033\\` ラップが必要。
- 公式: https://iterm2.com/documentation-escape-codes.html

---

## 3. it2api（iTerm2 同梱 CLI）

`/Applications/iTerm.app/Contents/Resources/utilities/it2api`（Python 製）。`iterm2` pip パッケージが必要。提供サブコマンド:

`list-sessions` / `show-hierarchy` / `send-text` / `create-tab` / `split-pane` / `get-buffer`（画面取得） / `get-prompt` / `get|set-profile-property` / `read` / `get|set-window-property` / `inject` / `activate` / `activate-app` / `set|get|list-variable(s)` / `saved-arrangement` / `show-focus` / `list-profiles` / `set-grid-size` / tmux 連携各種 / `sort-tabs` / color-preset / `monitor-variable` / `monitor-focus` / `set-cursor-color` / `monitor-screen` / `show-selection`。

→ **生の API 操作はほぼ網羅済み。** 新 CLI は「素の it2api で埋まらないギャップ」（高レベル操作・永続識別・構造化出力・送信作法・レイテンシ）に価値を集中させる。

### 3.1 動作・レイテンシ実測（2026-06-15 実測）
- 実行: `uv run --quiet --python 3.12 --with iterm2 -- python <it2api> list-sessions`（uv 隔離環境。グローバル pip 汚染なし）。
- **認証ダイアログは出ず**そのまま列挙成功。本セッションが iTerm2 内（API 許可済み環境）で動くため cookie/認証がキャッシュ済みと見られる。
- レイテンシ（`/usr/bin/time -p` の real）:
  - **cold（依存キャッシュ後の初回・python 起動＋接続＋認証込み）: 1.57s**
  - **warm（2回目）: 0.58s**
- 含意（G4）: **1 コマンドあたり概ね 0.6〜1.6s**。対話的な単発操作なら許容だが、高頻度バッチ（多数の send/read を連続）では無視できない。→ デーモン化（接続保持で接続/認証コストを償却）の優先度を裏付ける。
- 補足: list-sessions の実出力でセッション名に状態を表す絵文字（🔴/✳/⠂ 等）を入れている例が観測でき、「セッション名で状態を表示する」運用が一般的と分かった（本 CLI の `set-status` はこれを変数ベースで一般化）。

---

## 4. 先行ツール cmux（二次情報）

「cmux」は同名で 2 系統あり、それぞれ別の教訓。

### 4.1 manaflow-ai/cmux（Swift ネイティブ・AI エージェント向けターミナル）
- アーキ: Ghostty ベースのネイティブ macOS ターミナル。**スクリプタブル CLI ＋ Unix socket API**。
- socket: `/tmp/cmux.sock`（Release）/ `/tmp/cmux-debug.sock`（Debug）、`CMUX_SOCKET_PATH` で上書き。`CMUX_SOCKET_MODE`（cmuxOnly/allowAll/off）。
- プロトコル: JSON-RPC 風。リクエスト `{"id":"req-1","method":"workspace.list","params":{}}` / レスポンス `{"id":"req-1","ok":true,"result":{...}}`。v1 の `{"command":...}` 形式は非対応。
- method 名前空間: `workspace.*` / `surface.*`（split/send_text/send_key/list）/ `notification.create` / `system.ping` ほか。**CLI サブコマンドは socket method の薄いエイリアス。**
- コマンド体系: `new-workspace`/`new-split`/`new-pane`/`new-surface`/`select-workspace`/`close-*`/`move-*`/`reorder-*`/`send`/`send-key`/`send-panel`/`focus-pane`/`focus-window`/`notify`/`claude-hook`/`hooks setup [agent]`/`set-status`/`set-progress`/`log`/`sidebar-state`/`restore-session`/`surface resume set|show|clear`/`browser`/`ping`。
- **send / send-key 分離**: `send "text"`（本文）と `send-key enter|tab|escape|backspace|delete|up|down|left|right`（キー）を別コマンドに。
- env 自動注入: `CMUX_WORKSPACE_ID` / `CMUX_SURFACE_ID` を各 surface に設定 → CLI は引数省略で current 対象。`--workspace`/`--surface`/`--window` で明示。
- 状態報告: `set-status key value --icon --color`（status pill）/ `set-progress`（progress bar）/ `log --level`。サイドバーに反映。
- 完了/通知検知: ターミナルの **OSC 9 / 99 / 777** を拾って blue ring・通知・「Jump to latest unread」。
- 設定: `~/.config/ghostty/config` 参照、`cmux.json` でプロジェクト別カスタムコマンド。`--json` 出力対応。
- 出典: https://github.com/manaflow-ai/cmux , CLI リファレンス https://cmux.com/docs/api , 紹介記事 https://dev.to/arshtechpro/cmux-the-native-macos-terminal-built-for-running-ai-coding-agents-in-parallel-52il

### 4.2 craigsc/cmux（Bash 一枚, "tmux for Claude Code"）
- アーキ: 単一 `cmux.sh`（~560 行）を shell に source。git worktree ライフサイクル管理。依存は git と Claude CLI のみ、ビルド・テスト無し。
- コマンド: `new <branch>`（worktree+branch 作成→`.cmux/setup`実行→Claude 起動・冪等）/ `start <branch>` / `cd [branch]` / `ls` / `merge [branch]` / `rm [branch]` / `init`。
- 工夫: 動詞+対象の明快な体系、tab 補完、引数省略時 `$PWD` から worktree 推定、branch 名正規化（`/`→`-`）、worktree は `.worktrees/<branch>/`（gitignore）。
- 状態: **git/ファイルシステムを真実とし明示的メタデータ DB を持たない最小主義。**
- 出典: https://github.com/craigsc/cmux

### 4.3 iterm2-cli に取り入れる知見
1. **socket プロトコル形**: Unix socket + JSON `{id,method,params}`/`{id,ok,result}`、名前空間 method、CLI は薄いエイリアス（manaflow-ai）。
2. **send / send-key 分離**: 「本文送信→遅延→Enter」を明快に置換（manaflow-ai）。
3. **env による current 注入と `<target>` 省略 UX**（両 cmux）。
4. **状態報告プリミティブ** `set-status`/`set-progress`/`log` → iTerm2 のセッション名/バッジ/変数に対応付け。
5. **OSC 9/99/777・hook イベント駆動の完了検知** を第一候補に、画面マーカー走査はフォールバック。
6. **最小状態主義**（craigsc）: 永続化は session_id↔label の最小マッピングのみ。
7. **動詞+対象・冪等・tab 補完**の UX（craigsc）。

### 4.4 オーケストレーション系ツールに共通する既知の課題（一般知見）

複数ペインを操る既存ツールに共通して観察される落とし穴。本 CLI はこれらを設計で回避する:
- bracket-paste 中の早期 Enter → 本文と確定キーを分離（`send` / `send-key`）。
- busy 判定を画面マーカー走査に頼ると脆い → user 変数（`set-status` / OSC 1337 SetUserVar）を第一に。
- close 検知が `async_refresh()` の前だと遅延する → 列挙前に refresh。
- AppleScript 経由の UTF-8 エスケープ問題 → Python API は文字列を直接扱うため発生しない。
