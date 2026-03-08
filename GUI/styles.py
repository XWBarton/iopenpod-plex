"""
Centralized style definitions for iOpenPod.

All colors, dimensions, and reusable stylesheet fragments live here so that
every widget draws from a single visual language.

Theming
-------
Call ``apply_theme("dark")`` or ``apply_theme("light")`` *before* creating
any widgets (typically in main.py right after loading settings).  This patches
the ``Colors`` class attributes in-place so that every subsequent stylesheet
string picks up the correct values.
"""

import sys

from PyQt6.QtCore import QRect, Qt
from PyQt6.QtGui import QColor, QPainter
from PyQt6.QtWidgets import (
    QProxyStyle,
    QStyle,
    QStyleOptionComplex,
    QStyleOptionSlider,
)

# ── Cross-platform font ─────────────────────────────────────────────────────

if sys.platform == "darwin":
    FONT_FAMILY = ".AppleSystemUIFont"
    MONO_FONT_FAMILY = "Menlo"
    _CSS_FONT_STACK = '".AppleSystemUIFont", "Helvetica Neue"'
elif sys.platform == "win32":
    FONT_FAMILY = "Segoe UI"
    MONO_FONT_FAMILY = "Consolas"
    _CSS_FONT_STACK = '"Segoe UI"'
else:
    FONT_FAMILY = "Noto Sans"
    MONO_FONT_FAMILY = "Noto Sans Mono"
    _CSS_FONT_STACK = (
        '"Noto Sans", "Noto Sans Symbols 2", "Noto Emoji",'
        ' "Ubuntu", "DejaVu Sans"'
    )

# ── Theme palettes ────────────────────────────────────────────────────────────

_DARK_PALETTE: dict[str, str] = {
    # Accent
    "ACCENT": "#409cff",
    "ACCENT_LIGHT": "#60b0ff",
    "ACCENT_DIM": "rgba(64,156,255,80)",
    "ACCENT_HOVER": "rgba(64,156,255,120)",
    "ACCENT_PRESS": "rgba(64,156,255,60)",
    "ACCENT_MUTED": "rgba(64,156,255,22)",
    "ACCENT_BORDER": "rgba(64,156,255,100)",
    # Surfaces
    "BG_DARK": "#0c0c14",
    "BG_MID": "#101019",
    "SURFACE": "rgba(255,255,255,8)",
    "SURFACE_ALT": "rgba(255,255,255,12)",
    "SURFACE_RAISED": "rgba(255,255,255,18)",
    "SURFACE_HOVER": "rgba(255,255,255,25)",
    "SURFACE_ACTIVE": "rgba(255,255,255,40)",
    "MENU_BG": "#1a1a28",
    # Text
    "TEXT_PRIMARY": "rgba(255,255,255,230)",
    "TEXT_SECONDARY": "rgba(255,255,255,150)",
    "TEXT_TERTIARY": "rgba(255,255,255,100)",
    "TEXT_DISABLED": "rgba(255,255,255,60)",
    # Borders
    "BORDER": "rgba(255,255,255,30)",
    "BORDER_SUBTLE": "rgba(255,255,255,15)",
    "BORDER_FOCUS": "rgba(64,156,255,150)",
    # Misc
    "GRIDLINE": "rgba(255,255,255,12)",
    "SELECTION": "rgba(64,156,255,90)",
    "STAR": "#ffc857",
    "DANGER": "#ff6b6b",
    "SUCCESS": "#51cf66",
    "WARNING": "#fcc419",
    # Scrollbar (used by AppScrollbarStyle)
    "SCROLLBAR_THUMB": "rgba(255,255,255,70)",
    "SCROLLBAR_THUMB_HOVER": "rgba(255,255,255,110)",
    "SCROLLBAR_THUMB_PRESS": "rgba(255,255,255,140)",
    # Dialog / message box backgrounds (opaque, used in QSS strings)
    "DIALOG_BG": "#12121c",
    "MSGBOX_BG": "#12121c",
    "MSGBOX_FG": "white",
    "TOOLTIP_BG": "#1e1e2c",
}

