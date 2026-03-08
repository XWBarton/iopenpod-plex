"""
iPod Browser - Browse and manage content currently on the iPod.

Shows albums and tracks grouped by album. User can select items for removal
and trigger a removal sync via the existing SyncExecuteWorker pipeline.
"""

from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QWidget, QFrame, QLineEdit, QCheckBox, QSizePolicy,
)
from PyQt6.QtGui import QFont

from ..styles import Colors, FONT_FAMILY, Metrics, btn_css
from .formatters import format_size, format_duration_mmss


class _TrackRow(QFrame):
    """Single track row with a checkbox."""

    toggled = pyqtSignal(bool)

    def __init__(self, track: dict, parent=None):
        super().__init__(parent)
        self.track = track

        self.setStyleSheet(f"""
            QFrame {{
                background: transparent;
                border: none;
                border-radius: 3px;
            }}
            QFrame:hover {{
                background: {Colors.SURFACE_RAISED};
            }}
        """)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(36, 3, 12, 3)
        layout.setSpacing(8)

        self.cb = QCheckBox()
        self.cb.setChecked(False)
        self.cb.setStyleSheet(f"""
            QCheckBox::indicator {{
                width: 14px; height: 14px;
                border: 1px solid {Colors.BORDER};
                border-radius: 3px;
                background: transparent;
            }}
            QCheckBox::indicator:checked {{
                border-color: {Colors.ACCENT};
                background: {Colors.ACCENT};
            }}
        """)
        self.cb.toggled.connect(self.toggled.emit)
        layout.addWidget(self.cb)

        num = track.get("trackNumber") or ""
        num_label = QLabel(f"{num}." if num else "")
        num_label.setFixedWidth(22)
        num_label.setFont(QFont(FONT_FAMILY, 9))
        num_label.setStyleSheet(f"color: {Colors.TEXT_TERTIARY}; background: transparent;")
        layout.addWidget(num_label)

        title_label = QLabel(track.get("Title") or "Unknown")
        title_label.setFont(QFont(FONT_FAMILY, 10))
        title_label.setStyleSheet(f"color: {Colors.TEXT_PRIMARY}; background: transparent;")
        title_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        layout.addWidget(title_label, stretch=1)

        ms = track.get("length", 0)
        if ms:
            dur_label = QLabel(format_duration_mmss(ms))
            dur_label.setFont(QFont(FONT_FAMILY, 9))
            dur_label.setStyleSheet(f"color: {Colors.TEXT_TERTIARY}; background: transparent;")
            layout.addWidget(dur_label)

    def is_checked(self) -> bool:
        return self.cb.isChecked()

    def set_checked(self, v: bool):
        self.cb.blockSignals(True)
        self.cb.setChecked(v)
        self.cb.blockSignals(False)


