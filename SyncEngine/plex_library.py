"""
Plex Library - Connects to a Plex Music server and downloads tracks on demand.

Provides helpers for:
- PIN-based OAuth login (via plexapi.myplex.MyPlexPinLogin)
- Listing music server resources from a Plex account
- Browsing albums
- Downloading a single album to a local directory so PCLibrary can scan it

The downloaded folder is a plain directory of audio files that the existing
SyncEngine (PCLibrary → FingerprintDiffEngine → SyncExecutor) handles
without any modifications.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional, Callable

logger = logging.getLogger(__name__)

PLEXAPI_AVAILABLE = False
try:
    import plexapi  # noqa: F401
    PLEXAPI_AVAILABLE = True
except ImportError:
    logger.warning("plexapi not installed — Plex sync unavailable. Run: pip install plexapi")


# ── Connection ───────────────────────────────────────────────────────────────

def connect(base_url: str, token: str):
    """Return a connected PlexServer or raise on failure."""
    _require_plexapi()
    from plexapi.server import PlexServer
    return PlexServer(base_url, token, timeout=15)


def _require_plexapi():
    if not PLEXAPI_AVAILABLE:
        raise ImportError(
            "plexapi is not installed.\n"
            "Install it with:  pip install plexapi"
        )


# ── Server discovery ─────────────────────────────────────────────────────────

def get_servers_for_token(token: str) -> list[dict]:
    """Return list of Plex server info dicts for the given account token.

    Each dict has keys: name, clientIdentifier, owned, connections (list of URLs).
    Connections are ordered: local first, then relay.
    """
    _require_plexapi()
    from plexapi.myplex import MyPlexAccount

    account = MyPlexAccount(token=token)
    servers = []
    for resource in account.resources():
        if "server" not in resource.provides:
            continue
        connections = [c.uri for c in resource.connections if c.uri]
        # Put local (non-relay) connections first
        local = [c.uri for c in resource.connections if not c.relay and c.uri]
        remote = [c.uri for c in resource.connections if c.relay and c.uri]
        servers.append({
            "name": resource.name,
            "clientIdentifier": resource.clientIdentifier,
            "owned": resource.owned,
            "connections": local + remote,
        })
    return servers


def connect_best(token: str, server_info: dict, timeout: int = 10):
    """Try each connection URL for a server and return the first that works.

    Raises ConnectionError if all connections fail.
    """
    _require_plexapi()
    from plexapi.server import PlexServer

    errors = []
    for url in server_info.get("connections", []):
        try:
            server = PlexServer(url, token, timeout=timeout)
            # Quick sanity check
            _ = server.friendlyName
            return server, url
        except Exception as e:
            errors.append(f"{url}: {e}")

    raise ConnectionError(
        f"Could not connect to '{server_info.get('name', 'server')}'.\n"
        + "\n".join(errors)
    )


# ── Music library browsing ───────────────────────────────────────────────────

def get_music_section(server):
    """Return the first artist/music library section on the server."""
    sections = [s for s in server.library.sections() if s.type == "artist"]
    if not sections:
        raise ValueError("No Music library found on this Plex server.")
    return sections[0]


def search_albums(server, query: str = "", limit: int = 500) -> list:
    """Return Album objects matching query (or all albums if query is empty)."""
    music = get_music_section(server)
    if query:
        return music.searchAlbums(title=query, maxresults=limit)
    return music.albums()[:limit]


# ── Album art ─────────────────────────────────────────────────────────────────

def fetch_album_art(server, album) -> Optional[bytes]:
    """Download the album thumbnail from Plex and return raw image bytes.

    Returns None if no thumbnail is available or the request fails.
    """
    import requests

    thumb = getattr(album, "thumb", None)
    if not thumb:
        return None

    token = server._token  # type: ignore[attr-defined]
    base_url = server._baseurl  # type: ignore[attr-defined]
    url = f"{base_url}{thumb}?X-Plex-Token={token}"

    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        return resp.content
    except Exception as e:
        logger.warning("Could not fetch album art for '%s': %s", getattr(album, "title", "?"), e)
        return None


# ── Downloading ───────────────────────────────────────────────────────────────

def download_album(
    server,
    album,
    dest_dir: str,
    progress_callback: Optional[Callable[[int, int, str], None]] = None,
    is_cancelled: Optional[Callable[[], bool]] = None,
) -> list[str]:
    """Download all tracks in *album* to *dest_dir*.

    Args:
        server: Connected plexapi PlexServer instance.
        album:  plexapi Album object.
        dest_dir: Local directory to download into (must already exist).
        progress_callback: Called with (current, total, track_title).
        is_cancelled: Returns True to abort download.

    Returns:
        List of absolute paths to downloaded files.
    """
    import requests
    import shutil

    tracks = album.tracks()
    total = len(tracks)
    downloaded: list[str] = []

    token = server._token  # type: ignore[attr-defined]
    base_url = server._baseurl  # type: ignore[attr-defined]

    for i, track in enumerate(tracks, 1):
        if is_cancelled and is_cancelled():
            break

        if progress_callback:
            progress_callback(i, total, track.title)

        # Get first media part
        try:
            part = track.media[0].parts[0]
        except (IndexError, AttributeError):
            logger.warning("No media parts for track: %s", track.title)
            continue

        # Build download URL
        url = f"{base_url}{part.key}?X-Plex-Token={token}"

        # Determine extension: prefer part.container (reliable) over the server
        # file path (can be None or mismatched).  e.g. container="flac" → ".flac"
        container = getattr(part, "container", None) or getattr(track.media[0], "container", None)
        if container:
            ext = f".{container.lower().split('.')[-1]}"
        else:
            server_filename = part.file or ""
            ext = Path(server_filename).suffix.lower() if server_filename else ""
        if not ext:
            ext = ".mp3"

        # Safe filename: disc-track title.ext
        disc = getattr(track, "discNumber", None) or 1
        track_num = getattr(track, "trackNumber", None) or i
        safe_title = _safe_name(track.title)
        filename = f"{disc:02d}-{track_num:02d} {safe_title}{ext}"
        dest_path = os.path.join(dest_dir, filename)

        try:
            resp = requests.get(url, stream=True, timeout=60)
            resp.raise_for_status()
            with open(dest_path, "wb") as f:
                shutil.copyfileobj(resp.raw, f)
            downloaded.append(dest_path)
            logger.debug("Downloaded %s → %s", track.title, filename)
        except Exception as e:
            logger.error("Failed to download '%s': %s", track.title, e)

    # Fetch album art from Plex and embed into every downloaded file
    if downloaded:
        art_bytes = fetch_album_art(server, album)
        if art_bytes:
            try:
                from ArtworkDB_Writer.art_extractor import embed_art
                mime = "image/png" if art_bytes[:4] == b"\x89PNG" else "image/jpeg"
                embedded = 0
                for fpath in downloaded:
                    if embed_art(fpath, art_bytes, mime):
                        embedded += 1
                logger.info(
                    "Embedded album art into %d/%d tracks for '%s'",
                    embedded, len(downloaded), getattr(album, "title", "?"),
                )
            except Exception as e:
                logger.warning("Could not embed album art: %s", e)

    return downloaded


def _safe_name(name: str, max_len: int = 80) -> str:
    """Strip characters that are unsafe in filenames."""
    safe = "".join(c for c in name if c not in r'\/:*?"<>|').strip()
    return safe[:max_len] if safe else "unknown"
