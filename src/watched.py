import copy
import json
import os
import sqlite3
from datetime import datetime, timezone
from enum import IntEnum
from pydantic import BaseModel, Field
from loguru import logger
from typing import Any

from src.functions import search_mapping, to_aware_utc, get_env_value


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


class WatchedStatus(BaseModel):
    completed: bool
    time: int
    viewed_date: datetime
    manually_unwatched: bool = False


class MediaItem(BaseModel):
    identifiers: MediaIdentifiers
    status: WatchedStatus


class Series(BaseModel):
    identifiers: MediaIdentifiers
    episodes: list[MediaItem] = Field(default_factory=list)


class LibraryData(BaseModel):
    title: str
    movies: list[MediaItem] = Field(default_factory=list)
    series: list[Series] = Field(default_factory=list)


class UserData(BaseModel):
    libraries: dict[str, LibraryData] = Field(default_factory=dict)


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
    cached_keys = env.get("_watched_state_keys")
    if isinstance(cached_keys, set):
        source_server = str(env.get("_watched_state_source", ""))
        exact_key = mediaitem_state_key(item, source_server)
        if exact_key in cached_keys:
            return True
        for state_key in cached_keys:
            try:
                if (
                    f'"source_server": "{source_server}"' in state_key
                    and _identities_match(item, json.loads(state_key))
                ):
                    return True
            except json.JSONDecodeError:
                continue
        return False

    db_path = initialize_watched_state_db(env)
    with sqlite3.connect(db_path) as connection:
        row = connection.execute(
            "SELECT completed FROM media_state WHERE state_key = ?",
            (mediaitem_state_key(item, str(env.get("_watched_state_source", ""))),),
        ).fetchone()
    return bool(row and row[0])


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


def _find_state_row(
    connection: sqlite3.Connection,
    item: MediaItem,
    source_server: str | None,
) -> tuple | None:
    rows = connection.execute(
        """
        SELECT state_key, completed, resume_ms, state_changed_at,
               manual_unwatched_at
        FROM media_state
        WHERE state_key LIKE ?
        """,
        (
            f'%"source_server": "{source_server or ""}"%',
        ),
    ).fetchall()
    for row in rows:
        try:
            if _identities_match(item, json.loads(row[0])):
                return row
        except json.JSONDecodeError:
            continue
    legacy_rows = connection.execute(
            """
            SELECT state_key, completed, resume_ms, state_changed_at,
                   manual_unwatched_at
            FROM media_state
            WHERE state_key NOT LIKE '%"source_server":%'
            """
    ).fetchall()
    for row in legacy_rows:
        try:
            if _identities_match(item, json.loads(row[0])):
                return row
        except json.JSONDecodeError:
            continue
    return None


def _apply_manual_unwatched_item_state_db(
    connection: sqlite3.Connection,
    item: MediaItem,
    source_server: str | None,
) -> None:
    key = mediaitem_state_key(item, source_server)
    previous = _find_state_row(connection, item, source_server)
    state_key = previous[0] if previous else key
    now = datetime.now(timezone.utc)
    manual_unwatched_at = None
    pending = None
    pending_key = None
    for candidate in connection.execute(
        """
        SELECT state_key, expected_completed, expected_resume_ms
        FROM pending_sync
        WHERE destination_server = ?
        """,
        (source_server or "",),
    ).fetchall():
        try:
            if _identities_match(item, json.loads(candidate[0])):
                pending_key = candidate[0]
                pending = candidate[1:]
                break
        except json.JSONDecodeError:
            continue
    pending_matches = bool(
        pending
        and bool(pending[0]) == item.status.completed
        and abs(pending[1] - item.status.time) <= 10_000
    )

    if (
        previous
        and previous[3]
        and not item.status.completed
        and item.status.time <= 10_000
        and not pending_matches
    ):
        item.status.time = 0
        item.status.manually_unwatched = True

    if (
        previous
        and bool(previous[0])
        and not item.status.completed
        and item.status.time <= 10_000
        and not pending_matches
    ):
        item.status.viewed_date = now
        item.status.time = 0
        item.status.manually_unwatched = True
        manual_unwatched_at = now.isoformat()
    elif item.status.manually_unwatched:
        manual_unwatched_at = previous[3] if previous else now.isoformat()

    state_changed_at = (
        now.isoformat()
        if not previous
        or bool(previous[0]) != item.status.completed
        or abs(previous[1] - item.status.time) > 10_000
        else previous[2]
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
    if pending_matches:
        connection.execute(
            """
            DELETE FROM pending_sync
            WHERE state_key = ? AND destination_server = ?
            """,
            (pending_key or mediaitem_identity_key(item), source_server or ""),
        )


def record_pending_sync(
    env: dict[str, str | float | None],
    item: MediaItem,
    destination_server: str,
    destination_item: MediaItem | None = None,
) -> None:
    """Record a state written by this process for destination confirmation."""
    db_path = initialize_watched_state_db(env)
    with sqlite3.connect(db_path) as connection:
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
                mediaitem_identity_key(destination_item or item),
                destination_server,
                int(item.status.completed),
                item.status.time,
                datetime.now(timezone.utc).isoformat(),
            ),
        )


