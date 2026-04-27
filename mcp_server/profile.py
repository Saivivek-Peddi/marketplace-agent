"""User profile: saved places, preferences, recent rides.

Agent-side memory — the mock API knows nothing about this.
Stored as a JSON file on disk, read/written by MCP tools.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

DEFAULT_PROFILE = {
    "saved_places": {},
    "preferences": {
        "default_car_type": "comfort",
        "always_confirm": True,
    },
    "recent_rides": [],
}

MAX_RECENT_RIDES = 20


class UserProfile:
    def __init__(self, path: str | Path):
        self._path = Path(path)
        self._data: dict = self._load()

    def _load(self) -> dict:
        if self._path.exists():
            try:
                return json.loads(self._path.read_text())
            except (json.JSONDecodeError, ValueError):
                return dict(DEFAULT_PROFILE)
        return dict(DEFAULT_PROFILE)

    def _save(self) -> None:
        self._path.write_text(json.dumps(self._data, indent=2) + "\n")

    #  Places most visited

    def get_place(self, name: str) -> str | None:
        return self._data["saved_places"].get(name.lower())

    def resolve_address(self, raw: str) -> str:
        """If raw matches a saved place name, return the real address."""
        resolved = self.get_place(raw.strip().lower())
        return resolved if resolved else raw

    def save_place(self, name: str, address: str) -> None:
        self._data["saved_places"][name.lower()] = address
        self._save()

    def delete_place(self, name: str) -> bool:
        key = name.lower()
        if key in self._data["saved_places"]:
            del self._data["saved_places"][key]
            self._save()
            return True
        return False

    def list_places(self) -> dict[str, str]:
        return dict(self._data["saved_places"])

    # User Preferences

    def get_preference(self, key: str) -> Any:
        return self._data["preferences"].get(key)

    def save_preference(self, key: str, value: Any) -> None:
        self._data["preferences"][key] = value
        self._save()

    def list_preferences(self) -> dict[str, Any]:
        return dict(self._data["preferences"])

    #  Recent rides

    def add_recent_ride(self, ride: dict) -> None:
        self._data["recent_rides"].insert(0, ride)
        self._data["recent_rides"] = self._data["recent_rides"][:MAX_RECENT_RIDES]
        self._save()

    def recent_rides(self, count: int = 5) -> list[dict]:
        return self._data["recent_rides"][:count]
