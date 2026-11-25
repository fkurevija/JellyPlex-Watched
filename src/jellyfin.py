from packaging.version import parse

from src.jellyfin_emby import JellyfinEmby
from src.settings import AppSettings, JellyfinSettings


class Jellyfin(JellyfinEmby):
    def __init__(
        self,
        app_settings: AppSettings,
        server_settings: JellyfinSettings,
    ) -> None:
        authorization = (
            "MediaBrowser , "
            'Client="JellyPlex-Watched", '
            'Device="script", '
            'DeviceId="script", '
            'Version="6.0.2", '
            f'Token="{server_settings.token.get_secret_value()}"'
        )
        headers = {
            "Accept": "application/json",
            "Authorization": authorization,
        }

        super().__init__(
            app_settings=app_settings,
            server_settings=server_settings,
            server_type="Jellyfin",
            headers=headers,
            partial_update_min_version=parse("10.9.0"),
        )
