from datetime import datetime, timezone
import json
import sqlite3
import sys
import os

# getting the name of the directory
# where the this file is present.
current = os.path.dirname(os.path.realpath(__file__))

# Getting the parent directory name
# where the current directory is present.
parent = os.path.dirname(current)

# adding the parent directory to
# the sys.path.
sys.path.append(parent)

from src.watched import (
    LibraryData,
    MediaIdentifiers,
    MediaItem,
    Series,
    UserData,
    WatchedStatus,
    apply_manual_unwatched_state,
    check_remove_entry,
    cleanup_watched,
    compare_media_items,
    initialize_watched_state_db,
    load_state_index,
    was_previously_watched,
    mediaitem_state_key,
    mediaitem_identity_key,
    Ord,
    record_pending_sync,
)

viewed_date = datetime.today()

tv_shows_watched_list_1: list[Series] = [
    Series(
        identifiers=MediaIdentifiers(
            title="Doctor Who (2005)",
            locations=("Doctor Who (2005) {tvdb-78804} {imdb-tt0436992}",),
            imdb_id="tt0436992",
            tmdb_id="57243",
            tvdb_id="78804",
        ),
        episodes=[
            MediaItem(
                identifiers=MediaIdentifiers(
                    title="The Unquiet Dead",
                    locations=("S01E03.mkv",),
                    imdb_id="tt0563001",
                    tmdb_id="968589",
                    tvdb_id="295296",
                ),
                status=WatchedStatus(completed=True, time=0, viewed_date=viewed_date),
            ),
            MediaItem(
                identifiers=MediaIdentifiers(
                    title="Aliens of London (1)",
                    locations=("S01E04.mkv",),
                    imdb_id="tt0562985",
                    tmdb_id="968590",
                    tvdb_id="295297",
                ),
                status=WatchedStatus(
                    completed=False, time=240000, viewed_date=viewed_date
                ),
            ),
            MediaItem(
                identifiers=MediaIdentifiers(
                    title="World War Three (2)",
                    locations=("S01E05.mkv",),
                    imdb_id="tt0563003",
                    tmdb_id="968592",
                    tvdb_id="295298",
                ),
                status=WatchedStatus(completed=True, time=0, viewed_date=viewed_date),
            ),
        ],
    ),
    Series(
        identifiers=MediaIdentifiers(
            title="Monarch: Legacy of Monsters",
            locations=("Monarch - Legacy of Monsters {tvdb-422598} {imdb-tt17220216}",),
            imdb_id="tt17220216",
            tmdb_id="202411",
            tvdb_id="422598",
        ),
        episodes=[
            MediaItem(
                identifiers=MediaIdentifiers(
                    title="Secrets and Lies",
                    locations=("S01E03.mkv",),
                    imdb_id="tt21255044",
                    tmdb_id="4661246",
                    tvdb_id="10009418",
                ),
                status=WatchedStatus(completed=True, time=0, viewed_date=viewed_date),
            ),
            MediaItem(
                identifiers=MediaIdentifiers(
                    title="Parallels and Interiors",
                    locations=("S01E04.mkv",),
                    imdb_id="tt21255050",
                    tmdb_id="4712059",
                    tvdb_id="10009419",
                ),
                status=WatchedStatus(
                    completed=False, time=240000, viewed_date=viewed_date
                ),
            ),
            MediaItem(
                identifiers=MediaIdentifiers(
                    title="The Way Out",
                    locations=("S01E05.mkv",),
                    imdb_id="tt23787572",
                    tmdb_id="4712061",
                    tvdb_id="10009420",
                ),
                status=WatchedStatus(completed=True, time=0, viewed_date=viewed_date),
            ),
        ],
    ),
    Series(
        identifiers=MediaIdentifiers(
            title="My Adventures with Superman",
            locations=("My Adventures with Superman {tvdb-403172} {imdb-tt14681924}",),
            imdb_id="tt14681924",
            tmdb_id="125928",
            tvdb_id="403172",
        ),
        episodes=[
            MediaItem(
                identifiers=MediaIdentifiers(
                    title="Adventures of a Normal Man (1)",
                    locations=("S01E01.mkv",),
                    imdb_id="tt15699926",
                    tmdb_id="3070048",
                    tvdb_id="8438181",
                ),
                status=WatchedStatus(completed=True, time=0, viewed_date=viewed_date),
            ),
            MediaItem(
                identifiers=MediaIdentifiers(
                    title="Adventures of a Normal Man (2)",
                    locations=("S01E02.mkv",),
                    imdb_id="tt20413322",
                    tmdb_id="4568681",
                    tvdb_id="9829910",
                ),
                status=WatchedStatus(completed=True, time=0, viewed_date=viewed_date),
            ),
            MediaItem(
                identifiers=MediaIdentifiers(
                    title="My Interview with Superman",
                    locations=("S01E03.mkv",),
                    imdb_id="tt20413328",
                    tmdb_id="4497012",
                    tvdb_id="9870382",
                ),
                status=WatchedStatus(completed=True, time=0, viewed_date=viewed_date),
            ),
        ],
    ),
]

# ─────────────────────────────────────────────────────────────
# TV Shows Watched list 2

