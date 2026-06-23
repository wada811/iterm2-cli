"""socket プロトコル（design.md §3）。

リクエスト  : {"id": "...", "method": "session.send_text", "params": {...}}
成功レスポンス: {"id": "...", "ok": true,  "result": {...}}
失敗レスポンス: {"id": "...", "ok": false, "error": {"code": "...", "message": "..."}}

method は名前空間付き（session.* / pane.* / window.* / system.*）。CLI サブコマンドは
これらの人間向けエイリアス。デーモンは **target 解決を持たない**: params は常に具体的な
session_id を載せる（current の解決はクライアント側で行う。design 反映）。

純ロジック。socket I/O は daemon.py / client.py に分離。
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import asdict
from typing import Any

from .adapter import SessionNotFound
from .core import Controller
from .detect import State, WaitTimeout
from .keys import UnknownKey
from .resolver import ResolutionError


# --- メッセージ構築・符号化 -------------------------------------------
def make_request(req_id: str, method: str, params: dict | None = None) -> dict:
    return {"id": req_id, "method": method, "params": params or {}}


def success(req_id: str, result: Any) -> dict:
    return {"id": req_id, "ok": True, "result": result}


def error(req_id: str, code: str, message: str) -> dict:
    return {"id": req_id, "ok": False, "error": {"code": code, "message": message}}


def encode(msg: dict) -> bytes:
    """1 メッセージ = 1 行（改行区切り JSON）。"""
    return (json.dumps(msg, ensure_ascii=False) + "\n").encode("utf-8")


def decode(line: bytes | str) -> dict:
    if isinstance(line, bytes):
        line = line.decode("utf-8")
    return json.loads(line)


# --- ハンドラ（method → Controller 呼び出し）-------------------------
def _h_list(c: Controller, p: dict) -> Any:
    return {"sessions": [asdict(s) for s in c.list()]}


def _h_send_text(c: Controller, p: dict) -> Any:
    c.send(None, p["text"], session=p["session"])
    return {}


def _h_send_key(c: Controller, p: dict) -> Any:
    c.send_key(None, list(p["keys"]), session=p["session"])
    return {}


def _h_read(c: Controller, p: dict) -> Any:
    return {"lines": c.read(None, tail=p.get("tail"), session=p["session"])}


def _h_busy(c: Controller, p: dict) -> Any:
    return {"state": c.busy(None, session=p["session"]).value}


def _h_wait(c: Controller, p: dict) -> Any:
    state = c.wait(
        None,
        session=p["session"],
        until=State(p.get("until", "idle")),
        until_text=p.get("until_text"),
        timeout=p.get("timeout", 30.0),
        poll_interval=p.get("poll_interval", 0.5),
    )
    return {"state": state.value}


def _h_split(c: Controller, p: dict) -> Any:
    return {
        "session_id": c.split(
            None,
            vertical=p.get("vertical", True),
            before=p.get("before", False),
            profile=p.get("profile"),
            session=p["session"],
        )
    }


def _h_new_tab(c: Controller, p: dict) -> Any:
    # from_session はクライアント側で解決済みの「呼び出し元ペイン」（D5）。
    # 明示渡しすることでデーモンが current を再解決する（デーモン視点の窓に作る）のを防ぐ。
    return {
        "session_id": c.tab(
            profile=p.get("profile"),
            command=p.get("command"),
            window_id=p.get("window_id"),
            from_session=p.get("from_session"),
        )
    }


def _h_new_window(c: Controller, p: dict) -> Any:
    return {"session_id": c.window(profile=p.get("profile"), command=p.get("command"))}


def _h_focus(c: Controller, p: dict) -> Any:
    c.focus(None, session=p["session"])
    return {}


def _h_set_name(c: Controller, p: dict) -> Any:
    c.set_name(None, p["name"], session=p["session"])
    return {}


def _h_close(c: Controller, p: dict) -> Any:
    c.close(None, force=p.get("force", False), session=p["session"])
    return {}


def _h_get_var(c: Controller, p: dict) -> Any:
    return {"value": c.var_get(None, p["name"], session=p["session"])}


def _h_set_var(c: Controller, p: dict) -> Any:
    c.var_set(None, p["name"], p["value"], session=p["session"])
    return {}


def _h_ping(c: Controller, p: dict) -> Any:
    return {"ok": True}


HANDLERS: dict[str, Callable[[Controller, dict], Any]] = {
    "session.list": _h_list,
    "session.send_text": _h_send_text,
    "session.send_key": _h_send_key,
    "session.read": _h_read,
    "session.busy": _h_busy,
    "session.wait": _h_wait,
    "session.focus": _h_focus,
    "session.set_name": _h_set_name,
    "session.close": _h_close,
    "session.get_var": _h_get_var,
    "session.set_var": _h_set_var,
    "pane.split": _h_split,
    "window.new_tab": _h_new_tab,
    "window.new": _h_new_window,
    "system.ping": _h_ping,
}

_ERROR_CODES: list[tuple[type[Exception], str]] = [
    (ResolutionError, "resolution_error"),
    (SessionNotFound, "session_not_found"),
    (UnknownKey, "unknown_key"),
    (WaitTimeout, "wait_timeout"),
    # KeyError は handler 内の必須 param 欠落として下で先取りするため、ここには置かない。
    (ValueError, "bad_request"),  # 例: 不正な until 値（State(...) が ValueError）
]


def _code_for(exc: Exception) -> str:
    for typ, code in _ERROR_CODES:
        if isinstance(exc, typ):
            return code
    return "internal_error"


def dispatch(controller: Controller, request: dict) -> dict:
    """1 リクエストを処理してレスポンス dict を返す。例外は error に包む（NFR7）。"""
    req_id = request.get("id", "")
    method = request.get("method", "")
    params = request.get("params") or {}
    handler = HANDLERS.get(method)
    if handler is None:
        return error(req_id, "unknown_method", f"未知の method: {method!r}")
    try:
        return success(req_id, handler(controller, params))
    except KeyError as e:  # 必須 param 欠落
        return error(req_id, "bad_request", f"パラメータが不足: {e}")
    except Exception as e:  # noqa: BLE001 - すべて error に包む
        return error(req_id, _code_for(e), str(e))
