"""
Progress reporting for the long, LLM-backed layers.

A wiki or module run is a sequence of model calls that each take seconds to
minutes, with silence in between. Without a counter there is no way to tell a
working run from a hung one — and the layers below are slow enough that the
difference matters. graphify already gets this treatment via the heartbeat in
repo.py; this is the equivalent for calls we make ourselves, where we know both
the total and how long the finished ones took.
"""

from __future__ import annotations

import time

_LABEL_WIDTH = 9


def format_duration(seconds: float) -> str:
    """Render a duration the way a human reads a wait: 45s, 4m12s, 1h04m."""
    seconds = max(0, int(seconds))
    if seconds < 60:
        return f"{seconds}s"
    minutes, secs = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m{secs:02d}s"
    hours, mins = divmod(minutes, 60)
    return f"{hours}h{mins:02d}m"


class Progress:
    """Counts steps through a known-length job and estimates what is left.

    The estimate is a running mean over completed steps, which is the honest
    model here: per-item cost varies with file size but has no trend, so a mean
    converges quickly and never implies more precision than it has.
    """

    def __init__(self, total: int, label: str) -> None:
        self.total = total
        self.label = label.ljust(_LABEL_WIDTH)
        self.done = 0
        self._start = time.monotonic()

    @property
    def elapsed(self) -> float:
        return time.monotonic() - self._start

    def _eta(self) -> str:
        if self.done == 0 or self.done >= self.total:
            return ""
        remaining = (self.elapsed / self.done) * (self.total - self.done)
        return f" · ~{format_duration(remaining)} left"

    def step(self, detail: str) -> None:
        """Record one completed step and print a progress line."""
        self.done += 1
        width = len(str(self.total))
        print(
            f"{self.label}: [{self.done:>{width}}/{self.total}] {detail}"
            f" · {format_duration(self.elapsed)}{self._eta()}",
            flush=True,
        )

    def summary(self) -> str:
        return f"{self.done}/{self.total} in {format_duration(self.elapsed)}"
