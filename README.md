# iOpenPod — Plex & Pinepods Fork

> **Credit where it's due:** Massive thanks to [TheRealSavi](https://github.com/TheRealSavi) for doing 99% of the actual legwork — reverse-engineering the iTunesDB/ArtworkDB binary formats, implementing the hash/checksum logic for every iPod generation, building the fingerprint-based sync engine, and creating the whole foundation this fork is built on. This fork just bolts Plex and Pinepods onto something that already worked really well.

**Sync your iPod from Plex, Pinepods, or your local music library — no iTunes required.**

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.13+](https://img.shields.io/badge/Python-3.13%2B-3776AB.svg)](https://www.python.org/)
[![PyQt6](https://img.shields.io/badge/GUI-PyQt6-41CD52.svg)](https://www.riverbankcomputing.com/software/pyqt/)

This is a fork of [TheRealSavi/iOpenPod](https://github.com/TheRealSavi/iOpenPod) that adds **Plex Media Server integration**, **Pinepods podcast sync**, an **iPod file browser**, and a **light theme** on top of the core iPod sync engine.

![Album Browser](screenshots/albums.png)

---

## What's New in This Fork

### Plex Sync
Browse your Plex Music library directly in iOpenPod and sync albums straight to your iPod. Uses PIN-based OAuth — no password stored.

1. Click **Plex** in the sidebar
2. Sign in with your Plex account in the browser
3. Pick your music server and browse albums
4. Select an album → **Add to iPod** — it downloads, fingerprints, and syncs

Requires `plexapi`: `uv add plexapi` or `pip install plexapi`.

### Pinepods Podcast Sync
Browse podcast episodes from a self-hosted [Pinepods](https://www.pinepods.online/) server and push them to your iPod.

1. Click **Podcasts** in the sidebar
2. Enter your Pinepods server URL and credentials
3. Pick a podcast and episode → it streams, downloads, and syncs

Requires `requests`: `uv add requests` or `pip install requests`.

### iPod Browser
Browse the files and folder structure on your iPod directly from the app — useful for debugging or checking what's actually on the device.

### Light Theme
Toggle between dark and light themes from the settings page.

### Fuzzy Search
The track list now supports fuzzy search — find tracks even with partial or imprecise matches.

---

## Get Started

You'll need **Python 3.13+**. For transcoding, install **[FFmpeg](https://ffmpeg.org/)**. For fingerprinting, install **[Chromaprint](https://acoustid.org/chromaprint)**.

**With [uv](https://docs.astral.sh/uv/) (recommended):**

```bash
git clone https://github.com/XWBarton/iopenpod-plex.git
cd iopenpod-plex
uv sync
uv run python main.py
```

**With pip:**

```bash
git clone https://github.com/XWBarton/iopenpod-plex.git
cd iopenpod-plex
pip install -e .
python main.py
```

**Optional dependencies (install as needed):**

```bash
pip install plexapi   # Plex sync
pip install requests  # Pinepods sync
```

---

## How to Use

1. **Plug in your iPod** — it mounts as a regular drive
2. **Pick your device** — iOpenPod scans for connected iPods automatically
3. **Browse** — flip through albums, tracks, playlists, and artwork
4. **Sync** — choose your music folder, Plex library, or Pinepods feed; review what'll change and hit go

![Device Picker](screenshots/devicepicker.png)

---

## Core Features

**Sync music from any format.** Drop in FLAC, OGG, WMA, MP3, AAC — iOpenPod transcodes whatever the iPod can't play natively into ALAC or AAC. Converted files are cached so repeat syncs are fast.

**Keep play counts and ratings in sync.** When you listen on the iPod, those play counts and ratings come back to your library. You pick the conflict strategy.

**Album art just works.** Art gets extracted from your files, resized, and written in the iPod's RGB565 format. No extra steps.

**Review before you commit.** Every sync shows you exactly what's about to happen — new tracks, removals, metadata updates — with checkboxes for each item. Nothing changes until you say so.

![Sync Review](screenshots/syncreview.png)

**Playlists and smart playlists.** Browse and manage standard playlists. Smart playlists with rule-based filtering are supported too.

![Playlists](screenshots/playlists.png)

**Backups with one-click restore.** A snapshot of your iPod database is saved before every sync. If something goes wrong, roll back instantly.

![Backups](screenshots/backups.png)

**Configurable.** Tweak transcoding settings, sync behavior, theme, and more from the settings page.

![Settings](screenshots/settings.png)

---

## Supported iPods

| Device | Read | Write | Notes |
|--------|------|-------|-------|
| iPod 1G–5G, Mini, Photo | ✅ | ✅ | No hash required |
| iPod Classic (all gens) | ✅ | ✅ | Uses FireWire ID from SysInfo |
| iPod Nano 1G–2G | ✅ | ✅ | No hash required |
| iPod Nano 3G–4G | ✅ | ✅ | Uses FireWire ID from SysInfo |
| iPod Nano 5G | ✅ | ✅ | Needs one iTunes sync for HashInfo |
| iPod Nano 6G–7G | ✅ | ✅ | HASHAB via WebAssembly |

---

## Project Layout

```
iOpenPod/
├── GUI/                    # PyQt6 interface
│   ├── app.py              # Main window, device management
│   └── widgets/            # Album grid, track list, sidebar, Plex/Pinepods browsers, sync review, etc.
├── iTunesDB_Parser/        # Reads iPod's binary iTunesDB
├── iTunesDB_Writer/        # Writes iTunesDB with hash/checksum support
├── ArtworkDB_Parser/       # Reads ArtworkDB binary format
├── ArtworkDB_Writer/       # Writes album art to .ithmb files
├── SyncEngine/             # Fingerprinting, diffing, transcoding, Plex/Pinepods libraries, sync execution
└── main.py                 # Entry point
```

---

## Upstream

This fork tracks [TheRealSavi/iOpenPod](https://github.com/TheRealSavi/iOpenPod). For issues unrelated to Plex/Pinepods, consider checking or filing issues upstream.

Related projects:

- [libgpod](https://github.com/gtkpod/libgpod) — C library for iPod database access
- [Rockbox](https://www.rockbox.org/) — Open-source firmware replacement for iPods
- [Pinepods](https://www.pinepods.online/) — Self-hosted podcast manager

## License

MIT — see [LICENSE](LICENSE).