tv_shows_watched_list_2: list[Series] = [
    Series(
        identifiers=MediaIdentifiers(
            title="Doctor Who",
            locations=("Doctor Who (2005) {tvdb-78804} {imdb-tt0436992}",),
            imdb_id="tt0436992",
            tmdb_id="57243",
            tvdb_id="78804",
        ),
        episodes=[
            MediaItem(
                identifiers=MediaIdentifiers(
                    title="Rose",
                    locations=("S01E01.mkv",),
                    imdb_id="tt0562992",
                    tvdb_id="295294",
                    tmdb_id=None,
                ),
                status=WatchedStatus(completed=True, time=0, viewed_date=viewed_date),
            ),
            MediaItem(
                identifiers=MediaIdentifiers(
                    title="The End of the World",
                    locations=("S01E02.mkv",),
                    imdb_id="tt0562997",
                    tvdb_id="295295",
                    tmdb_id=None,
                ),
                status=WatchedStatus(
                    completed=False, time=300670, viewed_date=viewed_date
                ),
            ),
            MediaItem(
                identifiers=MediaIdentifiers(
                    title="World War Three (2)",
                    locations=("S01E05.mkv",),
                    imdb_id="tt0563003",
                    tvdb_id="295298",
                    tmdb_id=None,
                ),
                status=WatchedStatus(completed=True, time=0, viewed_date=viewed_date),
            ),
        ],
    ),
    Series(
        identifiers=MediaIdentifiers(
            title="Monarch: Legacy of Monsters",
            locations=("Monarch - Legacy of Monsters {tvdb-422598} {imdb-tt17220216}",),
            imdb_id="tt17220216",
            tmdb_id="202411",
            tvdb_id="422598",
        ),
        episodes=[
            MediaItem(
                identifiers=MediaIdentifiers(
                    title="Aftermath",
                    locations=("S01E01.mkv",),
                    imdb_id="tt20412166",
                    tvdb_id="9959300",
                    tmdb_id=None,
                ),
                status=WatchedStatus(completed=True, time=0, viewed_date=viewed_date),
            ),
            MediaItem(
                identifiers=MediaIdentifiers(
                    title="Departure",
                    locations=("S01E02.mkv",),
                    imdb_id="tt22866594",
                    tvdb_id="10009417",
                    tmdb_id=None,
                ),
                status=WatchedStatus(
                    completed=False, time=300741, viewed_date=viewed_date
                ),
            ),
            MediaItem(
                identifiers=MediaIdentifiers(
                    title="The Way Out",
                    locations=("S01E05.mkv",),
                    imdb_id="tt23787572",
                    tvdb_id="10009420",
                    tmdb_id=None,
                ),
                status=WatchedStatus(completed=True, time=0, viewed_date=viewed_date),
            ),
        ],
    ),
    Series(
        identifiers=MediaIdentifiers(
            title="My Adventures with Superman",
            locations=("My Adventures with Superman {tvdb-403172} {imdb-tt14681924}",),
            imdb_id="tt14681924",
            tmdb_id="125928",
            tvdb_id="403172",
        ),
        episodes=[
            MediaItem(
                identifiers=MediaIdentifiers(
                    title="Adventures of a Normal Man (1)",
                    locations=("S01E01.mkv",),
                    imdb_id="tt15699926",
                    tvdb_id="8438181",
                    tmdb_id=None,
                ),
                status=WatchedStatus(completed=True, time=0, viewed_date=viewed_date),
            ),
            MediaItem(
                identifiers=MediaIdentifiers(
                    title="Adventures of a Normal Man (2)",
                    locations=("S01E02.mkv",),
                    imdb_id="tt20413322",
                    tvdb_id="9829910",
                    tmdb_id=None,
                ),
                status=WatchedStatus(completed=True, time=0, viewed_date=viewed_date),
            ),
            MediaItem(
                identifiers=MediaIdentifiers(
                    title="My Interview with Superman",
                    locations=("S01E03.mkv",),
                    imdb_id="tt20413328",
                    tvdb_id="9870382",
                    tmdb_id=None,
                ),
                status=WatchedStatus(completed=True, time=0, viewed_date=viewed_date),
            ),
        ],
    ),
]

# ─────────────────────────────────────────────────────────────
# Expected TV Shows Watched list 1 (after cleanup)

expected_tv_show_watched_list_1: list[Series] = [
    Series(
        identifiers=MediaIdentifiers(
            title="Doctor Who (2005)",
            locations=("Doctor Who (2005) {tvdb-78804} {imdb-tt0436992}",),
            imdb_id="tt0436992",
            tmdb_id="57243",
            tvdb_id="78804",
        ),
        episodes=[
            MediaItem(
                identifiers=MediaIdentifiers(
                    title="The Unquiet Dead",
                    locations=("S01E03.mkv",),
                    imdb_id="tt0563001",
                    tmdb_id="968589",
                    tvdb_id="295296",
                ),
                status=WatchedStatus(completed=True, time=0, viewed_date=viewed_date),
            ),
            MediaItem(
                identifiers=MediaIdentifiers(
                    title="Aliens of London (1)",
                    locations=("S01E04.mkv",),
                    imdb_id="tt0562985",
                    tmdb_id="968590",
                    tvdb_id="295297",
                ),
                status=WatchedStatus(
                    completed=False, time=240000, viewed_date=viewed_date
                ),
            ),
        ],
    ),
    Series(
        identifiers=MediaIdentifiers(
            title="Monarch: Legacy of Monsters",
            locations=("Monarch - Legacy of Monsters {tvdb-422598} {imdb-tt17220216}",),
            imdb_id="tt17220216",
            tmdb_id="202411",
            tvdb_id="422598",
        ),
        episodes=[
            MediaItem(
                identifiers=MediaIdentifiers(
                    title="Secrets and Lies",
                    locations=("S01E03.mkv",),
                    imdb_id="tt21255044",
                    tmdb_id="4661246",
                    tvdb_id="10009418",
                ),
                status=WatchedStatus(completed=True, time=0, viewed_date=viewed_date),
            ),
            MediaItem(
                identifiers=MediaIdentifiers(
                    title="Parallels and Interiors",
                    locations=("S01E04.mkv",),
                    imdb_id="tt21255050",
                    tmdb_id="4712059",
                    tvdb_id="10009419",
                ),
                status=WatchedStatus(
                    completed=False, time=240000, viewed_date=viewed_date
                ),
            ),
        ],
    ),
]

