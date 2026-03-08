"""
Pinepods Library — Browse podcasts and download episodes from a Pinepods server.

API: GET /api/data/get_key  (Basic Auth)  → api_key
     GET /api/data/get_user (Api-Key hdr) → user_id
     GET /api/data/return_pods/{user_id}  → podcast list
     GET /api/data/podcast_episodes?user_id=X&podcast_id=Y → episode list
     GET /api/data/stream/{episode_id}?api_key=K&user_id=U → audio stream
"""

from __future__ import annotations

import base64
import logging
import os
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger(__name__)

try:
    import requests as _req
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False


def _hdrs(api_key: str) -> dict:
    return {"Api-Key": api_key}


# ── Authentication ─────────────────────────────────────────────────────────────

def authenticate(base_url: str, username: str, password: str) -> tuple[str, int]:
    """
    Log in to a Pinepods server with username+password.

    Returns (api_key, user_id).  Raises RuntimeError on failure.
    """
    if not REQUESTS_AVAILABLE:
        raise RuntimeError(
            "requests library not installed.\nRun: uv add requests"
        )
    import requests

    base_url = base_url.rstrip("/")
    creds = base64.b64encode(f"{username}:{password}".encode()).decode()
    resp = requests.get(
        f"{base_url}/api/data/get_key",
        headers={"Authorization": f"Basic {creds}"},
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()

    if data.get("status") == "mfa_required":
        raise RuntimeError(
            "MFA is enabled on this account — MFA login is not yet supported."
        )
    api_key = data.get("retrieved_key")
    if not api_key:
        raise RuntimeError(f"Authentication failed: {data}")

    resp2 = requests.get(
        f"{base_url}/api/data/get_user",
        headers=_hdrs(api_key),
        timeout=15,
    )
    resp2.raise_for_status()
    user_id = resp2.json().get("retrieved_id")
    if not user_id:
        raise RuntimeError("Could not retrieve user ID from server.")

    return api_key, int(user_id)


# ── Data fetching ──────────────────────────────────────────────────────────────

def get_podcasts(base_url: str, api_key: str, user_id: int) -> list[dict]:
    """Return subscribed podcast list."""
    import requests
    resp = requests.get(
        f"{base_url.rstrip('/')}/api/data/return_pods/{user_id}",
        headers=_hdrs(api_key),
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json().get("pods", [])


def get_episodes(base_url: str, api_key: str, user_id: int, podcast_id: int) -> list[dict]:
    """Return episode list for a podcast."""
    import requests
    resp = requests.get(
        f"{base_url.rstrip('/')}/api/data/podcast_episodes",
        params={"user_id": user_id, "podcast_id": podcast_id},
        headers=_hdrs(api_key),
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json().get("episodes", [])


# ── Download ───────────────────────────────────────────────────────────────────

def _ep_field(episode: dict, *keys: str):
    """Case-insensitive field lookup across multiple key name variants."""
    for key in keys:
        if key in episode:
            return episode[key]
    # Fallback: case-insensitive search
    lower_map = {k.lower(): v for k, v in episode.items()}
    for key in keys:
        v = lower_map.get(key.lower())
        if v is not None:
            return v
    return None


def download_episode(
    base_url: str,
    api_key: str,
    user_id: int,
    episode: dict,
    dest_dir: str,
    progress_callback: Optional[Callable[[int, int], None]] = None,
    is_cancelled: Optional[Callable[[], bool]] = None,
) -> Optional[str]:
    """
    Download one episode to dest_dir.

    Tries in order:
      1. Pinepods stream proxy  (/api/data/stream/<id>)
      2. Direct episode URL stored in the episode dict (RSS enclosure URL)

    Returns the local file path or None on failure.
    """
    import requests

    episode_id = _ep_field(episode, "EpisodeId", "Episodeid", "episode_id", "id")
    title = _ep_field(episode, "EpisodeTitle", "Episodetitle", "episode_title") or f"ep_{episode_id}"
    safe = "".join(c if c.isalnum() or c in " -_." else "_" for c in title).strip()[:80]

    def _ext_from_content_type(ct: str) -> str:
        ct = ct.lower()
        if "m4a" in ct or "mp4" in ct or "aac" in ct:
            return ".m4a"
        if "ogg" in ct:
            return ".ogg"
        return ".mp3"

    def _stream(url: str, headers: dict, params: dict) -> Optional[str]:
        dest_path = os.path.join(dest_dir, f"{safe}.mp3")
        try:
            with requests.get(url, params=params, headers=headers,
                              stream=True, timeout=60, allow_redirects=True) as resp:
                resp.raise_for_status()
                ext = _ext_from_content_type(resp.headers.get("Content-Type", ""))
                dest_path = os.path.join(dest_dir, f"{safe}{ext}")
                total = int(resp.headers.get("Content-Length", 0))
                done = 0
                with open(dest_path, "wb") as f:
                    for chunk in resp.iter_content(chunk_size=65536):
                        if is_cancelled and is_cancelled():
                            return None
                        if chunk:
                            f.write(chunk)
                            done += len(chunk)
                            if progress_callback:
                                progress_callback(done, total)
            return dest_path
        except Exception as exc:
            logger.warning("Stream attempt failed (%s): %s", url, exc)
            # Clean up partial file
            try:
                if os.path.exists(dest_path):
                    os.unlink(dest_path)
            except OSError:
                pass
            return None

    # ── Attempt 1: Pinepods stream proxy ─────────────────────────────────────
    if episode_id:
        proxy_url = f"{base_url.rstrip('/')}/api/data/stream/{episode_id}"
        result = _stream(
            proxy_url,
            headers=_hdrs(api_key),
            params={"api_key": api_key, "user_id": user_id},
        )
        if result:
            _embed_podcast_tags(result, episode)
            return result
        logger.warning("Proxy stream failed for episode %s — trying direct URL", episode_id)

    # ── Attempt 2: Direct RSS enclosure URL ───────────────────────────────────
    direct_url = _ep_field(episode, "EpisodeUrl", "Episodeurl", "episode_url", "url")
    if direct_url:
        result = _stream(direct_url, headers={}, params={})
        if result:
            _embed_podcast_tags(result, episode)
            return result

    logger.error("All download attempts failed for episode %s (%s)", episode_id, title)
    return None


def _embed_podcast_tags(file_path: str, episode: dict) -> None:
    """
    Embed podcast metadata (title, show, podcast flag, artwork) into the file
    so pc_library.py detects it as a podcast and the iPod displays it correctly.
    """
    try:
        import mutagen  # type: ignore
        ext = Path(file_path).suffix.lower()
        title = episode.get("Episodetitle") or episode.get("episode_title") or ""
        show  = episode.get("podcastname") or ""
        pub   = (episode.get("Episodepubdate") or episode.get("episode_pub_date") or "")[:4]
        art_url = episode.get("Episodeartwork") or ""

        art_bytes: Optional[bytes] = None
        if art_url:
            try:
                import requests
                r = requests.get(art_url, timeout=10)
                if r.ok:
                    art_bytes = r.content
            except Exception:
                pass

        if ext == ".mp3":
            from mutagen.id3 import ID3, TIT2, TPE1, TALB, PCST, TDRC, APIC  # type: ignore
            try:
                tags = ID3(file_path)
            except Exception:
                from mutagen.id3 import ID3NoHeaderError  # type: ignore
                tags = ID3()
            tags["TIT2"] = TIT2(encoding=3, text=title)
            tags["TPE1"] = TPE1(encoding=3, text=show)
            tags["TALB"] = TALB(encoding=3, text=show)
            tags["PCST"] = PCST()
            if pub:
                tags["TDRC"] = TDRC(encoding=3, text=pub)
            if art_bytes:
                tags["APIC"] = APIC(
                    encoding=0, mime="image/jpeg", type=3, desc="Cover", data=art_bytes
                )
            tags.save(file_path)

        elif ext in (".m4a", ".mp4", ".aac"):
            from mutagen.mp4 import MP4, MP4Cover  # type: ignore
            audio = MP4(file_path)
            if audio.tags is None:
                audio.add_tags()
            audio.tags["\xa9nam"] = [title]
            audio.tags["\xa9ART"] = [show]
            audio.tags["\xa9alb"] = [show]
            audio.tags["stik"]    = [21]    # Podcast media kind
            audio.tags["pcst"]    = [True]  # Podcast flag
            if pub:
                audio.tags["\xa9day"] = [pub]
            if art_bytes:
                audio.tags["covr"] = [MP4Cover(art_bytes, MP4Cover.FORMAT_JPEG)]
            audio.save()

    except Exception as exc:
        logger.warning("Could not embed podcast tags in %s: %s", file_path, exc)
