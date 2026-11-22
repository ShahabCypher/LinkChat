"""Styling constants, bundled font loading, and formatting helpers for LinkChat Windows UI."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import sys
from typing import Any

import customtkinter as ctk

from linkchat_core import DMStatus, PeerInfo

from ..i18n import DEFAULT_LANG, Lang, contains_persian, tr

BG_ROOT = "#0F141B"
BG_PANEL = "#161D26"
BG_CARD = "#1E2733"
BG_CARD_ACTIVE = "#263344"
BG_MSG_OUT = "#1B3B5F"
BG_MSG_IN = "#1E293B"
BG_INPUT = "#0D1117"

BORDER_SUBTLE = "#2B3646"

TEXT_PRIMARY = "#F1F5F9"
TEXT_MUTED = "#94A3B8"
TEXT_DIM = "#64748B"

ACCENT_BLUE = "#3B82F6"
ACCENT_BLUE_HOVER = "#2563EB"
ACCENT_CYAN = "#38BDF8"

STATUS_GREEN = "#22C55E"
STATUS_AMBER = "#F59E0B"
STATUS_RED = "#EF4444"

FONT_FAMILY = "Segoe UI"
FONT_PERSIAN = "Vazirmatn"
FONT_MONO = "Consolas"

_FONTS_LOADED = False


def load_bundled_fonts() -> None:
    """Register bundled Vazirmatn TTF fonts once for CustomTkinter/Tk."""
    global _FONTS_LOADED
    if _FONTS_LOADED:
        return
    font_dirs = [Path(__file__).resolve().parent.parent / "assets" / "fonts"]
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        font_dirs.insert(0, Path(meipass) / "linkchat_win" / "assets" / "fonts")
    for directory in font_dirs:
        if not directory.is_dir():
            continue
        for filename in ("Vazirmatn-Regular.ttf", "Vazirmatn-Bold.ttf"):
            font_path = directory / filename
            if font_path.is_file():
                try:
                    ctk.FontManager.load_font(str(font_path))
                except Exception:
                    pass
        _FONTS_LOADED = True
        return


def ui_font(lang: Lang, size: int, weight: str | None = None) -> tuple[Any, ...]:
    """Return UI font tuple using Vazirmatn for Persian and Segoe UI for English."""
    family = FONT_PERSIAN if lang == "fa" else FONT_FAMILY
    return (family, size, weight) if weight else (family, size)


def message_font(
    text: str, lang: Lang, size: int, weight: str | None = None
) -> tuple[Any, ...]:
    """Use Vazirmatn whenever text contains Persian characters or UI is Persian."""
    family = FONT_PERSIAN if (lang == "fa" or contains_persian(text)) else FONT_FAMILY
    return (family, size, weight) if weight else (family, size)


def format_timestamp(ts_ms: int) -> str:
    """Format epoch milliseconds into local HH:MM (Latin digits)."""
    return datetime.fromtimestamp(ts_ms / 1000.0).strftime("%H:%M")


def format_log_timestamp(ts_ms: int) -> str:
    """Format epoch milliseconds into local HH:MM:SS (Latin digits)."""
    return datetime.fromtimestamp(ts_ms / 1000.0).strftime("%H:%M:%S")


def format_hop_badge(peer: PeerInfo, lang: Lang = DEFAULT_LANG) -> tuple[str, str]:
    """Return (badge_text, color) describing peer reachability."""
    if not peer.connected:
        return tr(lang, "hop_offline"), TEXT_DIM
    if peer.direct or peer.hop_count <= 1:
        return tr(lang, "hop_direct"), STATUS_GREEN
    unit = "hop" if peer.hop_count == 1 else "hops"
    return tr(lang, "hop_n", n=peer.hop_count, unit=unit), ACCENT_CYAN


def format_rssi(
    rssi: int, direct: bool, connected: bool, lang: Lang = DEFAULT_LANG
) -> str:
    """Return human-readable signal indicator for a peer."""
    if not connected:
        return tr(lang, "rssi_disconnected")
    if not direct:
        return tr(lang, "rssi_relay")
    if rssi >= -60:
        bars = "▂▄▆█"
    elif rssi >= -75:
        bars = "▂▄▆"
    elif rssi >= -88:
        bars = "▂▄"
    else:
        bars = "▂"
    return f"{rssi} dBm {bars}"


def format_dm_status(status: str, lang: Lang = DEFAULT_LANG) -> tuple[str, str]:
    """Return (label, color) for message delivery status."""
    if status == DMStatus.DELIVERED.value:
        return tr(lang, "dm_delivered"), STATUS_GREEN
    if status == DMStatus.RELAYED.value:
        return tr(lang, "dm_relayed"), ACCENT_CYAN
    return tr(lang, "dm_sending"), TEXT_MUTED


def apply_window_icon(window: Any) -> None:
    """Apply the LinkChat app icon to a Tk/CTk window on Windows."""
    if not sys.platform.startswith("win"):
        return
    candidates = [Path(__file__).resolve().parent.parent / "assets" / "linkchat.ico"]
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.insert(0, Path(meipass) / "linkchat_win" / "assets" / "linkchat.ico")
    for path in candidates:
        if path.is_file():
            try:
                window.iconbitmap(str(path))
            except Exception:
                pass
            return
