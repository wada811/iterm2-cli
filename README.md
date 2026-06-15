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

要件定義・設計フェーズ。実装は次フェーズ。

| ドキュメント | 内容 |
|---|---|
| [docs/requirements.md](./docs/requirements.md) | 要求定義（ユースケース）・要件定義（FR/NFR）・it2api ギャップ分析・受け入れ基準 |
| [docs/design.md](./docs/design.md) | 言語選定（Python）・3層アーキ・コマンド表面×socket method 完全仕様・送信作法・完了検知・オーケストレータ 統合 |
| [docs/research.md](./docs/research.md) | iTerm2 制御手段比較・it2api・cmux 知見・オーケストレータ 既存実装の調査記録 |

## 今後の段階計画

1. **フェーズ1**: ライブラリ層＋都度接続の CLI（list/send/send-key/read/busy/wait/split/tab/focus/close/var）。
2. **フェーズ2**: 任意デーモン（Unix socket、低レイテンシ）。実体は オーケストレータ にホストさせる構成を軸に。
3. **段階的統合**: オーケストレータ の `(利用側スクリプト)` 等を本ライブラリへの委譲に置換。

言語は Python、依存は `uv`（PEP 723）で自己完結。