def apply_manual_unwatched_state(
    watched_list: dict[str, UserData],
    env: dict[str, str | float | None],
    source_server: str | None = None,
) -> dict[str, UserData]:
    db_path = initialize_watched_state_db(env)

    with sqlite3.connect(db_path) as connection:
        for user_data in watched_list.values():
            for library_data in user_data.libraries.values():
                for movie in library_data.movies:
                    _apply_manual_unwatched_item_state_db(
                        connection, movie, source_server
                    )

                for series in library_data.series:
                    for episode in series.episodes:
                        _apply_manual_unwatched_item_state_db(
                            connection, episode, source_server
                        )

    return watched_list


def compare_media_items(
    media1: MediaItem, media2: MediaItem, env: dict[str, str | float | None]
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
    if media1.status.manually_unwatched != media2.status.manually_unwatched:
        return (
            Ord.A_BETTER
            if media1.status.manually_unwatched
            else Ord.B_BETTER
        )

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
        threshold_time = (
            float(get_env_value(env, "AVERAGE_TIME", "100.0")) * 1.25
        ) + float(get_env_value(env, "SLEEP_DURATION", "5.0"))
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
    media1: MediaItem, media2: MediaItem, env: dict[str, str | float | None]
) -> MediaItem:
    """
    Merge two MediaItem episodes by comparing their watched status.
    If one is completed while the other isn't, choose the completed one.
    If both are completed or both are not, choose the one with the higher time.
    """

    ord_ = compare_media_items(media1, media2, env)
    return media1 if ord_ in (Ord.A_BETTER, Ord.TIE) else media2


def merge_series_data(
    series1: Series, series2: Series, env: dict[str, str | float | None]
) -> Series:
    """
    Merge two Series objects by combining their episodes.
    For duplicate episodes (determined by check_same_identifiers), merge their watched status.
    """
    merged_series = copy.deepcopy(series1)
    for ep in series2.episodes:
        for idx, merged_ep in enumerate(merged_series.episodes):
            if check_same_identifiers(ep.identifiers, merged_ep.identifiers):
                merged_series.episodes[idx] = merge_mediaitem_data(merged_ep, ep, env)
                break
        else:
            merged_series.episodes.append(copy.deepcopy(ep))
    return merged_series