_LIGHT_PALETTE: dict[str, str] = {
    # Accent — same blue, slightly stronger for legibility on white
    "ACCENT": "#1a7de8",
    "ACCENT_LIGHT": "#409cff",
    "ACCENT_DIM": "rgba(26,125,232,100)",
    "ACCENT_HOVER": "rgba(26,125,232,150)",
    "ACCENT_PRESS": "rgba(26,125,232,70)",
    "ACCENT_MUTED": "rgba(26,125,232,18)",
    "ACCENT_BORDER": "rgba(26,125,232,180)",
    # Surfaces — light gray / white tones
    "BG_DARK": "#f2f2f7",
    "BG_MID": "#e8e8ed",
    "SURFACE": "rgba(0,0,0,5)",
    "SURFACE_ALT": "rgba(0,0,0,8)",
    "SURFACE_RAISED": "rgba(0,0,0,13)",
    "SURFACE_HOVER": "rgba(0,0,0,20)",
    "SURFACE_ACTIVE": "rgba(0,0,0,30)",
    "MENU_BG": "#f5f5fa",
    # Text
    "TEXT_PRIMARY": "rgba(0,0,0,222)",
    "TEXT_SECONDARY": "rgba(0,0,0,140)",
    "TEXT_TERTIARY": "rgba(0,0,0,90)",
    "TEXT_DISABLED": "rgba(0,0,0,50)",
    # Borders
    "BORDER": "rgba(0,0,0,18)",
    "BORDER_SUBTLE": "rgba(0,0,0,10)",
    "BORDER_FOCUS": "rgba(26,125,232,200)",
    # Misc
    "GRIDLINE": "rgba(0,0,0,8)",
    "SELECTION": "rgba(26,125,232,80)",
    "STAR": "#e6a800",
    "DANGER": "#d93025",
    "SUCCESS": "#1e8e3e",
    "WARNING": "#e37400",
    # Scrollbar
    "SCROLLBAR_THUMB": "rgba(0,0,0,40)",
    "SCROLLBAR_THUMB_HOVER": "rgba(0,0,0,65)",
    "SCROLLBAR_THUMB_PRESS": "rgba(0,0,0,85)",
    # Dialog / message box backgrounds
    "DIALOG_BG": "#f0f0f5",
    "MSGBOX_BG": "#ebebf0",
    "MSGBOX_FG": "rgba(0,0,0,222)",
    "TOOLTIP_BG": "#ffffff",
}

# ── Color palette (patched by apply_theme) ───────────────────────────────────


class Colors:
    """Named colors used throughout the app.

    Do not read these at module import time — always reference them inside
    functions/methods so that ``apply_theme()`` has a chance to patch them
    first.
    """
    # Defaults match the dark palette (safe fallback if apply_theme not called)
    ACCENT = "#409cff"
    ACCENT_LIGHT = "#60b0ff"
    ACCENT_DIM = "rgba(64,156,255,80)"
    ACCENT_HOVER = "rgba(64,156,255,120)"
    ACCENT_PRESS = "rgba(64,156,255,60)"
    ACCENT_MUTED = "rgba(64,156,255,22)"
    ACCENT_BORDER = "rgba(64,156,255,100)"
    BG_DARK = "#0c0c14"
    BG_MID = "#101019"
    SURFACE = "rgba(255,255,255,8)"
    SURFACE_ALT = "rgba(255,255,255,12)"
    SURFACE_RAISED = "rgba(255,255,255,18)"
    SURFACE_HOVER = "rgba(255,255,255,25)"
    SURFACE_ACTIVE = "rgba(255,255,255,40)"
    MENU_BG = "#1a1a28"
    TEXT_PRIMARY = "rgba(255,255,255,230)"
    TEXT_SECONDARY = "rgba(255,255,255,150)"
    TEXT_TERTIARY = "rgba(255,255,255,100)"
    TEXT_DISABLED = "rgba(255,255,255,60)"
    BORDER = "rgba(255,255,255,30)"
    BORDER_SUBTLE = "rgba(255,255,255,15)"
    BORDER_FOCUS = "rgba(64,156,255,150)"
    GRIDLINE = "rgba(255,255,255,12)"
    SELECTION = "rgba(64,156,255,90)"
    STAR = "#ffc857"
    DANGER = "#ff6b6b"
    SUCCESS = "#51cf66"
    WARNING = "#fcc419"
    SCROLLBAR_THUMB = "rgba(255,255,255,70)"
    SCROLLBAR_THUMB_HOVER = "rgba(255,255,255,110)"
    SCROLLBAR_THUMB_PRESS = "rgba(255,255,255,140)"
    DIALOG_BG = "#12121c"
    MSGBOX_BG = "#12121c"
    MSGBOX_FG = "white"
    TOOLTIP_BG = "#1e1e2c"


