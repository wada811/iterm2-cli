# 設計思想・決定記録（なぜこうなっているか）

主要な設計判断を「決定／理由／退けた案」で簡潔に残す（ADR-lite）。各論の詳細は参照先に。
*何を*するかは各ドキュメント、*なぜ*そうしたかは本書、という分担。

---

## D1. it2api を完全代替する（シェルアウトしない・段階的に取り込む）

- **決定**: it2api を呼ばず、同じ `iterm2` Python API を直接叩く。必要になった操作だけ順次取り込む。
- **理由**: it2api はその Python API の薄いラッパに過ぎず特権機能を持たない。むしろ it2api への
  シェルアウトはプロセス毎起動・テキストのみ出力・接続非共有でデーモンの恩恵を失い、劣る。
- **退けた案**: it2api をサブプロセスで呼ぶ薄い CLI（実装は楽だが上記の劣化）。
- 参照: [requirements §3](./requirements.md) / [CLAUDE.md 不変条件 1](../CLAUDE.md)。

## D2. 言語は Python

- **決定**: Python 実装。
- **理由**: iTerm2 の実用 API は Python（async/websocket）のみ。Node/Go は API 到達コストが本質的に高く、
  結局 Python へ橋渡しするとレイテンシ・複雑性で勝てない。
- **退けた案**: Node/TS（ネイティブ手段なし）、Go/Rust（protobuf 自前実装の負担大）。
- 参照: [design §1](./design.md)。

## D3. テスタビリティの継ぎ目（adapter / port・humble object）

- **決定**: 中核ロジックは `ITerm2Adapter`(port) にのみ依存。本番 `RealAdapter`、テスト `FakeAdapter`。
  async/websocket/認証は RealAdapter 内に閉じる。
- **理由**: 状態を持つ外部アプリ（iTerm2）への実接続は遅く（cold 1.57s）不安定。素朴に全部を実接続で
  テストすると遅延と flakiness を招く。port を切ると iTerm2 無しでユニットが高速に回る。
- **退けた案**: iterm2 pip を中核から直接呼ぶ（テストが実 iTerm2 依存になる）。
- 参照: [design §2.2](./design.md) / [CLAUDE.md テスト戦略](../CLAUDE.md)。

## D4. 操作表面は「契約テスト」で守る（codegen で単一ソース化しない）

- **決定**: 操作は Controller / `protocol.HANDLERS` / `DaemonClient` の 3 層に分かれて存在し続けるが、
  全操作をデーモン越しに往復させる契約テスト＋「Backend 公開メソッド集合 == テスト網羅集合」の assert で
  3 層の追従漏れ（登録漏れ・params 名ズレ）を**緑のまま通さない**。
- **理由**: Controller のメソッドはシグネチャが不均一（位置 target / キーワード専用 / session）で、
  記述子テーブルからの codegen は結局各シグネチャの再エンコードになり、可読性を損なう過剰抽象。
  実リスクは「3 層のズレが検出されないこと」なので、抽象化で消すより**テストで封じる**のが適切な altitude。
- **退けた案**: 操作記述子テーブルから 3 層を生成する codegen（over-engineering）。
- 参照: [CLAUDE.md 新しい操作を足す手順](../CLAUDE.md) / `tests/test_daemon.py`。

## D5. デーモン＋クライアント側 target 解決

- **決定**: 低レイテンシ用に常駐デーモン（Unix socket）を任意で立て、未起動時は都度接続にフォールバック。
  **`<target>` 解決はクライアント側**で行い、デーモンには具体的 session_id だけ渡す。
- **理由**: 都度接続は ~0.6–1.6s/コマンド。デーモンで接続を償却すると ~5ms。current（`$ITERM_SESSION_ID`）
  は**クライアントのペイン**を指すべきで、別プロセスのデーモンでは解決できない。副産物として、
  デーモン起動中はクライアントに iterm2 パッケージが不要になる。
- **退けた案**: デーモン側で target 解決（current が壊れる）／デーモンを必須化（単体利用が重くなる）。
- 参照: [design §2.1, §3, §4](./design.md)。

## D6. 状態は user 変数に集約（busy/完了検知）

- **決定**: `busy`/`wait` は `user.itermcli_state` を最優先で読み、無ければ画面マーカー（env で上書き可）。
  書き手は `set-status` か、ペイン内からの OSC 1337 SetUserVar。
- **理由**: OSC 9/99/777 を直接購読する代わりに iTerm2 のユーザー変数へ集約すれば「変数を読む」一本に
  まとまる。画面マーカー走査は脆いのでフォールバック最後段。
- **退けた案**: 画面マーカーのみ（脆い・TUI 依存）／OSC を直接購読（複雑）。
- 参照: [design §7](./design.md)。

## D7. 永続状態は最小（session_id↔label のみ）

- **決定**: 永続化はラベル↔session_id の最小マッピングだけ。branch/cwd 等は iTerm2 変数や FS から都度引く。
- **理由**: 真実は iTerm2 と FS にある。メタデータ DB を増やすほど同期ずれの温床になる。
- 参照: [design §4](./design.md) / [CLAUDE.md 不変条件 4](../CLAUDE.md)。

## D8. 独立性（特定ツールを前提にしない・ラッパーは「可能」）

- **決定**: 本リポジトリは汎用 iTerm2 制御に徹し、特定の上位ツール（AI エージェント等）を前提にしない。
  ドメイン固有のお作法は外側の薄いラッパー（別リポジトリ）に載せる。
