"""
Extract embedded album art from media files (music, video, podcasts,
audiobooks) using mutagen.

Supports: MP3, M4A/AAC, M4B (audiobook), M4V/MP4 (video), FLAC,
OGG Vorbis, OPUS, WMA, AIFF/WAV

For video files without embedded cover art, falls back to extracting
a thumbnail frame using ffmpeg (if available).
"""

import hashlib
import logging
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

try:
    import mutagen
    MUTAGEN_AVAILABLE = True
except ImportError:
    MUTAGEN_AVAILABLE = False
    logger.warning("mutagen not installed - art extraction disabled")


def extract_art(file_path: str) -> Optional[bytes]:
    """
    Extract the first embedded album art image from a media file.

    Args:
        file_path: Path to the media file

    Returns:
        Raw image bytes (JPEG/PNG) or None if no art found
    """
    if not MUTAGEN_AVAILABLE:
        return None

    path = Path(file_path)
    ext = path.suffix.lower()

    try:
        if ext == '.mp3':
            return _extract_mp3(file_path)
        elif ext in ('.m4a', '.m4p', '.m4b', '.aac', '.alac'):
            return _extract_mp4(file_path)
        elif ext in ('.m4v', '.mp4', '.mov'):
            # Video files may have embedded cover art in the covr atom.
            # Fall back to extracting a thumbnail frame via ffmpeg.
            art = _extract_mp4(file_path)
            if art:
                return art
            return _extract_video_frame(file_path)
        elif ext == '.flac':
            return _extract_flac(file_path)
        elif ext == '.ogg':
            return _extract_ogg(file_path)
        elif ext == '.opus':
            return _extract_opus(file_path)
        elif ext in ('.aif', '.aiff'):
            return _extract_aiff(file_path)
        else:
            # Try generic mutagen
            return _extract_generic(file_path)
    except Exception as e:
        logger.warning(f"ART: Failed to extract art from {file_path}: {e}")
        return None


def _extract_mp3(path: str) -> Optional[bytes]:
    """Extract art from MP3 (ID3v2 APIC frames)."""
    from mutagen.mp3 import MP3

    audio = MP3(path)
    if audio.tags is None:
        return None

    # Look for APIC frames (cover art)
    for key in audio.tags:
        if key.startswith('APIC'):
            frame = audio.tags[key]
            if frame.data:
                return frame.data
    return None


def _extract_mp4(path: str) -> Optional[bytes]:
    """Extract art from M4A/AAC (covr atom)."""
    from mutagen.mp4 import MP4

    audio = MP4(path)
    if audio.tags is None:
        return None

    covers = audio.tags.get('covr', [])
    if covers:
        return bytes(covers[0])
    return None


def _extract_flac(path: str) -> Optional[bytes]:
    """Extract art from FLAC (picture blocks)."""
    from mutagen.flac import FLAC

    audio = FLAC(path)
    if audio.pictures:
        return audio.pictures[0].data
    return None


def _extract_ogg(path: str) -> Optional[bytes]:
    """Extract art from Ogg Vorbis (METADATA_BLOCK_PICTURE)."""
    from mutagen.oggvorbis import OggVorbis

    audio = OggVorbis(path)
    return _extract_vorbis_picture(audio)


def _extract_opus(path: str) -> Optional[bytes]:
    """Extract art from Opus (METADATA_BLOCK_PICTURE)."""
    from mutagen.oggopus import OggOpus

    audio = OggOpus(path)
    return _extract_vorbis_picture(audio)


def _extract_vorbis_picture(audio) -> Optional[bytes]:
    """Extract art from Vorbis comment METADATA_BLOCK_PICTURE."""
    import base64

    pictures = audio.get('metadata_block_picture', [])
    if pictures:
        try:
            from mutagen.flac import Picture
            pic = Picture(base64.b64decode(pictures[0]))
            return pic.data
        except Exception:
            pass
    return None


