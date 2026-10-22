from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock

from conftest import settings_override
from src import plex as plex_module
from src.settings import PlexSettings
from src.watched import LibraryData, MediaIdentifiers, MediaItem, WatchedStatus


class _Account:
    def __init__(self, users: list[object] | None = None) -> None:
        self._users = users or []

    def users(self) -> list[object]:
        return list(self._users)


class _PlexServer:
    def __init__(self, *_args: object, **_kwargs: object) -> None:
        self._baseurl = "http://plex"
        self.account = _Account()

    def myPlexAccount(self) -> _Account:
        return self.account


def _server_settings(**overrides: object) -> PlexSettings:
    return PlexSettings(
        name="plex-shared",
        baseurl="http://plex",
        token="server-token",
        **overrides,
    )


def test_uses_account_token_for_shared_server_account_apis(monkeypatch) -> None:
    account = _Account()
    account_calls: list[dict[str, object]] = []

    def create_account(**kwargs: object) -> _Account:
        account_calls.append(kwargs)
        return account

    monkeypatch.setattr(plex_module, "PlexServer", _PlexServer)
    monkeypatch.setattr(plex_module, "MyPlexAccount", create_account)

    adapter = plex_module.Plex(
        app_settings=settings_override(),
        server_settings=_server_settings(account_token="account-token"),
    )

    assert account_calls == [{"token": "account-token"}]
    assert adapter.admin_user is account
    assert adapter.users == [account]


def test_uses_server_token_for_account_apis_by_default(monkeypatch) -> None:
    monkeypatch.setattr(plex_module, "PlexServer", _PlexServer)

    adapter = plex_module.Plex(
        app_settings=settings_override(),
        server_settings=_server_settings(),
    )

    assert adapter.admin_user is adapter.plex.account
    assert adapter.users == [adapter.admin_user]


def test_catalog_scoped_movie_fetch_looks_up_only_catalog_identities(monkeypatch) -> None:
    settings = settings_override()
    adapter = object.__new__(plex_module.Plex)
    adapter.app_settings = settings
    adapter.server_settings = SimpleNamespace(name="plex-test")
    section = Mock()
    candidate = SimpleNamespace(
        title="Adventure Time",
        guids=[SimpleNamespace(id="tmdb://123")],
        locations=["/media/Adventure Time.mkv"],
        lastViewedAt=None,
        viewOffset=0,
        isWatched=True,
        ratingKey="movie-1",
        key="/library/metadata/movie-1",
    )
    section.search.side_effect = lambda **kwargs: (
        [candidate] if kwargs.get("guid") == "tmdb://123" else []
    )
    user_plex = SimpleNamespace(
        library=SimpleNamespace(section=Mock(return_value=section))
    )
    catalog = LibraryData(
        title="Movies",
        movies=[
            MediaItem(
                identifiers=MediaIdentifiers(
                    title="Adventure Time", tmdb_id="123"
                ),
                status=WatchedStatus(
                    completed=False,
                    time=0,
                    viewed_date=datetime.now(timezone.utc),
                ),
            )
        ],
    )
    monkeypatch.setattr(plex_module, "was_previously_watched", lambda *_args: False)

    result = adapter.get_user_library_watched_for_catalog(
        "alice",
        user_plex,
        SimpleNamespace(title="Movies", type="movie"),
        catalog,
    )

    assert result is not None
    assert [item.identifiers.tmdb_id for item in result.movies] == ["123"]
    assert section.search.call_args_list[0].kwargs == {
        "guid": "tmdb://123",
        "libtype": "movie",
    }
    assert section.search.call_args_list[1].kwargs == {
        "title": "Adventure Time",
        "libtype": "movie",
    }


def test_catalog_scoped_movie_fetch_keeps_unwatched_identity_baseline(monkeypatch):
    adapter = object.__new__(plex_module.Plex)
    adapter.app_settings = settings_override()
    adapter.server_settings = SimpleNamespace(name="plex-test")
    candidate = SimpleNamespace(
        title="Adventure Time",
        guids=[SimpleNamespace(id="tmdb://123"), SimpleNamespace(id="imdb://plex-id")],
        locations=["/media/Adventure Time.mkv"],
        lastViewedAt=None,
        viewOffset=0,
        isWatched=False,
        ratingKey="movie-1",
        key="/library/metadata/movie-1",
    )
    section = Mock(search=Mock(return_value=[candidate]))
    user_plex = SimpleNamespace(
        library=SimpleNamespace(section=Mock(return_value=section))
    )
    catalog = LibraryData(
        title="Movies",
        movies=[
            MediaItem(
                identifiers=MediaIdentifiers(title="Adventure Time", tmdb_id="123"),
                status=WatchedStatus(
                    completed=True,
                    time=0,
                    viewed_date=datetime.now(timezone.utc),
                ),
            )
        ],
    )
    monkeypatch.setattr(plex_module, "was_previously_watched", lambda *_args: False)

    result = adapter.get_user_library_watched_for_catalog(
        "alice",
        user_plex,
        SimpleNamespace(title="Movies", type="movie"),
        catalog,
    )

    assert result is not None
    assert len(result.movies) == 1
    assert not result.movies[0].status.completed
    assert result.movies[0].identifiers.imdb_id == "plex-id"


def test_catalog_scoped_movie_fetch_rejects_title_only_nonmatches(monkeypatch) -> None:
    adapter = object.__new__(plex_module.Plex)
    adapter.app_settings = settings_override()
    adapter.server_settings = SimpleNamespace(name="plex-test")
    candidate = SimpleNamespace(
        title="Adventure Time",
        guids=[SimpleNamespace(id="tmdb://456")],
        locations=["/media/Adventure Time (different).mkv"],
        lastViewedAt=None,
        viewOffset=0,
        isWatched=True,
        ratingKey="movie-2",
        key="/library/metadata/movie-2",
    )
    section = Mock()
    section.search.side_effect = lambda **kwargs: (
        [candidate] if "title" in kwargs else []
    )
    user_plex = SimpleNamespace(
        library=SimpleNamespace(section=Mock(return_value=section))
    )
    catalog = LibraryData(
        title="Movies",
        movies=[
            MediaItem(
                identifiers=MediaIdentifiers(
                    title="Adventure Time", tmdb_id="123"
                ),
                status=WatchedStatus(
                    completed=False,
                    time=0,
                    viewed_date=datetime.now(timezone.utc),
                ),
            )
        ],
    )
    monkeypatch.setattr(plex_module, "was_previously_watched", lambda *_args: False)

    result = adapter.get_user_library_watched_for_catalog(
        "alice",
        user_plex,
        SimpleNamespace(title="Movies", type="movie"),
        catalog,
    )

    assert result == LibraryData(title="Movies")