def merge_library_data(
    lib1: LibraryData, lib2: LibraryData, env: dict[str, str | float | None]
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
                merged.movies[idx] = merge_mediaitem_data(merged_movie, movie, env)
                break
        else:
            merged.movies.append(copy.deepcopy(movie))

    # Merge series.
    for series2 in lib2.series:
        for idx, series1 in enumerate(merged.series):
            if check_same_identifiers(series1.identifiers, series2.identifiers):
                merged.series[idx] = merge_series_data(series1, series2, env)
                break
        else:
            merged.series.append(copy.deepcopy(series2))

    return merged


def merge_user_data(
    user1: UserData, user2: UserData, env: dict[str, str | float | None]
) -> UserData:
    """
    Merge two UserData objects by merging their libraries.
    If a library exists in both, merge its content; otherwise, add the new library.
    """
    merged_libraries = copy.deepcopy(user1.libraries)
    for lib_key, lib_data in user2.libraries.items():
        if lib_key in merged_libraries:
            merged_libraries[lib_key] = merge_library_data(
                merged_libraries[lib_key], lib_data, env
            )
        else:
            merged_libraries[lib_key] = copy.deepcopy(lib_data)
    return UserData(libraries=merged_libraries)


def merge_server_watched(
    watched_list_1: dict[str, UserData],
    watched_list_2: dict[str, UserData],
    env: dict[str, str | float | None],
    user_mapping: dict[str, str] | None = None,
    library_mapping: dict[str, str] | None = None,
) -> dict[str, UserData]:
    """
    Merge two dictionaries of UserData while taking into account possible
    differences in user and library keys via the provided mappings.
    """
    merged_watched = copy.deepcopy(watched_list_1)

    for user_2, user_data in watched_list_2.items():
        # Determine matching user key.
        user_key = user_mapping.get(user_2, user_2) if user_mapping else user_2
        if user_key not in merged_watched:
            merged_watched[user_2] = copy.deepcopy(user_data)
            continue

        for lib_key, lib_data in user_data.libraries.items():
            mapped_lib_key = (
                library_mapping.get(lib_key, lib_key) if library_mapping else lib_key
            )
            if mapped_lib_key not in merged_watched[user_key].libraries:
                merged_watched[user_key].libraries[lib_key] = copy.deepcopy(lib_data)
            else:
                merged_watched[user_key].libraries[mapped_lib_key] = merge_library_data(
                    merged_watched[user_key].libraries[mapped_lib_key],
                    lib_data,
                    env,
                )

    return merged_watched


def check_same_identifiers(item1: MediaIdentifiers, item2: MediaIdentifiers) -> bool:
    # Check for duplicate based on file locations:
    if item1.locations and item2.locations:
        if set(item1.locations) & set(item2.locations):
            return True

    # Check for duplicate based on GUIDs:
    if (
        (item1.imdb_id and item2.imdb_id and item1.imdb_id == item2.imdb_id)
        or (item1.tvdb_id and item2.tvdb_id and item1.tvdb_id == item2.tvdb_id)
        or (item1.tmdb_id and item2.tmdb_id and item1.tmdb_id == item2.tmdb_id)
    ):
        return True

    return False


def check_remove_entry(
    item1: MediaItem, item2: MediaItem, env: dict[str, str | float | None]
) -> bool:
    """
    Returns True if item1 (from watched_list_1) should be removed
    in favor of item2 (from watched_list_2)
    """
    if not check_same_identifiers(item1.identifiers, item2.identifiers):
        return False

    # Removal policy for cleanup: drop item1 if item2 is as-good-or-better.
    return compare_media_items(item1, item2, env) in (Ord.B_BETTER, Ord.TIE)


def cleanup_watched(
    watched_list_1: dict[str, UserData],
    watched_list_2: dict[str, UserData],
    env: dict[str, str | float | None],
    user_mapping: dict[str, str] | None = None,
    library_mapping: dict[str, str] | None = None,
) -> dict[str, UserData]:
    modified_watched_list_1 = copy.deepcopy(watched_list_1)

    # remove entries from watched_list_1 that are in watched_list_2
    for user_1 in watched_list_1:
        user_other = None
        if user_mapping:
            user_other = search_mapping(user_mapping, user_1)
        user_2 = get_other(watched_list_2, user_1, user_other)
        if user_2 is None:
            continue

        for library_1_key in watched_list_1[user_1].libraries:
            library_other = None
            if library_mapping:
                library_other = search_mapping(library_mapping, library_1_key)
            library_2_key = get_other(
                watched_list_2[user_2].libraries, library_1_key, library_other
            )
            if library_2_key is None:
                continue

            library_1 = watched_list_1[user_1].libraries[library_1_key]
            library_2 = watched_list_2[user_2].libraries[library_2_key]

            filtered_movies = []
            for movie in library_1.movies:
                remove_flag = False
                for movie2 in library_2.movies:
                    if check_remove_entry(movie, movie2, env):
                        logger.trace(f"Removing movie: {movie.identifiers.title}")
                        remove_flag = True
                        break

                if not remove_flag:
                    filtered_movies.append(movie)

            modified_watched_list_1[user_1].libraries[
                library_1_key
            ].movies = filtered_movies

            # TV Shows
            filtered_series_list = []
            for series1 in library_1.series:
                matching_series = None
                for series2 in library_2.series:
                    if check_same_identifiers(series1.identifiers, series2.identifiers):
                        matching_series = series2
                        break

                if matching_series is None:
                    # No matching show in watched_list_2; keep the series as is.
                    filtered_series_list.append(series1)
                else:
                    # We have a matching show; now clean up the episodes.
                    filtered_episodes = []
                    for ep1 in series1.episodes:
                        remove_flag = False
                        for ep2 in matching_series.episodes:
                            if check_remove_entry(ep1, ep2, env):
                                logger.trace(
                                    f"Removing episode '{ep1.identifiers.title}' from show '{series1.identifiers.title}'",
                                )
                                remove_flag = True
                                break
                        if not remove_flag:
                            filtered_episodes.append(ep1)

                    # Only keep the series if there are remaining episodes.
                    if filtered_episodes:
                        modified_series1 = copy.deepcopy(series1)
                        modified_series1.episodes = filtered_episodes
                        filtered_series_list.append(modified_series1)
                    else:
                        logger.trace(
                            f"Removing entire show '{series1.identifiers.title}' as no episodes remain after cleanup.",
                        )
            modified_watched_list_1[user_1].libraries[
                library_1_key
            ].series = filtered_series_list

    # After processing, remove any library that is completely empty.
    for user, user_data in modified_watched_list_1.items():
        new_libraries = {}
        for lib_key, library in user_data.libraries.items():
            if library.movies or library.series:
                new_libraries[lib_key] = library
            else:
                logger.trace(f"Removing empty library '{lib_key}' for user '{user}'")
        user_data.libraries = new_libraries

    return modified_watched_list_1


def get_other(
    watched_list: dict[str, Any], object_1: str, object_2: str | None
) -> str | None:
    if object_1 in watched_list:
        return object_1

    if object_2 and object_2 in watched_list:
        return object_2

    logger.info(
        f"{object_1}{' and ' + object_2 if object_2 else ''} not found in watched list 2"
    )

    return None