def _extract_aiff(path: str) -> Optional[bytes]:
    """Extract art from AIFF (ID3v2 APIC frames)."""
    from mutagen.aiff import AIFF

    audio = AIFF(path)
    if audio.tags is None:
        return None
    for key in audio.tags:
        if key.startswith('APIC'):
            return audio.tags[key].data
    return None


def _extract_generic(path: str) -> Optional[bytes]:
    """Try generic mutagen extraction."""
    audio = mutagen.File(path)  # type: ignore[union-attr]
    if audio is None or audio.tags is None:
        return None

    # Try ID3 APIC
    for key in audio.tags:
        if hasattr(key, 'startswith') and key.startswith('APIC'):
            frame = audio.tags[key]
            if hasattr(frame, 'data'):
                return frame.data

    # Try MP4 covr
    covers = audio.tags.get('covr', [])
    if covers:
        return bytes(covers[0])

    return None


def _find_ffmpeg() -> Optional[str]:
    """Locate ffmpeg binary."""
    # Check SyncEngine's finder first (respects bundled ffmpeg)
    try:
        from SyncEngine.transcoder import find_ffmpeg
        path = find_ffmpeg()
        if path:
            return path
    except Exception:
        pass
    return shutil.which("ffmpeg")


def _extract_video_frame(file_path: str) -> Optional[bytes]:
    """Extract a thumbnail frame from a video file using ffmpeg.

    Seeks to 10% of the duration (or 5 seconds if duration unknown) and
    grabs a single JPEG frame scaled to fit within 320x320.  This provides
    a reasonable poster image for videos without embedded cover art.

    Returns raw JPEG bytes, or None if ffmpeg is unavailable or fails.
    """
    ffmpeg = _find_ffmpeg()
    if not ffmpeg:
        logger.debug("ART: ffmpeg not found, cannot extract video thumbnail")
        return None

    _SP_KWARGS = {}
    if sys.platform == "win32":
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        _SP_KWARGS["startupinfo"] = si

    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
            tmp_path = tmp.name

        cmd = [
            ffmpeg,
            "-ss", "5",                 # seek to 5 seconds
            "-i", str(file_path),
            "-frames:v", "1",            # single frame
            "-vf", "scale='min(320,iw)':'min(320,ih)':force_original_aspect_ratio=decrease",
            "-q:v", "2",                 # JPEG quality (2 = high)
            "-y",
            tmp_path,
        ]

        result = subprocess.run(
            cmd,
            capture_output=True,
            timeout=15,
            **_SP_KWARGS,
        )

        tmp_file = Path(tmp_path)
        if result.returncode == 0 and tmp_file.exists() and tmp_file.stat().st_size > 0:
            art_bytes = tmp_file.read_bytes()
            tmp_file.unlink(missing_ok=True)
            logger.debug("ART: extracted video thumbnail from %s (%d bytes)",
                         file_path, len(art_bytes))
            return art_bytes
        else:
            tmp_file.unlink(missing_ok=True)
            logger.debug("ART: ffmpeg frame extraction failed for %s", file_path)
            return None

    except Exception as e:
        logger.debug("ART: video frame extraction error for %s: %s", file_path, e)
        # Clean up temp file on error
        if tmp_path:
            try:
                Path(tmp_path).unlink(missing_ok=True)
            except Exception:
                pass
        return None


def art_hash(art_bytes: bytes) -> str:
    """
    Compute a hash of album art bytes for deduplication.

    Tracks with identical art will share the same ArtworkDB entry.
    """
    return hashlib.md5(art_bytes).hexdigest()