# ─────────────────────────────────────────────────────────────
# Expected TV Shows Watched list 2 (after cleanup)

expected_tv_show_watched_list_2: list[Series] = [
    Series(
        identifiers=MediaIdentifiers(
            title="Doctor Who",
            locations=("Doctor Who (2005) {tvdb-78804} {imdb-tt0436992}",),
            imdb_id="tt0436992",
            tmdb_id="57243",
            tvdb_id="78804",
        ),
        episodes=[
            MediaItem(
                identifiers=MediaIdentifiers(
                    title="Rose",
                    locations=("S01E01.mkv",),
                    imdb_id="tt0562992",
                    tvdb_id="295294",
                    tmdb_id=None,
                ),
                status=WatchedStatus(completed=True, time=0, viewed_date=viewed_date),
            ),
            MediaItem(
                identifiers=MediaIdentifiers(
                    title="The End of the World",
                    locations=("S01E02.mkv",),
                    imdb_id="tt0562997",
                    tvdb_id="295295",
                    tmdb_id=None,
                ),
                status=WatchedStatus(
                    completed=False, time=300670, viewed_date=viewed_date
                ),
            ),
        ],
    ),
    Series(
        identifiers=MediaIdentifiers(
            title="Monarch: Legacy of Monsters",
            locations=("Monarch - Legacy of Monsters {tvdb-422598} {imdb-tt17220216}",),
            imdb_id="tt17220216",
            tmdb_id="202411",
            tvdb_id="422598",
        ),
        episodes=[
            MediaItem(
                identifiers=MediaIdentifiers(
                    title="Aftermath",
                    locations=("S01E01.mkv",),
                    imdb_id="tt20412166",
                    tvdb_id="9959300",
                    tmdb_id=None,
                ),
                status=WatchedStatus(completed=True, time=0, viewed_date=viewed_date),
            ),
            MediaItem(
                identifiers=MediaIdentifiers(
                    title="Departure",
                    locations=("S01E02.mkv",),
                    imdb_id="tt22866594",
                    tvdb_id="10009417",
                    tmdb_id=None,
                ),
                status=WatchedStatus(
                    completed=False, time=300741, viewed_date=viewed_date
                ),
            ),
        ],
    ),
]

# ─────────────────────────────────────────────────────────────
# Movies Watched list 1

movies_watched_list_1: list[MediaItem] = [
    MediaItem(
        identifiers=MediaIdentifiers(
            title="Big Buck Bunny",
            locations=("Big Buck Bunny.mkv",),
            imdb_id="tt1254207",
            tmdb_id="10378",
            tvdb_id="12352",
        ),
        status=WatchedStatus(completed=True, time=0, viewed_date=viewed_date),
    ),
    MediaItem(
        identifiers=MediaIdentifiers(
            title="The Family Plan",
            locations=("The Family Plan (2023).mkv",),
            imdb_id="tt16431870",
            tmdb_id="1029575",
            tvdb_id="351194",
        ),
        status=WatchedStatus(completed=True, time=0, viewed_date=viewed_date),
    ),
    MediaItem(
        identifiers=MediaIdentifiers(
            title="Killers of the Flower Moon",
            locations=("Killers of the Flower Moon (2023).mkv",),
            imdb_id="tt5537002",
            tmdb_id="466420",
            tvdb_id="135852",
        ),
        status=WatchedStatus(completed=False, time=240000, viewed_date=viewed_date),
    ),
]

# ─────────────────────────────────────────────────────────────
# Movies Watched list 2

movies_watched_list_2: list[MediaItem] = [
    MediaItem(
        identifiers=MediaIdentifiers(
            title="The Family Plan",
            locations=("The Family Plan (2023).mkv",),
            imdb_id="tt16431870",
            tmdb_id="1029575",
            tvdb_id=None,
        ),
        status=WatchedStatus(completed=True, time=0, viewed_date=viewed_date),
    ),
    MediaItem(
        identifiers=MediaIdentifiers(
            title="Five Nights at Freddy's",
            locations=("Five Nights at Freddy's (2023).mkv",),
            imdb_id="tt4589218",
            tmdb_id="507089",
            tvdb_id=None,
        ),
        status=WatchedStatus(completed=True, time=0, viewed_date=viewed_date),
    ),
    MediaItem(
        identifiers=MediaIdentifiers(
            title="The Hunger Games: The Ballad of Songbirds & Snakes",
            locations=("The Hunger Games The Ballad of Songbirds & Snakes (2023).mkv",),
            imdb_id="tt10545296",
            tmdb_id="695721",
            tvdb_id=None,
        ),
        status=WatchedStatus(completed=False, time=301215, viewed_date=viewed_date),
    ),
]

# ─────────────────────────────────────────────────────────────
# Expected Movies Watched list 1

