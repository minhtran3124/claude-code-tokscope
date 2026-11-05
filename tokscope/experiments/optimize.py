"""The claude binary lookup and the model list that the dashboard and the optimize loop share."""

import os

from .. import paths

MODELS = ("", "sonnet", "opus", "haiku")


def _claude():
    if env := os.environ.get("TOKSCOPE_CLAUDE"):
        return env
    return paths.tool("claude", first=paths.CLAUDE_FIRST) or "claude"
