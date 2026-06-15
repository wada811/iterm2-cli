# CLAUDE.md — iterm2-cli 作業ガイド

このリポジトリで作業する Claude / 開発者向けの運用ガイド。**何を作るかは [docs/](./docs/) が一次情報**（要件 `requirements.md` / 設計 `design.md` / 調査 `research.md`）。本書は「どう進めるか」と「守るべき不変条件」をまとめる。

コマンド表面・使い方・アーキ俯瞰は [README.md](./README.md) が入口。

## このプロジェクトの一行説明

iTerm2 をスクリプト / AI エージェントから操作する CLI。同梱 `it2api` を**完全代替**することを目標に、`iterm2` Python API を直接叩く。複数ペイン（並列エージェント等）のオーケストレーション基盤として単体で完結させる。

## 開発の進め方

- **言語 = Python**（確定。理由は [docs/design.md](./docs/design.md) §1）。新言語の導入は設計変更なので独断で行わない。
- **依存・実行 = `uv`**。グローバル `pip install` はしない（環境汚染を避ける）。単発実行は PEP 723 インラインメタデータ、または `uv run --with iterm2 -- ...`。
- **リポジトリ構成（想定）**: [docs/design.md](./docs/design.md) §9。`src/iterm2_cli/`（ライブラリ中核）＋ 薄い CLI（typer）＋ 任意デーモン。単一スクリプトから始め、規模に応じてパッケージ化してよい。
- **コミット**: 日本語の要約 + 本文。push は明示の指示があるときだけ。

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
5. **完了/busy 検知の優先順** = `user.itermcli_state`（`set-status` / OSC 1337 SetUserVar で書かれる）→ 画面マーカー（フォールバック・env で上書き可）（§7）。
6. **全コマンドに `--json`** を用意（機械可読出力）。
7. **エラーは silent fail させない**（接続/認証失敗・対象セッション消失を明示）。

## 新しい操作を足す手順（it2api 機能の取り込み）

完全代替は**段階的**。実運用で「この it2api 機能が要る」となったら、その操作だけを Python API で
直接実装して足す（**シェルアウトはしない**＝不変条件 1）。it2api / iterm2 Python API は移植元リファレンス。

1. **移植元を確認**: it2api の該当サブコマンド or iterm2 Python API の `async_*` メソッドを見る。
2. **port**: `ITerm2Adapter`(adapter.py) に最小メソッドを足し、`RealAdapter` で実装、`tests/fakes.py` の `FakeAdapter` にも実装。
3. **中核**: `Controller`(core.py) に操作を足す（adapter にのみ依存・`<target>` 解決を通す）。
4. **表面**: `Backend`(backend.py) Protocol に署名追加。socket 経由が要るなら `protocol.HANDLERS` に登録＋`DaemonClient`(client.py) にメソッド追加。
5. **CLI**: cli.py にサブコマンド配線（target 指定規則・`--json`・exit code に従う）。
6. **テスト**: ユニット（FakeAdapter）＋ `tests/test_daemon.py` の契約テスト `DRIVEN` に追加（**Backend 集合一致 assert が追従漏れを強制検出**）＋ 必要なら結合（オプトイン）。
7. **docs**: README コマンド表 / design §5 socket 契約表を更新。
8. `uv run pytest` と `uv run ruff check src tests` が緑。

## プロンプト / ペイン送信の規約

- **本文とキーを分離**: 本文は `send <target> <text>`、確定は `send-key <target> enter`。本文送信直後に Enter を混ぜない（bracket-paste 中の早期確定を避ける）。
- **コマンドパレット系（`/`始まりの TUI 等）**: 本文送出 → パレット表示待ちの遅延 → 確定キー。遅延は対象 TUI に合わせて調整する。
- UTF-8 は Python API が文字列を直接扱うので、AppleScript のエスケープ問題は発生しない。

## 出力言語

ユーザーへの応答・コメント・ドキュメント・コミットメッセージは**日本語**。