expected_movie_watched_list_1: list[MediaItem] = [
    MediaItem(
        identifiers=MediaIdentifiers(
            title="Big Buck Bunny",
            locations=("Big Buck Bunny.mkv",),
            imdb_id="tt1254207",
            tmdb_id="10378",
            tvdb_id="12352",
        ),
        status=WatchedStatus(completed=True, time=0, viewed_date=viewed_date),
    ),
    MediaItem(
        identifiers=MediaIdentifiers(
            title="Killers of the Flower Moon",
            locations=("Killers of the Flower Moon (2023).mkv",),
            imdb_id="tt5537002",
            tmdb_id="466420",
            tvdb_id="135852",
        ),
        status=WatchedStatus(completed=False, time=240000, viewed_date=viewed_date),
    ),
]

# ─────────────────────────────────────────────────────────────
# Expected Movies Watched list 2

expected_movie_watched_list_2: list[MediaItem] = [
    MediaItem(
        identifiers=MediaIdentifiers(
            title="Five Nights at Freddy's",
            locations=("Five Nights at Freddy's (2023).mkv",),
            imdb_id="tt4589218",
            tmdb_id="507089",
            tvdb_id=None,
        ),
        status=WatchedStatus(completed=True, time=0, viewed_date=viewed_date),
    ),
    MediaItem(
        identifiers=MediaIdentifiers(
            title="The Hunger Games: The Ballad of Songbirds & Snakes",
            locations=("The Hunger Games The Ballad of Songbirds & Snakes (2023).mkv",),
            imdb_id="tt10545296",
            tmdb_id="695721",
            tvdb_id=None,
        ),
        status=WatchedStatus(completed=False, time=301215, viewed_date=viewed_date),
    ),
]

# ─────────────────────────────────────────────────────────────
# TV Shows 2 Watched list 1 (for testing deletion up to the root)
# Here we use a single Series entry for "Criminal Minds"

tv_shows_2_watched_list_1: list[Series] = [
    Series(
        identifiers=MediaIdentifiers(
            title="Criminal Minds",
            locations=("Criminal Minds",),
            imdb_id="tt0452046",
            tmdb_id="4057",
            tvdb_id="75710",
        ),
        episodes=[
            MediaItem(
                identifiers=MediaIdentifiers(
                    title="Extreme Aggressor",
                    locations=(
                        "Criminal Minds S01E01 Extreme Aggressor WEBDL-720p.mkv",
                    ),
                    imdb_id="tt0550489",
                    tmdb_id="282843",
                    tvdb_id="176357",
                ),
                status=WatchedStatus(completed=True, time=0, viewed_date=viewed_date),
            )
        ],
    )
]


def test_simple_cleanup_watched():
    user_watched_list_1: dict[str, UserData] = {
        "user1": UserData(
            libraries={
                "TV Shows": LibraryData(
                    title="TV Shows",
                    movies=[],
                    series=tv_shows_watched_list_1,
                ),
                "Movies": LibraryData(
                    title="Movies",
                    movies=movies_watched_list_1,
                    series=[],
                ),
                "Other Shows": LibraryData(
                    title="Other Shows",
                    movies=[],
                    series=tv_shows_2_watched_list_1,
                ),
            }
        )
    }

    user_watched_list_2: dict[str, UserData] = {
        "user1": UserData(
            libraries={
                "TV Shows": LibraryData(
                    title="TV Shows",
                    movies=[],
                    series=tv_shows_watched_list_2,
                ),
                "Movies": LibraryData(
                    title="Movies",
                    movies=movies_watched_list_2,
                    series=[],
                ),
                "Other Shows": LibraryData(
                    title="Other Shows",
                    movies=[],
                    series=tv_shows_2_watched_list_1,
                ),
            }
        )
    }

    expected_watched_list_1: dict[str, UserData] = {
        "user1": UserData(
            libraries={
                "TV Shows": LibraryData(
                    title="TV Shows",
                    movies=[],
                    series=expected_tv_show_watched_list_1,
                ),
                "Movies": LibraryData(
                    title="Movies",
                    movies=expected_movie_watched_list_1,
                    series=[],
                ),
            }
        )
    }

    expected_watched_list_2: dict[str, UserData] = {
        "user1": UserData(
            libraries={
                "TV Shows": LibraryData(
                    title="TV Shows",
                    movies=[],
                    series=expected_tv_show_watched_list_2,
                ),
                "Movies": LibraryData(
                    title="Movies",
                    movies=expected_movie_watched_list_2,
                    series=[],
                ),
            }
        )
    }

    return_watched_list_1 = cleanup_watched(
        user_watched_list_1, user_watched_list_2, env={}
    )
    return_watched_list_2 = cleanup_watched(
        user_watched_list_2, user_watched_list_1, env={}
    )

    assert return_watched_list_1 == expected_watched_list_1
    assert return_watched_list_2 == expected_watched_list_2


