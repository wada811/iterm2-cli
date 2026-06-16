"""typer による CLI（design.md §5）。

CLI は薄いクライアント。各サブコマンドは Controller を呼ぶだけ。
adapter の生成は ``make_controller`` に集約し、テストではここを差し替えて
FakeAdapter を注入する（実 iTerm2 に触れずに CLI を検証）。

TARGET の既定は current（$ITERM_SESSION_ID）。send/send-key はペイロードを持つため
対象は -t/--target で指定する。
"""

from __future__ import annotations

import json
from dataclasses import asdict

import typer

from .backend import Backend
from .core import Controller
from .detect import State
from .labels import LabelStore
from .resolver import ResolutionError, SessionResolver

app = typer.Typer(no_args_is_help=True, help="iTerm2 を操作する CLI")
var_app = typer.Typer(no_args_is_help=True, help="セッション変数 get/set")
label_app = typer.Typer(no_args_is_help=True, help="label ↔ session_id マッピング")
app.add_typer(var_app, name="var")
app.add_typer(label_app, name="label")


def make_controller() -> Backend:
    """操作のバックエンドを組み立てる。

    デーモンが生きていれば軽量な DaemonClient（socket 経由・低レイテンシ）を、
    いなければ RealAdapter で都度接続する Controller を返す（同一コマンド表面）。
    テストはこの関数を monkeypatch して FakeAdapter ベースの Controller を返す。
    """
    from .daemon import default_socket_path, is_alive

    resolver = SessionResolver(labels=LabelStore().all())
    socket_path = default_socket_path()
    if is_alive(socket_path):
        from .client import DaemonClient

        return DaemonClient(socket_path, resolver)

    from .adapter_real import RealAdapter

    return Controller(RealAdapter.connect(), resolver)


