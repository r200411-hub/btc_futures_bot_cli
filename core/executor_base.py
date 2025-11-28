# core/executor_base.py
from abc import ABC, abstractmethod

class ExecutorBase(ABC):
    """Abstract execution interface."""

    @abstractmethod
    def start(self):
        """Start any background workers required (non-blocking)."""
        raise NotImplementedError

    @abstractmethod
    def stop(self):
        """Stop background workers and flush state."""
        raise NotImplementedError

    @abstractmethod
    def submit_order(self, side: str, size: float, price: float, meta: dict=None):
        """Submit order to executor. Non-blocking; fills will be delivered via callbacks to trader."""
        raise NotImplementedError

    @abstractmethod
    def cancel_all(self):
        """Cancel outstanding simulated orders (if any)."""
        raise NotImplementedError
