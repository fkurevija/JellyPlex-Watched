"""Select the per-user libraries needed for the watched-data fetch phase."""

from dataclasses import dataclass
from typing import cast

from loguru import logger
from plexapi.myplex import MyPlexAccount, MyPlexUser

from src.emby import Emby
from src.functions import normalize_name
from src.jellyfin import Jellyfin
from src.library import combine_library_lists
from src.plex import Plex
from src.settings import AppSettings
from src.users import combine_user_lists
from src.watched import (
    STATE_ENV,
    LibraryData,
    UserData,
    apply_manual_unwatched_state,
    load_state_index,
)


type Server = Plex | Jellyfin | Emby
type ServerUser = MyPlexAccount | MyPlexUser | tuple[str, str]


@dataclass
class UserLibraries:
    user: ServerUser
    libraries: dict[str, str]  # Original library name -> server-native type.
    sizes: dict[str, int] | None = None

    @property
    def username(self) -> str:
        if isinstance(self.user, tuple):
            return normalize_name(cast(tuple[str, str], self.user)[0])
        return normalize_name(self.user.username or self.user.title)


def generate_sync_inventory(
    server_users: dict[Server, list[ServerUser]],
    settings: AppSettings,
) -> dict[Server, list[UserLibraries]]:
    """Fetch each selected user's libraries once and retain both sync ends.

    Omit empty users and servers. This inventory specifies what to fetch;
    updates must still apply directional user and library policy.
    """
    inventory: dict[Server, dict[str, UserLibraries]] = {}
    for server, users in server_users.items():
        inventory[server] = {}
        for user in users:
            try:
                if isinstance(server, Plex) and not isinstance(user, tuple):
                    libraries = server.get_user_libraries(user)
                elif isinstance(server, (Jellyfin, Emby)) and isinstance(user, tuple):
                    libraries = server.get_user_libraries(cast(tuple[str, str], user))
                else:
                    raise TypeError("User representation does not match server")
            except Exception as error:
                # Adapter errors may contain credentials; log only the error type.
                logger.warning(
                    "Skipping library discovery for user {} on {} ({})",
                    UserLibraries(user, {}).username,
                    server.server_settings.name,
                    type(error).__name__,
                )
                continue
            try:
                if isinstance(server, Plex) and not isinstance(user, tuple):
                    sizes = server.get_user_library_sizes(user)
                elif isinstance(server, (Jellyfin, Emby)) and isinstance(user, tuple):
                    sizes = server.get_user_library_sizes(
                        cast(tuple[str, str], user), libraries
                    )
                else:
                    raise TypeError("User representation does not match server")
            except Exception as error:
                logger.warning(
                    "Could not get library sizes for {} on {} ({}); "
                    "catalog scoping will be unavailable for those libraries",
                    UserLibraries(user, {}).username,
                    server.server_settings.name,
                    type(error).__name__,
                )
                sizes = {}
            entry = UserLibraries(user, libraries, sizes)
            inventory[server][entry.username] = entry

    selected: dict[Server, dict[str, set[str]]] = {
        server: {} for server in server_users
    }

    def permits(
        source: str,
        target: str,
        source_user: str,
        target_user: str,
        source_library: str,
        target_library: str,
        source_type: str,
        target_type: str,
    ) -> bool:
        return (
            settings.should_sync_scope(
                source_user,
                source_library,
                source,
                target,
                library_type=source_type,
                target_library_type=target_type,
            )
            and target_user
            in {
                normalize_name(name)
                for name in settings.sync_targets_for_user(source, source_user, target)
            }
            and normalize_name(target_library)
            in {
                normalize_name(name)
                for name in settings.sync_targets_for_library(
                    source, source_library, target
                )
            }
        )

    servers = list(server_users)
    for index, source in enumerate(servers):
        for target in servers[index + 1 :]:
            source_name = source.server_settings.name
            target_name = target.server_settings.name
            user_pairs = combine_user_lists(
                source_name,
                target_name,
                list(inventory[source]),
                list(inventory[target]),
                settings,
            )
            for source_user, target_users in user_pairs.items():
                for target_user in target_users:
                    library_pairs = combine_library_lists(
                        source_name,
                        target_name,
                        inventory[source][source_user].libraries,
                        inventory[target][target_user].libraries,
                        settings,
                    )
                    for source_library, target_libraries in library_pairs.items():
                        for target_library in target_libraries:
                            if not (
                                permits(
                                    source_name,
                                    target_name,
                                    source_user,
                                    target_user,
                                    source_library,
                                    target_library,
                                    inventory[source][source_user].libraries[
                                        source_library
                                    ],
                                    inventory[target][target_user].libraries[
                                        target_library
                                    ],
                                )
                                or permits(
                                    target_name,
                                    source_name,
                                    target_user,
                                    source_user,
                                    target_library,
                                    source_library,
                                    inventory[target][target_user].libraries[
                                        target_library
                                    ],
                                    inventory[source][source_user].libraries[
                                        source_library
                                    ],
                                )
                            ):
                                continue
                            selected[source].setdefault(source_user, set()).add(
                                source_library
                            )
                            selected[target].setdefault(target_user, set()).add(
                                target_library
                            )

    return {
        server: [
            UserLibraries(
                entry.user,
                {
                    name: kind
                    for name, kind in entry.libraries.items()
                    if name in selected[server].get(username, set())
                },
                entry.sizes,
            )
            for username, entry in users.items()
            if username in selected[server]
        ]
        for server, users in inventory.items()
        if selected[server]
    }