def _run(fn):
    """make_controller → fn(backend) → 後始末。エラーは明示メッセージで終了。

    既知のドメインエラーは経路（都度接続 / デーモン）に依らず整った 1 行で終了させる。
    """
    from .adapter import SessionNotFound
    from .client import DaemonError
    from .detect import WaitTimeout
    from .keys import UnknownKey

    try:
        backend = make_controller()
    except Exception as e:  # 接続失敗等
        typer.secho(f"接続に失敗しました: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(2) from None
    try:
        return fn(backend)
    except ResolutionError as e:
        typer.secho(f"対象を解決できません: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(2) from None
    except SessionNotFound as e:
        typer.secho(f"セッションが見つかりません: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(2) from None
    except UnknownKey as e:
        typer.secho(f"未知のキー: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(2) from None
    except WaitTimeout as e:
        typer.secho(f"待機がタイムアウトしました: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(2) from None
    except DaemonError as e:
        typer.secho(f"デーモンエラー: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(2) from None
    finally:
        backend.shutdown()


def _emit(obj, as_json: bool, human) -> None:
    if as_json:
        typer.echo(json.dumps(obj, ensure_ascii=False))
    else:
        human(obj)


@app.command(name="list")
def list_sessions(json_out: bool = typer.Option(False, "--json", help="JSON 出力")):
    """セッション/ペインを列挙する。"""

    def run(c: Controller):
        sessions = [asdict(s) for s in c.list()]
        _emit(
            sessions,
            json_out,
            lambda ss: [
                typer.echo(f"{s['session_id']}  {'*' if s['is_active'] else ' '} {s['name']}")
                for s in ss
            ],
        )

    _run(run)


@app.command()
def send(
    text: str = typer.Argument(..., help="送信する本文（Enter は含めない）"),
    target: str | None = typer.Option(None, "-t", "--target", help="対象（省略時 current）"),
    session: str | None = typer.Option(None, "-s", "--session", help="session_id を明示"),
    enter: bool = typer.Option(False, "-e", "--enter", help="本文送信後に Enter で確定する"),
):
    """本文を送信する（確定は send-key enter、または --enter）。"""

    def run(c):
        c.send(target, text, session=session)
        if enter:
            c.send_key(target, ["enter"], session=session)

    _run(run)


@app.command(name="send-key")
def send_key(
    keys: list[str] = typer.Argument(..., help="キー名（enter/tab/esc/up/ctrl-c ...）"),
    target: str | None = typer.Option(None, "-t", "--target"),
    session: str | None = typer.Option(None, "-s", "--session"),
):
    """特殊キー/確定キーを送る。"""
    _run(lambda c: c.send_key(target, keys, session=session))


@app.command()
def read(
    target: str | None = typer.Argument(None, help="対象（省略時 current）"),
    tail: int | None = typer.Option(None, "--tail", help="末尾 N 行"),
    session: str | None = typer.Option(None, "-s", "--session"),
    json_out: bool = typer.Option(False, "--json"),
):
    """画面内容を読み取る。"""

    def run(c: Controller):
        lines = c.read(target, tail=tail, session=session)
        _emit({"lines": lines}, json_out, lambda o: [typer.echo(line) for line in o["lines"]])

    _run(run)


@app.command()
def busy(
    target: str | None = typer.Argument(None),
    session: str | None = typer.Option(None, "-s", "--session"),
    json_out: bool = typer.Option(False, "--json"),
):
    """busy 判定。busy のとき exit code 1。"""

    def run(c: Controller):
        state = c.busy(target, session=session)
        _emit({"state": state.value}, json_out, lambda o: typer.echo(o["state"]))
        if state == State.BUSY:
            raise typer.Exit(1)

    _run(run)


@app.command()
def wait(
    target: str | None = typer.Argument(None),
    timeout: float = typer.Option(30.0, "--timeout"),
    until: State = typer.Option(State.IDLE, "--until"),
    until_text: str | None = typer.Option(None, "--until-text", help="画面にこの文字列が出るまで待つ"),
    session: str | None = typer.Option(None, "-s", "--session"),
):
    """対象が指定状態（既定 idle）になるまで待つ。--until-text 指定時は画面に文字列が出るまで。"""

    def run(c):
        state = c.wait(target, until=until, until_text=until_text, timeout=timeout, session=session)
        # 状態待ちは最終状態を、文字列待ち（--until-text）は見つかった marker を出力する。
        typer.echo(until_text if until_text is not None else state.value)

    _run(run)


@app.command()
def split(
    target: str | None = typer.Argument(None),
    horizontal: bool = typer.Option(False, "-h", "--horizontal", help="水平分割（既定は垂直）"),
    profile: str | None = typer.Option(None, "--profile"),
    session: str | None = typer.Option(None, "-s", "--session"),
):
    """ペインを分割し、新 session_id を出力する。"""
    _run(lambda c: typer.echo(c.split(target, vertical=not horizontal, profile=profile, session=session)))


@app.command()
def tab(
    target: str | None = typer.Option(None, "-t", "--target", help="呼び出し元ペイン（省略時 current）"),
    profile: str | None = typer.Option(None, "--profile"),
    command: str | None = typer.Option(None, "--cmd"),
    new_window: bool = typer.Option(False, "--window", help="新規ウィンドウ"),
    in_window: str | None = typer.Option(None, "--in-window", help="既存ウィンドウ（window_id）内にタブを作る"),
    session: str | None = typer.Option(None, "-s", "--session", help="session_id を明示"),
):
    """タブを作り、新 session_id を出力する。

    既定は呼び出し元（current）のウィンドウ。--window で新規ウィンドウ、--in-window <wid> で指定ウィンドウ内。
    デーモン起動中でも current 窓はクライアント側で解決するため、呼び出し元の窓にタブが作られる（D5）。
    """
    _run(
        lambda c: typer.echo(
            c.tab(
                target,
                profile=profile,
                command=command,
                new_window=new_window,
                window_id=in_window,
                session=session,
            )
        )
    )


@app.command()
def focus(
    target: str | None = typer.Argument(None),
    session: str | None = typer.Option(None, "-s", "--session"),
):
    """対象にフォーカスを移す。"""
    _run(lambda c: c.focus(target, session=session))


@app.command(name="set-name")
def set_name(
    name: str = typer.Argument(..., help="ペインの表示名"),
    target: str | None = typer.Option(None, "-t", "--target"),
    session: str | None = typer.Option(None, "-s", "--session"),
    json_out: bool = typer.Option(False, "--json"),
):
    """ペイン（セッション）の表示名を設定する。"""

    def run(c):
        sid = c.set_name(target, name, session=session)
        if json_out:
            typer.echo(json.dumps({"session_id": sid, "name": name}, ensure_ascii=False))

    _run(run)


@app.command()
def close(
    target: str | None = typer.Argument(None),
    force: bool = typer.Option(False, "--force"),
    session: str | None = typer.Option(None, "-s", "--session"),
):
    """対象（ペイン/タブ）を閉じる。"""
    _run(lambda c: c.close(target, force=force, session=session))


@var_app.command("get")
def var_get(
    name: str = typer.Argument(...),
    target: str | None = typer.Option(None, "-t", "--target"),
    session: str | None = typer.Option(None, "-s", "--session"),
):
    def run(c):
        value = c.var_get(target, name, session=session)
        if value is not None:
            typer.echo(value)

    _run(run)


@var_app.command("set")
def var_set(
    name: str = typer.Argument(...),
    value: str = typer.Argument(...),
    target: str | None = typer.Option(None, "-t", "--target"),
    session: str | None = typer.Option(None, "-s", "--session"),
):
    _run(lambda c: c.var_set(target, name, value, session=session))


@label_app.command("set")
def label_set(name: str = typer.Argument(...), session_id: str = typer.Argument(...)):
    """label に session_id を割り当てる。"""
    LabelStore().set(name, session_id)


@label_app.command("ls")
def label_ls(json_out: bool = typer.Option(False, "--json")):
    mapping = LabelStore().all()
    if json_out:
        typer.echo(json.dumps(mapping, ensure_ascii=False))
    else:
        for k, v in sorted(mapping.items()):
            typer.echo(f"{k}\t{v}")


@label_app.command("rm")
def label_rm(name: str = typer.Argument(...)):
    if not LabelStore().remove(name):
        typer.secho(f"label が見つかりません: {name}", fg=typer.colors.YELLOW, err=True)
        raise typer.Exit(1)


@app.command(name="set-status")
def set_status(
    key: str = typer.Argument(..., help="状態キー（busy/wait が読むのは itermcli_state）"),
    value: str = typer.Argument(...),
    target: str | None = typer.Option(None, "-t", "--target"),
    session: str | None = typer.Option(None, "-s", "--session"),
):
    """状態を user 変数 user.<key> に書く（非破壊）。

    例: `set-status itermcli_state running` → busy/wait が running と判定。
    ペイン内からは OSC 1337 SetUserVar でも同じ変数を書ける。
    """
    _run(lambda c: c.var_set(target, f"user.{key}", value, session=session))


@app.command(name="set-progress")
def set_progress(
    value: int = typer.Argument(..., help="進捗（0-100 など）"),
    target: str | None = typer.Option(None, "-t", "--target"),
    session: str | None = typer.Option(None, "-s", "--session"),
):
    """進捗を user.itermcli_progress に書く。"""
    from .detect import PROGRESS_VAR

    _run(lambda c: c.var_set(target, PROGRESS_VAR, str(value), session=session))


@app.command()
def ping():
    """iTerm2 へ接続できるか確認する（デーモン経由なら socket、なければ都度接続）。"""

    def run(c):
        c.list()
        typer.echo("ok")

    _run(run)


@app.command()
def daemon(
    socket_path: str | None = typer.Option(None, "--socket", help="socket パス"),
    stop: bool = typer.Option(False, "--stop", help="起動中のデーモンを停止"),
):
    """常駐デーモンを起動する（接続を保持し低レイテンシ）。--stop で停止。"""
    import signal

    from .daemon import Daemon, default_socket_path, is_alive

    path = socket_path or str(default_socket_path())

    if stop:
        from .client import DaemonClient

        if is_alive(path):
            DaemonClient(path).stop_daemon()
            typer.echo("stopped")
        else:
            typer.echo("not running")
        return

    if is_alive(path):
        typer.secho(f"既に起動しています: {path}", fg=typer.colors.YELLOW, err=True)
        raise typer.Exit(1)

    from .adapter_real import RealAdapter

    try:
        controller = Controller(RealAdapter.connect(), SessionResolver())
    except Exception as e:  # 接続失敗
        typer.secho(f"接続に失敗しました: {e}", fg=typer.colors.RED, err=True)
        raise typer.Exit(2) from None

    d = Daemon(controller, path)
    signal.signal(signal.SIGINT, lambda *_: d.stop())
    signal.signal(signal.SIGTERM, lambda *_: d.stop())
    typer.echo(f"iterm2-cli daemon listening: {path}")
    d.serve()
    typer.echo("daemon stopped")


if __name__ == "__main__":
    app()
