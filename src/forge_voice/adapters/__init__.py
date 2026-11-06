"""Synthetic local adapters (SQLite stores and file outbox)."""

from forge_voice.adapters.outbox import Outbox, confirmation_record
from forge_voice.adapters.sqlite import SQLiteAdapter

__all__ = ["Outbox", "SQLiteAdapter", "confirmation_record"]