class _AlbumCard(QFrame):
    """Collapsible card for one album with per-track checkboxes."""

    selection_changed = pyqtSignal()

    def __init__(self, album_title: str, artist: str, tracks: list[dict], parent=None):
        super().__init__(parent)
        self.album_title = album_title
        self.artist = artist
        self._tracks_data = tracks
        self._expanded = False
        self._track_rows: list[_TrackRow] = []

        self.setStyleSheet(f"""
            QFrame#albumCard {{
                background: {Colors.SURFACE};
                border: 1px solid {Colors.BORDER_SUBTLE};
                border-radius: {Metrics.BORDER_RADIUS_SM}px;
            }}
        """)
        self.setObjectName("albumCard")

        self._outer = QVBoxLayout(self)
        self._outer.setContentsMargins(0, 0, 0, 0)
        self._outer.setSpacing(0)

        # ── Header ──────────────────────────────────────────────────────────
        self._header = QFrame()
        self._header.setStyleSheet("background: transparent; border: none;")
        self._header.setCursor(Qt.CursorShape.PointingHandCursor)
        self._header.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        hl = QHBoxLayout(self._header)
        hl.setContentsMargins(12, 10, 12, 10)
        hl.setSpacing(10)

        self._cb = QCheckBox()
        self._cb.setChecked(False)
        self._cb.setStyleSheet(f"""
            QCheckBox::indicator {{
                width: 15px; height: 15px;
                border: 1px solid {Colors.BORDER};
                border-radius: 3px;
                background: transparent;
            }}
            QCheckBox::indicator:checked {{
                border-color: {Colors.ACCENT};
                background: {Colors.ACCENT};
            }}
            QCheckBox::indicator:indeterminate {{
                border-color: {Colors.ACCENT};
                background: {Colors.SURFACE_RAISED};
            }}
        """)
        self._cb.toggled.connect(self._on_album_cb)
        hl.addWidget(self._cb)

        self._arrow = QLabel("▶")
        self._arrow.setFont(QFont(FONT_FAMILY, 8))
        self._arrow.setFixedWidth(12)
        self._arrow.setStyleSheet(f"color: {Colors.TEXT_TERTIARY}; background: transparent;")
        hl.addWidget(self._arrow)

        text_col = QVBoxLayout()
        text_col.setSpacing(1)

        album_label = QLabel(album_title)
        album_label.setFont(QFont(FONT_FAMILY, 11, QFont.Weight.DemiBold))
        album_label.setStyleSheet(f"color: {Colors.TEXT_PRIMARY}; background: transparent;")
        text_col.addWidget(album_label)

        n = len(tracks)
        total_size = sum(t.get("fileSize", 0) for t in tracks)
        parts = [artist, f"{n} track{'s' if n != 1 else ''}"]
        if total_size:
            parts.append(format_size(total_size))
        sub_label = QLabel("  ·  ".join(parts))
        sub_label.setFont(QFont(FONT_FAMILY, 9))
        sub_label.setStyleSheet(f"color: {Colors.TEXT_TERTIARY}; background: transparent;")
        text_col.addWidget(sub_label)

        hl.addLayout(text_col, stretch=1)
        self._outer.addWidget(self._header)

        # ── Track container (hidden by default) ──────────────────────────
        self._track_container = QWidget()
        self._track_container.setStyleSheet("background: transparent;")
        tl = QVBoxLayout(self._track_container)
        tl.setContentsMargins(0, 2, 0, 8)
        tl.setSpacing(0)

        for t in sorted(tracks, key=lambda x: (x.get("discNumber") or 1, x.get("trackNumber") or 0)):
            row = _TrackRow(t)
            row.toggled.connect(self._on_track_toggle)
            self._track_rows.append(row)
            tl.addWidget(row)

        self._track_container.hide()
        self._outer.addWidget(self._track_container)

        self._header.mousePressEvent = self._header_clicked

    def _header_clicked(self, event=None):
        # Left-click on the arrow area or text area expands; checkbox handles itself
        self._expanded = not self._expanded
        self._track_container.setVisible(self._expanded)
        self._arrow.setText("▼" if self._expanded else "▶")

    def _on_album_cb(self, checked: bool):
        self._cb.setTristate(False)
        for row in self._track_rows:
            row.set_checked(checked)
        self.selection_changed.emit()

    def _on_track_toggle(self, _checked: bool):
        n_checked = sum(1 for r in self._track_rows if r.is_checked())
        n_total = len(self._track_rows)
        self._cb.blockSignals(True)
        if n_checked == 0:
            self._cb.setTristate(False)
            self._cb.setChecked(False)
        elif n_checked == n_total:
            self._cb.setTristate(False)
            self._cb.setChecked(True)
        else:
            self._cb.setTristate(True)
            self._cb.setCheckState(Qt.CheckState.PartiallyChecked)
        self._cb.blockSignals(False)
        self.selection_changed.emit()

    def selected_tracks(self) -> list[dict]:
        return [r.track for r in self._track_rows if r.is_checked()]


