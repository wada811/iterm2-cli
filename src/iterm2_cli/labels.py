"""label ↔ session_id の最小マッピング永続化（design.md §4 / 最小状態主義）。

session_id↔label だけを JSON に保存する。branch/cwd 等は持たない（iTerm2 変数や FS から都度引く）。
保存先既定: $XDG_STATE_HOME/iterm2-cli/labels.json（無ければ ~/.local/state/...）。
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path


def default_path() -> Path:
    base = os.environ.get("XDG_STATE_HOME") or os.path.join(os.path.expanduser("~"), ".local", "state")
    return Path(base) / "iterm2-cli" / "labels.json"


def normalize_label(name: str) -> str:
    """ラベル名を正規化する（cmux 由来: 空白/スラッシュ等を ``-`` に）。"""
    return re.sub(r"[\s/]+", "-", name.strip())


class LabelStore:
    def __init__(self, path: Path | str | None = None) -> None:
        self.path = Path(path) if path is not None else default_path()

    def _load(self) -> dict[str, str]:
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {}
        return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}

    def _save(self, mapping: dict[str, str]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(mapping, f, ensure_ascii=False, indent=2, sort_keys=True)
        os.replace(tmp, self.path)

    def all(self) -> dict[str, str]:
        return self._load()

    def get(self, label: str) -> str | None:
        return self._load().get(normalize_label(label))

    def set(self, label: str, session_id: str) -> None:
        mapping = self._load()
        mapping[normalize_label(label)] = session_id
        self._save(mapping)

    def remove(self, label: str) -> bool:
        mapping = self._load()
        if normalize_label(label) in mapping:
            del mapping[normalize_label(label)]
            self._save(mapping)
            return True
        return False
