"""iterm2-cli: iTerm2 をスクリプト/AIエージェントから操作する CLI のライブラリ層。

公開 API（外部のライブラリ利用側から import する想定）:
    from iterm2_cli import Controller, RealAdapter, SessionResolver, State, Backend, LabelStore

RealAdapter はクラス参照の import だけなら iterm2 パッケージ不要（connect() で遅延 import）。
"""

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _version

from .adapter import ITerm2Adapter, SessionInfo, SessionNotFound
from .adapter_real import RealAdapter
from .backend import Backend
from .core import Controller
from .detect import PROGRESS_VAR, STATE_VAR, State
from .labels import LabelStore
from .resolver import ResolutionError, SessionResolver

# バージョンは pyproject.toml を単一ソースとし、インストール済みメタデータから引く
# （`__version__` への二重定義を避けてドリフトを防ぐ）。未インストール時は安全な既定。
try:
    __version__ = _version("iterm2-cli")
except PackageNotFoundError:  # pragma: no cover - 未インストールのソース実行
    __version__ = "0.0.0+unknown"

__all__ = [
    "Backend",
    "Controller",
    "ITerm2Adapter",
    "LabelStore",
    "PROGRESS_VAR",
    "RealAdapter",
    "ResolutionError",
    "STATE_VAR",
    "SessionInfo",
    "SessionNotFound",
    "SessionResolver",
    "State",
    "__version__",
]