def test_json_state_is_migrated_and_unwatched_transition_is_persisted(tmp_path):
    item = MediaItem(
        identifiers=MediaIdentifiers(
            title="Migrated Item",
            locations=("Migrated Item.mkv",),
            imdb_id="tt7654321",
        ),
        status=WatchedStatus(
            completed=False,
            time=0,
            viewed_date=datetime(2024, 1, 1, tzinfo=timezone.utc),
        ),
    )
    json_path = tmp_path / "watched.json"
    db_path = tmp_path / "watched.db"
    json_path.write_text(
        json.dumps(
            {
                mediaitem_state_key(item): {
                    "completed": True,
                    "time": 0,
                    "viewed_date": "2024-01-01T00:00:00+00:00",
                }
            }
        ),
        encoding="utf-8",
    )

    env = {
        "WATCHED_STATE_DB": str(db_path),
        "WATCHED_STATE_FILE": str(json_path),
    }
    watched = {
        "user": UserData(
            libraries={
                "Movies": LibraryData(title="Movies", movies=[item]),
            }
        )
    }

    apply_manual_unwatched_state(watched, env)

    assert item.status.time == 0
    assert item.status.viewed_date > datetime(2024, 1, 1, tzinfo=timezone.utc)
    with sqlite3.connect(initialize_watched_state_db(env)) as connection:
        row = connection.execute(
            "SELECT completed, resume_ms, manual_unwatched_at FROM media_state"
        ).fetchone()
    assert row == (0, 0, item.status.viewed_date.isoformat())


def test_watched_state_is_scoped_to_source_server(tmp_path):
    item_identifiers = MediaIdentifiers(
        title="Source Scoped Item",
        locations=("Source Scoped Item.mkv",),
        imdb_id="tt7654322",
    )
    watched_item = MediaItem(
        identifiers=item_identifiers,
        status=WatchedStatus(
            completed=True,
            time=0,
            viewed_date=datetime(2024, 1, 1, tzinfo=timezone.utc),
        ),
    )
    unwatched_item = MediaItem(
        identifiers=item_identifiers,
        status=WatchedStatus(
            completed=False,
            time=0,
            viewed_date=datetime(2024, 1, 1, tzinfo=timezone.utc),
        ),
    )
    env = {"WATCHED_STATE_DB": str(tmp_path / "watched.db")}

    apply_manual_unwatched_state(
        {
            "user": UserData(
                libraries={
                    "Movies": LibraryData(title="Movies", movies=[watched_item])
                }
            )
        },
        env,
        "Plex",
    )
    apply_manual_unwatched_state(
        {
            "user": UserData(
                libraries={
                    "Movies": LibraryData(title="Movies", movies=[unwatched_item])
                }
            )
        },
        env,
        "Emby",
    )

    assert unwatched_item.status.viewed_date == datetime(
        2024, 1, 1, tzinfo=timezone.utc
    )


def test_manual_unwatched_state_wins_over_partial_progress():
    identifiers = MediaIdentifiers(
        title="Reset Item",
        locations=("Reset Item.mkv",),
        imdb_id="tt7654323",
    )
    unwatched_item = MediaItem(
        identifiers=identifiers,
        status=WatchedStatus(
            completed=False,
            time=0,
            viewed_date=datetime.now(timezone.utc),
            manually_unwatched=True,
        ),
    )
    partial_item = MediaItem(
        identifiers=identifiers,
        status=WatchedStatus(
            completed=False,
            time=300_000,
            viewed_date=datetime.now(timezone.utc),
        ),
    )

    assert compare_media_items(unwatched_item, partial_item, {}) == Ord.A_BETTER
    assert compare_media_items(partial_item, unwatched_item, {}) == Ord.B_BETTER

    completed_item = MediaItem(
        identifiers=identifiers,
        status=WatchedStatus(
            completed=True,
            time=0,
            viewed_date=datetime.now(timezone.utc),
        ),
    )
    assert compare_media_items(unwatched_item, completed_item, {}) == Ord.A_BETTER
    assert compare_media_items(completed_item, unwatched_item, {}) == Ord.B_BETTER


def test_completed_state_beats_newer_unknown_incomplete_state():
    identifiers = MediaIdentifiers(title="Unknown Item")
    completed_item = MediaItem(
        identifiers=identifiers,
        status=WatchedStatus(
            completed=True,
            time=0,
            viewed_date=datetime(2024, 1, 1, tzinfo=timezone.utc),
        ),
    )
    unknown_incomplete_item = MediaItem(
        identifiers=identifiers,
        status=WatchedStatus(
            completed=False,
            time=0,
            viewed_date=datetime.now(timezone.utc),
        ),
    )

    assert (
        compare_media_items(completed_item, unknown_incomplete_item, {})
        == Ord.A_BETTER
    )
    assert (
        compare_media_items(unknown_incomplete_item, completed_item, {})
        == Ord.B_BETTER
    )


def test_unknown_zero_progress_item_does_not_remove_real_state():
    identifiers = MediaIdentifiers(title="Unknown Cleanup Item")
    real_state = MediaItem(
        identifiers=identifiers,
        status=WatchedStatus(
            completed=True,
            time=0,
            viewed_date=datetime(2024, 1, 1, tzinfo=timezone.utc),
        ),
    )
    unknown_state = MediaItem(
        identifiers=identifiers,
        status=WatchedStatus(
            completed=False,
            time=0,
            viewed_date=datetime.now(timezone.utc),
        ),
    )

    assert not check_remove_entry(real_state, unknown_state, {})


