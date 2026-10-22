from __future__ import annotations

import copy
from dataclasses import dataclass
import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from enum import IntEnum
from typing import Any, Literal, TypeVar

from loguru import logger
from pydantic import BaseModel, Field

from src.functions import get_env_value, normalize_name, to_aware_utc
from src.settings import AppSettings


class Ord(IntEnum):
    A_BETTER = -1
    TIE = 0
    B_BETTER = 1


class MediaIdentifiers(BaseModel):
    title: str | None = None

    # File information, will be folder for series and media file for episode/movie
    locations: tuple[str, ...] = tuple()

    # Guids
    imdb_id: str | None = None
    tvdb_id: str | None = None
    tmdb_id: str | None = None

    # A planned winner keeps its native identifiers above. These additional
    # (namespace, value) pairs retain matches learned from permitted histories,
    # including multiple IDs from the same provider or alternate filenames.
    matching_aliases: frozenset[tuple[str, str]] = frozenset()


class WatchedStatus(BaseModel):
    completed: bool
    time: int
    viewed_date: datetime
    manually_unwatched: bool = False
    manual_unwatched_at: datetime | None = None
    # Timestamp of the last time this item's completed/resume state materially
    # changed for this source server, per the watched-state DB (mirrors the
    # media_state.state_changed_at column). Used to let a rewatch that
    # happened AFTER the other server's manual-unwatch timestamp override a
    # stale manual-unwatched marker, no matter how many cycles have passed
    # since either event was first recorded.
    state_changed_at: datetime | None = None


class MediaItem(BaseModel):
    identifiers: MediaIdentifiers
    status: WatchedStatus


class Series(BaseModel):
    identifiers: MediaIdentifiers
    episodes: list[MediaItem] = Field(default_factory=list)


class LibraryData(BaseModel):
    title: str
    # Discovery metadata used for directional type filters and rule exceptions.
    library_type: str | None = None
    movies: list[MediaItem] = Field(default_factory=list)
    series: list[Series] = Field(default_factory=list)


class UserData(BaseModel):
    libraries: dict[str, LibraryData] = Field(default_factory=dict)


@dataclass(frozen=True, order=True)
class WatchedScope:
    """One server-native user/library scope along an authorized sync path."""

    server_name: str
    username: str
    library_name: str


@dataclass(frozen=True)
class WatchedUpdate:
    """One pending library update from a source scope to a concrete destination."""

    source_user: str
    target_user: str
    source_library: str
    target_library: str
    library_data: LibraryData
    # Indirect plans retain the original source and every hop, including the
    # destination. source_user/source_library describe the final incoming hop
    # so adapters can resolve its aliases without inventing a direct mapping.
    relay_path: tuple[WatchedScope, ...] = ()


WriteOutcomeStatus = Literal[
    "applied",
    "skipped",
    "unsupported",
    "failed",
    "uncertain",
]


@dataclass(frozen=True)
class WatchedWriteOutcome:
    """Result for one attempted item update on a concrete destination."""

    status: WriteOutcomeStatus
    target_user: str
    target_library: str
    media_item: MediaItem
    series_identifiers: MediaIdentifiers | None = None
    target_user_id: str | None = None
    target_library_id: str | None = None
    target_item_id: str | None = None
    reason: str | None = None


def resulting_media_item(
    media_item: MediaItem,
    completed: bool,
    identifiers: MediaIdentifiers | None = None,
) -> MediaItem:
    """Return the state represented by a completed or partial write."""
    updates: dict[str, Any] = {
        "status": media_item.status.model_copy(
            update={
                "completed": completed,
                "time": 0 if completed else media_item.status.time,
            }
        )
    }
    if identifiers is not None:
        updates["identifiers"] = identifiers
    return media_item.model_copy(
        update=updates
    )


_WatchedData = TypeVar("_WatchedData")


def _lookup_named(
    values: dict[str, _WatchedData], name: str
) -> _WatchedData | None:
    """Find a watched-data entry using the same case-folded lookup as settings."""
    if name in values:
        return values[name]

    name_normalized = normalize_name(name)
    for actual_name, value in values.items():
        if normalize_name(actual_name) == name_normalized:
            return value
    return None


def expand_watched_updates(
    watched_list: dict[str, UserData],
    source_server_name: str,
    target_server_name: str,
    settings: AppSettings,
) -> list[WatchedUpdate]:
    """Expand source-shaped watched data into destination-scoped updates.

    Preserve each source scope for authorization before fan-in. Callers must
    check should_sync_scope once the destination library type is known.

    This is also used for callers that provide a complete source watched
    dictionary directly to an adapter. A missing destination history is
    represented by an update with the source library data unchanged; the
    adapter will still verify that the destination user and library exist.
    """
    updates: list[WatchedUpdate] = []
    for source_user, user_data in watched_list.items():
        if not settings.should_sync_user(
            source_user, source_server_name, target_server_name
        ):
            continue
        target_users = settings.sync_targets_for_user(
            source_server_name, source_user, target_server_name
        )
        for target_user in target_users:
            for source_library, library_data in user_data.libraries.items():
                target_libraries = settings.sync_targets_for_library(
                    source_server_name,
                    source_library,
                    target_server_name,
                )
                for target_library in target_libraries:
                    updates.append(
                        WatchedUpdate(
                            source_user=source_user,
                            target_user=target_user,
                            source_library=source_library,
                            target_library=target_library,
                            library_data=library_data,
                        )
                    )
    return updates

STATE_ENV: dict[str, Any] = {}
"""Shared state for the watched-state DB (path from WATCHED_STATE_DB env var,
per-server in-memory indexes, and the current fetch source)."""


def mediaitem_identity_key(item: MediaItem) -> str:
    return json.dumps(
        {
        "title": item.identifiers.title or "",
        "locations": list(item.identifiers.locations),
        "imdb_id": item.identifiers.imdb_id or "",
        "tvdb_id": item.identifiers.tvdb_id or "",
        "tmdb_id": item.identifiers.tmdb_id or "",
        },
        sort_keys=True,
    )