class iPodBrowserDialog(QDialog):
    """Browse iPod content and select tracks/albums for removal."""

    remove_requested = pyqtSignal(list)  # list[SyncItem]

    def __init__(self, cache, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Manage iPod Content")
        self.resize(600, 640)
        self.setStyleSheet(f"QDialog {{ background: {Colors.DIALOG_BG}; color: {Colors.TEXT_PRIMARY}; }}")

        self._cache = cache
        self._album_cards: list[_AlbumCard] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 16)
        root.setSpacing(12)

        # Title
        title = QLabel("Manage iPod Content")
        title.setFont(QFont(FONT_FAMILY, 16, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {Colors.TEXT_PRIMARY};")
        root.addWidget(title)

        sub = QLabel("Select albums or individual tracks to remove from the device.")
        sub.setFont(QFont(FONT_FAMILY, 10))
        sub.setStyleSheet(f"color: {Colors.TEXT_SECONDARY};")
        root.addWidget(sub)

        # Search
        self._search = QLineEdit()
        self._search.setPlaceholderText("Search albums or artists…")
        self._search.setStyleSheet(f"""
            QLineEdit {{
                background: {Colors.SURFACE};
                border: 1px solid {Colors.BORDER};
                border-radius: {Metrics.BORDER_RADIUS_SM}px;
                color: {Colors.TEXT_PRIMARY};
                padding: 7px 11px;
                font-size: 11px;
            }}
            QLineEdit:focus {{ border-color: {Colors.ACCENT}; }}
        """)
        self._search.textChanged.connect(self._filter)
        root.addWidget(self._search)

        # Select-all / deselect-all row
        sel_row = QHBoxLayout()
        sel_row.setSpacing(8)
        for label, checked in [("Select All", True), ("Deselect All", False)]:
            btn = QPushButton(label)
            btn.setFont(QFont(FONT_FAMILY, 9))
            btn.setStyleSheet(btn_css(
                bg="transparent",
                bg_hover=Colors.SURFACE_RAISED,
                bg_press=Colors.SURFACE,
                fg=Colors.TEXT_TERTIARY,
                padding="3px 10px",
            ))
            btn.clicked.connect(lambda _, c=checked: self._select_all(c))
            sel_row.addWidget(btn)
        sel_row.addStretch()
        root.addLayout(sel_row)

        # Album list
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setStyleSheet(f"""
            QScrollArea {{ background: transparent; border: none; }}
            QScrollBar:vertical {{ background: transparent; width: 8px; }}
            QScrollBar::handle:vertical {{
                background: {Colors.SCROLLBAR_THUMB};
                border-radius: 4px; min-height: 30px;
            }}
            QScrollBar::handle:vertical:hover {{
                background: {Colors.SCROLLBAR_THUMB_HOVER};
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
        """)

        self._list_widget = QWidget()
        self._list_widget.setStyleSheet("background: transparent;")
        self._list_layout = QVBoxLayout(self._list_widget)
        self._list_layout.setContentsMargins(0, 0, 4, 0)
        self._list_layout.setSpacing(6)
        self._list_layout.addStretch()

        self._scroll.setWidget(self._list_widget)
        root.addWidget(self._scroll, stretch=1)

        # Bottom bar
        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet(f"background: {Colors.BORDER_SUBTLE};")
        root.addWidget(sep)

        bottom = QHBoxLayout()
        bottom.setSpacing(10)

        self._status_label = QLabel("Loading…")
        self._status_label.setFont(QFont(FONT_FAMILY, 10))
        self._status_label.setStyleSheet(f"color: {Colors.TEXT_SECONDARY};")
        bottom.addWidget(self._status_label, stretch=1)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setFont(QFont(FONT_FAMILY, 10))
        cancel_btn.setStyleSheet(btn_css(
            bg=Colors.SURFACE_RAISED,
            bg_hover=Colors.SURFACE_ACTIVE,
            bg_press=Colors.SURFACE,
            padding="8px 20px",
        ))
        cancel_btn.clicked.connect(self.reject)
        bottom.addWidget(cancel_btn)

        self._remove_btn = QPushButton("Remove from iPod")
        self._remove_btn.setFont(QFont(FONT_FAMILY, 10, QFont.Weight.DemiBold))
        self._remove_btn.setStyleSheet(btn_css(
            bg="#b03a2e",
            bg_hover="#c0392b",
            bg_press="#922b21",
            fg="white",
            padding="8px 20px",
        ))
        self._remove_btn.setEnabled(False)
        self._remove_btn.clicked.connect(self._on_remove)
        bottom.addWidget(self._remove_btn)

        root.addLayout(bottom)

        self._populate()

    # ── Population ───────────────────────────────────────────────────────────

    def _populate(self):
        album_index = self._cache.get_album_index()
        album_only_index = self._cache.get_album_only_index()
        albums_data = self._cache.get_albums()

        albums: list[tuple[str, str, list[dict]]] = []
        for album_entry in albums_data:
            artist = album_entry.get("Artist (Used by Album Item)") or ""
            album = album_entry.get("Album (Used by Album Item)") or "Unknown Album"

            tracks: list[dict] = []
            if artist:
                tracks = album_index.get((album, artist), [])
            if not tracks:
                tracks = album_only_index.get(album, [])
                if tracks and not artist:
                    artist = (tracks[0].get("Album Artist")
                              or tracks[0].get("Artist")
                              or "Unknown Artist")
            if not tracks:
                continue
            if not artist:
                artist = "Unknown Artist"

            albums.append((album, artist, tracks))

        albums.sort(key=lambda x: x[0].lower())

        # Remove the trailing stretch, insert cards, re-add stretch
        self._list_layout.takeAt(self._list_layout.count() - 1)
        for album, artist, tracks in albums:
            card = _AlbumCard(album, artist, tracks)
            card.selection_changed.connect(self._update_status)
            self._album_cards.append(card)
            self._list_layout.addWidget(card)
        self._list_layout.addStretch()

        self._update_status()

    # ── Filtering / selection ────────────────────────────────────────────────

    def _filter(self, query: str):
        q = query.strip().lower()
        for card in self._album_cards:
            card.setVisible(
                not q
                or q in card.album_title.lower()
                or q in card.artist.lower()
            )

    def _select_all(self, checked: bool):
        for card in self._album_cards:
            if card.isVisible():
                card._cb.setChecked(checked)

    def _selected_tracks(self) -> list[dict]:
        result = []
        for card in self._album_cards:
            if card.isVisible():
                result.extend(card.selected_tracks())
        return result

    def _update_status(self):
        tracks = self._selected_tracks()
        n = len(tracks)
        total_size = sum(t.get("fileSize", 0) for t in tracks)
        if n == 0:
            self._status_label.setText("No tracks selected")
            self._remove_btn.setEnabled(False)
            self._remove_btn.setText("Remove from iPod")
        else:
            size_str = f"  ·  {format_size(total_size)}" if total_size else ""
            self._status_label.setText(
                f"{n} track{'s' if n != 1 else ''} selected{size_str}"
            )
            self._remove_btn.setEnabled(True)
            self._remove_btn.setText(
                f"Remove {n} track{'s' if n != 1 else ''}"
            )

    # ── Removal ──────────────────────────────────────────────────────────────

    def _on_remove(self):
        from SyncEngine.fingerprint_diff_engine import SyncAction, SyncItem

        tracks = self._selected_tracks()
        if not tracks:
            return

        items = []
        for t in tracks:
            title = t.get("Title") or "Unknown"
            artist = t.get("Artist") or ""
            album = t.get("Album") or ""
            desc_parts = [title]
            if artist:
                desc_parts.append(artist)
            if album:
                desc_parts.append(f"({album})")
            items.append(SyncItem(
                action=SyncAction.REMOVE_FROM_IPOD,
                dbid=t.get("dbid"),
                ipod_track=t,
                description=" — ".join(desc_parts),
            ))

        self.remove_requested.emit(items)
        self.accept()
