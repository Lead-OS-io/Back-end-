"""In-process registry used by the onboarding endpoint to wait until the
auth-service consumer has processed the matching `tenant.created` event.

The registry is thread-safe and supports a single waiter per `user_id`.
The consumer thread calls `complete()`; the request thread calls
`wait_for(user_id, timeout)`.
"""
import threading
import uuid
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class OnboardingCompletion:
    user_id: uuid.UUID
    tenant_id: uuid.UUID


class OnboardingCompletionRegistry:
    """Thread-safe completion registry."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._events: dict[uuid.UUID, threading.Event] = {}
        self._results: dict[uuid.UUID, OnboardingCompletion] = {}

    def register(self, user_id: uuid.UUID) -> threading.Event:
        """Register a waiter. Returns the event the waiter should block on."""
        with self._lock:
            event = self._events.get(user_id)
            if event is None:
                event = threading.Event()
                self._events[user_id] = event
                self._results.pop(user_id, None)
            return event

    def complete(self, completion: OnboardingCompletion) -> None:
        """Signal that onboarding completed for `completion.user_id`."""
        with self._lock:
            self._results[completion.user_id] = completion
            event = self._events.get(completion.user_id)
            if event is not None:
                event.set()

    def wait_for(
        self, user_id: uuid.UUID, timeout: float
    ) -> Optional[OnboardingCompletion]:
        """Wait up to `timeout` seconds for completion."""
        event = self.register(user_id)
        if event.wait(timeout=timeout):
            with self._lock:
                return self._results.get(user_id)
        return None

    def clear(self, user_id: uuid.UUID) -> None:
        with self._lock:
            self._events.pop(user_id, None)
            self._results.pop(user_id, None)


__all__ = ["OnboardingCompletion", "OnboardingCompletionRegistry"]
