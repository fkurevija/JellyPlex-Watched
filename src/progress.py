from math import ceil
from time import monotonic

from loguru import logger


class ProgressLogger:
    """Log estimated time remaining at fixed intervals."""

    def __init__(
        self, server_name: str, operation: str, total: int, interval: int = 10
    ) -> None:
        if interval < 1 or interval > 100:
            raise ValueError("progress interval must be between 1 and 100")
        self.server_name = server_name
        self.operation = operation
        self.total = total
        self.interval = interval
        self._last_reported = -1
        self._started_at = monotonic()

    def update(self, current: int) -> None:
        if current < 0:
            raise ValueError("progress cannot be negative")
        if self.total < 0:
            raise ValueError("progress total cannot be negative")
        if current > self.total:
            raise ValueError("progress cannot exceed its total")

        percentage = 100 if self.total == 0 else current * 100 // self.total
        bucket = 100 if percentage == 100 else percentage // self.interval
        if bucket == self._last_reported:
            return

        self._last_reported = bucket
        remaining = self._estimate_remaining(current)
        logger.info(
            "{}: {} progress: {}/{} (time remaining: {})",
            self.server_name,
            self.operation,
            current,
            self.total,
            remaining,
        )

    def _estimate_remaining(self, current: int) -> str:
        if current == self.total:
            return "~0 sec"
        if current == 0 or self.total == 0:
            return "calculating"

        elapsed = monotonic() - self._started_at
        if elapsed <= 0:
            return "calculating"

        remaining_seconds = ceil(elapsed / current * (self.total - current))
        return f"~{_format_duration(remaining_seconds)}"


def _format_duration(seconds: int) -> str:
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    parts = []
    if hours:
        parts.append(f"{hours} hr")
    if minutes:
        parts.append(f"{minutes} min")
    if seconds or not parts:
        parts.append(f"{seconds} sec")
    return ", ".join(parts)
