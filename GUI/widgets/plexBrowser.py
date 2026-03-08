"""
Plex Browser - Browse a Plex Music library and add albums to an iPod.

Contains:
  PlexBrowserDialog  — QDialog that handles login + album browsing.
  PlexSyncWorker     — QThread that downloads a Plex album then computes the
                       add-only sync diff so the existing SyncReviewWidget can
                       show and execute it.

Login flow:
  1. User clicks "Sign in with Plex".
  2. We request a PIN from Plex and open the auth URL in the system browser.
  3. A QTimer polls every 2 s until the user completes login.
  4. We fetch the available Plex servers and ask the user to pick one.
  5. We save the token + server URL to settings for future sessions.

Sync flow (after the user picks an album):
  1. PlexSyncWorker downloads the album to a temp directory.
  2. It runs PCLibrary + FingerprintDiffEngine on the temp dir.
  3. It clears plan.to_remove (add-only — we never delete existing iPod tracks).
  4. It emits finished(plan, temp_dir).
  5. app.py shows the SyncReviewWidget; after execution it deletes temp_dir.
"""

from __future__ import annotations

import logging
import os
import tempfile
import shutil
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer, QUrl
from PyQt6.QtGui import QFont, QDesktopServices
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QListWidget, QListWidgetItem, QStackedWidget,
    QFrame, QProgressBar, QSplitter, QWidget, QMessageBox,
    QScrollArea, QSizePolicy,
)

from ..styles import Colors, FONT_FAMILY, Metrics, btn_css, accent_btn_css

logger = logging.getLogger(__name__)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _fuzzy_score(query: str, text: str) -> int:
    """Return a relevance score for fuzzy-matching query against text.

    Uses subsequence matching: every character of the query must appear in
    order in the text.  Consecutive character runs and prefix matches score
    higher so the best results sort to the top.

    Returns 0 if the query is not a subsequence of the text (no match).
    """
    q = query.lower()
    t = text.lower()

    # Exact substring — highest priority
    if q in t:
        bonus = 200 if t.startswith(q) else 100
        return bonus + len(q) * 10

    # Subsequence walk
    score = 0
    qi = 0
    consecutive = 0
    for ch in t:
        if qi < len(q) and ch == q[qi]:
            qi += 1
            consecutive += 1
            score += consecutive * 3   # reward runs of consecutive hits
        else:
            consecutive = 0

    return score if qi == len(q) else 0   # 0 = no match


def _label(text: str, size: int = 11, bold: bool = False,
           color: str = Colors.TEXT_PRIMARY) -> QLabel:
    lbl = QLabel(text)
    w = QFont.Weight.Bold if bold else QFont.Weight.Normal
    lbl.setFont(QFont(FONT_FAMILY, size, w))
    lbl.setStyleSheet(f"color: {color}; background: transparent; border: none;")
    return lbl


def _sep() -> QFrame:
    f = QFrame()
    f.setFixedHeight(1)
    f.setStyleSheet(f"background: {Colors.BORDER_SUBTLE}; border: none;")
    return f


# ── PIN Login Worker ──────────────────────────────────────────────────────────

class _PinPollWorker(QThread):
    """Polls Plex every 2 s until the PIN login completes."""

    succeeded = pyqtSignal(str)   # auth token
    failed = pyqtSignal(str)       # error message

    def __init__(self, pin_login, parent=None):
        super().__init__(parent)
        self._login = pin_login

    def run(self):
        try:
            # run() starts the internal polling thread with a 5-minute timeout
            self._login.run(timeout=300)
            # waitForLogin() blocks until that thread finishes
            result = self._login.waitForLogin()
            if result:
                self.succeeded.emit(self._login.token)
            else:
                self.failed.emit("Login timed out. Please try again.")
        except Exception as e:
            self.failed.emit(str(e))


# ── Server Fetch Worker ───────────────────────────────────────────────────────

class _ServerFetchWorker(QThread):
    """Fetches available Plex servers for an account token."""

    finished = pyqtSignal(list)   # list[dict]
    error = pyqtSignal(str)

    def __init__(self, token: str, parent=None):
        super().__init__(parent)
        self._token = token

    def run(self):
        try:
            from SyncEngine.plex_library import get_servers_for_token
            servers = get_servers_for_token(self._token)
            self.finished.emit(servers)
        except Exception as e:
            self.error.emit(str(e))


# ── Album Load Worker ─────────────────────────────────────────────────────────