def test_pending_unwatched_sync_is_not_detected_as_manual(tmp_path):
    identifiers = MediaIdentifiers(
        title="Propagated Reset",
        locations=("Propagated Reset.mkv",),
        imdb_id="tt7654324",
    )
    watched_item = MediaItem(
        identifiers=identifiers,
        status=WatchedStatus(
            completed=True,
            time=0,
            viewed_date=datetime.now(timezone.utc),
        ),
    )
    unwatched_item = MediaItem(
        identifiers=identifiers,
        status=WatchedStatus(
            completed=False,
            time=0,
            viewed_date=datetime.now(timezone.utc),
        ),
    )
    env = {"WATCHED_STATE_DB": str(tmp_path / "watched.db")}

    apply_manual_unwatched_state(
        {"user": UserData(libraries={"Movies": LibraryData(title="Movies", movies=[watched_item])})},
        env,
        "Plex",
    )
    record_pending_sync(env, unwatched_item, "Jellyfin")
    apply_manual_unwatched_state(
        {"user": UserData(libraries={"Movies": LibraryData(title="Movies", movies=[unwatched_item])})},
        env,
        "Jellyfin",
    )

    assert not unwatched_item.status.manually_unwatched

    restored_item = MediaItem(
        identifiers=identifiers,
        status=WatchedStatus(
            completed=True,
            time=0,
            viewed_date=datetime.now(timezone.utc),
        ),
    )
    apply_manual_unwatched_state(
        {"user": UserData(libraries={"Movies": LibraryData(title="Movies", movies=[restored_item])})},
        env,
        "Jellyfin",
    )
    assert restored_item.status.completed
    assert not restored_item.status.manually_unwatched


def test_pending_sync_matches_destination_without_server_scoped_key(tmp_path):
    source_identifiers = MediaIdentifiers(
        title="Episode From Plex",
        locations=("episode.mkv",),
        imdb_id="tt7654325",
    )
    destination_identifiers = MediaIdentifiers(
        title="Episode From Jellyfin",
        locations=("episode.mkv",),
        imdb_id="tt7654325",
    )
    source_watched = MediaItem(
        identifiers=source_identifiers,
        status=WatchedStatus(
            completed=True,
            time=0,
            viewed_date=datetime.now(timezone.utc),
        ),
    )
    destination_unwatched = MediaItem(
        identifiers=destination_identifiers,
        status=WatchedStatus(
            completed=False,
            time=0,
            viewed_date=datetime.now(timezone.utc),
        ),
    )
    env = {"WATCHED_STATE_DB": str(tmp_path / "watched.db")}

    apply_manual_unwatched_state(
        {"user": UserData(libraries={"Shows": LibraryData(title="Shows", movies=[source_watched])})},
        env,
        "Plex",
    )
    record_pending_sync(env, destination_unwatched, "Jellyfin")
    apply_manual_unwatched_state(
        {"user": UserData(libraries={"Shows": LibraryData(title="Shows", movies=[destination_unwatched])})},
        env,
        "Jellyfin",
    )

    assert not destination_unwatched.status.manually_unwatched
    with sqlite3.connect(initialize_watched_state_db(env)) as connection:
        pending = connection.execute("SELECT COUNT(*) FROM pending_sync").fetchone()
    assert pending == (0,)


def test_diverged_pending_sync_is_discarded_before_manual_unwatched_detection(
    tmp_path,
):
    identifiers = MediaIdentifiers(
        title="Diverged Pending Item",
        locations=("diverged-pending-item.mkv",),
        imdb_id="tt7654328",
    )
    watched_item = MediaItem(
        identifiers=identifiers,
        status=WatchedStatus(
            completed=True, time=0, viewed_date=datetime.now(timezone.utc)
        ),
    )
    unwatched_item = MediaItem(
        identifiers=identifiers,
        status=WatchedStatus(
            completed=False, time=0, viewed_date=datetime.now(timezone.utc)
        ),
    )
    env = {"WATCHED_STATE_DB": str(tmp_path / "watched.db")}

    apply_manual_unwatched_state(
        {"user": UserData(libraries={"Shows": LibraryData(title="Shows", movies=[watched_item])})},
        env,
        "Jellyfin",
    )
    record_pending_sync(env, watched_item, "Jellyfin")
    apply_manual_unwatched_state(
        {"user": UserData(libraries={"Shows": LibraryData(title="Shows", movies=[unwatched_item])})},
        env,
        "Jellyfin",
    )

    assert unwatched_item.status.manually_unwatched
    with sqlite3.connect(initialize_watched_state_db(env)) as connection:
        assert connection.execute("SELECT COUNT(*) FROM pending_sync").fetchone() == (0,)


def test_manual_unwatched_transition_remains_explicit_until_watched(tmp_path):
    identifiers = MediaIdentifiers(
        title="Persistent Reset",
        locations=("Persistent Reset.mkv",),
        imdb_id="tt7654326",
    )
    watched_item = MediaItem(
        identifiers=identifiers,
        status=WatchedStatus(
            completed=True, time=0, viewed_date=datetime.now(timezone.utc)
        ),
    )
    unwatched_item = MediaItem(
        identifiers=identifiers,
        status=WatchedStatus(
            completed=False, time=0, viewed_date=datetime.now(timezone.utc)
        ),
    )
    env = {"WATCHED_STATE_DB": str(tmp_path / "watched.db")}

    watched = {"user": UserData(libraries={"Movies": LibraryData(title="Movies", movies=[watched_item])})}
    unwatched = {"user": UserData(libraries={"Movies": LibraryData(title="Movies", movies=[unwatched_item])})}

    apply_manual_unwatched_state(watched, env, "Jellyfin")
    apply_manual_unwatched_state(unwatched, env, "Jellyfin")
    assert unwatched_item.status.manually_unwatched

    next_unwatched = unwatched_item.model_copy(deep=True)
    next_unwatched.status.manually_unwatched = False
    apply_manual_unwatched_state(
        {"user": UserData(libraries={"Movies": LibraryData(title="Movies", movies=[next_unwatched])})},
        env,
        "Jellyfin",
    )
    assert next_unwatched.status.manually_unwatched

    restored = watched_item.model_copy(deep=True)
    apply_manual_unwatched_state(
        {"user": UserData(libraries={"Movies": LibraryData(title="Movies", movies=[restored])})},
        env,
        "Jellyfin",
    )
    assert not restored.status.manually_unwatched


