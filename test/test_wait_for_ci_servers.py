from unittest.mock import Mock

import pytest
import requests
import wait_for_ci_servers as readiness


def test_waits_until_each_media_server_is_responding(monkeypatch, capsys):
    request = Mock(
        side_effect=[
            requests.ConnectionError("starting"),
            Mock(raise_for_status=Mock()),
            Mock(raise_for_status=Mock()),
            Mock(raise_for_status=Mock()),
        ]
    )
    sleep = Mock()
    monkeypatch.setattr(readiness.requests, "get", request)
    monkeypatch.setattr(readiness.time, "sleep", sleep)

    readiness.wait_for_ci_servers()

    assert request.call_count == 4
    sleep.assert_called_once_with(2)
    assert set(capsys.readouterr().out.splitlines()) == {
        "Plex is ready",
        "Jellyfin is ready",
        "Emby is ready",
    }
    assert request.call_args_list[0].args == ("http://localhost:32400/identity",)
    jellyfin_headers = request.call_args_list[1].kwargs["headers"]
    assert jellyfin_headers["Accept"] == "application/json"
    assert jellyfin_headers["Authorization"].startswith("MediaBrowser , ")
    assert 'Token="' in jellyfin_headers["Authorization"]
    emby_headers = request.call_args_list[2].kwargs["headers"]
    assert emby_headers["Accept"] == "application/json"
    assert emby_headers["X-Emby-Token"]
    assert emby_headers["X-Emby-Authorization"].startswith("Emby , ")
    assert request.call_args_list[3].args == ("http://localhost:32400/identity",)


def test_waits_for_authenticated_users_api_after_server_public_info_is_ready(
    monkeypatch, capsys
):
    request = Mock(
        side_effect=[
            Mock(raise_for_status=Mock()),
            Mock(raise_for_status=Mock(side_effect=requests.HTTPError("503"))),
            Mock(raise_for_status=Mock()),
            Mock(raise_for_status=Mock()),
        ]
    )
    monkeypatch.setattr(readiness.requests, "get", request)
    monkeypatch.setattr(readiness.time, "sleep", Mock())

    readiness.wait_for_ci_servers()

    assert request.call_count == 4
    assert request.call_args_list[1].args == ("http://localhost:8096/Users",)
    assert (
        request.call_args_list[1].kwargs["headers"]["Authorization"]
        .startswith("MediaBrowser , ")
    )
    assert request.call_args_list[3].args == ("http://localhost:8096/Users",)
    assert set(capsys.readouterr().out.splitlines()) == {
        "Plex is ready",
        "Jellyfin is ready",
        "Emby is ready",
    }


def test_reports_services_that_do_not_become_ready(monkeypatch):
    now = 0.0
    monkeypatch.setattr(readiness.time, "monotonic", lambda: now)
    monkeypatch.setattr(readiness.time, "sleep", lambda duration: None)
    monkeypatch.setattr(
        readiness.requests,
        "get",
        Mock(side_effect=requests.ConnectionError("connection refused")),
    )

    with pytest.raises(TimeoutError, match="Plex: connection refused"):
        readiness.wait_for_ci_servers(timeout=0, interval=0)
