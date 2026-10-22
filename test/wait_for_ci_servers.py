from __future__ import annotations

import time
from pathlib import Path

import requests
from dotenv import dotenv_values


_ROOT = Path(__file__).resolve().parents[1]


def _ci_token(env_file: str, key: str) -> str:
    token = dotenv_values(_ROOT / "test" / env_file).get(key)
    if not token:
        raise ValueError(f"{key} is missing from test/{env_file}")
    return token


_SERVER_PROBES = {
    "Plex": ("http://localhost:32400/identity", None),
    "Jellyfin": (
        "http://localhost:8096/Users",
        {
            "Accept": "application/json",
            "Authorization": (
                "MediaBrowser , "
                'Client="JellyPlex-Watched", '
                'Device="script", '
                'DeviceId="script", '
                'Version="6.0.2", '
                f'Token="{_ci_token("ci_jellyfin.env", "JELLYFIN_TOKEN")}"'
            ),
        },
    ),
    "Emby": (
        "http://localhost:8097/Users",
        {
            "Accept": "application/json",
            "X-Emby-Token": _ci_token("ci_emby.env", "EMBY_TOKEN"),
            "X-Emby-Authorization": (
                "Emby , "
                'Client="JellyPlex-Watched", '
                'Device="script", '
                'DeviceId="script", '
                'Version="6.0.2"'
            ),
        },
    ),
}


def wait_for_ci_servers(timeout: float = 180, interval: float = 2) -> None:
    deadline = time.monotonic() + timeout
    pending = dict(_SERVER_PROBES)
    last_errors: dict[str, str] = {}

    while pending:
        for server, (url, headers) in pending.copy().items():
            try:
                response = requests.get(url, headers=headers, timeout=2)
                response.raise_for_status()
            except requests.RequestException as error:
                last_errors[server] = str(error)
                continue

            del pending[server]
            print(f"{server} is ready")

        if not pending:
            return

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            failures = "; ".join(
                f"{server}: {last_errors.get(server, 'no response')}"
                for server in pending
            )
            raise TimeoutError(
                f"Media servers did not become ready within {timeout:g} seconds: "
                f"{failures}"
            )

        time.sleep(min(interval, remaining))


if __name__ == "__main__":
    wait_for_ci_servers()
