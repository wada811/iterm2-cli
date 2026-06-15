"""iterm2-cli: iTerm2 をスクリプト/AIエージェントから操作する CLI のライブラリ層。

公開 API（オーケストレータ 等から import する想定）:
    from iterm2_cli import Controller, RealAdapter, SessionResolver, State, Backend, LabelStore

RealAdapter はクラス参照の import だけなら iterm2 パッケージ不要（connect() で遅延 import）。
"""

from .adapter import ITerm2Adapter, SessionInfo, SessionNotFound
from .adapter_real import RealAdapter
from .backend import Backend
from .core import Controller
from .detect import PROGRESS_VAR, STATE_VAR, State
from .labels import LabelStore
from .resolver import ResolutionError, SessionResolver

__version__ = "0.0.1"

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