def embed_art(file_path: str, art_bytes: bytes, mime_type: str = "image/jpeg") -> bool:
    """Embed album art into a media file, replacing any existing cover art.

    Supports MP3, M4A/M4B/AAC, FLAC, OGG Vorbis, OPUS, AIFF.

    Args:
        file_path: Path to the audio file to modify in-place.
        art_bytes: Raw image bytes (JPEG or PNG).
        mime_type: MIME type of the image ("image/jpeg" or "image/png").

    Returns:
        True on success, False if the format is unsupported or mutagen unavailable.
    """
    if not MUTAGEN_AVAILABLE:
        return False

    path = Path(file_path)
    ext = path.suffix.lower()

    try:
        if ext == ".mp3":
            return _embed_mp3(file_path, art_bytes, mime_type)
        elif ext in (".m4a", ".m4p", ".m4b", ".aac", ".alac", ".m4v", ".mp4"):
            return _embed_mp4(file_path, art_bytes, mime_type)
        elif ext == ".flac":
            return _embed_flac(file_path, art_bytes, mime_type)
        elif ext == ".ogg":
            return _embed_ogg(file_path, art_bytes, mime_type)
        elif ext == ".opus":
            return _embed_opus(file_path, art_bytes, mime_type)
        elif ext in (".aif", ".aiff"):
            return _embed_aiff(file_path, art_bytes, mime_type)
        else:
            logger.debug("embed_art: unsupported format %s", ext)
            return False
    except Exception as e:
        logger.warning("embed_art: failed for %s: %s", file_path, e)
        return False


def _embed_mp3(path: str, art_bytes: bytes, mime_type: str) -> bool:
    from mutagen.mp3 import MP3
    from mutagen.id3 import ID3, APIC, ID3NoHeaderError

    try:
        tags = ID3(path)
    except ID3NoHeaderError:
        tags = ID3()

    tags.delall("APIC")
    tags.add(APIC(
        encoding=3,       # UTF-8
        mime=mime_type,
        type=3,           # Cover (front)
        desc="Cover",
        data=art_bytes,
    ))
    tags.save(path)
    return True


def _embed_mp4(path: str, art_bytes: bytes, mime_type: str) -> bool:
    from mutagen.mp4 import MP4, MP4Cover

    fmt = MP4Cover.FORMAT_PNG if "png" in mime_type else MP4Cover.FORMAT_JPEG
    audio = MP4(path)
    if audio.tags is None:
        audio.add_tags()
    audio.tags["covr"] = [MP4Cover(art_bytes, imageformat=fmt)]
    audio.save()
    return True


def _embed_flac(path: str, art_bytes: bytes, mime_type: str) -> bool:
    from mutagen.flac import FLAC, Picture

    audio = FLAC(path)
    pic = Picture()
    pic.type = 3          # Cover (front)
    pic.mime = mime_type
    pic.data = art_bytes
    audio.clear_pictures()
    audio.add_picture(pic)
    audio.save()
    return True


def _embed_ogg(path: str, art_bytes: bytes, mime_type: str) -> bool:
    from mutagen.oggvorbis import OggVorbis
    return _embed_vorbis(OggVorbis(path), path, art_bytes, mime_type)


def _embed_opus(path: str, art_bytes: bytes, mime_type: str) -> bool:
    from mutagen.oggopus import OggOpus
    return _embed_vorbis(OggOpus(path), path, art_bytes, mime_type)


def _embed_vorbis(audio, path: str, art_bytes: bytes, mime_type: str) -> bool:
    import base64
    from mutagen.flac import Picture

    pic = Picture()
    pic.type = 3
    pic.mime = mime_type
    pic.data = art_bytes
    encoded = base64.b64encode(pic.write()).decode("ascii")
    audio["metadata_block_picture"] = [encoded]
    audio.save(path)
    return True


def _embed_aiff(path: str, art_bytes: bytes, mime_type: str) -> bool:
    from mutagen.aiff import AIFF
    from mutagen.id3 import APIC

    audio = AIFF(path)
    if audio.tags is None:
        audio.add_tags()
    audio.tags.delall("APIC")
    audio.tags.add(APIC(
        encoding=3,
        mime=mime_type,
        type=3,
        desc="Cover",
        data=art_bytes,
    ))
    audio.save()
    return True
