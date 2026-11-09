from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx


class JellyfinClient:
    def __init__(self, base_url: str, api_key: str) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._http = httpx.Client(timeout=30)

    @classmethod
    def from_env(cls) -> "JellyfinClient | None":
        api_key = os.getenv("JELLYFIN_API_KEY", "").strip()
        if not api_key:
            return None
        base_url = os.getenv("JELLYFIN_BASE_URL", "http://localhost:8096").strip()
        return cls(base_url=base_url, api_key=api_key)

    def close(self) -> None:
        self._http.close()

    def list_libraries(self) -> list[dict]:
        data = self._api_get("/Library/VirtualFolders")
        return [{"name": item.get("Name", ""), "id": item.get("ItemId", "")} for item in data]

    def resolve_library(self, library_name: str) -> dict:
        libraries = self.list_libraries()
        needle = library_name.strip().lower()
        exact = [item for item in libraries if str(item.get("name", "")).strip().lower() == needle]
        if len(exact) == 1:
            return {"name": exact[0]["name"], "id": exact[0]["id"]}
        contains = [item for item in libraries if needle in str(item.get("name", "")).strip().lower()]
        if len(contains) == 1:
            return {"name": contains[0]["name"], "id": contains[0]["id"]}
        if not contains:
            raise ValueError(f"Jellyfin library not found: {library_name}")
        names = ", ".join(str(item.get("name", "")) for item in contains)
        raise ValueError(f"Ambiguous Jellyfin library name '{library_name}': {names}")

    def get_recent_items(
        self,
        library_name: str,
        since_hours: int = 72,
        limit: int = 200,
    ) -> list[dict]:
        library = self.resolve_library(library_name)
        user_id = self._get_user_id()
        cutoff = datetime.now(UTC) - timedelta(hours=since_hours)

        params: dict[str, str] = {
            "ParentId": library["id"],
            "Recursive": "true",
            "IncludeItemTypes": "Movie,Episode",
            "SortBy": "DateCreated",
            "SortOrder": "Descending",
            "Limit": str(limit),
            "Fields": "Path,DateCreated,MediaSources",
            "UserId": user_id,
        }
        data = self._api_get("/Items", params)
        items = data.get("Items", [])

        recent = []
        for item in items:
            date_created = item.get("DateCreated")
            if date_created:
                try:
                    dt = datetime.fromisoformat(str(date_created).replace("Z", "+00:00"))
                    if dt < cutoff:
                        continue
                except ValueError:
                    pass
            path = self._get_item_path(item)
            if path:
                recent.append({
                    "path": path,
                    "name": item.get("Name", ""),
                    "library_name": library_name,
                })
        return recent

    def get_library_paths(self, library_name: str) -> list[str]:
        library = self.resolve_library(library_name)
        data = self._api_get(f"/Library/VirtualFolders")
        for lib in data:
            if lib.get("ItemId") == library["id"]:
                locations = lib.get("Locations") or []
                return [loc for loc in locations if loc]
        return []

    def _get_item_path(self, item: dict) -> str | None:
        path = item.get("Path", "") or ""
        path_obj = Path(path)
        if path_obj.exists():
            return str(path_obj)
        media_sources = item.get("MediaSources") or []
        for ms in media_sources:
            p = ms.get("Path", "") or ""
            if p and Path(p).exists():
                return p
        return path if path else None

    def _api_get(self, path: str, params: dict[str, str] | None = None) -> dict | list:
        r = self._http.get(
            f"{self._base_url}{path}",
            params=params,
            headers={"Authorization": f'MediaBrowser Token="{self._api_key}"'},
        )
        r.raise_for_status()
        return r.json()

    def _get_user_id(self) -> str:
        users = self._api_get("/Users")
        if isinstance(users, list) and len(users) > 0:
            uid = users[0].get("Id")
            if uid:
                return uid
        raise ValueError("Could not resolve Jellyfin user")
