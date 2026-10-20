"""The adapter contract any AI provider plugs into. See docs/ARCHITECTURE.md#providers.

`Engine` never imports a concrete adapter by name outside its default construction;
it only calls `available()` and `run()` on whatever objects are passed as `adapters`.
`codex.CodexAdapter` is the one built-in implementation today.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import threading
from typing import Callable, Protocol, runtime_checkable


@dataclass
class Result:
    kind: str
    output: str = ''
    error: str = ''
    retry_at: float | None = None
    quota: dict | None = None
    notices: list[str] = field(default_factory=list)
    partial_output: str = ''


@runtime_checkable
class Provider(Protocol):
    """Structural contract for a job-running adapter.

    `Engine(adapters={name: provider, ...})` accepts any object satisfying this
    shape under any provider name except the reserved `mock`; the name is what
    users pick in a job's `provider` field.
    """

    def available(self) -> bool:
        """Whether this provider can currently accept work (e.g. the CLI is installed and signed in)."""
        ...

    def run(self, job: dict, prompt: str, on_session: Callable[[str], None], stop: threading.Event) -> Result:
        """Run one step. `on_session` reports a resumable session/thread id as soon as it is known.
        `stop` is set to request cancellation; an adapter should stop promptly when it is set."""
        ...