def fetch_watched_inventory(
    inventory: dict[Server, list[UserLibraries]],
    settings: AppSettings | None = None,
) -> dict[Server, dict[str, UserData]]:
    """Fetch watched data against the smallest catalog per matched user/library.

    Fetch each user independently so an adapter failure returning an empty
    result cannot discard data already fetched for other users on that server.
    Scopes without a reliable catalog are skipped instead of scanned broadly.
    """
    catalogs_by_server: dict[Server, dict[str, dict[str, LibraryData]]] = {}
    excluded_scopes: dict[Server, dict[str, set[str]]] = {}

    def exclude_catalog_scopes(
        scopes: list[tuple[Server, UserLibraries, str]],
    ) -> None:
        for scoped_server, scoped_entry, library_name in scopes:
            excluded_scopes.setdefault(scoped_server, {}).setdefault(
                scoped_entry.username, set()
            ).add(normalize_name(library_name))

    if settings is not None:
        groups: dict[tuple[str, str], list[tuple[Server, UserLibraries, str]]] = {}
        for server, entries in inventory.items():
            server_name = server.server_settings.name
            for entry in entries:
                canonical_user = settings.lookup_user(server_name, entry.username)
                user_key = (
                    f"mapping:{canonical_user}"
                    if canonical_user is not None
                    else f"name:{normalize_name(entry.username)}"
                )
                for library_name in entry.libraries:
                    canonical_library = settings.lookup_library(
                        server_name, library_name
                    )
                    library_key = (
                        f"mapping:{canonical_library}"
                        if canonical_library is not None
                        else f"name:{normalize_name(library_name)}"
                    )
                    groups.setdefault((user_key, library_key), []).append(
                        (server, entry, library_name)
                    )

        for (_, library_key), scopes in groups.items():
            if len(scopes) < 2:
                continue
            sized_scopes: list[tuple[tuple[Server, UserLibraries, str], int]] = []
            for scope in scopes:
                size = (scope[1].sizes or {}).get(scope[2])
                if size is not None:
                    sized_scopes.append((scope, size))
            if len(sized_scopes) != len(scopes):
                logger.warning(
                    "Skipping watched fetch for {} because one or more matching "
                    "libraries have no reliable size for catalog selection",
                    library_key,
                )
                exclude_catalog_scopes(scopes)
                continue

            (seed_server, seed_entry, seed_library), seed_size = min(
                sized_scopes,
                key=lambda scoped_size: scoped_size[1],
            )
            try:
                if isinstance(seed_server, Plex) and not isinstance(
                    seed_entry.user, tuple
                ):
                    catalog = seed_server.get_user_library_catalog(
                        seed_entry.username, seed_entry.user, seed_library
                    )
                elif isinstance(seed_server, (Jellyfin, Emby)) and isinstance(
                    seed_entry.user, tuple
                ):
                    library_type = seed_entry.libraries[seed_library]
                    if library_type == "movies":
                        catalog = seed_server.get_user_library_catalog(
                            cast(tuple[str, str], seed_entry.user),
                            seed_library,
                            "movies",
                        )
                    elif library_type == "tvshows":
                        catalog = seed_server.get_user_library_catalog(
                            cast(tuple[str, str], seed_entry.user),
                            seed_library,
                            "tvshows",
                        )
                    else:
                        raise ValueError(
                            f"Unsupported catalog library type: {library_type}"
                        )
                else:
                    raise TypeError("User representation does not match server")
            except Exception as error:
                logger.warning(
                    "Could not build catalog from {} library {} ({})",
                    seed_server.server_settings.name,
                    seed_library,
                    type(error).__name__,
                )
                catalog = None

            if catalog is None:
                logger.warning(
                    "Skipping watched fetch for {} library {} because its "
                    "catalog could not be built",
                    seed_server.server_settings.name,
                    seed_library,
                )
                exclude_catalog_scopes(scopes)
                continue

            logger.info(
                "Using smallest catalog {} ({}) for {} matched libraries",
                seed_library,
                seed_size,
                len(scopes),
            )
            for server, entry, library_name in scopes:
                catalogs_by_server.setdefault(server, {}).setdefault(
                    entry.username, {}
                )[library_name] = catalog

    servers_watched: dict[Server, dict[str, UserData]] = {}
    for server, entries in inventory.items():
        watched: dict[str, UserData] = {}
        # Adapters consult the persisted state while reading so previously
        # watched items that now read as unwatched are retained.
        state_indexes = STATE_ENV.setdefault("_watched_state_indexes", {})
        state_index = load_state_index(STATE_ENV, type(server).__name__)
        state_indexes[type(server).__name__] = state_index
        STATE_ENV["_watched_state_source"] = type(server).__name__
        STATE_ENV["_watched_state_index"] = state_index
        for entry in entries:
            if not entry.libraries:
                continue
            user = entry.user
            excluded = excluded_scopes.get(server, {}).get(entry.username, set())
            libraries_to_fetch = {
                name: kind
                for name, kind in entry.libraries.items()
                if normalize_name(name) not in excluded
            }
            if not libraries_to_fetch:
                watched[entry.username] = UserData()
                continue
            try:
                if isinstance(server, Plex) and not isinstance(user, tuple):
                    catalogs = catalogs_by_server.get(server, {}).get(entry.username)
                    if catalogs is None:
                        user_watched = server.get_watched(
                            [user], list(libraries_to_fetch)
                        )
                    else:
                        user_watched = server.get_watched(
                            [user], list(libraries_to_fetch), catalogs=catalogs
                        )
                elif isinstance(server, (Jellyfin, Emby)) and isinstance(user, tuple):
                    username, user_id = cast(tuple[str, str], user)
                    catalogs = catalogs_by_server.get(server, {}).get(entry.username)
                    if catalogs is None:
                        user_watched = server.get_watched(
                            {username: user_id},
                            list(libraries_to_fetch),
                            library_types=libraries_to_fetch,
                        )
                    else:
                        user_watched = server.get_watched(
                            {username: user_id},
                            list(libraries_to_fetch),
                            library_types=libraries_to_fetch,
                            catalogs=catalogs,
                        )
                else:
                    raise TypeError("User representation does not match server")
            except Exception as error:
                logger.warning(
                    "Skipping watched fetch for {} ({})",
                    entry.username,
                    type(error).__name__,
                )
                continue
            # Missing data is unknown, not a successfully fetched empty history.
            user_data = user_watched.get(entry.username)
            if user_data is None or not {
                normalize_name(name) for name in libraries_to_fetch
            }.issubset({normalize_name(name) for name in user_data.libraries}):
                logger.warning(
                    "Skipping incomplete watched fetch for {}", entry.username
                )
                continue
            # Retain types for the planner: a library fetched because of an
            # exception on one edge still needs normal filtering on other edges.
            library_types = {
                normalize_name(name): kind for name, kind in libraries_to_fetch.items()
            }
            watched[entry.username] = user_data.model_copy(
                update={
                    "libraries": {
                        name: library.model_copy(
                            update={
                                "library_type": library_types.get(normalize_name(name))
                            }
                        )
                        for name, library in user_data.libraries.items()
                    }
                }
            )
        STATE_ENV["_watched_state_source"] = type(server).__name__
        STATE_ENV["_watched_state_index"] = state_index
        servers_watched[server] = apply_manual_unwatched_state(
            watched, STATE_ENV, type(server).__name__
        )
    return servers_watched