class _AlbumLoadWorker(QThread):
    """Loads albums from a connected Plex server in the background."""

    finished = pyqtSignal(list)   # list of album dicts
    error = pyqtSignal(str)

    def __init__(self, base_url: str, token: str, query: str = "", parent=None):
        super().__init__(parent)
        self._url = base_url
        self._token = token
        self._query = query

    def run(self):
        try:
            from SyncEngine.plex_library import connect, search_albums
            server = connect(self._url, self._token)
            albums = search_albums(server, self._query)
            result = []
            for a in albums:
                result.append({
                    "rating_key": a.ratingKey,
                    "title": a.title,
                    "artist": a.parentTitle or "",
                    "year": getattr(a, "year", None) or "",
                    "track_count": getattr(a, "leafCount", None) or len(a.tracks()),
                })
            self.finished.emit(result)
        except Exception as e:
            self.error.emit(str(e))


# ── PlexSyncWorker ────────────────────────────────────────────────────────────

class PlexSyncWorker(QThread):
    """Downloads one or more Plex albums to a temp dir, then computes an add-only diff.

    Signals:
        progress(stage, current, total, message)
        finished(plan, temp_dir)  — temp_dir must be deleted after sync
        error(message)
    """

    progress = pyqtSignal(str, int, int, str)
    finished = pyqtSignal(object, str)   # (SyncPlan, temp_dir)
    error = pyqtSignal(str)

    def __init__(
        self,
        base_url: str,
        token: str,
        album_rating_key,   # int or list[int]
        ipod_tracks: list,
        ipod_path: str,
        supports_video: bool = False,
        supports_podcast: bool = True,
        parent=None,
    ):
        super().__init__(parent)
        self._url = base_url
        self._token = token
        # Normalise to list
        self._album_keys = (
            album_rating_key if isinstance(album_rating_key, list)
            else [album_rating_key]
        )
        self._ipod_tracks = ipod_tracks
        self._ipod_path = ipod_path
        self._supports_video = supports_video
        self._supports_podcast = supports_podcast
        self._temp_dir: str = ""

    def run(self):
        try:
            from SyncEngine.plex_library import connect, PLEXAPI_AVAILABLE
            from SyncEngine.pc_library import PCLibrary
            from SyncEngine.fingerprint_diff_engine import FingerprintDiffEngine

            if not PLEXAPI_AVAILABLE:
                self.error.emit(
                    "plexapi is not installed.\n"
                    "Run:  pip install plexapi"
                )
                return

            # ── 1. Connect ───────────────────────────────────────────
            self.progress.emit("plex_connect", 0, 0, "Connecting to Plex…")
            server = connect(self._url, self._token)

            # ── 2. Create temp dir and download all albums ───────────
            self._temp_dir = tempfile.mkdtemp(prefix="iopenpod_plex_")
            from SyncEngine.plex_library import download_album
            total_albums = len(self._album_keys)
            all_downloaded: list[str] = []

            for album_idx, key in enumerate(self._album_keys, 1):
                if self.isInterruptionRequested():
                    self._cleanup()
                    return

                album = server.fetchItem(key)
                album_label = f"{album.parentTitle} — {album.title}"
                tracks = album.tracks()
                total_tracks = len(tracks)

                prefix = (
                    f"[{album_idx}/{total_albums}] " if total_albums > 1 else ""
                )
                self.progress.emit(
                    "plex_download", 0, total_tracks,
                    f"{prefix}Downloading {album_label}…"
                )

                def _dl_progress(current: int, total: int, title: str,
                                  _p=prefix):
                    if self.isInterruptionRequested():
                        return
                    self.progress.emit(
                        "plex_download", current, total,
                        f"{_p}Downloading: {title}"
                    )

                downloaded = download_album(
                    server, album, self._temp_dir,
                    progress_callback=_dl_progress,
                    is_cancelled=self.isInterruptionRequested,
                )
                all_downloaded.extend(downloaded)

            if self.isInterruptionRequested():
                self._cleanup()
                return

            if not all_downloaded:
                self._cleanup()
                self.error.emit(
                    "No tracks were downloaded.\n"
                    "Check that the Plex server can reach the media files."
                )
                return

            # ── 3. Compute add-only diff ─────────────────────────────
            self.progress.emit("fingerprint", 0, 0, "Analysing downloaded tracks…")

            pc_library = PCLibrary(self._temp_dir)
            diff_engine = FingerprintDiffEngine(
                pc_library, self._ipod_path,
                supports_video=self._supports_video,
                supports_podcast=self._supports_podcast,
            )

            plan = diff_engine.compute_diff(
                self._ipod_tracks,
                progress_callback=lambda stage, cur, tot, msg:
                    self.progress.emit(stage, cur, tot, msg),
                is_cancelled=self.isInterruptionRequested,
            )

            if self.isInterruptionRequested():
                self._cleanup()
                return

            # ── 4. Strip removes — we only add, never delete ─────────
            plan.to_remove.clear()

            self.finished.emit(plan, self._temp_dir)

        except Exception as e:
            import traceback
            traceback.print_exc()
            self._cleanup()
            self.error.emit(str(e))

    def _cleanup(self):
        if self._temp_dir and os.path.isdir(self._temp_dir):
            try:
                shutil.rmtree(self._temp_dir, ignore_errors=True)
            except Exception:
                pass
        self._temp_dir = ""