# Track the active theme name for reference elsewhere
_active_theme: str = "dark"


def apply_theme(name: str) -> None:
    """Patch Colors class attributes for the given theme ('dark' or 'light').

    Must be called before any widgets are constructed so that all stylesheet
    strings pick up the correct values.
    """
    global _active_theme
    palette = _LIGHT_PALETTE if name == "light" else _DARK_PALETTE
    for attr, value in palette.items():
        setattr(Colors, attr, value)
    _active_theme = name


def current_theme() -> str:
    """Return the name of the currently active theme."""
    return _active_theme


class Metrics:
    """Shared dimension constants."""
    BORDER_RADIUS = 8
    BORDER_RADIUS_SM = 6
    BORDER_RADIUS_LG = 10
    BORDER_RADIUS_XL = 12

    GRID_ITEM_W = 172
    GRID_ITEM_H = 230
    GRID_ART_SIZE = 152
    GRID_SPACING = 14

    SIDEBAR_WIDTH = 220
    SCROLLBAR_W = 8
    SCROLLBAR_MIN_H = 40

    BTN_PADDING_V = 7
    BTN_PADDING_H = 14


# ── Custom proxy style for scrollbar painting ───────────────────────────────

class DarkScrollbarStyle(QProxyStyle):
    """Overrides Fusion scrollbar painting with thin, rounded bars.

    Qt stylesheet-based scrollbar styling is unreliable on Windows with
    Fusion (CSS is silently ignored). This proxy style paints scrollbars
    directly via QPainter so they always render correctly.

    Thumb colors are read from Colors at draw time so they follow the
    active theme automatically.
    """

    _THICKNESS = 8                         # thin like macOS/VS Code
    _MIN_HANDLE = 36                       # minimum thumb length
    _TRACK = QColor(0, 0, 0, 0)           # invisible track

    # Kept for backwards compat — actual colors read from Colors at draw time
    _THUMB = QColor(255, 255, 255, 70)
    _THUMB_HOVER = QColor(255, 255, 255, 110)
    _THUMB_PRESS = QColor(255, 255, 255, 140)

    @staticmethod
    def _thumb_color(pressed: bool, hovered: bool) -> QColor:
        if pressed:
            return QColor(Colors.SCROLLBAR_THUMB_PRESS)
        if hovered:
            return QColor(Colors.SCROLLBAR_THUMB_HOVER)
        return QColor(Colors.SCROLLBAR_THUMB)

    def __init__(self, base_key: str = "Fusion"):
        super().__init__(base_key)

    # -- Metrics: make scrollbars thin --

    def pixelMetric(self, metric, option=None, widget=None):
        if metric in (
            QStyle.PixelMetric.PM_ScrollBarExtent,
        ):
            return self._THICKNESS
        if metric == QStyle.PixelMetric.PM_ScrollBarSliderMin:
            return self._MIN_HANDLE
        return super().pixelMetric(metric, option, widget)

    # -- Sub-control rectangles --

    def subControlRect(self, cc, opt, sc, widget=None):
        if cc != QStyle.ComplexControl.CC_ScrollBar or not isinstance(opt, QStyleOptionSlider):
            return super().subControlRect(cc, opt, sc, widget)

        r = opt.rect
        horiz = opt.orientation == Qt.Orientation.Horizontal
        length = r.width() if horiz else r.height()

        # No step buttons
        if sc in (
            QStyle.SubControl.SC_ScrollBarAddLine,
            QStyle.SubControl.SC_ScrollBarSubLine,
        ):
            return QRect()

        # Groove = full rect
        if sc == QStyle.SubControl.SC_ScrollBarGroove:
            return r

        # Slider handle
        if sc == QStyle.SubControl.SC_ScrollBarSlider:
            rng = opt.maximum - opt.minimum
            if rng <= 0:
                return r  # full when no range
            page = max(opt.pageStep, 1)
            handle_len = max(
                int(length * page / (rng + page)),
                self._MIN_HANDLE,
            )
            available = length - handle_len
            if available <= 0:
                pos = 0
            else:
                pos = int(available * (opt.sliderValue - opt.minimum) / rng)
            if horiz:
                return QRect(r.x() + pos, r.y(), handle_len, r.height())
            else:
                return QRect(r.x(), r.y() + pos, r.width(), handle_len)

        # Page areas
        if sc in (
            QStyle.SubControl.SC_ScrollBarAddPage,
            QStyle.SubControl.SC_ScrollBarSubPage,
        ):
            slider = self.subControlRect(cc, opt, QStyle.SubControl.SC_ScrollBarSlider, widget)
            if sc == QStyle.SubControl.SC_ScrollBarSubPage:
                if horiz:
                    return QRect(r.x(), r.y(), slider.x() - r.x(), r.height())
                else:
                    return QRect(r.x(), r.y(), r.width(), slider.y() - r.y())
            else:
                if horiz:
                    end = slider.x() + slider.width()
                    return QRect(end, r.y(), r.right() - end + 1, r.height())
                else:
                    end = slider.y() + slider.height()
                    return QRect(r.x(), end, r.width(), r.bottom() - end + 1)

        return super().subControlRect(cc, opt, sc, widget)

    # -- Hit testing --

    def hitTestComplexControl(self, control, option, pos, widget=None):
        if control == QStyle.ComplexControl.CC_ScrollBar and isinstance(option, QStyleOptionSlider):
            slider = self.subControlRect(control, option, QStyle.SubControl.SC_ScrollBarSlider, widget)
            if slider.contains(pos):
                return QStyle.SubControl.SC_ScrollBarSlider
            groove = self.subControlRect(control, option, QStyle.SubControl.SC_ScrollBarGroove, widget)
            if groove.contains(pos):
                horiz = option.orientation == Qt.Orientation.Horizontal
                if (horiz and pos.x() < slider.x()) or (not horiz and pos.y() < slider.y()):
                    return QStyle.SubControl.SC_ScrollBarSubPage
                return QStyle.SubControl.SC_ScrollBarAddPage
            return QStyle.SubControl.SC_None
        return super().hitTestComplexControl(control, option, pos, widget)

    # -- Draw the scrollbar --

    def drawComplexControl(self, control, option, painter, widget=None):
        if control != QStyle.ComplexControl.CC_ScrollBar or not isinstance(option, QStyleOptionSlider):
            super().drawComplexControl(control, option, painter, widget)
            return

        # Guard against None painter (can happen during widget destruction)
        if painter is None:
            return

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # No track — completely transparent

        # Handle (pill shape)
        slider = self.subControlRect(control, option, QStyle.SubControl.SC_ScrollBarSlider, widget)
        if slider.isValid() and not slider.isEmpty():
            pressed = bool(option.state & QStyle.StateFlag.State_Sunken)
            active_sc = option.activeSubControls if isinstance(option, QStyleOptionComplex) else QStyle.SubControl.SC_None
            hovered = bool(
                (option.state & QStyle.StateFlag.State_MouseOver)
                and (active_sc & QStyle.SubControl.SC_ScrollBarSlider)  # noqa: W503
            )

            color = self._thumb_color(pressed, hovered)

            horiz = option.orientation == Qt.Orientation.Horizontal
            # Inset to create a floating pill centered in the track
            pad = 2  # padding from edge of scrollbar track
            if horiz:
                thumb_h = max(slider.height() - pad * 2, 4)
                adj = QRect(
                    slider.x() + 2, slider.y() + pad,
                    slider.width() - 4, thumb_h,
                )
            else:
                thumb_w = max(slider.width() - pad * 2, 4)
                adj = QRect(
                    slider.x() + pad, slider.y() + 2,
                    thumb_w, slider.height() - 4,
                )

            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(color)
            # Fully rounded — radius = half the shorter dimension
            r = min(adj.width(), adj.height()) / 2.0
            painter.drawRoundedRect(adj, r, r)

        painter.restore()

    # -- Suppress default Fusion scrollbar primitives --

    def drawPrimitive(self, element, option, painter, widget=None):
        # Skip the default scrollbar arrow drawing
        if element in (
            QStyle.PrimitiveElement.PE_PanelScrollAreaCorner,
        ):
            return  # paint nothing — transparent corner
        super().drawPrimitive(element, option, painter, widget)


