"""Import the pinned framework without its import-time global side effects.

The 0.2.8 examples load an implicit .env, and its memory module calls
``logging.basicConfig(level=INFO)``. Both would silently replace this service's
configuration, so the previous state is restored after the import.
"""

import logging
import os

_previous = os.environ.get("PYTHON_DOTENV_DISABLED")
_root = logging.getLogger()
_handlers, _level = list(_root.handlers), _root.level
os.environ["PYTHON_DOTENV_DISABLED"] = "1"
try:
    from hello_agents import Config, HelloAgentsLLM, Message
    from hello_agents.context import ContextBuilder, ContextConfig
    from hello_agents.context.builder import ContextPacket
    from hello_agents.core import Agent
    from hello_agents.tools import Tool, ToolParameter, ToolRegistry
finally:
    if _previous is None:
        os.environ.pop("PYTHON_DOTENV_DISABLED", None)
    else:
        os.environ["PYTHON_DOTENV_DISABLED"] = _previous
    # Log output belongs to the entrypoint (core.logs), not to a library import.
    for _handler in [item for item in _root.handlers if item not in _handlers]:
        _root.removeHandler(_handler)
    _root.setLevel(_level)

__all__ = [
    "Config",
    "HelloAgentsLLM",
    "Message",
    "ContextBuilder",
    "ContextConfig",
    "ContextPacket",
    "Agent",
    "Tool",
    "ToolParameter",
    "ToolRegistry",
]
