"""Jellyfin client: authentication, user import, music library reading."""

from __future__ import annotations

import base64
import logging
from typing import Any

import httpx

from .. import __version__
from .base import HttpService, ServiceError, ServiceNotConfigured, normalize_base_url
from .settings import JellyfinSettings

logger = logging.getLogger(__name__)

CLIENT_NAME = "Muzikk"
DEVICE_ID = "muzikk-server"

LOSSLESS_CONTAINERS = {"flac", "alac", "wav", "aiff", "aif", "ape", "wv", "wvpack", "dsf", "dff"}


def _authorization_header(token: str | None = None) -> str:
    parts = [
        f'Client="{CLIENT_NAME}"',
        f'Device="{CLIENT_NAME}"',
        f'DeviceId="{DEVICE_ID}"',
        f'Version="{__version__}"',
    ]
    if token:
        parts.append(f'Token="{token}"')
    return "MediaBrowser " + ", ".join(parts)


class JellyfinClient(HttpService):
    service_name = "jellyfin"

    def __init__(self, settings: JellyfinSettings) -> None:
        super().__init__(normalize_base_url(settings.url))
        self.settings = settings
        self.api_key = settings.api_key or ""

    @property
    def configured(self) -> bool:
        return bool(self.base_url)

    def _api_headers(self) -> dict[str, str]:
        if not self.api_key:
            raise ServiceError(self.service_name, "no API key configured")
        return {
            "Authorization": _authorization_header(self.api_key),
            "X-Emby-Token": self.api_key,
            "X-Emby-Authorization": _authorization_header(self.api_key),
            "Accept": "application/json",
        }

    # ---------------------------------------------------------------- auth

    async def authenticate_by_name(self, username: str, password: str) -> dict[str, Any]:
        """Validate credentials against Jellyfin and return the auth result."""
        if not self.base_url:
            raise ServiceNotConfigured(self.service_name)
        headers = {
            "Authorization": _authorization_header(),
            "X-Emby-Authorization": _authorization_header(),
            "Content-Type": "application/json",
        }
        return await self.request(
            "POST",
            "/Users/AuthenticateByName",
            json={"Username": username, "Pw": password},
            headers=headers,
        )

    async def get_public_system_info(self) -> dict[str, Any]:
        return await self.request("GET", "/System/Info/Public")

    async def get_system_info(self) -> dict[str, Any]:
        return await self.request("GET", "/System/Info", headers=self._api_headers())

    async def get_users(self) -> list[dict[str, Any]]:
        return await self.request("GET", "/Users", headers=self._api_headers()) or []

    async def get_user(self, user_id: str) -> dict[str, Any]:
        return await self.request("GET", f"/Users/{user_id}", headers=self._api_headers())

    # ------------------------------------------------------------- library

    async def get_music_libraries(self) -> list[dict[str, Any]]:
        """Return the virtual folders whose collection type is music."""
        folders = await self.request("GET", "/Library/VirtualFolders", headers=self._api_headers()) or []
        result = []
        for folder in folders:
            if (folder.get("CollectionType") or "").lower() != "music":
                continue
            result.append(
                {
                    "id": folder.get("ItemId"),
                    "name": folder.get("Name"),
                    "locations": folder.get("Locations") or [],
                }
            )
        return result

    async def _resolve_user_id(self) -> str | None:
        users = await self.get_users()
        for user in users:
            if (user.get("Policy") or {}).get("IsAdministrator"):
                return user.get("Id")
        return users[0].get("Id") if users else None

    async def iter_items(
        self,
        item_types: str,
        *,
        fields: str,
        parent_ids: list[str] | None = None,
        page_size: int = 500,
        extra_params: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch every item of the given types, one library at a time."""
        user_id = await self._resolve_user_id()
        targets: list[str | None] = list(parent_ids) if parent_ids else [None]
        collected: list[dict[str, Any]] = []

        async with httpx.AsyncClient(timeout=httpx.Timeout(90.0, connect=10.0)) as client:
            for parent_id in targets:
                start_index = 0
                while True:
                    params: dict[str, Any] = {
                        "IncludeItemTypes": item_types,
                        "Recursive": "true",
                        "Fields": fields,
                        "StartIndex": start_index,
                        "Limit": page_size,
                        "SortBy": "SortName",
                        "SortOrder": "Ascending",
                        "EnableUserData": "false",
                        "EnableImages": "true",
                    }
                    if parent_id:
                        params["ParentId"] = parent_id
                    if user_id:
                        params["userId"] = user_id
                    if extra_params:
                        params.update(extra_params)

                    payload = await self.request(
                        "GET",
                        "/Items",
                        params=params,
                        headers=self._api_headers(),
                        client=client,
                    )
                    items = (payload or {}).get("Items") or []
                    collected.extend(items)
                    total = (payload or {}).get("TotalRecordCount") or 0
                    start_index += page_size
                    if not items or start_index >= total:
                        break
        return collected

    async def get_albums(self, parent_ids: list[str] | None = None) -> list[dict[str, Any]]:
        return await self.iter_items(
            "MusicAlbum",
            fields="ProviderIds,Path,ChildCount,Genres,DateCreated,ProductionYear,AlbumArtists",
            parent_ids=parent_ids,
        )

    async def get_artists(self, parent_ids: list[str] | None = None) -> list[dict[str, Any]]:
        """Album artists, read through /Artists which supports ParentId filtering."""
        user_id = await self._resolve_user_id()
        collected: list[dict[str, Any]] = []
        targets: list[str | None] = list(parent_ids) if parent_ids else [None]

        async with httpx.AsyncClient(timeout=httpx.Timeout(90.0, connect=10.0)) as client:
            for parent_id in targets:
                start_index = 0
                while True:
                    params: dict[str, Any] = {
                        "Fields": "ProviderIds",
                        "StartIndex": start_index,
                        "Limit": 500,
                    }
                    if parent_id:
                        params["ParentId"] = parent_id
                    if user_id:
                        params["userId"] = user_id
                    payload = await self.request(
                        "GET", "/Artists/AlbumArtists", params=params,
                        headers=self._api_headers(), client=client,
                    )
                    items = (payload or {}).get("Items") or []
                    collected.extend(items)
                    total = (payload or {}).get("TotalRecordCount") or 0
                    start_index += 500
                    if not items or start_index >= total:
                        break
        return collected

    async def get_audio_files(self, parent_ids: list[str] | None = None) -> list[dict[str, Any]]:
        """Minimal track listing, used to know which container each album uses."""
        return await self.iter_items(
            "Audio",
            fields="Path,Container,AlbumId,ParentId",
            parent_ids=parent_ids,
            page_size=1000,
            extra_params={"SortBy": "Album"},
        )

    async def get_audio_items(self, parent_ids: list[str] | None = None) -> list[dict[str, Any]]:
        """Every track with what Jellyfin believes its title and numbering are.

        One sweep over the whole library rather than a call per album: comparing
        thousands of albums track by track is only affordable this way.
        """
        return await self.iter_items(
            "Audio",
            fields="Path,AlbumId,IndexNumber,ParentIndexNumber",
            parent_ids=parent_ids,
            page_size=1000,
        )

    async def get_album_tracks(self, album_id: str) -> list[dict[str, Any]]:
        user_id = await self._resolve_user_id()
        params: dict[str, Any] = {
            "ParentId": album_id,
            "IncludeItemTypes": "Audio",
            "Fields": "Path,Container,MediaSources,ProviderIds,IndexNumber,ParentIndexNumber",
            "SortBy": "ParentIndexNumber,IndexNumber",
            "Limit": 500,
        }
        if user_id:
            params["userId"] = user_id
        payload = await self.request("GET", "/Items", params=params, headers=self._api_headers())
        return (payload or {}).get("Items") or []

    async def search_audio(
        self, term: str, *, limit: int = 40, parent_ids: list[str] | None = None
    ) -> list[dict[str, Any]]:
        """Tracks whose title, album or artist matches ``term``."""
        term = (term or "").strip()
        if not term:
            return []

        user_id = await self._resolve_user_id()
        params: dict[str, Any] = {
            "IncludeItemTypes": "Audio",
            "Recursive": "true",
            "searchTerm": term,
            "Limit": limit,
            "Fields": (
                "Path,Container,AlbumId,ProviderIds,IndexNumber,"
                "ParentIndexNumber,RunTimeTicks,Album,AlbumArtist,Artists"
            ),
            "EnableImages": "false",
        }
        if user_id:
            params["userId"] = user_id
        if parent_ids:
            params["ParentId"] = parent_ids[0]

        payload = await self.request("GET", "/Items", params=params, headers=self._api_headers())
        return (payload or {}).get("Items") or []

    async def get_item(self, item_id: str) -> dict[str, Any]:
        user_id = await self._resolve_user_id()
        params: dict[str, Any] = {
            "Ids": item_id,
            "Fields": (
                "Path,Container,AlbumId,ProviderIds,IndexNumber,"
                "ParentIndexNumber,RunTimeTicks,Album,AlbumArtist,Artists"
            ),
        }
        if user_id:
            params["userId"] = user_id
        payload = await self.request("GET", "/Items", params=params, headers=self._api_headers())
        items = (payload or {}).get("Items") or []
        return items[0] if items else {}

    # ------------------------------------------------------------ playlists

    def _user_headers(self, token: str) -> dict[str, str]:
        """Headers that make Jellyfin act as the listener, not as the server.

        A playlist belongs to whoever created it, so every call below carries
        the token of the person clicking in Muzikk. Under the server API key
        the playlists would all pile up on the account owning that key.
        """
        if not token:
            raise ServiceError(self.service_name, "no Jellyfin session for this account")
        return {
            "Authorization": _authorization_header(token),
            "X-Emby-Token": token,
            "Accept": "application/json",
        }

    async def get_playlists(self, *, token: str, user_id: str) -> list[dict[str, Any]]:
        """The playlists this account can see, music ones first and only."""
        params = {
            "IncludeItemTypes": "Playlist",
            "Recursive": "true",
            "SortBy": "SortName",
            "Fields": "ChildCount,DateCreated,CanDelete",
            "userId": user_id,
        }
        payload = await self.request(
            "GET", "/Items", params=params, headers=self._user_headers(token)
        )
        items = (payload or {}).get("Items") or []
        # A video playlist has nothing to do here; an empty one has no media
        # type yet and might still become a music playlist.
        return [item for item in items if (item.get("MediaType") or "Audio") == "Audio"]

    async def get_playlist_items(
        self, playlist_id: str, *, token: str, user_id: str
    ) -> list[dict[str, Any]]:
        """The tracks of one playlist, in playlist order.

        Each entry carries a ``PlaylistItemId`` of its own: the same track can
        appear twice, and removing one of them takes that identifier, not the
        identifier of the track.
        """
        params = {
            "userId": user_id,
            "Fields": (
                "AlbumId,Container,IndexNumber,ParentIndexNumber,"
                "RunTimeTicks,Album,AlbumArtist,Artists"
            ),
            "Limit": 1000,
        }
        payload = await self.request(
            "GET", f"/Playlists/{playlist_id}/Items", params=params,
            headers=self._user_headers(token),
        )
        return (payload or {}).get("Items") or []

    async def create_playlist(
        self, name: str, *, token: str, user_id: str, item_ids: list[str] | None = None
    ) -> str:
        payload = await self.request(
            "POST",
            "/Playlists",
            json={
                "Name": name,
                "Ids": list(item_ids or []),
                "UserId": user_id,
                "MediaType": "Audio",
            },
            headers={**self._user_headers(token), "Content-Type": "application/json"},
        )
        return str((payload or {}).get("Id") or "")

    async def add_to_playlist(
        self, playlist_id: str, item_ids: list[str], *, token: str, user_id: str
    ) -> None:
        await self.request(
            "POST",
            f"/Playlists/{playlist_id}/Items",
            params={"ids": ",".join(item_ids), "userId": user_id},
            headers=self._user_headers(token),
            expect_json=False,
        )

    async def remove_from_playlist(
        self, playlist_id: str, entry_ids: list[str], *, token: str
    ) -> None:
        await self.request(
            "DELETE",
            f"/Playlists/{playlist_id}/Items",
            params={"entryIds": ",".join(entry_ids)},
            headers=self._user_headers(token),
            expect_json=False,
        )

    async def delete_playlist(self, playlist_id: str, *, token: str) -> None:
        """Delete a playlist, which Jellyfin treats as deleting its item."""
        await self.request(
            "DELETE", f"/Items/{playlist_id}", headers=self._user_headers(token),
            expect_json=False,
        )

    # ------------------------------------------------------------- playback

    def stream_url(self, item_id: str, *, token: str, max_bitrate: int = 0) -> str:
        """Progressive audio URL.

        The universal endpoint direct plays whatever the browser understands
        and only transcodes the exotic containers, which keeps a lossless
        library lossless while still playing an APE or a DSF file.
        """
        containers = "flac,mp3,aac,m4a,ogg,opus,wav,webma,webm"
        params = [
            f"api_key={token}",
            f"DeviceId={DEVICE_ID}",
            f"Container={containers}",
            "AudioCodec=aac",
            "TranscodingContainer=mp4",
            "TranscodingProtocol=http",
            "EnableRedirection=false",
        ]
        if max_bitrate > 0:
            params.append(f"MaxStreamingBitrate={max_bitrate}")
        return f"{self.base_url}/Audio/{item_id}/universal?" + "&".join(params)

    async def report_playback(
        self, stage: str, payload: dict[str, Any], *, token: str
    ) -> None:
        """Feed the Jellyfin session so the play counts as listened.

        Reporting needs the token of the listener: the server API key would
        credit the play to whichever account owns it.
        """
        suffix = {"start": "", "progress": "/Progress", "stop": "/Stopped"}.get(stage)
        if suffix is None:
            raise ServiceError(self.service_name, f"unknown playback stage: {stage}")
        await self.request(
            "POST",
            f"/Sessions/Playing{suffix}",
            json=payload,
            headers={
                "Authorization": _authorization_header(token),
                "X-Emby-Token": token,
                "Content-Type": "application/json",
            },
            expect_json=False,
        )

    async def refresh_library(self) -> None:
        await self.request(
            "POST", "/Library/Refresh", headers=self._api_headers(), expect_json=False
        )

    async def refresh_item(self, item_id: str, *, replace_images: bool = False) -> None:
        """Ask Jellyfin to look at one item again.

        ``replace_images`` stays false by default on purpose: asking the server
        to replace the images of a music album is known to delete the
        ``cover.jpg`` files sitting in the folders (jellyfin#12629). The call
        returns as soon as the refresh is queued, not when it is done.
        """
        await self.request(
            "POST",
            f"/Items/{item_id}/Refresh",
            params={
                "metadataRefreshMode": "Default",
                "imageRefreshMode": "FullRefresh",
                "replaceAllImages": "true" if replace_images else "false",
                "replaceAllMetadata": "false",
            },
            headers=self._api_headers(),
            expect_json=False,
        )

    async def refresh_item_metadata(self, item_id: str) -> None:
        """Ask Jellyfin to read the files of one item again, and to believe them.

        The default refresh mode only fills in what is missing, so an album
        Jellyfin once named from a broken tag keeps that name for ever, however
        wrong it becomes. Replacing the metadata is the only mode that makes the
        server read the tags again. Images are left alone: replacing those on a
        music library deletes the cover files in the folders (jellyfin#12629).
        """
        await self.request(
            "POST",
            f"/Items/{item_id}/Refresh",
            params={
                "metadataRefreshMode": "FullRefresh",
                "replaceAllMetadata": "true",
                "imageRefreshMode": "None",
                "replaceAllImages": "false",
            },
            headers=self._api_headers(),
            expect_json=False,
        )

    async def get_item_for_edit(self, item_id: str) -> dict[str, Any]:
        """One item with everything it holds, as the web editor loads it.

        Editing is a read, modify and write round trip: the update endpoint
        applies every field of the body, so sending a partial item would blank
        out whatever was left out of it.
        """
        user_id = await self._resolve_user_id()
        params = {"userId": user_id} if user_id else None
        try:
            return await self.request(
                "GET", f"/Items/{item_id}", params=params, headers=self._api_headers()
            )
        except ServiceError:
            # The per user route is the older spelling, still served by 10.x.
            if not user_id:
                raise
            return await self.request(
                "GET", f"/Users/{user_id}/Items/{item_id}", headers=self._api_headers()
            )

    async def update_item(self, item_id: str, payload: dict[str, Any]) -> None:
        """Write an edited item back, exactly what *Edit metadata* posts.

        This asks no provider and reads no NFO file, which is the whole point:
        it is the only way to correct a value Jellyfin refuses to re-read.
        """
        await self.request(
            "POST",
            f"/Items/{item_id}",
            json=payload,
            headers={**self._api_headers(), "Content-Type": "application/json"},
            expect_json=False,
        )

    async def upload_primary_image(
        self, item_id: str, data: bytes, *, mime_type: str = "image/jpeg"
    ) -> None:
        """Set the front cover of an item, the way the web client does.

        This bypasses the image providers entirely, which is the whole point:
        the picture lands in the Jellyfin metadata folder even when the local
        image provider refuses to see the file next to the tracks.

        The body has to be the base64 form of the picture with an explicit mime
        type. Jellyfin decodes base64 from the request body and answers
        ``400 Incorrect ContentType`` on ``image/*``. Should a future release
        expect raw bytes instead, the binary form is tried as a fallback.
        """
        headers = {**self._api_headers(), "Content-Type": mime_type}
        try:
            await self.request(
                "POST",
                f"/Items/{item_id}/Images/Primary",
                content=base64.b64encode(data),
                headers=headers,
                expect_json=False,
                timeout=httpx.Timeout(60.0, connect=10.0),
            )
        except ServiceError as exc:
            if exc.status_code not in (400, 415, 500):
                raise
            logger.debug("Base64 upload refused for %s (%s), trying raw bytes", item_id, exc)
            await self.request(
                "POST",
                f"/Items/{item_id}/Images/Primary",
                content=data,
                headers=headers,
                expect_json=False,
                timeout=httpx.Timeout(60.0, connect=10.0),
            )

    def image_url(self, item_id: str, tag: str | None = None, max_height: int = 500) -> str:
        url = f"{self.base_url}/Items/{item_id}/Images/Primary?fillHeight={max_height}&quality=90"
        if tag:
            url += f"&tag={tag}"
        return url

    async def test_connection(self) -> dict[str, Any]:
        info = await self.get_system_info()
        libraries = await self.get_music_libraries()
        return {
            "server_name": info.get("ServerName"),
            "version": info.get("Version"),
            "music_libraries": libraries,
        }


def container_is_lossless(container: str | None, path: str | None = None) -> bool:
    value = (container or "").lower().strip()
    if not value and path:
        value = path.rsplit(".", 1)[-1].lower() if "." in path else ""
    return value in LOSSLESS_CONTAINERS
