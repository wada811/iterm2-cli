"""キー名 → 端末へ送る制御シーケンスの符号化（send-key コマンド用）。

design.md の send/send-key 分離: 本文は send_text、確定や特殊キーは send-key。
ここで符号化した文字列を adapter.send_text に渡せば、ユーザー打鍵と同等に届く。
"""

from __future__ import annotations

# 名前付きキー → 送出シーケンス。
_NAMED: dict[str, str] = {
    "enter": "\r",
    "return": "\r",
    "tab": "\t",
    "escape": "\x1b",
    "esc": "\x1b",
    "backspace": "\x7f",
    "delete": "\x1b[3~",
    "space": " ",
    "up": "\x1b[A",
    "down": "\x1b[B",
    "right": "\x1b[C",
    "left": "\x1b[D",
    "home": "\x1b[H",
    "end": "\x1b[F",
    "pageup": "\x1b[5~",
    "pagedown": "\x1b[6~",
}


class UnknownKey(Exception):
    """未知のキー名（NFR7: silent fail しない）。"""


def encode_key(name: str) -> str:
    """単一キー名を制御シーケンスへ符号化する。

    - 名前付きキー（enter/tab/esc/矢印…）
    - ``ctrl-x`` / ``c-x`` / ``^x``: Ctrl + 文字（例 ctrl-c → 0x03）
    """
    key = name.strip().lower()
    if key in _NAMED:
        return _NAMED[key]

    for prefix in ("ctrl-", "ctrl+", "c-", "^"):
        if key.startswith(prefix) and len(key) > len(prefix):
            rest = key[len(prefix):]
            if len(rest) == 1 and rest.isalpha():
                return chr(ord(rest.upper()) - 64)  # A->1(0x01) ... C->3(0x03)
            break

    raise UnknownKey(name)


def encode_keys(names: list[str]) -> str:
    """複数キー名を順に符号化して連結する。"""
    return "".join(encode_key(n) for n in names)