def test_indexed_state_preserves_transition_timestamps(tmp_path):
    identifiers = MediaIdentifiers(
        title="Indexed Jellyfin Item",
        locations=("indexed-jellyfin-item.mkv",),
        imdb_id="tt7654327",
    )
    watched_item = MediaItem(
        identifiers=identifiers,
        status=WatchedStatus(
            completed=True, time=0, viewed_date=datetime.now(timezone.utc)
        ),
    )
    unwatched_item = MediaItem(
        identifiers=identifiers,
        status=WatchedStatus(
            completed=False, time=0, viewed_date=datetime.now(timezone.utc)
        ),
    )
    env = {"WATCHED_STATE_DB": str(tmp_path / "watched.db")}

    apply_manual_unwatched_state(
        {"user": UserData(libraries={"Shows": LibraryData(title="Shows", movies=[watched_item])})},
        env,
        "Jellyfin",
    )
    apply_manual_unwatched_state(
        {"user": UserData(libraries={"Shows": LibraryData(title="Shows", movies=[unwatched_item])})},
        env,
        "Jellyfin",
    )

    with sqlite3.connect(initialize_watched_state_db(env)) as connection:
        state_changed_at, manual_unwatched_at = connection.execute(
            "SELECT state_changed_at, manual_unwatched_at FROM media_state"
        ).fetchone()

    assert unwatched_item.status.manually_unwatched
    assert state_changed_at
    assert manual_unwatched_at
    datetime.fromisoformat(state_changed_at)
    datetime.fromisoformat(manual_unwatched_at)


def test_tracked_unwatched_state_remains_collectable(tmp_path):
    identifiers = MediaIdentifiers(
        title="Tracked Unwatched Item",
        locations=("tracked-unwatched-item.mkv",),
        imdb_id="tt7654329",
    )
    item = MediaItem(
        identifiers=identifiers,
        status=WatchedStatus(
            completed=True, time=0, viewed_date=datetime.now(timezone.utc)
        ),
    )
    env = {"WATCHED_STATE_DB": str(tmp_path / "watched.db")}
    apply_manual_unwatched_state(
        {"user": UserData(libraries={"Movies": LibraryData(title="Movies", movies=[item])})},
        env,
        "Jellyfin",
    )
    item.status.completed = False
    apply_manual_unwatched_state(
        {"user": UserData(libraries={"Movies": LibraryData(title="Movies", movies=[item])})},
        env,
        "Jellyfin",
    )

    env["_watched_state_index"] = load_state_index(env, "Jellyfin")
    assert was_previously_watched(item, env)


def test_cross_server_state_remains_collectable_for_unwatched_transition(tmp_path):
    identifiers = MediaIdentifiers(
        title="Cross Server Item",
        locations=("cross-server-item.mkv",),
        imdb_id="tt7654331",
    )
    watched_item = MediaItem(
        identifiers=identifiers,
        status=WatchedStatus(
            completed=True, time=0, viewed_date=datetime.now(timezone.utc)
        ),
    )
    unwatched_item = watched_item.model_copy(deep=True)
    unwatched_item.status.completed = False
    env = {"WATCHED_STATE_DB": str(tmp_path / "watched.db")}

    apply_manual_unwatched_state(
        {"user": UserData(libraries={"Movies": LibraryData(title="Movies", movies=[watched_item])})},
        env,
        "Plex",
    )
    env["_watched_state_index"] = load_state_index(env, "Jellyfin")

    assert was_previously_watched(unwatched_item, env)


def test_cross_server_state_does_not_collect_completed_items(tmp_path):
    identifiers = MediaIdentifiers(
        title="Cross Server Watched Item",
        locations=("cross-server-watched-item.mkv",),
        imdb_id="tt7654332",
    )
    watched_item = MediaItem(
        identifiers=identifiers,
        status=WatchedStatus(
            completed=True, time=0, viewed_date=datetime.now(timezone.utc)
        ),
    )
    env = {"WATCHED_STATE_DB": str(tmp_path / "watched.db")}

    apply_manual_unwatched_state(
        {"user": UserData(libraries={"Movies": LibraryData(title="Movies", movies=[watched_item])})},
        env,
        "Plex",
    )
    env["_watched_state_index"] = load_state_index(env, "Jellyfin")

    assert not was_previously_watched(watched_item, env)


def test_cross_server_fallback_ignores_partial_baseline(tmp_path):
    identifiers = MediaIdentifiers(
        title="Cross Server Partial Item",
        locations=("cross-server-partial-item.mkv",),
        imdb_id="tt7654333",
    )
    partial_item = MediaItem(
        identifiers=identifiers,
        status=WatchedStatus(
            completed=False,
            time=240_000,
            viewed_date=datetime.now(timezone.utc),
        ),
    )
    current_unwatched = partial_item.model_copy(deep=True)
    current_unwatched.status.time = 0
    env = {"WATCHED_STATE_DB": str(tmp_path / "watched.db")}

    apply_manual_unwatched_state(
        {"user": UserData(libraries={"Movies": LibraryData(title="Movies", movies=[partial_item])})},
        env,
        "Plex",
    )
    env["_watched_state_index"] = load_state_index(env, "Emby")

    assert not was_previously_watched(current_unwatched, env)


