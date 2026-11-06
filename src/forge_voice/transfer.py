"""Deterministic warm-transfer simulator; a human answer is explicit, never assumed."""

from __future__ import annotations


class TransferSimulator:
    """`answered_targets=None` means every configured target answers in the demo."""

    def __init__(self, answered_targets: set[str] | None = None) -> None:
        self._answered = answered_targets
        self.attempts: list[str] = []

    def answers(self, target_id: str) -> bool:
        self.attempts.append(target_id)
        if self._answered is None:
            return True
        return target_id in self._answered
