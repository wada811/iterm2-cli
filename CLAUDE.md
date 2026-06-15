# CLAUDE.md — iterm2-cli 作業ガイド

このリポジトリで作業する Claude / 開発者向けの運用ガイド。**何を作るかは [docs/](./docs/) が一次情報**（要件 `requirements.md` / 設計 `design.md` / 調査 `research.md`）。本書は「どう進めるか」と「守るべき不変条件」をまとめる。

現状: **要件定義・設計フェーズ完了、実装は未着手**（リポジトリは docs と本書のみ）。

## このプロジェクトの一行説明

iTerm2 をスクリプト / AI エージェントから操作する CLI。同梱 `it2api` を**完全代替**することを目標に、`iterm2` Python API を直接叩く。主用途は orchestrator のペイン制御基盤。

## 開発の進め方

- **言語 = Python**（確定。理由は [docs/design.md](./docs/design.md) §1）。新言語の導入は設計変更なので独断で行わない。
- **依存・実行 = `uv`**。グローバル `pip install` はしない（環境汚染を避ける）。単発実行は PEP 723 インラインメタデータ、または `uv run --with iterm2 -- ...`。
- **リポジトリ構成（想定）**: [docs/design.md](./docs/design.md) §9。`src/iterm2_cli/`（ライブラリ中核）＋ 薄い CLI（typer）＋ 任意デーモン。単一スクリプトから始め、規模に応じてパッケージ化してよい。
- **コミット**: 日本語の要約 + 本文。末尾に `Co-Authored-By` トレーラ。push は**しない**（§ オーケストレータ 規約参照）。
- **作業ブランチ**: 現在は `main` に一本化（オーケストレータ の feature worktree は廃止済み）。

## 検証（実装したら必ず回す）

- iTerm2 が起動し API 有効（`defaults read com.googlecode.iterm2 EnableAPIServer` = 1）な前提。
- lint ゲート: `uv run ruff check src tests`（F=pyflakes / B=bugbear / I=import順。B008 は typer 用法のため除外）。
- 動作確認は **uv 隔離環境**で。例: `uv run --with iterm2 -- python -m iterm2_cli list --json`。
- レイテンシ感覚: it2api 都度接続で cold 1.57s / warm 0.58s（[docs/research.md](./docs/research.md) §3.1）。高頻度操作はデーモン経由を測る。
- 「実装したつもり」で終えず、実際にペインを作る/送る/読むを 1 往復させて確認する。

## テスト戦略（Canon TDD ＋ テスタブルな構造）

外部の状態を持つアプリ（iTerm2）を async websocket で操作するため、**テスタビリティの継ぎ目（seam）設計が最重要**。素朴に全部を実 iTerm2 でテストすると遅く（cold 1.57s）不安定になる。

- **adapter で外部 I/O を隔離（ports & adapters / humble object）**: `iterm2` Python API は薄い adapter（`adapter.py`）の裏に閉じ込める。中核ロジックは adapter インターフェースにのみ依存させ、テストでは **fake adapter** を差し込む。
- **ユニット（fake・高速）で TDD する対象**: `<target>` 解決、label マッピング、socket プロトコルの encode/decode、send/send-key のキー符号化、**完了/busy 検知の状態機械**、`--json` 整形。← iTerm2 不要で赤緑が回る。
- **結合テスト（実 iTerm2・少数）**: split→send→read を実際に 1 往復。遅いので最小限・別レーン。
- **Canon TDD の進め方**（[t-wada 解説](https://t-wada.hatenablog.jp/entry/canon-tdd-by-kent-beck)）:
  1. **テストリスト先行**: [docs/design.md](./docs/design.md) §5 のコマンド表面と末尾「検討余地」を期待振る舞いの一覧として起点にする。
  2. リストから 1 つ選び、実行可能なテストを書く → 緑にする → **緑後に**リファクタ。空になるまで反復。
  3. 失敗パターンを避ける: テストに実装判断を混ぜない／全項目を先に具体化しない／緑化とリファクタを混ぜない／**過度な抽象化をしない**（3層を最初から作り込まず、都度接続 1 コマンドの緑から）。

## 設計上の不変条件（実装時に必ず守る）

これらを破る変更は設計判断の変更なので、docs を更新し理由を残す:

1. **it2api にシェルアウトしない**。全操作を `iterm2` Python API へ直接実装する（it2api は移植元リファレンス）。
2. **CLI サブコマンド ↔ socket method を 1:1** に保つ。CLI は薄いクライアント、ロジックはライブラリ層に置く（[design.md](./docs/design.md) §2, §5）。
3. **`<target>` 解決順** = `--session <id>` → ラベル → `$ITERM_SESSION_ID`（current）。省略時 current（§4）。
4. **永続状態は session_id↔label の最小マッピングのみ**。branch/cwd 等は都度 iTerm2 変数や FS から引く。
5. **完了/busy 検知の優先順** = hook イベント → OSC 9/99/777 → 画面マーカー（フォールバック）（§7）。
6. **全コマンドに `--json`** を用意（機械可読出力）。
7. **エラーは silent fail させない**（接続/認証失敗・対象セッション消失を明示）。

## プロンプト / ペイン送信の規約

- **本文とキーを分離**: 本文は `send <target> <text>`、確定は `send-key <target> enter`。本文送信直後に Enter を混ぜない（bracket-paste 中の早期確定を避ける）。
- **`/remote-control` などパレット系**: 本文送出 → パレット表示待ちの遅延 → 確定キー。実測遅延は オーケストレータ の `(利用側スクリプト)` を参照して合わせる。
- UTF-8 は Python API が文字列を直接扱うので、AppleScript のエスケープ問題は発生しない。

## オーケストレータ 規約（重要・不可逆操作）

このプロジェクトは orchestrator の一部として動くことがある。**不可逆・重大な操作は実行せず停止し、管理者 に報告**する:

- 公開リポジトリへの push / リポジトリ名変更・削除、本番デプロイ、credential 生成/失効、**worktree やリポジトリの物理削除**、API 許可設定(`disable-automation-auth`)の改変 など。
- 迷ったら 不可逆操作 扱い（安全側）。規約全文: `~/orchestrator/recipes/irreversible-ops.md`。
- 報告は `~/orchestrator/.state/events.jsonl` に 1 行 JSON で追記。

## 出力言語

ユーザーへの応答・コメント・ドキュメント・コミットメッセージは**日本語**。
