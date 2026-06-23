# 移行ガイド（Migration Guide）

`0.0.1` から次のリリース（Unreleased）への移行手順。コマンド体系を cmux / tmux 準拠の
「動詞-名詞」に統一したため、**いくつかのコマンド名・引数が変わりました**（破壊的変更）。
背景と判断理由は [docs/decisions.md](./docs/decisions.md) の **D10 / D11** を参照。

> `Development Status :: Alpha` のため後方互換エイリアスは残していません。スクリプトは下表で置換してください。

## 破壊的変更 早見表（旧 → 新）

| 旧（0.0.1） | 新 | 備考 |
|---|---|---|
| `iterm2 tab` | `iterm2 new-tab` | 機能同じ。`-t` / `--in-window` / `--cmd` / `--profile` は据え置き |
| `iterm2 tab --window` | `iterm2 new-window` | 「窓を作る」を独立コマンドに分離（D10） |
| `iterm2 split` | `iterm2 new-split`（= `right`） | 既定は垂直分割・後ろ |
| `iterm2 split -h` / `--horizontal` | `iterm2 new-split down` | 水平分割・後ろ |
| `iterm2 split -b` / `--before` | `iterm2 new-split left` | 垂直分割・前 |
| `iterm2 split -h -b` | `iterm2 new-split up` | 水平分割・前 |
| `iterm2 set-name <name>` | `iterm2 rename <name>` | 機能同じ。`-t` / `--json` 据え置き |
| `iterm2 daemon` | `iterm2 daemon start` | 起動 |
| `iterm2 daemon --stop` | `iterm2 daemon stop` | 停止 |

操作系コマンド（`list` / `send` / `send-key` / `read` / `busy` / `wait` / `focus` /
`close` / `var` / `label` / `set-status` / `set-progress` / `ping`）は**変更ありません**。

## 詳細

### 1. ペイン分割: `split` → `new-split <方向>`

方向をフラグ（`-h` / `-b`）ではなく cmux 風の**位置引数**で指定します。1 引数で「分割軸＋前後」を表現できます。

| 方向 | 意味 | 旧フラグ相当 |
|---|---|---|
| `right`（既定） | 垂直分割・新ペインは右 | `split`（フラグなし） |
| `left` | 垂直分割・新ペインは左 | `split -b` |
| `down` | 水平分割・新ペインは下 | `split -h` |
| `up` | 水平分割・新ペインは上 | `split -h -b` |

```sh
# 旧
iterm2 split worker -h
# 新（対象は -t で指定）
iterm2 new-split down -t worker
```

> 注: 対象ペインの指定方法が変わりました。旧 `split` は第1位置引数が対象でしたが、`new-split` は
> 第1位置引数が**方向**になり、対象は `-t/--target`（または `-s/--session`）で指定します。

### 2. タブ作成と窓作成の分離: `tab` / `tab --window` → `new-tab` / `new-window`

「タブを作る」と「新規ウィンドウを作る」を別コマンドに分けました（D10）。

```sh
# 旧
iterm2 tab                      # current の窓にタブ
iterm2 tab --window             # 新規ウィンドウ
iterm2 tab --in-window <wid>    # 指定窓にタブ

# 新
iterm2 new-tab                  # current の窓にタブ
iterm2 new-window               # 新規ウィンドウ
iterm2 new-tab --in-window <wid># 指定窓にタブ（据え置き）
```

### 3. 改名: `set-name` → `rename`

```sh
iterm2 set-name "🟢 worker" -t worker     # 旧
iterm2 rename   "🟢 worker" -t worker     # 新
```

### 4. デーモン: `daemon` / `daemon --stop` → `daemon start` / `daemon stop`

```sh
iterm2 daemon          # 旧: 起動
iterm2 daemon --stop   # 旧: 停止

iterm2 daemon start    # 新: 起動
iterm2 daemon stop     # 新: 停止
```

## 新機能: `identify`

呼び出し元（current）の session を特定して出力します（cmux の `identify` 相当）。
`--json` で全フィールド＋割当 label を返します。エージェントが「自分はどの session か」を知るのに使えます。

```sh
iterm2 identify            # "<session_id>  <name>  [labels]"
iterm2 identify --json     # {"session_id":..., "name":..., "labels":[...], ...}
```

## スクリプト一括置換の目安

既存スクリプトは概ね以下の置換で移行できます（`split` の対象指定だけは手当てが必要）。

```sh
iterm2 tab            → iterm2 new-tab
iterm2 tab --window   → iterm2 new-window
iterm2 set-name       → iterm2 rename
iterm2 daemon --stop  → iterm2 daemon stop
iterm2 daemon         → iterm2 daemon start
iterm2 split          → iterm2 new-split          # = right
iterm2 split -h       → iterm2 new-split down
iterm2 split -b       → iterm2 new-split left
```

## socket プロトコルを直接叩いている場合

CLI ではなく Unix socket の JSON-RPC を直接利用している場合、メソッド名の追加があります
（既存メソッドの互換は維持）。

- 追加: `window.new`（新規ウィンドウ）。
- `window.new_tab` の params から `new_window` を削除（窓作成は `window.new` へ）。
- `identify` は専用メソッドを持たず `session.list` ＋ クライアント側 current 解決の合成です。

詳細は [docs/design.md](./docs/design.md) §5 の socket 契約表を参照。
