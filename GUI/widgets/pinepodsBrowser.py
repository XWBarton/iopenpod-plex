"""
Pinepods Browser — Browse a Pinepods server and add podcast episodes to an iPod.

Contains:
  PinepodsBrowserDialog  — Login + podcast/episode picker.
  PinepodsSyncWorker     — Downloads selected episodes then computes add-only
                           sync diff (same pattern as PlexSyncWorker).
"""

from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QListWidget, QListWidgetItem, QSplitter, QWidget,
    QFrame, QMessageBox, QStackedWidget, QSizePolicy,
)

from ..styles import Colors, FONT_FAMILY, Metrics, btn_css, accent_btn_css

logger = logging.getLogger(__name__)


# ── Sync Worker ────────────────────────────────────────────────────────────────

class PinepodsSyncWorker(QThread):
    """
    Downloads selected episodes from Pinepods, then runs
    PCLibrary + FingerprintDiffEngine to produce an add-only SyncPlan.

    Signals:
        progress(stage, current, total, message)
        finished(plan, temp_dir)
        error(message)
    """

    progress = pyqtSignal(str, int, int, str)
    finished = pyqtSignal(object, str)   # (SyncPlan, temp_dir)
    error    = pyqtSignal(str)

    def __init__(
        self,
        base_url: str,
        api_key: str,
        user_id: int,
        episodes: list[dict],          # list of episode dicts to download
        ipod_tracks: list,
        ipod_path: str,
        supports_podcast: bool = True,
        supports_video: bool = False,
    ):
        super().__init__()
        self._url            = base_url
        self._api_key        = api_key
        self._user_id        = user_id
        self._episodes       = episodes
        self._ipod_tracks    = ipod_tracks
        self._ipod_path      = ipod_path
        self._supports_pod   = supports_podcast
        self._supports_video = supports_video
        self._temp_dir: str  = ""

    def run(self):
        try:
            from SyncEngine.pinepods_library import download_episode

            self._temp_dir = tempfile.mkdtemp(prefix="iopenpod_pinepods_")
            total = len(self._episodes)

            # ── 1. Download all selected episodes ────────────────────
            downloaded: list[str] = []
            for idx, ep in enumerate(self._episodes, 1):
                if self.isInterruptionRequested():
                    self._cleanup()
                    return

                title = ep.get("Episodetitle") or ep.get("episode_title") or f"Episode {idx}"
                self.progress.emit("pinepods_download", idx - 1, total, f"Downloading: {title}")

                def _prog(done: int, tot: int, _t=title):
                    if self.isInterruptionRequested():
                        return
                    if tot:
                        self.progress.emit(
                            "pinepods_download", done, tot,
                            f"Downloading: {_t}",
                        )

                path = download_episode(
                    self._url, self._api_key, self._user_id, ep,
                    self._temp_dir,
                    progress_callback=_prog,
                    is_cancelled=self.isInterruptionRequested,
                )
                if path:
                    downloaded.append(path)

            if self.isInterruptionRequested():
                self._cleanup()
                return

            if not downloaded:
                self._cleanup()
                self.error.emit("No episodes were downloaded.\nCheck server connectivity.")
                return

            # ── 2. Fingerprint + diff ────────────────────────────────
            self.progress.emit("fingerprint", 0, 0, "Analysing downloaded episodes…")

            from SyncEngine.pc_library import PCLibrary
            from SyncEngine.fingerprint_diff_engine import FingerprintDiffEngine

            pc_library  = PCLibrary(self._temp_dir)
            diff_engine = FingerprintDiffEngine(
                pc_library, self._ipod_path,
                supports_video=self._supports_video,
                supports_podcast=self._supports_pod,
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

            # Add-only — never remove existing iPod tracks
            plan.to_remove.clear()

            self.finished.emit(plan, self._temp_dir)

        except Exception as exc:
            import traceback
            traceback.print_exc()
            self._cleanup()
            self.error.emit(str(exc))

    def _cleanup(self):
        import shutil
        if self._temp_dir and os.path.isdir(self._temp_dir):
            shutil.rmtree(self._temp_dir, ignore_errors=True)
        self._temp_dir = ""


# ── Browser Dialog ─────────────────────────────────────────────────────────────

class PinepodsBrowserDialog(QDialog):
    """
    Two-page dialog:
      Page 0 — Login (server URL, username, password)
      Page 1 — Podcast list (left) + episode list (right) with multi-select
    """

    def __init__(self, parent=None, saved_url: str = "", saved_api_key: str = "",
                 saved_user_id: int = 0):
        super().__init__(parent)
        self.setWindowTitle("Pinepods — Podcast Browser")
        self.setMinimumSize(780, 540)
        self.setModal(True)
        self.setStyleSheet(f"background: {Colors.BG_DARK}; color: {Colors.TEXT_PRIMARY};")

        # State
        self._api_key  = saved_api_key
        self._user_id  = saved_user_id
        self._base_url = saved_url
        self._podcasts: list[dict] = []
        self._episodes: list[dict] = []

        # Public result
        self.selected_url     = ""
        self.selected_api_key = ""
        self.selected_user_id = 0
        self.selected_episodes: list[dict] = []

        self._stack = QStackedWidget()
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(self._stack)

        self._build_login_page()
        self._build_browser_page()

        # Skip login if we already have credentials
        if self._api_key and self._user_id and self._base_url:
            self._stack.setCurrentIndex(1)
            self._load_podcasts()
        else:
            self._stack.setCurrentIndex(0)

    # ── Page 0: Login ─────────────────────────────────────────────────────────

    def _build_login_page(self):
        page = QFrame()
        page.setStyleSheet("background: transparent;")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(60, 60, 60, 60)
        layout.setSpacing(16)
        layout.addStretch()

        title = QLabel("Connect to Pinepods")
        title.setFont(QFont(FONT_FAMILY, 18, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {Colors.TEXT_PRIMARY};")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        sub = QLabel("Enter your server details to browse and download podcasts.")
        sub.setFont(QFont(FONT_FAMILY, 10))
        sub.setStyleSheet(f"color: {Colors.TEXT_SECONDARY};")
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(sub)

        layout.addSpacing(8)

        field_style = f"""
            QLineEdit {{
                background: {Colors.SURFACE_RAISED};
                border: 1px solid {Colors.BORDER};
                border-radius: {Metrics.BORDER_RADIUS_SM}px;
                color: {Colors.TEXT_PRIMARY};
                padding: 8px 12px;
                font-size: 13px;
            }}
            QLineEdit:focus {{
                border-color: {Colors.ACCENT};
            }}
        """

        self._url_input = QLineEdit(self._base_url)
        self._url_input.setPlaceholderText("Server URL (e.g. http://192.168.1.10:8040)")
        self._url_input.setStyleSheet(field_style)
        layout.addWidget(self._url_input)

        self._user_input = QLineEdit()
        self._user_input.setPlaceholderText("Username")
        self._user_input.setStyleSheet(field_style)
        layout.addWidget(self._user_input)

        self._pass_input = QLineEdit()
        self._pass_input.setPlaceholderText("Password")
        self._pass_input.setEchoMode(QLineEdit.EchoMode.Password)
        self._pass_input.setStyleSheet(field_style)
        self._pass_input.returnPressed.connect(self._on_login)
        layout.addWidget(self._pass_input)

        self._login_status = QLabel("")
        self._login_status.setFont(QFont(FONT_FAMILY, 10))
        self._login_status.setStyleSheet(f"color: {Colors.DANGER};")
        self._login_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._login_status.hide()
        layout.addWidget(self._login_status)

        self._login_btn = QPushButton("Connect")
        self._login_btn.setFont(QFont(FONT_FAMILY, 11, QFont.Weight.DemiBold))
        self._login_btn.setStyleSheet(accent_btn_css())
        self._login_btn.clicked.connect(self._on_login)
        layout.addWidget(self._login_btn)

        layout.addStretch()
        self._stack.addWidget(page)

    def _on_login(self):
        url  = self._url_input.text().strip()
        user = self._user_input.text().strip()
        pwd  = self._pass_input.text()

        if not url or not user or not pwd:
            self._show_login_error("Please fill in all fields.")
            return

        self._login_btn.setText("Connecting…")
        self._login_btn.setEnabled(False)
        self._login_status.hide()

        from PyQt6.QtWidgets import QApplication
        QApplication.processEvents()

        try:
            from SyncEngine.pinepods_library import authenticate
            api_key, user_id = authenticate(url, user, pwd)
        except Exception as exc:
            self._login_btn.setText("Connect")
            self._login_btn.setEnabled(True)
            self._show_login_error(str(exc))
            return

        self._base_url = url
        self._api_key  = api_key
        self._user_id  = user_id

        self._login_btn.setText("Connect")
        self._login_btn.setEnabled(True)
        self._stack.setCurrentIndex(1)
        self._load_podcasts()

    def _show_login_error(self, msg: str):
        self._login_status.setText(msg)
        self._login_status.show()

    # ── Page 1: Browser ───────────────────────────────────────────────────────

    def _build_browser_page(self):
        page = QFrame()
        page.setStyleSheet("background: transparent;")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        # Header
        hdr = QHBoxLayout()
        title = QLabel("Pinepods — Podcast Browser")
        title.setFont(QFont(FONT_FAMILY, 14, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {Colors.TEXT_PRIMARY};")
        hdr.addWidget(title)
        hdr.addStretch()

        self._status_label = QLabel("")
        self._status_label.setFont(QFont(FONT_FAMILY, 10))
        self._status_label.setStyleSheet(f"color: {Colors.TEXT_SECONDARY};")
        hdr.addWidget(self._status_label)

        layout.addLayout(hdr)

        # Splitter: podcast list | episode list
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setStyleSheet("QSplitter::handle { background: transparent; width: 8px; }")

        list_style = f"""
            QListWidget {{
                background: {Colors.SURFACE};
                border: 1px solid {Colors.BORDER};
                border-radius: {Metrics.BORDER_RADIUS_SM}px;
                color: {Colors.TEXT_PRIMARY};
                outline: none;
            }}
            QListWidget::item {{
                padding: 8px 10px;
                border-bottom: 1px solid {Colors.BORDER_SUBTLE};
            }}
            QListWidget::item:selected {{
                background: {Colors.ACCENT};
                color: white;
            }}
            QListWidget::item:hover:!selected {{
                background: {Colors.SURFACE_RAISED};
            }}
        """

        # Left: podcast list
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 4, 0)
        left_layout.setSpacing(6)

        pod_label = QLabel("Podcasts")
        pod_label.setFont(QFont(FONT_FAMILY, 10, QFont.Weight.DemiBold))
        pod_label.setStyleSheet(f"color: {Colors.TEXT_SECONDARY};")
        left_layout.addWidget(pod_label)

        self._podcast_list = QListWidget()
        self._podcast_list.setStyleSheet(list_style)
        self._podcast_list.currentItemChanged.connect(self._on_podcast_selected)
        left_layout.addWidget(self._podcast_list)

        splitter.addWidget(left)

        # Right: episode list (multi-select)
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(4, 0, 0, 0)
        right_layout.setSpacing(6)

        ep_hdr = QHBoxLayout()
        ep_label = QLabel("Episodes")
        ep_label.setFont(QFont(FONT_FAMILY, 10, QFont.Weight.DemiBold))
        ep_label.setStyleSheet(f"color: {Colors.TEXT_SECONDARY};")
        ep_hdr.addWidget(ep_label)
        ep_hdr.addStretch()

        self._sel_all_btn = QPushButton("Select all")
        self._sel_all_btn.setFont(QFont(FONT_FAMILY, 9))
        self._sel_all_btn.setStyleSheet(btn_css(
            bg="transparent", bg_hover=Colors.SURFACE_RAISED,
            bg_press=Colors.SURFACE, fg=Colors.TEXT_TERTIARY, padding="3px 8px",
        ))
        self._sel_all_btn.clicked.connect(self._select_all_episodes)
        ep_hdr.addWidget(self._sel_all_btn)

        right_layout.addLayout(ep_hdr)

        self._episode_list = QListWidget()
        self._episode_list.setStyleSheet(list_style)
        self._episode_list.setSelectionMode(
            QListWidget.SelectionMode.ExtendedSelection
        )
        self._episode_list.itemSelectionChanged.connect(self._on_episode_selection_changed)
        right_layout.addWidget(self._episode_list)

        splitter.addWidget(right)
        splitter.setSizes([260, 500])
        layout.addWidget(splitter, stretch=1)

        # Footer
        footer = QHBoxLayout()

        self._ep_status = QLabel("Select episodes to add to iPod")
        self._ep_status.setFont(QFont(FONT_FAMILY, 10))
        self._ep_status.setStyleSheet(f"color: {Colors.TEXT_SECONDARY};")
        footer.addWidget(self._ep_status)
        footer.addStretch()

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setFont(QFont(FONT_FAMILY, 10, QFont.Weight.DemiBold))
        cancel_btn.setStyleSheet(btn_css(
            bg=Colors.SURFACE_RAISED, bg_hover=Colors.SURFACE_ACTIVE,
            bg_press=Colors.SURFACE, padding="8px 16px",
        ))
        cancel_btn.clicked.connect(self.reject)
        footer.addWidget(cancel_btn)

        self._add_btn = QPushButton("Add to iPod")
        self._add_btn.setFont(QFont(FONT_FAMILY, 10, QFont.Weight.DemiBold))
        self._add_btn.setStyleSheet(accent_btn_css())
        self._add_btn.setEnabled(False)
        self._add_btn.clicked.connect(self._on_add)
        footer.addWidget(self._add_btn)

        layout.addLayout(footer)
        self._stack.addWidget(page)

    def _load_podcasts(self):
        self._status_label.setText("Loading podcasts…")
        from PyQt6.QtWidgets import QApplication
        QApplication.processEvents()

        try:
            from SyncEngine.pinepods_library import get_podcasts
            self._podcasts = get_podcasts(self._base_url, self._api_key, self._user_id)
        except Exception as exc:
            QMessageBox.warning(self, "Error", f"Could not load podcasts:\n{exc}")
            self._status_label.setText("")
            return

        self._podcast_list.clear()
        for pod in self._podcasts:
            name = pod.get("podcastname") or "Unknown Podcast"
            count = pod.get("episodecount", "")
            label = f"{name}  ({count} ep)" if count else name
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, pod)
            self._podcast_list.addItem(item)

        self._status_label.setText(f"{len(self._podcasts)} podcast{'s' if len(self._podcasts) != 1 else ''}")

    def _on_podcast_selected(self, current: QListWidgetItem, _prev):
        if current is None:
            return
        pod = current.data(Qt.ItemDataRole.UserRole)
        podcast_id = pod.get("podcastid")
        self._episode_list.clear()
        self._ep_status.setText("Loading episodes…")
        from PyQt6.QtWidgets import QApplication
        QApplication.processEvents()

        try:
            from SyncEngine.pinepods_library import get_episodes
            self._episodes = get_episodes(
                self._base_url, self._api_key, self._user_id, podcast_id
            )
        except Exception as exc:
            QMessageBox.warning(self, "Error", f"Could not load episodes:\n{exc}")
            self._ep_status.setText("")
            return

        for ep in self._episodes:
            title = ep.get("Episodetitle") or ep.get("episode_title") or "Unknown"
            pub   = (ep.get("Episodepubdate") or ep.get("episode_pub_date") or "")[:10]
            dur_s = ep.get("Episodeduration") or ep.get("episode_duration") or 0
            if dur_s:
                mins, secs = divmod(int(dur_s), 60)
                hrs,  mins = divmod(mins, 60)
                dur_str = f"{hrs}:{mins:02d}:{secs:02d}" if hrs else f"{mins}:{secs:02d}"
            else:
                dur_str = ""
            label = f"{pub}  {title}" + (f"  [{dur_str}]" if dur_str else "")
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, ep)
            self._episode_list.addItem(item)

        self._ep_status.setText(
            f"{len(self._episodes)} episode{'s' if len(self._episodes) != 1 else ''}"
        )

    def _select_all_episodes(self):
        self._episode_list.selectAll()

    def _on_episode_selection_changed(self):
        n = len(self._episode_list.selectedItems())
        if n == 0:
            self._add_btn.setText("Add to iPod")
            self._add_btn.setEnabled(False)
        else:
            self._add_btn.setText(f"Add {n} episode{'s' if n != 1 else ''} to iPod")
            self._add_btn.setEnabled(True)

    def _on_add(self):
        eps = [
            item.data(Qt.ItemDataRole.UserRole)
            for item in self._episode_list.selectedItems()
        ]
        if not eps:
            return

        self.selected_url       = self._base_url
        self.selected_api_key   = self._api_key
        self.selected_user_id   = self._user_id
        self.selected_episodes  = eps
        self.accept()