# ── Login Page ────────────────────────────────────────────────────────────────

class _LoginPage(QWidget):
    """Handles PIN-based Plex OAuth + server selection."""

    # Emitted once the user has connected to a server
    connected = pyqtSignal(str, str, str)  # (base_url, token, server_name)

    _STATE_IDLE = "idle"
    _STATE_WAITING = "waiting"
    _STATE_PICKING = "picking"

    def __init__(self, parent=None):
        super().__init__(parent)
        self._token: str = ""
        self._servers: list[dict] = []
        self._pin_login = None
        self._poll_worker: Optional[_PinPollWorker] = None
        self._server_worker: Optional[_ServerFetchWorker] = None

        root = QVBoxLayout(self)
        root.setContentsMargins(32, 32, 32, 32)
        root.setSpacing(20)
        root.setAlignment(Qt.AlignmentFlag.AlignTop)

        # Icon + title
        icon = _label("♪", 36)
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(icon)

        title = _label("Connect to Plex", 18, bold=True)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(title)

        subtitle = _label(
            "Sign in with your Plex account to browse your music library\n"
            "and add albums directly to your iPod.",
            10, color=Colors.TEXT_SECONDARY,
        )
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setWordWrap(True)
        root.addWidget(subtitle)

        root.addWidget(_sep())

        # ── PIN flow ─────────────────────────────────────────────────
        self._pin_stack = QStackedWidget()

        # Page 0: "Sign in" button
        idle_widget = QWidget()
        idle_lay = QVBoxLayout(idle_widget)
        idle_lay.setContentsMargins(0, 0, 0, 0)
        idle_lay.setSpacing(12)
        idle_lay.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._sign_in_btn = QPushButton("Sign in with Plex")
        self._sign_in_btn.setFont(QFont(FONT_FAMILY, 12, QFont.Weight.DemiBold))
        self._sign_in_btn.setMinimumHeight(44)
        self._sign_in_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._sign_in_btn.setStyleSheet(accent_btn_css())
        self._sign_in_btn.clicked.connect(self._start_pin_login)
        idle_lay.addWidget(self._sign_in_btn)

        self._pin_stack.addWidget(idle_widget)   # index 0

        # Page 1: waiting for browser
        waiting_widget = QWidget()
        wait_lay = QVBoxLayout(waiting_widget)
        wait_lay.setContentsMargins(0, 0, 0, 0)
        wait_lay.setSpacing(12)
        wait_lay.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._wait_title = _label("Waiting for Plex sign-in…", 11, bold=True)
        self._wait_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        wait_lay.addWidget(self._wait_title)

        self._open_browser_btn = QPushButton("Open browser to sign in")
        self._open_browser_btn.setFont(QFont(FONT_FAMILY, 10))
        self._open_browser_btn.setMinimumHeight(36)
        self._open_browser_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._open_browser_btn.setStyleSheet(btn_css(
            bg=Colors.SURFACE_RAISED, bg_hover=Colors.SURFACE_ACTIVE,
            bg_press=Colors.SURFACE, padding="6px 20px",
        ))
        self._open_browser_btn.clicked.connect(self._reopen_browser)
        wait_lay.addWidget(self._open_browser_btn)

        wait_bar = QProgressBar()
        wait_bar.setRange(0, 0)
        wait_bar.setFixedHeight(4)
        wait_bar.setTextVisible(False)
        wait_bar.setStyleSheet(f"""
            QProgressBar {{ background: {Colors.SURFACE}; border: none; border-radius: 2px; }}
            QProgressBar::chunk {{ background: {Colors.ACCENT}; border-radius: 2px; }}
        """)
        wait_lay.addWidget(wait_bar)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setFont(QFont(FONT_FAMILY, 9))
        cancel_btn.setStyleSheet(f"color: {Colors.TEXT_TERTIARY}; background: transparent; border: none;")
        cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel_btn.clicked.connect(self._cancel_login)
        wait_lay.addWidget(cancel_btn, alignment=Qt.AlignmentFlag.AlignCenter)

        self._pin_stack.addWidget(waiting_widget)  # index 1

        # Page 2: server picker
        server_widget = QWidget()
        srv_lay = QVBoxLayout(server_widget)
        srv_lay.setContentsMargins(0, 0, 0, 0)
        srv_lay.setSpacing(8)

        srv_title = _label("Choose your Plex server", 11, bold=True)
        srv_lay.addWidget(srv_title)

        self._server_list = QListWidget()
        self._server_list.setMinimumHeight(100)
        self._server_list.setMaximumHeight(180)
        self._server_list.setStyleSheet(f"""
            QListWidget {{
                background: {Colors.SURFACE};
                border: 1px solid {Colors.BORDER};
                border-radius: {Metrics.BORDER_RADIUS}px;
                color: {Colors.TEXT_PRIMARY};
                font-family: {FONT_FAMILY};
                font-size: 11px;
            }}
            QListWidget::item:selected {{
                background: {Colors.ACCENT_DIM};
                color: {Colors.TEXT_PRIMARY};
            }}
            QListWidget::item:hover {{
                background: {Colors.SURFACE_RAISED};
            }}
        """)
        srv_lay.addWidget(self._server_list)

        self._connect_server_btn = QPushButton("Connect")
        self._connect_server_btn.setFont(QFont(FONT_FAMILY, 11, QFont.Weight.DemiBold))
        self._connect_server_btn.setMinimumHeight(40)
        self._connect_server_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._connect_server_btn.setStyleSheet(accent_btn_css())
        self._connect_server_btn.clicked.connect(self._connect_selected_server)
        srv_lay.addWidget(self._connect_server_btn)

        self._server_status = _label("", 9, color=Colors.TEXT_TERTIARY)
        self._server_status.setWordWrap(True)
        srv_lay.addWidget(self._server_status)

        self._pin_stack.addWidget(server_widget)  # index 2

        root.addWidget(self._pin_stack)

        # ── Manual URL fallback ───────────────────────────────────────
        root.addWidget(_sep())

        manual_label = _label(
            "Already have a server URL and token?",
            9, color=Colors.TEXT_TERTIARY,
        )
        manual_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(manual_label)

        manual_row = QHBoxLayout()
        manual_row.setSpacing(6)

        self._url_edit = QLineEdit()
        self._url_edit.setPlaceholderText("http://192.168.x.x:32400")
        self._url_edit.setFont(QFont(FONT_FAMILY, 10))
        self._url_edit.setStyleSheet(f"""
            QLineEdit {{
                background: {Colors.SURFACE};
                border: 1px solid {Colors.BORDER};
                border-radius: {Metrics.BORDER_RADIUS}px;
                color: {Colors.TEXT_PRIMARY};
                padding: 6px 10px;
            }}
            QLineEdit:focus {{ border-color: {Colors.ACCENT}; }}
        """)
        manual_row.addWidget(self._url_edit, stretch=2)

        self._token_edit = QLineEdit()
        self._token_edit.setPlaceholderText("Plex token")
        self._token_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self._token_edit.setFont(QFont(FONT_FAMILY, 10))
        self._token_edit.setStyleSheet(self._url_edit.styleSheet())
        manual_row.addWidget(self._token_edit, stretch=1)

        manual_connect_btn = QPushButton("Connect")
        manual_connect_btn.setFont(QFont(FONT_FAMILY, 10, QFont.Weight.DemiBold))
        manual_connect_btn.setMinimumHeight(36)
        manual_connect_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        manual_connect_btn.setStyleSheet(btn_css(
            bg=Colors.SURFACE_RAISED, bg_hover=Colors.SURFACE_ACTIVE,
            bg_press=Colors.SURFACE, padding="6px 14px",
        ))
        manual_connect_btn.clicked.connect(self._manual_connect)
        manual_row.addWidget(manual_connect_btn)

        root.addLayout(manual_row)

        self._status_label = _label("", 9, color="#ff6b6b")
        self._status_label.setWordWrap(True)
        self._status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status_label.hide()
        root.addWidget(self._status_label)

        root.addStretch()

        self._login_url: str = ""

    # ── PIN flow ──────────────────────────────────────────────────────

    def _start_pin_login(self):
        from SyncEngine.plex_library import PLEXAPI_AVAILABLE, _require_plexapi
        if not PLEXAPI_AVAILABLE:
            self._show_error(
                "plexapi is not installed.\n"
                "Run:  pip install plexapi"
            )
            return

        try:
            from plexapi.myplex import MyPlexPinLogin
            self._pin_login = MyPlexPinLogin(
                headers={"X-Plex-Product": "iOpenPod", "X-Plex-Version": "1.0"},
                oauth=True,
            )
            self._login_url = self._pin_login.oauthUrl()
        except Exception as e:
            self._show_error(f"Could not start Plex login: {e}")
            return

        # Show waiting page and open browser
        self._pin_stack.setCurrentIndex(1)
        self._open_browser()

        # Start background poller
        self._poll_worker = _PinPollWorker(self._pin_login)
        self._poll_worker.succeeded.connect(self._on_pin_succeeded)
        self._poll_worker.failed.connect(self._on_pin_failed)
        self._poll_worker.start()

    def _open_browser(self):
        if self._login_url:
            QDesktopServices.openUrl(QUrl(self._login_url))

    def _reopen_browser(self):
        self._open_browser()

    def _cancel_login(self):
        if self._poll_worker and self._poll_worker.isRunning():
            self._poll_worker.requestInterruption()
        self._pin_stack.setCurrentIndex(0)

    def _on_pin_succeeded(self, token: str):
        self._token = token
        # Save token to settings immediately
        try:
            from ..settings import get_settings
            s = get_settings()
            s.plex_token = token
            s.save()
        except Exception:
            pass
        # Now fetch server list
        self._fetch_servers(token)

    def _on_pin_failed(self, message: str):
        self._pin_stack.setCurrentIndex(0)
        self._show_error(message)

    # ── Server selection ──────────────────────────────────────────────

    def _fetch_servers(self, token: str):
        self._server_list.clear()
        self._server_status.setText("Loading servers…")
        self._pin_stack.setCurrentIndex(2)

        self._server_worker = _ServerFetchWorker(token)
        self._server_worker.finished.connect(self._on_servers_loaded)
        self._server_worker.error.connect(self._on_server_error)
        self._server_worker.start()

    def _on_servers_loaded(self, servers: list):
        self._servers = servers
        self._server_list.clear()
        self._server_status.setText("")
        if not servers:
            self._server_status.setText("No Plex servers found on this account.")
            return
        for s in servers:
            owned = " (yours)" if s.get("owned") else " (shared)"
            item = QListWidgetItem(f"{s['name']}{owned}")
            item.setData(Qt.ItemDataRole.UserRole, s)
            self._server_list.addItem(item)
        if self._server_list.count() > 0:
            self._server_list.setCurrentRow(0)

    def _on_server_error(self, message: str):
        self._server_status.setText(f"Error: {message}")

    def _connect_selected_server(self):
        item = self._server_list.currentItem()
        if not item:
            return
        server_info = item.data(Qt.ItemDataRole.UserRole)
        self._server_status.setText(f"Connecting to {server_info['name']}…")
        self._connect_server_btn.setEnabled(False)

        # Try connections in background
        token = self._token

        class _ConnectWorker(QThread):
            done = pyqtSignal(str, str)     # (url, name)
            err = pyqtSignal(str)

            def __init__(self, token, server_info):
                super().__init__()
                self._token = token
                self._info = server_info

            def run(self):
                try:
                    from SyncEngine.plex_library import connect_best
                    _, url = connect_best(self._token, self._info)
                    self.done.emit(url, self._info["name"])
                except Exception as e:
                    self.err.emit(str(e))

        self._connect_worker = _ConnectWorker(token, server_info)
        self._connect_worker.done.connect(self._on_server_connected)
        self._connect_worker.err.connect(self._on_connect_error)
        self._connect_worker.start()

    def _on_server_connected(self, url: str, name: str):
        try:
            from ..settings import get_settings
            s = get_settings()
            s.plex_url = url
            s.plex_token = self._token
            s.save()
        except Exception:
            pass
        self.connected.emit(url, self._token, name)

    def _on_connect_error(self, message: str):
        self._connect_server_btn.setEnabled(True)
        self._server_status.setText(f"Connection failed: {message}")

    # ── Manual URL ────────────────────────────────────────────────────

    def _manual_connect(self):
        url = self._url_edit.text().strip().rstrip("/")
        token = self._token_edit.text().strip()
        if not url or not token:
            self._show_error("Please enter both server URL and token.")
            return
        self._hide_error()

        class _ManualWorker(QThread):
            done = pyqtSignal(str, str)
            err = pyqtSignal(str)

            def __init__(self, url, token):
                super().__init__()
                self._url = url
                self._token = token

            def run(self):
                try:
                    from SyncEngine.plex_library import connect
                    server = connect(self._url, self._token)
                    name = server.friendlyName or self._url
                    self.done.emit(self._url, name)
                except Exception as e:
                    self.err.emit(str(e))

        self._manual_worker = _ManualWorker(url, token)
        self._manual_worker.done.connect(
            lambda u, n: self._finish_manual(u, token, n)
        )
        self._manual_worker.err.connect(
            lambda e: self._show_error(f"Connection failed: {e}")
        )
        self._manual_worker.start()

    def _finish_manual(self, url: str, token: str, name: str):
        try:
            from ..settings import get_settings
            s = get_settings()
            s.plex_url = url
            s.plex_token = token
            s.save()
        except Exception:
            pass
        self.connected.emit(url, token, name)

    # ── Utilities ─────────────────────────────────────────────────────

    def _show_error(self, msg: str):
        self._status_label.setText(msg)
        self._status_label.show()

    def _hide_error(self):
        self._status_label.hide()