def mediaitem_state_key(item: MediaItem, source_server: str | None = None) -> str:
    payload = json.loads(mediaitem_identity_key(item))
    if source_server:
        payload["source_server"] = source_server
    return json.dumps(payload, sort_keys=True)


def watched_state_db_path(env: dict[str, str | float | None] | None) -> str:
    db_path = get_env_value(env, "WATCHED_STATE_DB", ".jellyplex-watched-state.db")
    if not os.path.isabs(db_path):
        db_path = os.path.join(os.getcwd(), db_path)
    return db_path


def legacy_watched_state_path(env: dict[str, str | float | None] | None) -> str:
    state_path = get_env_value(env, "WATCHED_STATE_FILE", ".jellyplex-watched-state.json")
    if not os.path.isabs(state_path):
        state_path = os.path.join(os.getcwd(), state_path)
    return state_path


def initialize_watched_state_db(
    env: dict[str, str | float | None] | None,
) -> str:
    db_path = watched_state_db_path(env)
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)

    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS media_state (
                state_key TEXT PRIMARY KEY,
                completed INTEGER NOT NULL,
                resume_ms INTEGER NOT NULL,
                viewed_date TEXT NOT NULL,
                manual_unwatched_at TEXT,
                observed_at TEXT NOT NULL DEFAULT '',
                state_changed_at TEXT
            )
            """
        )
        columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(media_state)").fetchall()
        }
        if "observed_at" not in columns:
            connection.execute(
                "ALTER TABLE media_state ADD COLUMN observed_at TEXT NOT NULL DEFAULT ''"
            )
        if "state_changed_at" not in columns:
            connection.execute(
                "ALTER TABLE media_state ADD COLUMN state_changed_at TEXT"
            )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS pending_sync (
                state_key TEXT NOT NULL,
                destination_server TEXT NOT NULL,
                expected_completed INTEGER NOT NULL,
                expected_resume_ms INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY (state_key, destination_server)
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """
        )

        migrated = connection.execute(
            "SELECT 1 FROM metadata WHERE key = 'json_migrated'"
        ).fetchone()
        legacy_path = legacy_watched_state_path(env)
        if migrated is None and os.path.exists(legacy_path):
            try:
                with open(legacy_path, "r", encoding="utf-8") as state_file:
                    legacy_state = json.load(state_file)
                if not isinstance(legacy_state, dict):
                    raise ValueError("legacy state is not a JSON object")

                for state_key, state in legacy_state.items():
                    if not isinstance(state, dict):
                        continue
                    connection.execute(
                        """
                        INSERT OR IGNORE INTO media_state
                        (state_key, completed, resume_ms, viewed_date, manual_unwatched_at)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (
                            state_key,
                            int(bool(state.get("completed", False))),
                            int(state.get("time", 0)),
                            str(
                                state.get(
                                    "viewed_date",
                                    datetime.now(timezone.utc).isoformat(),
                                )
                            ),
                            state.get("manual_unwatched_at"),
                        ),
                    )
                logger.info(f"Migrated watched state from {legacy_path} to {db_path}")
                connection.execute(
                    "INSERT INTO metadata (key, value) VALUES ('json_migrated', 'true')"
                )
            except (OSError, ValueError, TypeError, json.JSONDecodeError) as error:
                logger.warning(
                    f"Failed to migrate watched state from {legacy_path}: {error}"
                )

    return db_path


def was_previously_watched(
    item: MediaItem,
    env: dict[str, str | float | None],
) -> bool:
    state_index = env.get("_watched_state_index")
    if isinstance(state_index, dict):
        row = _find_indexed(
            item, state_index, str(env.get("_watched_state_source", ""))
        )
        if (
            row is None
            and not item.status.completed
            and item.status.time <= 60_000
        ):
            row = _find_any_indexed(item, state_index)
        return row is not None

    db_path = initialize_watched_state_db(env)
    with sqlite3.connect(db_path) as connection:
        row = connection.execute(
            "SELECT completed FROM media_state WHERE state_key = ?",
            (mediaitem_state_key(item, str(env.get("_watched_state_source", ""))),),
        ).fetchone()
    return row is not None


def load_previously_watched_keys(
    env: dict[str, str | float | None],
    source_server: str | None,
) -> set[str]:
    """Load completed state keys once for a server snapshot."""
    db_path = initialize_watched_state_db(env)
    with sqlite3.connect(db_path) as connection:
        rows = connection.execute(
            """
            SELECT state_key
            FROM media_state
            WHERE completed = 1 AND state_key LIKE ?
            """,
            (f'%"source_server": "{source_server or ""}"%',),
        ).fetchall()

    return {row[0] for row in rows}


def _identity_values(item: MediaItem) -> tuple[tuple[str, ...], str | None, str | None, str | None, str | None]:
    identifiers = item.identifiers
    return (
        tuple(identifiers.locations),
        identifiers.imdb_id,
        identifiers.tvdb_id,
        identifiers.tmdb_id,
        identifiers.title,
    )


def load_state_index(
    env: dict[str, str | float | None],
    source_server: str | None,
) -> dict[str, Any]:
    """Load and normalize all state used during one server snapshot."""
    db_path = initialize_watched_state_db(env)
    with sqlite3.connect(db_path) as connection:
        rows = connection.execute(
            """
            SELECT state_key, completed, resume_ms, state_changed_at,
                   manual_unwatched_at
            FROM media_state
            WHERE state_key LIKE ?
            """,
            (f'%"source_server": "{source_server or ""}"%',),
        ).fetchall()
        rows += connection.execute(
            """
            SELECT state_key, completed, resume_ms, state_changed_at,
                   manual_unwatched_at
            FROM media_state
            WHERE state_key NOT LIKE '%"source_server":%'
            """
        ).fetchall()
        rows += connection.execute(
            """
            SELECT state_key, completed, resume_ms, state_changed_at,
                   manual_unwatched_at
            FROM media_state
            WHERE state_key LIKE '%"source_server":%'
              AND state_key NOT LIKE ?
            """,
            (f'%"source_server": "{source_server or ""}"%',),
        ).fetchall()
        pending_ttl_hours = float(
            get_env_value(env, "WATCHED_STATE_PENDING_TTL_HOURS", "24") or 24
        )
        pending_cutoff = (
            datetime.now(timezone.utc) - timedelta(hours=pending_ttl_hours)
        ).isoformat()
        pending_rows = connection.execute(
            """
            SELECT state_key, expected_completed, expected_resume_ms
            FROM pending_sync
            WHERE destination_server = ? AND created_at >= ?
            """,
            (source_server or "", pending_cutoff),
        ).fetchall()

    index: dict[str, Any] = {
        "by_state_key": {},
        "by_location": {},
        "by_imdb_id": {},
        "by_tvdb_id": {},
        "by_tmdb_id": {},
        "by_title": {},
        "by_any_state_key": {},
        "by_any_location": {},
        "by_any_imdb_id": {},
        "by_any_tvdb_id": {},
        "by_any_tmdb_id": {},
        "by_any_title": {},
        "pending": {},
    }
    source_rows = rows[:]
    for row in source_rows:
        try:
            identity = json.loads(row[0])
        except json.JSONDecodeError:
            continue
        normalized = (row, identity)
        is_current_source = (
            f'"source_server": "{source_server or ""}"' in row[0]
            or '"source_server":' not in row[0]
        )
        state_key_name = "by_state_key" if is_current_source else "by_any_state_key"
        location_name = "by_location" if is_current_source else "by_any_location"
        index[state_key_name].setdefault(row[0], normalized)
        for location in identity.get("locations", []):
            index[location_name].setdefault(location, normalized)
        for field, index_name in (
            ("imdb_id", "by_imdb_id"),
            ("tvdb_id", "by_tvdb_id"),
            ("tmdb_id", "by_tmdb_id"),
            ("title", "by_title"),
        ):
            value = identity.get(field)
            if value:
                index[
                    index_name if is_current_source else f"by_any_{field}"
                ].setdefault(value, normalized)

    for row in pending_rows:
        try:
            identity = json.loads(row[0])
        except json.JSONDecodeError:
            continue
        normalized = (row, identity)
        for location in identity.get("locations", []):
            index["pending"].setdefault(("location", location), normalized)
        for field in ("imdb_id", "tvdb_id", "tmdb_id", "title"):
            value = identity.get(field)
            if value:
                index["pending"].setdefault((field, value), normalized)
    return index


def _find_indexed(
    item: MediaItem,
    index: dict[str, Any],
    source_server: str | None = None,
) -> tuple | None:
    exact_key = mediaitem_state_key(item, source_server)
    if exact_key in index["by_state_key"]:
        return index["by_state_key"][exact_key][0]

    locations, imdb_id, tvdb_id, tmdb_id, title = _identity_values(item)
    for location in locations:
        if location in index["by_location"]:
            return index["by_location"][location][0]
    for field, value in (
        ("imdb_id", imdb_id),
        ("tvdb_id", tvdb_id),
        ("tmdb_id", tmdb_id),
        ("title", title),
    ):
        if value and value in index[f"by_{field}"]:
            return index[f"by_{field}"][value][0]
    return None


def _find_any_indexed(
    item: MediaItem,
    index: dict[str, Any],
) -> tuple | None:
    locations, imdb_id, tvdb_id, tmdb_id, title = _identity_values(item)
    for location in locations:
        if location in index["by_any_location"]:
            row = index["by_any_location"][location][0]
            if bool(row[1]):
                return row
    for field, value in (
        ("imdb_id", imdb_id),
        ("tvdb_id", tvdb_id),
        ("tmdb_id", tmdb_id),
        ("title", title),
    ):
        if value and value in index[f"by_any_{field}"]:
            row = index[f"by_any_{field}"][value][0]
            if bool(row[1]):
                return row
    return None


def _index_state_row(
    state_index: dict[str, Any],
    row: tuple,
) -> None:
    """Add the latest persisted state row to the in-memory lookup index."""
    try:
        identity = json.loads(row[0])
    except (TypeError, json.JSONDecodeError):
        return

    normalized = (row, identity)
    state_index["by_state_key"][row[0]] = normalized
    for location in identity.get("locations", []):
        state_index["by_location"][location] = normalized
    for field, index_name in (
        ("imdb_id", "by_imdb_id"),
        ("tvdb_id", "by_tvdb_id"),
        ("tmdb_id", "by_tmdb_id"),
        ("title", "by_title"),
    ):
        value = identity.get(field)
        if value:
            state_index[index_name][value] = normalized


def _find_state_row(
    connection: sqlite3.Connection,
    item: MediaItem,
    source_server: str | None,
    state_index: dict[str, Any] | None = None,
) -> tuple | None:
    if state_index is not None:
        exact_key = mediaitem_state_key(item, source_server)
        exact = state_index.get("by_state_key", {}).get(exact_key)
        if exact is not None:
            return exact[0]

    rows = connection.execute(
        """
        SELECT state_key, completed, resume_ms, state_changed_at,
               manual_unwatched_at
        FROM media_state
        WHERE state_key LIKE ?
        """,
        (f'%"source_server": "{source_server or ""}"%',),
    ).fetchall()
    rows += connection.execute(
        """
        SELECT state_key, completed, resume_ms, state_changed_at,
               manual_unwatched_at
        FROM media_state
        WHERE state_key NOT LIKE '%"source_server":%'
        """
    ).fetchall()
    for row in rows:
        try:
            identity = json.loads(row[0])
        except (TypeError, json.JSONDecodeError):
            continue
        stored_source = identity.get("source_server")
        if stored_source not in (None, source_server):
            continue
        if _identities_match(item, identity):
            return row
    return None


def _identities_match(item: MediaItem, stored_identity: dict[str, Any]) -> bool:
    if set(item.identifiers.locations).intersection(
        stored_identity.get("locations", [])
    ):
        return True
    for field in ("imdb_id", "tvdb_id", "tmdb_id"):
        value = getattr(item.identifiers, field)
        if value and value == stored_identity.get(field):
            return True
    return item.identifiers.title == stored_identity.get("title")


def _find_pending(index: dict[str, Any], item: MediaItem) -> tuple | None:
    locations, imdb_id, tvdb_id, tmdb_id, title = _identity_values(item)
    for key in [(("location", value)) for value in locations] + [
        ("imdb_id", imdb_id),
        ("tvdb_id", tvdb_id),
        ("tmdb_id", tmdb_id),
        ("title", title),
    ]:
        if key[1] and key in index["pending"]:
            return index["pending"][key][0]
    return None


def _remove_pending_from_index(
    state_index: dict[str, Any] | None,
    pending_key: str,
) -> None:
    if not state_index:
        return
    for key_name, value in list(state_index["pending"].items()):
        if value[0][0] == pending_key:
            del state_index["pending"][key_name]


def _apply_manual_unwatched_item_state_db(
    connection: sqlite3.Connection,
    item: MediaItem,
    source_server: str | None,
    state_index: dict[str, Any] | None = None,
) -> None:
    key = mediaitem_state_key(item, source_server)
    previous = _find_state_row(connection, item, source_server, state_index)
    state_key = previous[0] if previous else key
    now = datetime.now(timezone.utc)
    manual_unwatched_at = None
    pending = _find_pending(state_index, item) if state_index else None
    pending_key = pending[0] if pending else None
    if pending:
        pending = pending[1:]
    pending_matches = bool(
        pending
        and bool(pending[0]) == item.status.completed
        and abs(pending[1] - item.status.time) <= 10_000
    )

    if (
        previous
        and previous[4]
        and not item.status.completed
        and item.status.time <= 10_000
        and not pending_matches
    ):
        # Re-affirming an already-established manual-unwatched state. Preserve
        # the ORIGINAL detection timestamp rather than bumping it to `now` -
        # otherwise this marker's effective timestamp would advance forever
        # on every cycle it stays unwatched, making it perpetually "newer"
        # than any rewatch on the other server and permanently defeating the
        # state_changed_at-based override below.
        item.status.time = 0
        item.status.manually_unwatched = True
        item.status.manual_unwatched_at = datetime.fromisoformat(previous[4])

    if (
        previous
        and bool(previous[1])
        and not item.status.completed
        and item.status.time <= 10_000
        and not pending_matches
    ):
        item.status.viewed_date = now
        item.status.time = 0
        item.status.manually_unwatched = True
        item.status.manual_unwatched_at = now
        manual_unwatched_at = now.isoformat()
    elif item.status.manually_unwatched:
        manual_unwatched_at = previous[4] if previous else now.isoformat()

    # On the very first observation of this item (no previous DB row), we
    # have no evidence of WHEN its current completed/time state actually
    # arose - it could be old, pre-existing history, not a fresh change.
    # Treating a first observation as "changed now" would let a
    # long-completed item on one server spuriously "postdate" (and thus
    # override) a manual-unwatched marker recorded moments earlier on the
    # other server in the very same cycle. Record state_changed_at as
    # unknown (None) instead so first observations can never trigger the
    # rewatch-overrides-stale-unwatch logic below.
    state_changed_at = (
        None
        if not previous
        else (
            now.isoformat()
            if bool(previous[1]) != item.status.completed
            or abs(previous[2] - item.status.time) > 10_000
            else previous[3]
        )
    )
    item.status.state_changed_at = (
        datetime.fromisoformat(state_changed_at) if state_changed_at else None
    )
    connection.execute(
        """
        INSERT INTO media_state
        (state_key, completed, resume_ms, viewed_date, manual_unwatched_at,
         observed_at, state_changed_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(state_key) DO UPDATE SET
            completed = excluded.completed,
            resume_ms = excluded.resume_ms,
            viewed_date = excluded.viewed_date,
            manual_unwatched_at = excluded.manual_unwatched_at,
            observed_at = excluded.observed_at,
            state_changed_at = excluded.state_changed_at
        """,
        (
            state_key,
            int(item.status.completed),
            item.status.time,
            item.status.viewed_date.isoformat(),
            manual_unwatched_at,
            now.isoformat(),
            state_changed_at,
        ),
    )
    if state_index is not None:
        _index_state_row(
            state_index,
            (
                state_key,
                int(item.status.completed),
                item.status.time,
                state_changed_at,
                manual_unwatched_at,
            ),
        )
    if pending:
        pending_state_key = pending_key or mediaitem_identity_key(item)
        connection.execute(
            """
            DELETE FROM pending_sync
            WHERE state_key = ? AND destination_server = ?
            """,
            (pending_state_key, source_server or ""),
        )
        _remove_pending_from_index(state_index, pending_state_key)


def record_pending_sync(
    env: dict[str, str | float | None],
    item: MediaItem,
    destination_server: str,
    destination_item: MediaItem | None = None,
) -> None:
    """Record a state written by this process for destination confirmation."""
    env["_watched_state_dirty"] = True
    db_path = initialize_watched_state_db(env)
    identity_key = mediaitem_identity_key(destination_item or item)
    expected = (
        identity_key,
        int(item.status.completed),
        item.status.time,
    )
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()
    # The destination server's own media_state baseline is otherwise only
    # ever updated by READING that server on a later cycle - never by this
    # process's own writes. If the destination's real state is changed again
    # (e.g. the user manually unwatches it) before that next read happens,
    # the stale baseline (still showing the pre-write value) makes the
    # subsequent read look unchanged, so the manual transition is silently
    # missed. Proactively record what we just wrote as the destination's new
    # baseline so a later divergent read is correctly recognized as a fresh
    # manual change.
    destination_state_key = mediaitem_state_key(
        destination_item or item, destination_server
    )
    destination_index = (
        env.get("_watched_state_indexes", {}).get(destination_server)
        if isinstance(env.get("_watched_state_indexes"), dict)
        else env.get("_watched_state_index")
    )
    manual_unwatched_at = (
        item.status.manual_unwatched_at.isoformat()
        if item.status.manually_unwatched and item.status.manual_unwatched_at
        else None
    )
    with sqlite3.connect(db_path) as connection:
        # Reuse the row the destination's own reads resolve to (matched by
        # location/ids/title) so the baseline is updated in place instead of
        # creating an orphan row under the source item's identity key.
        existing = _find_state_row(
            connection,
            destination_item or item,
            destination_server,
            destination_index if isinstance(destination_index, dict) else None,
        )
        if existing:
            destination_state_key = existing[0]
        connection.execute(
            """
            INSERT INTO pending_sync
            (state_key, destination_server, expected_completed,
             expected_resume_ms, created_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(state_key, destination_server) DO UPDATE SET
                expected_completed = excluded.expected_completed,
                expected_resume_ms = excluded.expected_resume_ms,
                created_at = excluded.created_at
            """,
            (
                identity_key,
                destination_server,
                int(item.status.completed),
                item.status.time,
                now_iso,
            ),
        )
        connection.execute(
            """
            INSERT INTO media_state
            (state_key, completed, resume_ms, viewed_date, manual_unwatched_at,
             observed_at, state_changed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(state_key) DO UPDATE SET
                completed = excluded.completed,
                resume_ms = excluded.resume_ms,
                viewed_date = excluded.viewed_date,
                manual_unwatched_at = excluded.manual_unwatched_at,
                observed_at = excluded.observed_at,
                state_changed_at = excluded.state_changed_at
            """,
            (
                destination_state_key,
                int(item.status.completed),
                item.status.time,
                item.status.viewed_date.isoformat(),
                manual_unwatched_at,
                now_iso,
                now_iso,
            ),
        )
    state_indexes = env.get("_watched_state_indexes")
    state_index = (
        state_indexes.get(destination_server)
        if isinstance(state_indexes, dict)
        else env.get("_watched_state_index")
    )
    if isinstance(state_index, dict):
        normalized = ((identity_key, expected[1], expected[2]), json.loads(identity_key))
        identity = normalized[1]
        for location in identity.get("locations", []):
            state_index["pending"][("location", location)] = normalized
        for field in ("imdb_id", "tvdb_id", "tmdb_id", "title"):
            value = identity.get(field)
            if value:
                state_index["pending"][(field, value)] = normalized


def apply_manual_unwatched_state(
    watched_list: dict[str, UserData],
    env: dict[str, str | float | None],
    source_server: str | None = None,
) -> dict[str, UserData]:
    db_path = initialize_watched_state_db(env)
    state_index = env.get("_watched_state_index")
    if not isinstance(state_index, dict):
        state_index = load_state_index(env, source_server)

    with sqlite3.connect(db_path) as connection:
        for user_data in watched_list.values():
            for library_data in user_data.libraries.values():
                for movie in library_data.movies:
                    _apply_manual_unwatched_item_state_db(
                        connection, movie, source_server, state_index
                    )

                for series in library_data.series:
                    for episode in series.episodes:
                        _apply_manual_unwatched_item_state_db(
                            connection, episode, source_server, state_index
                        )

    return watched_list


def compare_media_items(
    media1: MediaItem,
    media2: MediaItem,
    settings: AppSettings,
    average_time: float,
) -> Ord:
    logger.trace(
        "Comparing the following media items:"
        f"\n'{media1.identifiers}' (completed={media1.status.completed}, time={media1.status.time}, viewed_date={media1.status.viewed_date})"
        f"\n'{media2.identifiers}' (completed={media2.status.completed}, time={media2.status.time}, viewed_date={media2.status.viewed_date})"
    )

    media1_viewed_date, media2_viewed_date = (
        to_aware_utc(media1.status.viewed_date),
        to_aware_utc(media2.status.viewed_date),
    )

    # A manual unwatched transition is an explicit user action and must win
    # over stale watched or partial-progress state. A watched state restored
    # by the user is propagated through pending_sync and is not marked as a
    # manual-unwatched transition, so it can still become the new baseline.
    # Exception: if the other (not manually-unwatched) item became completed
    # on its own server AFTER the manual-unwatch happened (comparing the
    # persisted state_changed_at/manual_unwatched_at timestamps, not a
    # transient single-cycle flag), that's a fresh, deliberate rewatch that
    # postdates the unwatch action and must be allowed to override the stale
    # manual-unwatched marker rather than being silently reverted forever.
    if media1.status.manually_unwatched != media2.status.manually_unwatched:
        unwatched_media = media1 if media1.status.manually_unwatched else media2
        other_media = media2 if media1.status.manually_unwatched else media1
        other_state_changed_at = to_aware_utc(other_media.status.state_changed_at)
        unwatched_manual_unwatched_at = to_aware_utc(
            unwatched_media.status.manual_unwatched_at
        )
        rewatch_overrides = bool(
            other_media.status.completed
            and other_state_changed_at is not None
            and unwatched_manual_unwatched_at is not None
            and other_state_changed_at > unwatched_manual_unwatched_at
        )
        logger.trace(
            "Manual-unwatched priority check: "
            f"other.completed={other_media.status.completed}, "
            f"other.state_changed_at={other_state_changed_at}, "
            f"unwatched.manual_unwatched_at={unwatched_manual_unwatched_at}, "
            f"rewatch_overrides={rewatch_overrides}"
        )
        if not rewatch_overrides:
            return (
                Ord.A_BETTER
                if media1.status.manually_unwatched
                else Ord.B_BETTER
            )

    # An unknown incomplete item may have a newly generated viewed date.
    # Completion must take priority unless the item is explicitly manually unwatched.
    if media1.status.completed != media2.status.completed:
        incomplete = media2 if media1.status.completed else media1
        if incomplete.status.time == 0:
            return Ord.A_BETTER if media1.status.completed else Ord.B_BETTER

    # If both are completed, it's a tie.
    if media1.status.completed and media2.status.completed:
        logger.trace("Both media items are completed. Considering it a tie.")
        return Ord.TIE

    # If both are not completed, but their time is within 10 seconds, it's also a tie.
    if (not media1.status.completed and not media2.status.completed) and abs(
        media1.status.time - media2.status.time
    ) <= 10 * 1_000:
        logger.trace(
            "Both media items are not completed but their time is within 10 seconds. Considering it a tie."
        )
        return Ord.TIE

    # If both have viewed dates, compare them. If they are close enough, consider it a tie.
    if media1_viewed_date and media2_viewed_date:
        # Define threshold time as 25% above the average time plus sleep duration to account for minor discrepancies in viewing times.
        threshold_time = (average_time * 1.25) + float(settings.sleep_duration)
        # If not within threshold_time of each other, choose the more recent one as better.
        if (
            abs((media1_viewed_date - media2_viewed_date).total_seconds())
            > threshold_time
        ):
            logger.trace(
                f"Both media items have viewed dates that are more than {threshold_time} seconds apart. Chosing the more recent one as better."
            )

            return (
                Ord.A_BETTER
                if media1_viewed_date > media2_viewed_date
                else Ord.B_BETTER
            )

    # If one is completed and the other isn't, the completed one is better.
    if media1.status.completed != media2.status.completed:
        logger.trace(
            "One media item is completed while the other is not. Choosing the completed one as better."
        )
        return Ord.A_BETTER if media1.status.completed else Ord.B_BETTER

    # If both are not completed, compare their time. The one with the higher time is better.
    if media1.status.time != media2.status.time:
        logger.trace(
            "Both media items are not completed but have different times. Choosing the one with the higher time as better."
        )
        return Ord.A_BETTER if media1.status.time > media2.status.time else Ord.B_BETTER

    # If we can't determine a clear winner based on the above criteria, consider it a tie.
    logger.trace(
        "Unable to determine a clear winner based on watched status. Considering it a tie."
    )
    return Ord.TIE


def merge_mediaitem_data(
    media1: MediaItem,
    media2: MediaItem,
    settings: AppSettings,
    average_time: float,
) -> MediaItem:
    """
    Merge two MediaItem episodes by comparing their watched status.
    If one is completed while the other isn't, choose the completed one.
    If both are completed or both are not, choose the one with the higher time.
    """

    ord_ = compare_media_items(media1, media2, settings, average_time)
    return media1 if ord_ in (Ord.A_BETTER, Ord.TIE) else media2


def merge_series_data(
    series1: Series, series2: Series, settings: AppSettings, average_time: float
) -> Series:
    """
    Merge two Series objects by combining their episodes.
    For duplicate episodes (determined by check_same_identifiers), merge their watched status.
    """
    merged_series = copy.deepcopy(series1)
    for ep in series2.episodes:
        for idx, merged_ep in enumerate(merged_series.episodes):
            if check_same_identifiers(ep.identifiers, merged_ep.identifiers):
                merged_series.episodes[idx] = merge_mediaitem_data(
                    merged_ep, ep, settings, average_time
                )
                break
        else:
            merged_series.episodes.append(copy.deepcopy(ep))
    return merged_series


def merge_library_data(
    lib1: LibraryData,
    lib2: LibraryData,
    settings: AppSettings,
    average_time: float,
) -> LibraryData:
    """
    Merge two LibraryData objects by extending movies and merging series.
    For series, duplicates are determined using check_same_identifiers.
    """
    merged = copy.deepcopy(lib1)

    # Merge movies.
    for movie in lib2.movies:
        for idx, merged_movie in enumerate(merged.movies):
            if check_same_identifiers(movie.identifiers, merged_movie.identifiers):
                merged.movies[idx] = merge_mediaitem_data(
                    merged_movie, movie, settings, average_time
                )
                break
        else:
            merged.movies.append(copy.deepcopy(movie))

    # Merge series.
    for series2 in lib2.series:
        for idx, series1 in enumerate(merged.series):
            if check_same_identifiers(series1.identifiers, series2.identifiers):
                merged.series[idx] = merge_series_data(
                    series1, series2, settings, average_time
                )
                break
        else:
            merged.series.append(copy.deepcopy(series2))

    return merged


def merge_destination_watched(
    watched_list: dict[str, UserData],
    outcomes: list[WatchedWriteOutcome],
    settings: AppSettings,
    average_time: float,
) -> dict[str, UserData]:
    """Merge confirmed writes into the cache using destination-native names.

    Adapter receipts already identify the concrete user and library that were
    written. They must be merged against the cache for that same destination;
    translating them through the source server can credit a write to an
    unrelated identity. A receipt for an identity absent from the cache is
    ignored because it cannot be safely associated with the snapshot.
    """
    merged_watched = copy.deepcopy(watched_list)
    user_keys = {normalize_name(key): key for key in merged_watched}

    for outcome in outcomes:
        if outcome.status != "applied":
            continue

        user_key = user_keys.get(normalize_name(outcome.target_user))
        if user_key is None:
            logger.warning(
                "Skipping confirmed watched receipt for unknown destination user {}",
                outcome.target_user,
            )
            continue

        library_keys = {
            normalize_name(key): key
            for key in merged_watched[user_key].libraries
        }
        library_key = library_keys.get(normalize_name(outcome.target_library))
        if library_key is None:
            logger.warning(
                "Skipping confirmed watched receipt for unknown destination "
                "library {} for user {}",
                outcome.target_library,
                outcome.target_user,
            )
            continue

        receipt_library = LibraryData(title=library_key)
        if outcome.series_identifiers is None:
            receipt_library.movies.append(copy.deepcopy(outcome.media_item))
        else:
            receipt_library.series.append(
                Series(
                    identifiers=copy.deepcopy(outcome.series_identifiers),
                    episodes=[copy.deepcopy(outcome.media_item)],
                )
            )

        merged_watched[user_key].libraries[library_key] = merge_library_data(
            merged_watched[user_key].libraries[library_key],
            receipt_library,
            settings,
            average_time,
        )

    return merged_watched


def _coalesce_watched_updates(
    pending_updates: list[WatchedUpdate],
    settings: AppSettings,
    average_time: float,
) -> list[WatchedUpdate]:
    """Combine competing updates that target the same user and library.

    Fan-in mappings can produce several source updates for one concrete
    destination. Sort each group by its source identity before merging so
    equal states are resolved consistently, regardless of source traversal
    order. Duplicate media items are then reduced with the normal watched
    state comparison while distinct items remain in the combined update.
    """
    grouped: dict[tuple[str, str], list[WatchedUpdate]] = {}
    for update in pending_updates:
        destination = (
            normalize_name(update.target_user),
            normalize_name(update.target_library),
        )
        grouped.setdefault(destination, []).append(update)

    coalesced: list[WatchedUpdate] = []
    for destination in sorted(grouped):
        updates = sorted(
            grouped[destination],
            key=lambda update: (
                normalize_name(update.source_user),
                normalize_name(update.source_library),
            ),
        )
        first = updates[0]
        library_data = first.library_data
        for update in updates[1:]:
            library_data = merge_library_data(
                library_data,
                update.library_data,
                settings,
                average_time,
            )

        coalesced.append(
            WatchedUpdate(
                source_user=first.source_user,
                target_user=first.target_user,
                source_library=first.source_library,
                target_library=first.target_library,
                library_data=library_data,
            )
        )

    return coalesced


def find_target_user_keys(
    settings: AppSettings,
    source_server: str,
    source_user: str,
    target_server: str,
    target_watched: dict[str, Any],
) -> list[str]:
    """
    Find every key in `target_watched` that corresponds to `source_user` (as
    known on `source_server`) on `target_server`.

    Resolves candidate target usernames via settings.sync_targets_for_user
    (which handles explicit user_mappings aliases plus the implicit
    same-username fallback) and returns *every* candidate that is actually
    present as a key in `target_watched`. A single source user may fan out
    to multiple target users (e.g. a shared family Plex account mapping to
    several individual Jellyfin users), so this returns a list. Matching uses
    the shared case-folded name normalization.
    """
    matched: list[str] = []
    target_keys = {normalize_name(key): key for key in target_watched}
    for target in settings.sync_targets_for_user(
        source_server, source_user, target_server
    ):
        target_key = target if target in target_watched else target_keys.get(
            normalize_name(target)
        )
        if target_key is not None:
            matched.append(target_key)
    return matched


def find_target_library_keys(
    settings: AppSettings,
    source_server: str,
    source_library: str,
    target_server: str,
    target_libraries: dict[str, Any],
) -> list[str]:
    """
    Library counterpart of find_target_user_keys. Resolves candidate target
    library names via settings.sync_targets_for_library and returns every one
    present in `target_libraries` (libraries can fan out too).
    """
    matched: list[str] = []
    target_keys = {normalize_name(key): key for key in target_libraries}
    for target in settings.sync_targets_for_library(
        source_server, source_library, target_server
    ):
        target_key = target if target in target_libraries else target_keys.get(
            normalize_name(target)
        )
        if target_key is not None:
            matched.append(target_key)
    return matched


def merge_server_watched(
    watched_list_1: dict[str, UserData],
    watched_list_2: dict[str, UserData],
    server_1_name: str,
    server_2_name: str,
    settings: AppSettings,
    average_time: float,
) -> dict[str, UserData]:
    """
    Merge two dictionaries of UserData while taking into account possible
    differences in user and library keys.

    User/library correspondence between the two servers is resolved through
    the settings model (sync_targets_for_user / sync_targets_for_library),
    so explicit mappings and the implicit same-name fallback are both
    handled. server_1 / server_2 supply the configured server names that the
    settings lookups key off of.
    """
    merged_watched = copy.deepcopy(watched_list_1)

    for user_2, user_data in watched_list_2.items():
        # A server_2 user may correspond to multiple server_1 users
        # (fan-out). Merge this user's data into every matching server_1 key.
        user_keys = find_target_user_keys(
            settings, server_2_name, user_2, server_1_name, merged_watched
        )
        if not user_keys:
            merged_watched[user_2] = copy.deepcopy(user_data)
            continue

        for user_key in user_keys:
            for lib_key, lib_data in user_data.libraries.items():
                mapped_lib_keys = find_target_library_keys(
                    settings,
                    server_2_name,
                    lib_key,
                    server_1_name,
                    merged_watched[user_key].libraries,
                )
                if not mapped_lib_keys:
                    merged_watched[user_key].libraries[lib_key] = copy.deepcopy(
                        lib_data
                    )
                else:
                    for mapped_lib_key in mapped_lib_keys:
                        merged_watched[user_key].libraries[mapped_lib_key] = (
                            merge_library_data(
                                merged_watched[user_key].libraries[mapped_lib_key],
                                lib_data,
                                settings,
                                average_time,
                            )
                        )

    return merged_watched


def media_identifier_keys(item: MediaIdentifiers) -> frozenset[tuple[str, str]]:
    """Return namespaced matching keys; titles are never identity evidence."""
    keys = {("location", location) for location in item.locations}
    for provider, value in (
        ("imdb", item.imdb_id),
        ("tvdb", item.tvdb_id),
        ("tmdb", item.tmdb_id),
    ):
        if value:
            keys.add((provider, value))
    return frozenset(keys) | item.matching_aliases


def check_same_identifiers(item1: MediaIdentifiers, item2: MediaIdentifiers) -> bool:
    return not media_identifier_keys(item1).isdisjoint(media_identifier_keys(item2))


def check_remove_entry(
    item1: MediaItem,
    item2: MediaItem,
    settings: AppSettings,
    average_time: float,
) -> bool:
    """
    Returns True if item1 (from watched_list_1) should be removed
    in favor of item2 (from watched_list_2)
    """
    if not check_same_identifiers(item1.identifiers, item2.identifiers):
        return False

    # Services commonly return never-played items as incomplete with a
    # synthetic current timestamp. Without an explicit manual-unwatched
    # transition, that observation must not remove a real watched or partial
    # state from the other server.
    if (
        not item2.status.completed
        and item2.status.manual_unwatched_at is None
        and item2.status.time == 0
    ):
        return False

    # A fresh zero-progress observation is not an authoritative state. If
    # item2 has meaningful progress, remove the unknown item1 candidate
    # instead of letting its synthetic current timestamp win the comparison.
    if (
        not item1.status.completed
        and item1.status.manual_unwatched_at is None
        and item1.status.time == 0
        and (item2.status.completed or item2.status.time > 0)
    ):
        logger.trace(
            "check_remove_entry: treating item1 as unknown/never-played "
            f"(no manual_unwatched_at) and removing it in favor of item2. "
            f"item1='{item1.identifiers}' (completed={item1.status.completed}, time={item1.status.time}, manual_unwatched_at={item1.status.manual_unwatched_at}), "
            f"item2='{item2.identifiers}' (completed={item2.status.completed}, time={item2.status.time})"
        )
        return True

    # Removal policy for cleanup: drop item1 if item2 is as-good-or-better.
    return compare_media_items(item1, item2, settings, average_time) in (
        Ord.B_BETTER,
        Ord.TIE,
    )


def filter_library_watched(
    source_library: LibraryData,
    target_library: LibraryData | None,
    settings: AppSettings,
    average_time: float,
) -> LibraryData:
    """Copy source items whose state is better than the matching destination."""
    target_movies = target_library.movies if target_library else []
    target_series_list = target_library.series if target_library else []

    filtered_movies = []
    for movie in source_library.movies:
        if any(
            check_remove_entry(movie, target_movie, settings, average_time)
            for target_movie in target_movies
        ):
            logger.trace(
                f"Removing movie '{movie.identifiers.title}' for "
                f"library {target_library.title if target_library else source_library.title}"
            )
        else:
            filtered_movies.append(copy.deepcopy(movie))

    filtered_series_list: list[Series] = []
    for source_series in source_library.series:
        matching_episodes: list[MediaItem] = []
        for target_series in target_series_list:
            if check_same_identifiers(
                source_series.identifiers, target_series.identifiers
            ):
                matching_episodes.extend(target_series.episodes)

        if not matching_episodes:
            filtered_series_list.append(copy.deepcopy(source_series))
            continue

        filtered_episodes = []
        for source_episode in source_series.episodes:
            if any(
                check_remove_entry(
                    source_episode,
                    target_episode,
                    settings,
                    average_time,
                )
                for target_episode in matching_episodes
            ):
                logger.trace(
                    f"Removing episode '{source_episode.identifiers.title}' "
                    f"from show '{source_series.identifiers.title}' for "
                    f"library {target_library.title if target_library else source_library.title}"
                )
            else:
                filtered_episodes.append(copy.deepcopy(source_episode))

        if filtered_episodes:
            filtered_series = copy.deepcopy(source_series)
            filtered_series.episodes = filtered_episodes
            filtered_series_list.append(filtered_series)
        else:
            logger.trace(
                f"Removing entire show '{source_series.identifiers.title}' "
                f"in library {target_library.title if target_library else source_library.title}"
            )

    return LibraryData(
        title=source_library.title,
        library_type=source_library.library_type,
        movies=filtered_movies,
        series=filtered_series_list,
    )


def cleanup_watched(
    watched_list_1: dict[str, UserData],
    watched_list_2: dict[str, UserData],
    server_1_name: str,
    server_2_name: str,
    settings: AppSettings,
    average_time: float,
    *,
    require_destination_scope: bool = False,
) -> list[WatchedUpdate]:
    """Return pending updates with comparisons scoped to each destination.

    A source user or library can fan out to several destinations. Each
    destination gets its own comparison against its own watched history, so
    one destination having an item does not suppress the update for another.
    """
    pending_updates: list[WatchedUpdate] = []

    for update in expand_watched_updates(
        watched_list_1,
        server_1_name,
        server_2_name,
        settings,
    ):
        target_user_data = _lookup_named(watched_list_2, update.target_user)
        target_library = (
            _lookup_named(target_user_data.libraries, update.target_library)
            if target_user_data is not None
            else None
        )

        # Global fetches omit unknown/failed scopes; never treat these as empty.
        if require_destination_scope and target_library is None:
            continue

        if not settings.should_sync_scope(
            update.source_user,
            update.source_library,
            server_1_name,
            server_2_name,
            library_type=update.library_data.library_type,
            target_library_type=target_library.library_type if target_library else None,
        ):
            continue

        filtered = filter_library_watched(
            update.library_data, target_library, settings, average_time
        )
        if filtered.movies or filtered.series:
            pending_updates.append(
                WatchedUpdate(
                    source_user=update.source_user,
                    target_user=update.target_user,
                    source_library=update.source_library,
                    target_library=update.target_library,
                    library_data=filtered,
                )
            )

    return _coalesce_watched_updates(pending_updates, settings, average_time)
