"""Styling constants and formatting helpers for LinkChat Windows UI."""

from __future__ import annotations

from datetime import datetime

from linkchat_core import DMStatus, PeerInfo

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
FONT_MONO = "Consolas"


def format_timestamp(ts_ms: int) -> str:
    """Format epoch milliseconds into local HH:MM."""
    return datetime.fromtimestamp(ts_ms / 1000.0).strftime("%H:%M")


def format_log_timestamp(ts_ms: int) -> str:
    """Format epoch milliseconds into local HH:MM:SS."""
    return datetime.fromtimestamp(ts_ms / 1000.0).strftime("%H:%M:%S")


def format_hop_badge(peer: PeerInfo) -> tuple[str, str]:
    """Return (badge_text, color) describing peer reachability."""
    if not peer.connected:
        return "Offline", TEXT_DIM
    if peer.direct or peer.hop_count <= 1:
        return "Direct", STATUS_GREEN
    unit = "hop" if peer.hop_count == 1 else "hops"
    return f"{peer.hop_count} {unit}", ACCENT_CYAN


def format_rssi(rssi: int, direct: bool, connected: bool) -> str:
    """Return human-readable signal indicator for a peer."""
    if not connected:
        return "disconnected"
    if not direct:
        return "via mesh relay"
    if rssi >= -60:
        bars = "▂▄▆█"
    elif rssi >= -75:
        bars = "▂▄▆"
    elif rssi >= -88:
        bars = "▂▄"
    else:
        bars = "▂"
    return f"{rssi} dBm {bars}"


def format_dm_status(status: str) -> tuple[str, str]:
    """Return (label, color) for message delivery status."""
    if status == DMStatus.DELIVERED.value:
        return "Delivered ✓", STATUS_GREEN
    if status == DMStatus.RELAYED.value:
        return "Relayed", ACCENT_CYAN
    return "Sending...", TEXT_MUTED