# ── Album Browser Page ────────────────────────────────────────────────────────

class _BrowserPage(QWidget):
    """Browse albums on a connected Plex server and pick albums to sync."""

    # Emitted when user clicks "Add to iPod" — list of rating keys
    album_selected = pyqtSignal(str, str, list, str)  # (url, token, rating_keys, label)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._base_url: str = ""
        self._token: str = ""
        self._server_name: str = ""
        self._albums: list[dict] = []
        self._load_worker: Optional[_AlbumLoadWorker] = None

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 12, 16, 16)
        root.setSpacing(8)

        # ── Header row ────────────────────────────────────────────────
        header = QHBoxLayout()
        self._server_label = _label("", 10, color=Colors.TEXT_SECONDARY)
        header.addWidget(self._server_label)
        header.addStretch()

        self._disconnect_btn = QPushButton("Disconnect")
        self._disconnect_btn.setFont(QFont(FONT_FAMILY, 9))
        self._disconnect_btn.setStyleSheet(
            f"color: {Colors.TEXT_TERTIARY}; background: transparent; border: none;"
        )
        self._disconnect_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._disconnect_btn.clicked.connect(self._on_disconnect)
        header.addWidget(self._disconnect_btn)
        root.addLayout(header)

        # ── Search ────────────────────────────────────────────────────
        search_row = QHBoxLayout()
        search_row.setSpacing(6)

        self._search_edit = QLineEdit()
        self._search_edit.setPlaceholderText("Filter by album or artist…")
        self._search_edit.setFont(QFont(FONT_FAMILY, 11))
        self._search_edit.setStyleSheet(f"""
            QLineEdit {{
                background: {Colors.SURFACE};
                border: 1px solid {Colors.BORDER};
                border-radius: {Metrics.BORDER_RADIUS}px;
                color: {Colors.TEXT_PRIMARY};
                padding: 7px 10px;
            }}
            QLineEdit:focus {{ border-color: {Colors.ACCENT}; }}
        """)
        self._search_edit.textChanged.connect(self._on_filter)
        search_row.addWidget(self._search_edit)

        root.addLayout(search_row)

        # ── Content: album list + track list ─────────────────────────
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setHandleWidth(3)
        splitter.setStyleSheet(f"""
            QSplitter::handle {{ background: {Colors.BORDER_SUBTLE}; }}
            QSplitter::handle:hover {{ background: {Colors.ACCENT}; }}
        """)

        # Album list
        album_frame = QFrame()
        album_frame.setStyleSheet(f"""
            QFrame {{
                background: {Colors.SURFACE};
                border: 1px solid {Colors.BORDER};
                border-radius: {Metrics.BORDER_RADIUS}px;
            }}
        """)
        album_frame_lay = QVBoxLayout(album_frame)
        album_frame_lay.setContentsMargins(0, 0, 0, 0)
        album_frame_lay.setSpacing(0)

        self._album_list = QListWidget()
        self._album_list.setStyleSheet(f"""
            QListWidget {{
                background: transparent;
                border: none;
                color: {Colors.TEXT_PRIMARY};
                font-family: {FONT_FAMILY};
                font-size: 11px;
                outline: none;
            }}
            QListWidget::item {{ padding: 6px 10px; border-bottom: 1px solid {Colors.BORDER_SUBTLE}; }}
            QListWidget::item:selected {{ background: {Colors.ACCENT_DIM}; }}
            QListWidget::item:hover {{ background: {Colors.SURFACE_RAISED}; }}
        """)
        self._album_list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self._album_list.itemSelectionChanged.connect(self._on_selection_changed)
        self._album_list.currentItemChanged.connect(self._on_current_changed)
        album_frame_lay.addWidget(self._album_list)

        self._loading_bar = QProgressBar()
        self._loading_bar.setRange(0, 0)
        self._loading_bar.setFixedHeight(3)
        self._loading_bar.setTextVisible(False)
        self._loading_bar.setStyleSheet(f"""
            QProgressBar {{ background: {Colors.SURFACE}; border: none; }}
            QProgressBar::chunk {{ background: {Colors.ACCENT}; }}
        """)
        self._loading_bar.hide()
        album_frame_lay.addWidget(self._loading_bar)

        splitter.addWidget(album_frame)

        # Track list
        track_frame = QFrame()
        track_frame.setStyleSheet(album_frame.styleSheet())
        track_frame_lay = QVBoxLayout(track_frame)
        track_frame_lay.setContentsMargins(0, 0, 0, 0)
        track_frame_lay.setSpacing(0)

        self._track_header = _label("  Select an album", 10, color=Colors.TEXT_TERTIARY)
        self._track_header.setContentsMargins(10, 8, 10, 8)
        track_frame_lay.addWidget(self._track_header)
        track_frame_lay.addWidget(_sep())

        self._track_list = QListWidget()
        self._track_list.setStyleSheet(self._album_list.styleSheet())
        self._track_list.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        track_frame_lay.addWidget(self._track_list)

        splitter.addWidget(track_frame)
        splitter.setSizes([300, 300])
        root.addWidget(splitter, stretch=1)

        # ── Status + action row ───────────────────────────────────────
        bottom = QHBoxLayout()
        bottom.setSpacing(8)

        self._status_label = _label("", 9, color=Colors.TEXT_TERTIARY)
        bottom.addWidget(self._status_label)
        bottom.addStretch()

        self._add_btn = QPushButton("Add to iPod")
        self._add_btn.setFont(QFont(FONT_FAMILY, 11, QFont.Weight.DemiBold))
        self._add_btn.setMinimumHeight(40)
        self._add_btn.setMinimumWidth(140)
        self._add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._add_btn.setStyleSheet(accent_btn_css())
        self._add_btn.setEnabled(False)
        self._add_btn.clicked.connect(self._on_add_clicked)
        bottom.addWidget(self._add_btn)

        root.addLayout(bottom)

    # ── Public interface ──────────────────────────────────────────────

    def load_server(self, base_url: str, token: str, server_name: str):
        self._base_url = base_url
        self._token = token
        self._server_name = server_name
        self._server_label.setText(f"Connected to {server_name}")
        self._add_btn.setEnabled(False)
        self._load_albums()

    def disconnect_requested(self):
        """Signal emitted when user clicks Disconnect."""

    # ── Private ───────────────────────────────────────────────────────

    def _on_disconnect(self):
        # Clear stored credentials
        try:
            from ..settings import get_settings
            s = get_settings()
            s.plex_url = ""
            s.plex_token = ""
            s.save()
        except Exception:
            pass
        # Tell parent to go back to login
        dlg = self.window()
        if isinstance(dlg, PlexBrowserDialog):
            dlg._go_to_login()

    def _load_albums(self, query: str = ""):
        """Fetch all albums from Plex (ignoring query — filtering is done client-side)."""
        self._album_list.clear()
        self._track_list.clear()
        self._track_header.setText("  Select an album")
        self._add_btn.setEnabled(False)
        self._loading_bar.show()
        self._status_label.setText("Loading albums…")

        if self._load_worker and self._load_worker.isRunning():
            self._load_worker.requestInterruption()

        # Always fetch all albums; client-side fuzzy filter handles the rest
        self._load_worker = _AlbumLoadWorker(self._base_url, self._token, "")
        self._load_worker.finished.connect(self._on_albums_loaded)
        self._load_worker.error.connect(self._on_load_error)
        self._load_worker.start()

    def _on_albums_loaded(self, albums: list):
        self._albums = albums
        self._loading_bar.hide()
        # Apply any query already in the search box
        self._on_filter(self._search_edit.text())

    def _on_load_error(self, message: str):
        self._loading_bar.hide()
        self._status_label.setText(f"Error: {message}")

    def _on_filter(self, query: str):
        """Client-side fuzzy filter over the full album list."""
        self._album_list.clear()
        q = query.strip()

        if q:
            scored = [
                (a, _fuzzy_score(q, f"{a['artist']} {a['title']}"))
                for a in self._albums
            ]
            matches = [(a, s) for a, s in scored if s > 0]
            matches.sort(key=lambda x: -x[1])
            filtered = [a for a, _ in matches]
        else:
            filtered = self._albums

        for a in filtered:
            year = f" ({a['year']})" if a.get("year") else ""
            text = f"{a['artist']} — {a['title']}{year}"
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, a)
            self._album_list.addItem(item)

        count = len(filtered)
        self._status_label.setText(
            f"{count} album{'s' if count != 1 else ''}" if count else "No albums found."
        )

    def _on_selection_changed(self):
        """Update button label whenever the selection set changes."""
        selected = self._album_list.selectedItems()
        n = len(selected)
        if n == 0:
            self._add_btn.setEnabled(False)
            self._add_btn.setText("Add to iPod")
        else:
            self._add_btn.setEnabled(True)
            self._add_btn.setText(
                f"Add {n} album{'s' if n != 1 else ''} to iPod"
            )

    def _on_current_changed(self, current, _previous):
        """Show track preview for the most recently clicked album."""
        self._track_list.clear()
        if not current:
            self._track_header.setText("  Select an album")
            return

        album = current.data(Qt.ItemDataRole.UserRole)
        self._track_header.setText(
            f"  {album['artist']} — {album['title']} "
            f"({album.get('track_count', '?')} tracks)"
        )

        # Load track list in background
        class _TrackFetcher(QThread):
            done = pyqtSignal(list)
            err = pyqtSignal(str)

            def __init__(self, url, token, rating_key):
                super().__init__()
                self._url = url
                self._token = token
                self._key = rating_key

            def run(self):
                try:
                    from SyncEngine.plex_library import connect
                    server = connect(self._url, self._token)
                    album_obj = server.fetchItem(self._key)
                    tracks = album_obj.tracks()
                    result = []
                    for t in tracks:
                        fmt = ""
                        try:
                            part = t.media[0].parts[0]
                            import os as _os
                            fmt = _os.path.splitext(part.file or "")[1].lstrip(".").upper()
                        except Exception:
                            pass
                        result.append({
                            "disc": getattr(t, "discNumber", 1) or 1,
                            "track": getattr(t, "trackNumber", 0) or 0,
                            "title": t.title,
                            "duration_ms": getattr(t, "duration", 0) or 0,
                            "format": fmt,
                        })
                    self.done.emit(result)
                except Exception as e:
                    self.err.emit(str(e))

        self._track_fetcher = _TrackFetcher(
            self._base_url, self._token, album["rating_key"]
        )
        self._track_fetcher.done.connect(self._populate_tracks)
        self._track_fetcher.start()

    def _populate_tracks(self, tracks: list):
        self._track_list.clear()
        for t in tracks:
            disc = t["disc"]
            num = t["track"]
            mins, secs = divmod((t["duration_ms"] or 0) // 1000, 60)
            dur = f"{mins}:{secs:02d}"
            fmt = f"  [{t['format']}]" if t["format"] else ""
            prefix = f"{disc}-{num:02d}" if disc > 1 else f"{num:02d}"
            self._track_list.addItem(f"{prefix}  {t['title']}  —  {dur}{fmt}")

    def _on_add_clicked(self):
        selected = self._album_list.selectedItems()
        if not selected:
            return
        keys = [int(item.data(Qt.ItemDataRole.UserRole)["rating_key"]) for item in selected]
        if len(selected) == 1:
            a = selected[0].data(Qt.ItemDataRole.UserRole)
            label = f"{a['artist']} — {a['title']}"
        else:
            label = f"{len(selected)} albums"
        self.album_selected.emit(self._base_url, self._token, keys, label)


# ── Main Dialog ───────────────────────────────────────────────────────────────

class PlexBrowserDialog(QDialog):
    """Browse a Plex Music library and return a selected album for syncing.

    On accept, the caller should read:
        dialog.selected_url        — Plex server base URL
        dialog.selected_token      — auth token
        dialog.selected_album_key  — album rating key (int)
        dialog.selected_album_label — "Artist — Album" string for UI
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add from Plex")
        self.setMinimumSize(720, 520)
        self.resize(820, 580)
        self.setModal(True)
        self.setStyleSheet(f"QDialog {{ background: {Colors.SURFACE_ALT}; }}")

        self.selected_url: str = ""
        self.selected_token: str = ""
        self.selected_album_keys: list[int] = []
        self.selected_album_label: str = ""

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._stack = QStackedWidget()
        layout.addWidget(self._stack)

        # Page 0: login
        self._login_page = _LoginPage()
        self._login_page.connected.connect(self._on_connected)
        self._stack.addWidget(self._login_page)

        # Page 1: browser
        self._browser_page = _BrowserPage()
        self._browser_page.album_selected.connect(self._on_album_selected)
        self._stack.addWidget(self._browser_page)

        # Try to resume from saved credentials
        self._try_restore_session()

    def _try_restore_session(self):
        try:
            from ..settings import get_settings
            s = get_settings()
            if s.plex_url and s.plex_token:
                self._stack.setCurrentIndex(1)
                self._browser_page.load_server(s.plex_url, s.plex_token, s.plex_url)
                return
        except Exception:
            pass
        self._stack.setCurrentIndex(0)

    def _on_connected(self, url: str, token: str, name: str):
        self._stack.setCurrentIndex(1)
        self._browser_page.load_server(url, token, name)

    def _go_to_login(self):
        self._stack.setCurrentIndex(0)

    def _on_album_selected(self, url: str, token: str, rating_keys: list, label: str):
        self.selected_url = url
        self.selected_token = token
        self.selected_album_keys = rating_keys
        self.selected_album_label = label
        self.accept()
