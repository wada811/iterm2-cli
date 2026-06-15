# iterm2-cli

iTerm2 をスクリプト / AI エージェントから操作する CLI。

複数の Claude Code ペインをオーケストレーションする [orchestrator](../orchestrator) のペイン制御を、再利用可能な基盤（ライブラリ＋CLI）へ一本化することを主目的とする。

## 位置付け（it2api との差別化）

iTerm2 には同梱 CLI `it2api` があり、`iterm2` Python API のほぼ全操作（列挙・送信・分割・画面取得・変数 等）を既に CLI 化している。ただし it2api はその Python API の薄いラッパに過ぎず特権機能を持たないため、**本 CLI は同じ Python API を直接叩いて it2api を完全代替する**ことを目標とする（it2api へのシェルアウト＝実行時依存はゼロ。it2api は移植元リファレンスとして残す）。

it2api の全操作網羅は段階的に進め、まず **it2api で埋まらないギャップに価値を集中**する:

- 永続的なペイン識別（ラベル / 再起動跨ぎ）
- 高レベル操作（完了待ち `wait` / busy 検知 / リトライ）
- 構造化出力（全コマンド `--json`）
- 送信作法（本文 `send` と確定キー `send-key` の分離・bracket-paste 安全）
- 状態報告（`set-status` / `set-progress`）
- 低レイテンシ（任意のデーモン化）

設計は先行ツール cmux（manaflow-ai / craigsc）の知見を取り入れている。

## ステータス

**フェーズ1（都度接続 MVP）＋フェーズ2（デーモン）実装済み。** ライブラリ層＋CLI が動作し、
実 iTerm2 に対し list/send/send-key/read/split/tab/focus/close/var が通る。デーモン起動時は
Unix socket 経由で動作し、未起動時は都度接続に自動フォールバックする（同一コマンド表面）。

| ドキュメント | 内容 |
|---|---|
| [docs/requirements.md](./docs/requirements.md) | 要求定義（ユースケース）・要件定義（FR/NFR）・it2api ギャップ分析・受け入れ基準 |
| [docs/design.md](./docs/design.md) | 言語選定（Python）・3層アーキ・コマンド表面×socket method 完全仕様・送信作法・完了検知・オーケストレータ 統合 |
| [docs/research.md](./docs/research.md) | iTerm2 制御手段比較・it2api・cmux 知見・オーケストレータ 既存実装の調査記録 |
| [CLAUDE.md](./CLAUDE.md) | 作業ガイド（開発手順・送信規約・設計不変条件・テスト戦略・オーケストレータ 規約） |

## 使い方

iTerm2 が起動し API（Settings > General > Magic > Enable Python API）が有効な前提。
依存 `iterm2` は optional extra。`uv` で隔離実行する（グローバル pip 汚染なし）:

```sh
# 実 iTerm2 を操作するコマンド（--extra iterm2 が必要）
uv run --extra iterm2 iterm2-cli list --json          # セッション/ペイン一覧
uv run --extra iterm2 iterm2-cli send "echo hi" -t worker   # 本文送信（対象はラベル/ -s id / 省略時 current）
uv run --extra iterm2 iterm2-cli send "echo hi" -t worker -e   # 本文＋Enter（--enter）
uv run --extra iterm2 iterm2-cli send-key enter -t worker   # 確定キー
uv run --extra iterm2 iterm2-cli wait -t worker             # 完了(idle)まで待つ
uv run --extra iterm2 iterm2-cli set-status itermcli_state running   # 状態報告（busy/wait が読む）
uv run --extra iterm2 iterm2-cli read --tail 20            # current ペインの末尾20行
uv run --extra iterm2 iterm2-cli busy worker                # busy なら exit 1
uv run --extra iterm2 iterm2-cli split -v                  # 分割し新 session_id を出力
uv run --extra iterm2 iterm2-cli tab --cmd "claude"        # 新タブで起動

# ラベル（session_id↔名前の最小マッピング、iTerm2 不要）
uv run iterm2-cli label set worker <session_id>
```

`<target>` 解決順は `--session/-s <id>` → ラベル → `$ITERM_SESSION_ID`（current）。

### デーモン（低レイテンシ）

都度接続は 1 コマンド ~0.6〜1.6s かかる（websocket 接続+認証）。高頻度操作はデーモンを起動すると
接続を保持し、各コマンドは Unix socket 経由になる（**実測 list ≈ 5ms**）:

```sh
uv run --extra iterm2 iterm2-cli daemon        # 常駐起動（Ctrl-C で停止）
uv run --extra iterm2 iterm2-cli daemon --stop # 停止
```

デーモン起動中はクライアント側に iterm2 パッケージは不要（`uv run iterm2-cli list` だけで socket 経由）。
`<target>` の current 解決はクライアント側で行うため、デーモンが別プロセスでも各ペインの current は正しく解決される。
socket パスは `ITERM2_CLI_SOCKET`（既定 `/tmp/iterm2-cli.sock`）。

## 開発

```sh
uv run pytest                                   # ユニット（FakeAdapter・iTerm2 不要）
ITERM2_CLI_INTEGRATION=1 uv run --extra iterm2 pytest tests/integration   # 実 iTerm2 結合（オプトイン）
```

中核ロジックは `ITerm2Adapter`(port) にのみ依存し、テストは `FakeAdapter` を差し込む（[CLAUDE.md](./CLAUDE.md) のテスト戦略）。

## 今後の段階計画

1. ~~**フェーズ1**: ライブラリ層＋都度接続の CLI~~（実装済み）。
2. ~~**フェーズ2**: 任意デーモン（Unix socket、低レイテンシ）~~（実装済み）。
3. **段階的統合**: オーケストレータ の `(利用側スクリプト)` 等を本ライブラリへの委譲に置換。デーモン実体を オーケストレータ にホストさせる。

言語は Python、依存は `uv` で自己完結。
