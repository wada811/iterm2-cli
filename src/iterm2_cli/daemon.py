"""Unix socket デーモン（design.md §2.1 フェーズ2 / §3）。

接続を保持した Controller を載せ、CLI（軽量クライアント）からの 1 リクエスト＝1 接続を
処理する。都度 websocket 接続+認証（~1.5s）を償却し、高頻度操作を低レイテンシにする。

デーモンは target 解決を持たない（current 解決はクライアント側）。
"""

from __future__ import annotations

import os
import socket
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


class Daemon:
    def __init__(self, controller: Controller, socket_path: Path | str | None = None) -> None:
        self.controller = controller
        self.path = Path(socket_path) if socket_path is not None else default_socket_path()
        self._sock: socket.socket | None = None
        self._stop = False

    def serve(self) -> None:
        self._prepare()
        self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._sock.bind(str(self.path))
        self._sock.listen(16)
        try:
            while not self._stop:
                try:
                    conn, _ = self._sock.accept()
                except OSError:
                    break  # close() により叩き起こされた
                with conn:
                    self._handle(conn)
        finally:
            self._cleanup()

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
            self._stop = True
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
