"""DryRunPublisher — logs what it would post, touches no network, writes no posts.

This is the safety default: outside live mode, this stands in for every channel so nothing is
actually published. Returns `posted=False`, so the orchestrator records nothing — flipping to live
later posts fresh.
"""

from __future__ import annotations

import logging

from pulse.persona import Persona
from pulse.publish.base import PostResult
from pulse.writer.base import Draft, enforce_bluesky_length

log = logging.getLogger("pulse")


class DryRunPublisher:
    def __init__(self, channel: str) -> None:
        self.name = channel

    def publish(self, draft: Draft, persona: Persona) -> PostResult:
        text = enforce_bluesky_length(draft.text)
        log.info("would post [%s] (persona=%s): %s", self.name, persona.name, text)
        return PostResult(channel=self.name, posted=False, text=text)