def test_cross_server_observation_does_not_create_manual_unwatched_state(tmp_path):
    identifiers = MediaIdentifiers(
        title="Cross Server Observation",
        locations=("cross-server-observation.mkv",),
        imdb_id="tt7654334",
    )
    plex_item = MediaItem(
        identifiers=identifiers,
        status=WatchedStatus(
            completed=True, time=0, viewed_date=datetime.now(timezone.utc)
        ),
    )
    emby_item = MediaItem(
        identifiers=identifiers,
        status=WatchedStatus(
            completed=False, time=0, viewed_date=datetime.now(timezone.utc)
        ),
    )
    env = {"WATCHED_STATE_DB": str(tmp_path / "watched.db")}

    apply_manual_unwatched_state(
        {"user": UserData(libraries={"Movies": LibraryData(title="Movies", movies=[plex_item])})},
        env,
        "Plex",
    )
    apply_manual_unwatched_state(
        {"user": UserData(libraries={"Movies": LibraryData(title="Movies", movies=[emby_item])})},
        env,
        "Emby",
    )

    assert not emby_item.status.manually_unwatched


def test_manual_unwatched_detection_ignores_other_source_baseline(tmp_path):
    identifiers = MediaIdentifiers(
        title="Source Scoped Baseline",
        locations=("source-scoped-baseline.mkv",),
        imdb_id="tt7654335",
    )
    emby_item = MediaItem(
        identifiers=identifiers,
        status=WatchedStatus(
            completed=False,
            time=0,
            viewed_date=datetime.now(timezone.utc),
        ),
    )
    env = {"WATCHED_STATE_DB": str(tmp_path / "watched.db")}
    db_path = initialize_watched_state_db(env)

    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            INSERT INTO media_state
            (state_key, completed, resume_ms, viewed_date, manual_unwatched_at,
             observed_at, state_changed_at)
            VALUES (?, 1, 0, ?, NULL, ?, ?)
            """,
            (
                mediaitem_state_key(emby_item, "Plex"),
                emby_item.status.viewed_date.isoformat(),
                datetime.now(timezone.utc).isoformat(),
                datetime.now(timezone.utc).isoformat(),
            ),
        )

    apply_manual_unwatched_state(
        {"user": UserData(libraries={"Movies": LibraryData(title="Movies", movies=[emby_item])})},
        env,
        "Emby",
    )

    assert not emby_item.status.manually_unwatched


def test_source_exact_state_precedes_flexible_identity_match(tmp_path):
    identifiers = MediaIdentifiers(
        title="Exact Source Item",
        locations=("exact-source-item.mkv",),
        imdb_id="tt7654330",
    )
    watched_item = MediaItem(
        identifiers=identifiers,
        status=WatchedStatus(
            completed=True, time=0, viewed_date=datetime.now(timezone.utc)
        ),
    )
    unwatched_item = watched_item.model_copy(deep=True)
    unwatched_item.status.completed = False
    env = {"WATCHED_STATE_DB": str(tmp_path / "watched.db")}

    apply_manual_unwatched_state(
        {"user": UserData(libraries={"Movies": LibraryData(title="Movies", movies=[watched_item])})},
        env,
        "Plex",
    )
    apply_manual_unwatched_state(
        {"user": UserData(libraries={"Movies": LibraryData(title="Movies", movies=[watched_item])})},
        env,
        "Jellyfin",
    )
    apply_manual_unwatched_state(
        {"user": UserData(libraries={"Movies": LibraryData(title="Movies", movies=[unwatched_item])})},
        env,
        "Jellyfin",
    )

    assert unwatched_item.status.manually_unwatched


# def test_mapping_cleanup_watched():
#    user_watched_list_1 = {
#        "user1": {
#            "TV Shows": tv_shows_watched_list_1,
#            "Movies": movies_watched_list_1,
#            "Other Shows": tv_shows_2_watched_list_1,
#        },
#    }
#    user_watched_list_2 = {
#        "user2": {
#            "Shows": tv_shows_watched_list_2,
#            "Movies": movies_watched_list_2,
#            "Other Shows": tv_shows_2_watched_list_1,
#        }
#    }
#
#    expected_watched_list_1 = {
#        "user1": {
#            "TV Shows": expected_tv_show_watched_list_1,
#            "Movies": expected_movie_watched_list_1,
#        }
#    }
#
#    expected_watched_list_2 = {
#        "user2": {
#            "Shows": expected_tv_show_watched_list_2,
#            "Movies": expected_movie_watched_list_2,
#        }
#    }
#
#    user_mapping = {"user1": "user2"}
#    library_mapping = {"TV Shows": "Shows"}
#
#    return_watched_list_1 = cleanup_watched(
#        user_watched_list_1,
#        user_watched_list_2,
#        user_mapping=user_mapping,
#        library_mapping=library_mapping,
#    )
#    return_watched_list_2 = cleanup_watched(
#        user_watched_list_2,
#        user_watched_list_1,
#        user_mapping=user_mapping,
#        library_mapping=library_mapping,
#    )
#
#    assert return_watched_list_1 == expected_watched_list_1
#    assert return_watched_list_2 == expected_watched_list_2
