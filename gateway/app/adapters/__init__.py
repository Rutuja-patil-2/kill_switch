from .base import Adapter, Snapshot  # noqa: F401

_DEFAULT = Adapter()
_ADAPTERS: dict[str, Adapter] = {}  # tool name -> specific adapter (Phase 2)


def get_adapter(tool: str) -> Adapter:
    return _ADAPTERS.get(tool, _DEFAULT)
