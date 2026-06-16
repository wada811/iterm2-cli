"""Unix socket デーモン（design.md §2.1 フェーズ2 / §3）。

接続を保持した Controller を載せ、CLI（軽量クライアント）からの 1 リクエスト＝1 接続を
処理する。都度 websocket 接続+認証（~1.5s）を償却し、高頻度操作を低レイテンシにする。

デーモンは target 解決を持たない（current 解決はクライアント側）。
"""

from __future__ import annotations

import os
import socket
import threading
from pathlib import Path

from .core import Controller
from .protocol import decode, dispatch, encode, error


def default_socket_path() -> Path:
    env = os.environ.get("ITERM2_CLI_SOCKET")
    if env:
        return Path(env)
    base = os.environ.get("XDG_RUNTIME_DIR") or "/tmp"
    return Path(base) / "iterm2-cli.sock"


def read_line(sock: socket.socket) -> bytes:
    """改行までの 1 行を読む（プロトコルは 1 メッセージ = 1 行）。"""
    buf = bytearray()
    while True:
        chunk = sock.recv(4096)
        if not chunk:
            break
        buf.extend(chunk)
        if b"\n" in chunk:
            break
    return bytes(buf)


def is_alive(socket_path: Path | str, *, timeout: float = 0.5) -> bool:
    """ソケットに ping して生きているデーモンがいるか判定する。"""
    from .protocol import make_request

    path = str(socket_path)
    if not os.path.exists(path):
        return False
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(timeout)
            s.connect(path)
            s.sendall(encode(make_request("ping", "system.ping")))
            resp = decode(read_line(s))
        return bool(resp.get("ok"))
    except OSError:
        return False


_CONN_TIMEOUT = 30.0  # 1 接続でリクエスト行の受信・応答送信に許す上限（stuck client 対策）


class Daemon:
    def __init__(
        self,
        controller: Controller,
        socket_path: Path | str | None = None,
        *,
        conn_timeout: float = _CONN_TIMEOUT,
    ) -> None:
        self.controller = controller
        self.path = Path(socket_path) if socket_path is not None else default_socket_path()
        self._conn_timeout = conn_timeout
        self._sock: socket.socket | None = None
        self._stop = False

    def serve(self) -> None:
        self._prepare()
        self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        # bind 時点から 0600 相当で作る（bind→chmod 間に他ユーザが接続できる窓を塞ぐ）。
        old_umask = os.umask(0o077)
        try:
            self._sock.bind(str(self.path))
        finally:
            os.umask(old_umask)
        os.chmod(self.path, 0o600)  # 保険（ローカル単一ユーザー前提・design.md §3 認可方針）
        self._sock.listen(16)
        try:
            while not self._stop:
                try:
                    conn, _ = self._sock.accept()
                except OSError:
                    break  # close() により叩き起こされた
                # 接続ごとにスレッド処理。長い wait が他コマンドを塞がない（HOL 回避）。
                # RealAdapter は単一イベントループ上で呼び出しを直列化するためスレッド安全。
                threading.Thread(target=self._serve_conn, args=(conn,), daemon=True).start()
        finally:
            self._cleanup()

    def _serve_conn(self, conn: socket.socket) -> None:
        with conn:
            # 改行を送らず固まったクライアントが受信/応答スレッドを無期限に占有しないよう、
            # socket 操作にタイムアウトを設ける（長い wait は handle 内の Controller 側で
            # 進むため socket 操作中ではなく、このタイムアウトには掛からない）。
            conn.settimeout(self._conn_timeout)
            try:
                self._handle(conn)
            except OSError:
                # timeout 含む socket エラー（stuck/切断クライアント）は接続を閉じて握り潰す。
                pass

    def stop(self) -> None:
        """別スレッド/シグナルから安全に停止する。"""
        self._stop = True
        if self._sock is not None:
            try:
                self._sock.close()  # accept() を中断させる
            except OSError:
                pass

    def _handle(self, conn: socket.socket) -> None:
        line = read_line(conn)
        if not line.strip():
            return
        try:
            request = decode(line)
        except Exception as e:  # noqa: BLE001
            conn.sendall(encode(error("", "bad_json", str(e))))
            return
        if request.get("method") == "system.stop":
            conn.sendall(encode({"id": request.get("id", ""), "ok": True, "result": {"stopping": True}}))
            self.stop()  # accept() を中断して serve ループを抜けさせる
            return
        conn.sendall(encode(dispatch(self.controller, request)))

    def _prepare(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            if is_alive(self.path):
                raise RuntimeError(f"既にデーモンが起動しています: {self.path}")
            self.path.unlink()  # stale を掃除

    def _cleanup(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
        try:
            if self.path.exists():
                self.path.unlink()
        except OSError:
            pass
        self.controller.shutdown()
