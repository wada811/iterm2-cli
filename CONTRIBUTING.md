# コントリビューションガイド

iterm2-cli への貢献ありがとうございます。本書は最小限の入口です。**設計の一次情報は [docs/](./docs/)**（要件 `requirements.md` / 設計 `design.md` / 調査 `research.md`）、**各決定の理由は [docs/decisions.md](./docs/decisions.md)**、**作業の進め方・守るべき不変条件は [CLAUDE.md](./CLAUDE.md)** にまとまっています。新しい操作を足すときは CLAUDE.md「新しい操作を足す手順」に従ってください。

## 開発環境

- 言語は Python、依存・実行は [`uv`](https://docs.astral.sh/uv/)（グローバル `pip install` はしない）。
- セットアップ不要。下記コマンドは `uv` が仮想環境を自動作成して実行します。

## 検証（PR 前に必ず緑にする）

```sh
uv run pytest                      # ユニット＋契約テスト（iTerm2 不要・FakeAdapter）
uv run ruff check src tests        # lint（F=pyflakes / B=bugbear / I=import順）
```

実 iTerm2 への結合スモーク（オプトイン・iTerm2 が起動し API 有効な状態で）:

```sh
ITERM2_CLI_INTEGRATION=1 uv run --extra iterm2 pytest tests/integration -q
```

## 守ってほしいこと（要点・詳細は CLAUDE.md）

- **テスタビリティの継ぎ目を保つ**: 外部 I/O は `adapter.py` の port に隔離し、中核は adapter にのみ依存。テストは `FakeAdapter` で回す。
- **新しい操作はテストを伴わせる**: 特に `tests/test_daemon.py` の契約テスト（Backend 操作集合の一致 assert）に追従させると、3 層（client / handler / controller）のドリフトを検出できます。
- **`it2api` にシェルアウトしない**: 全操作を `iterm2` Python API で直接実装します。
- **ユーザー向け文言（コミットメッセージ・ドキュメント・コメント）は日本語**。

## コミット / PR

- コミットは日本語の要約＋本文。`push` は明示の指示があるときだけ。
- 変更がユーザーに見える振る舞いを変える場合は [CHANGELOG.md](./CHANGELOG.md) の `Unreleased` に 1 行追記してください。
