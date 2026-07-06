"""Writer factory (mirrors publish/engage/metrics factories).

ClaudeWriter when an API key is configured; the zero-cost template writer otherwise.
"""

from __future__ import annotations

import logging

from pulse import config
from pulse.writer.base import Writer
from pulse.writer.claude import ClaudeWriter
from pulse.writer.template import TemplateWriter

log = logging.getLogger("pulse")


def make_writer() -> Writer:
    if config.anthropic_api_key():
        return ClaudeWriter()
    log.warning("ANTHROPIC_API_KEY not set — using the template writer (no LLM).")
    return TemplateWriter()