- **理由**: 単体で完結させ外部利用に委ねるほうが、再利用性が高く結合の腐敗を避けられる。本 CLI は
  ラッパーを**可能にする**だけで、特定のラッパーを内包しない。
- **退けた案**: 特定オーケストレータの一部としてその規約・状態ファイルを取り込む（結合・独立性喪失）。
- 参照: [design §8](./design.md) / [README](../README.md)。

## D9. 据え置きは「記録して必要時に改善」

- **決定**: 実害の小さい改善は実装せず、[design §11](./design.md) に効果と理由を 1〜2 行で記録する。
- **理由**: 「必要時に直す」だけだと据え置きの根拠が失われ、再調査や「未対応＝バグ」の誤認を招く。
  一方で投機的 TODO の肥大は鮮度を損なうので、実在項目だけ最小限に残す。

## D10. 「タブを作る」と「窓を作る」は別コマンド（tab / window）

- **決定**: 新規ウィンドウ作成は `tab --window` フラグではなく独立した `window` コマンド（socket `window.new`）に
  分離する。`tab` は「タブを作る」一操作に専念し、`--in-window <wid>` は**行き先のパラメータ**として残す
  （既定=current 窓、指定でその窓）。
- **理由**: `tab --window` は内部で `Window.async_create`（窓を作る）を呼び、`window.new_tab` という単一 socket
  method が 2 操作を兼ねていた。これは「1 コマンド 1 操作」（UNIX 哲学）と不変条件 #2（CLI↔socket を 1:1・
  socket method は一操作）の両方に反する。iTerm2 API も `async_create_tab` と `Window.async_create` で分かれており、
  分離するとコマンド・socket・API の三層が素直に対応する。
- **`--in-window` を残した理由**: これは別操作ではなく「タブをどの窓に作るか」の場所指定（`cp src dst` の dst と同類）。
  current 既定の上書きにすぎないので `tab` の一操作性を壊さない。`tab` が窓ゼロの環境で呼ばれた場合のみ、行き先が
  無いためやむを得ず新規窓を作る（フォールバック・[design §5](./design.md) 注記）。
- **退けた案**:
  - **`tab --window` をエイリアスで残す**（後方互換）: 粗い表面を温存し、`--window`/`--in-window` の行き先衝突
    （排他チェックが必要になる）も残る。`Development Status :: Alpha` 段階で利用者が限られるため、クリーンな
    破壊的変更を選んだ。再検討トリガー = 外部利用者が `tab --window` に依存していると判明したとき。
- 参照: [design §5 socket 契約表](./design.md) / 契約テスト `DRIVEN`（`tests/test_daemon.py`）。
- **後日の改名**: D11（後述）で `tab`→`new-tab` / `window`→`new-window` に改名（命名規約の統一）。本決定（窓作成の分離）自体は不変。

## D11. コマンド命名は cmux / tmux 準拠の「動詞-名詞」

- **決定**: ライフサイクル系コマンドは cmux / tmux に倣い **`動詞-名詞` のハイフン結合フラット名**に統一する。
  `window`→`new-window`、`tab`→`new-tab`、`split`→`new-split`、`set-name`→`rename`。
  操作系（current ペインに作用）は **素の動詞**のまま（`send` / `send-key` / `read` / `wait` / `busy` / `focus`）、
  状態メタ（`set-status` / `set-progress`）は cmux と既に一致。加えて current を特定する `identify` を新設。
- **理由**: 改名前は3つの文法が混在していた——create-名詞（`tab`/`window`）・裸の動詞（`split`）・grouped（`var`/`label`）。
  特に「子オブジェクトを作る」操作が `split`/`tab`/`window` でバラバラだった。本ツールは並列エージェントの
  オーケストレーション基盤であり、利用者の参照モデルが cmux。cmux も tmux も「ライフサイクル=動詞-名詞、操作=裸の動詞」
  で一貫しており、これに揃えると 1 ルールで発見性（`new-<TAB>` で作成系が揃う）と一貫性が出る。
- **`identify` を socket method なしにした理由**: current 解決はクライアント側（D5）で行い、情報は `session.list` の
  再利用で足りる。専用 method を足すと往復が増え D5 とも矛盾するため、CLI 層の合成（resolve + list）にした。
  これは「CLI↔socket を 1:1」の明示的な例外（[design §5](./design.md) の表に「socket method なし」と記載）。
- **`new-split` の方向**: cmux `new-split <dir>` に倣い位置引数 `right`/`left`/`down`/`up` を採用（旧 `-h`/`-b` フラグを置換）。
  left/right=垂直分割、down/up=水平分割、left/up=source の前側。1 引数で「分割軸＋前後」を表現でき、フラグ 2 つより明快。
- **退けた案**:
  - **`object verb` のネスト型**（`window new` / `pane split`、kubectl/docker 流）: 一見クリーンだが、参照モデルの
    cmux も tmux も採らない流儀で、ホットパス（`send`/`read`）が `session send` のように冗長化する。エージェントが
    叩く頻度の高い操作を素の動詞に保ちたいので不採用。
  - **現状フラット名のまま据え置き**: create の3パターン不揃いが残り、発見性も上がらない。`Alpha` 段階で破壊的改名の
    コストが小さい今が好機と判断。再検討トリガー = 外部利用者が旧名（`tab`/`split` 等）に依存していると判明したとき。
- 参照: [design §5 socket 契約表](./design.md) / [README コマンド表](../README.md) / 契約テスト `DRIVEN`。
