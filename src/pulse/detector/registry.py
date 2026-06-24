"""Rule registry — a rule is a pure function tagged with the asset-classes it handles.

The engine runs every registered rule whose `applies_to` includes the snapshot's
`value_kind`. Adding a venue with a new asset class (e.g. PRICE for NYSE/crypto) means
adding rules tagged for that class — no engine change.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass

from pulse.models import Event, Snapshot, ValueKind

RuleFn = Callable[[Sequence[Snapshot]], "Event | None"]


@dataclass(frozen=True)
class RuleSpec:
    name: str
    applies_to: frozenset[ValueKind]
    fn: RuleFn


REGISTRY: list[RuleSpec] = []


def rule(name: str, applies_to: Iterable[ValueKind]) -> Callable[[RuleFn], RuleFn]:
    """Decorator: register a pure rule function under `name` for the given asset-classes."""

    def deco(fn: RuleFn) -> RuleFn:
        REGISTRY.append(RuleSpec(name=name, applies_to=frozenset(applies_to), fn=fn))
        return fn

    return deco