# ── Reusable stylesheet fragments ───────────────────────────────────────────

def scrollbar_css(width: int = Metrics.SCROLLBAR_W, orient: str = "vertical") -> str:
    """Minimal modern scrollbar — thin track, rounded thumb.

    Covers every pseudo-element so that native platform chrome never leaks
    through (especially on Windows where the default blue bar is visible
    if any sub-element is left unstyled).

    Colors are read from Colors at call time so they follow the active theme.
    """
    bar = f"QScrollBar:{orient}"
    r = max(width // 2, 1)
    thumb = Colors.SCROLLBAR_THUMB
    thumb_h = Colors.SCROLLBAR_THUMB_HOVER
    thumb_p = Colors.SCROLLBAR_THUMB_PRESS
    if orient == "vertical":
        return f"""
            {bar} {{
                background: transparent;
                width: {width}px;
                margin: 0;
                padding: 2px 1px;
                border: none;
            }}
            {bar}::handle {{
                background: {thumb};
                border-radius: {r}px;
                min-height: {Metrics.SCROLLBAR_MIN_H}px;
            }}
            {bar}::handle:hover {{
                background: {thumb_h};
            }}
            {bar}::handle:pressed {{
                background: {thumb_p};
            }}
            {bar}::add-line, {bar}::sub-line {{
                border: none; background: none; height: 0px; width: 0px;
            }}
            {bar}::add-page, {bar}::sub-page {{
                background: none;
            }}
            {bar}::up-arrow, {bar}::down-arrow {{
                background: none; width: 0px; height: 0px;
            }}
        """
    else:
        return f"""
            {bar} {{
                background: transparent;
                height: {width}px;
                margin: 0;
                padding: 1px 2px;
                border: none;
            }}
            {bar}::handle {{
                background: {thumb};
                border-radius: {r}px;
                min-width: {Metrics.SCROLLBAR_MIN_H}px;
            }}
            {bar}::handle:hover {{
                background: {thumb_h};
            }}
            {bar}::handle:pressed {{
                background: {thumb_p};
            }}
            {bar}::add-line, {bar}::sub-line {{
                border: none; background: none; height: 0px; width: 0px;
            }}
            {bar}::add-page, {bar}::sub-page {{
                background: none;
            }}
            {bar}::left-arrow, {bar}::right-arrow {{
                background: none; width: 0px; height: 0px;
            }}
        """


def scrollbar_corner_css() -> str:
    """Style the corner widget where horizontal & vertical scrollbars meet."""
    return """
        QAbstractScrollArea::corner {
            background: transparent;
            border: none;
        }
    """


def btn_css(
    bg: str = None,
    bg_hover: str = None,
    bg_press: str = None,
    fg: str = None,
    border: str = "none",
    radius: int = Metrics.BORDER_RADIUS_SM,
    padding: str = f"{Metrics.BTN_PADDING_V}px {Metrics.BTN_PADDING_H}px",
    extra: str = "",
) -> str:
    """Standard button stylesheet.

    All color defaults are resolved at call time from the current Colors palette
    so they follow whichever theme is active.
    """
    _bg = bg if bg is not None else Colors.SURFACE_RAISED
    _bg_hover = bg_hover if bg_hover is not None else Colors.SURFACE_HOVER
    _bg_press = bg_press if bg_press is not None else Colors.SURFACE_ALT
    _fg = fg if fg is not None else Colors.TEXT_PRIMARY
    return f"""
        QPushButton {{
            background: {_bg};
            border: {border};
            border-radius: {radius}px;
            color: {_fg};
            padding: {padding};
            {extra}
        }}
        QPushButton:hover {{
            background: {_bg_hover};
        }}
        QPushButton:pressed {{
            background: {_bg_press};
        }}
    """


def accent_btn_css() -> str:
    """Primary action button (blue accent) — always white text."""
    return btn_css(
        bg=Colors.ACCENT_DIM,
        bg_hover=Colors.ACCENT_HOVER,
        bg_press=Colors.ACCENT_PRESS,
        fg="white",
        border=f"1px solid {Colors.ACCENT_BORDER}",
        radius=Metrics.BORDER_RADIUS,
        padding=f"10px {Metrics.BTN_PADDING_H}px",
    )


# ── Application-level stylesheet ────────────────────────────────────────────

def get_app_stylesheet() -> str:
    """Build the application-wide stylesheet using the current Colors palette.

    Call this *after* ``apply_theme()`` so the correct colors are used.
    """
    return f"""
    /* ── Base ──────────────────────────────────────────────────── */
    QMainWindow {{
        background: qlineargradient(x1:0, y1:0, x2:0.2, y2:1,
            stop:0 {Colors.BG_DARK}, stop:1 {Colors.BG_MID});
    }}
    QWidget {{
        font-family: {_CSS_FONT_STACK};
    }}
    QStackedWidget {{
        background: transparent;
    }}
    QFrame {{
        background: transparent;
        border: none;
    }}

    /* ── Tooltips ──────────────────────────────────────────────── */
    QToolTip {{
        background: {Colors.TOOLTIP_BG};
        color: {Colors.TEXT_PRIMARY};
        border: 1px solid {Colors.BORDER};
        border-radius: 6px;
        padding: 5px 10px;
        font-size: 11px;
    }}

    /* ── Splitter handle ───────────────────────────────────────── */
    QSplitter::handle {{
        background: {Colors.BORDER_SUBTLE};
    }}
    QSplitter::handle:hover {{
        background: {Colors.ACCENT};
    }}
    QSplitter::handle:pressed {{
        background: {Colors.ACCENT_LIGHT};
    }}

    /* ── Message boxes ─────────────────────────────────────────── */
    QMessageBox {{
        background: {Colors.MSGBOX_BG};
        color: {Colors.MSGBOX_FG};
    }}
    QMessageBox QLabel {{
        color: {Colors.MSGBOX_FG};
    }}
    QMessageBox QPushButton {{
        background: {Colors.SURFACE_RAISED};
        border: 1px solid {Colors.BORDER};
        border-radius: {Metrics.BORDER_RADIUS_SM}px;
        color: {Colors.TEXT_PRIMARY};
        padding: 6px 20px;
        min-width: 70px;
    }}
    QMessageBox QPushButton:hover {{
        background: {Colors.SURFACE_HOVER};
    }}

    /* ── Dialog ─────────────────────────────────────────────────── */
    QDialog {{
        background: {Colors.DIALOG_BG};
        color: {Colors.TEXT_PRIMARY};
    }}

    /* ── Input dialogs ──────────────────────────────────────────── */
    QInputDialog {{
        background: {Colors.DIALOG_BG};
        color: {Colors.TEXT_PRIMARY};
    }}
    QInputDialog QLabel {{
        color: {Colors.TEXT_PRIMARY};
    }}
    QInputDialog QLineEdit {{
        background: {Colors.SURFACE_ALT};
        color: {Colors.TEXT_PRIMARY};
        border: 1px solid {Colors.BORDER};
        border-radius: {Metrics.BORDER_RADIUS_SM}px;
        padding: 6px 10px;
    }}
    QInputDialog QPushButton {{
        background: {Colors.SURFACE_RAISED};
        border: 1px solid {Colors.BORDER};
        border-radius: {Metrics.BORDER_RADIUS_SM}px;
        color: {Colors.TEXT_PRIMARY};
        padding: 6px 20px;
        min-width: 70px;
    }}
    QInputDialog QPushButton:hover {{
        background: {Colors.SURFACE_HOVER};
    }}

    /* ── Combo boxes ─────────────────────────────────────────────── */
    QComboBox {{
        background: {Colors.SURFACE_RAISED};
        color: {Colors.TEXT_PRIMARY};
        border: 1px solid {Colors.BORDER};
        border-radius: {Metrics.BORDER_RADIUS_SM}px;
        padding: 5px 10px;
    }}
    QComboBox:hover {{
        background: {Colors.SURFACE_HOVER};
        border-color: {Colors.ACCENT_BORDER};
    }}
    QComboBox::drop-down {{
        border: none;
        width: 20px;
    }}
    QComboBox QAbstractItemView {{
        background: {Colors.MENU_BG};
        color: {Colors.TEXT_PRIMARY};
        border: 1px solid {Colors.BORDER};
        border-radius: {Metrics.BORDER_RADIUS_SM}px;
        selection-background-color: {Colors.ACCENT_DIM};
        outline: none;
    }}

    /* ── Line edits ──────────────────────────────────────────────── */
    QLineEdit {{
        background: {Colors.SURFACE_ALT};
        color: {Colors.TEXT_PRIMARY};
        border: 1px solid {Colors.BORDER_SUBTLE};
        border-radius: {Metrics.BORDER_RADIUS_SM}px;
        padding: 6px 10px;
    }}
    QLineEdit:focus {{
        border-color: {Colors.BORDER_FOCUS};
    }}

    /* ── Menus ───────────────────────────────────────────────────── */
    QMenu {{
        background: {Colors.MENU_BG};
        color: {Colors.TEXT_PRIMARY};
        border: 1px solid {Colors.BORDER};
        border-radius: {Metrics.BORDER_RADIUS}px;
        padding: 4px 0;
    }}
    QMenu::item {{
        padding: 6px 20px;
        border-radius: 4px;
        margin: 1px 4px;
    }}
    QMenu::item:selected {{
        background: {Colors.ACCENT_DIM};
    }}
    QMenu::separator {{
        height: 1px;
        background: {Colors.BORDER_SUBTLE};
        margin: 4px 8px;
    }}
"""


# Backwards-compatible alias — evaluated lazily so it always reflects the
# current theme as long as apply_theme() was called before first access.
# (main.py now uses get_app_stylesheet() directly; this shim keeps any other
# import sites working without changes.)
class _LazyStylesheet(str):
    """A str subclass that returns the current stylesheet on str() / use."""

    def __new__(cls):
        return str.__new__(cls, "")

    def __str__(self):
        return get_app_stylesheet()

    def __format__(self, spec):
        return format(get_app_stylesheet(), spec)


APP_STYLESHEET = _LazyStylesheet()
