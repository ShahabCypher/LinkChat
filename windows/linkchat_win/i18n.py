"""Bilingual (Persian default / English) localization and BiDi helpers for LinkChat Windows UI."""

from __future__ import annotations

import unicodedata
from typing import Literal

Lang = Literal["fa", "en"]
DEFAULT_LANG: Lang = "fa"
SUPPORTED_LANGS: tuple[Lang, ...] = ("fa", "en")

_RLM = "\u200F"
_RLE = "\u202B"
_PDF = "\u202C"

STRINGS: dict[Lang, dict[str, str]] = {
    "fa": {
        "window_title": "لینک‌چت — پیام‌رسان توری آفلاین بلوتوث",
        "app_name": "لینک‌چت",
        "id_prefix": "ID:",
        "mode_starting": "در حال راه‌اندازی...",
        "mode_dual_role": "دوحالته",
        "mode_central_only": "فقط مرکزی",
        "connecting": "در حال اتصال...",
        "nickname_label": "نام:",
        "save": "ذخیره",
        "lang_toggle": "EN",
        "inspector_btn": "تحلیلگر شبکه",
        "reset_identity": "بازنشانی هویت",
        "resetting": "در حال بازنشانی...",
        "public_channel_btn": "#public  ·  Mesh Broadcast",
        "public_channel_title": "#public — Mesh Broadcast",
        "peer_radar_zero": "رادار همتایان (0)",
        "peer_radar_header": "رادار همتایان ({online}/{total})",
        "scanning_peers": "در حال جستجوی همتایان لینک‌چت...",
        "verify_safety": "تایید امنیت",
        "key_changed_banner": "⚠ کلید هویت این همتا از اولین تماس تغییر کرده است. پیش از ارسال پیام خصوصی اثرانگشت را تایید کنید.",
        "msg_placeholder_public": "پیام در #public...",
        "msg_placeholder_dm": "پیام رمزنگاری‌شده به {nick}...",
        "send": "ارسال",
        "inspector_header": "تحلیلگر شبکه",
        "clear": "پاک کردن",
        "dm_unknown_title": "پیام خصوصی · {short_id}",
        "verified": "تایید شده ✓",
        "unverified": "تایید نشده",
        "dm_header_title": "پیام رمزنگاری‌شده · {nick} ({tag}) · {status}",
        "hop_offline": "آفلاین",
        "hop_direct": "مستقیم",
        "hop_n": "{n} جهش",
        "rssi_disconnected": "قطع",
        "rssi_relay": "از طریق رله توری",
        "dm_delivered": "تحویل شد ✓",
        "dm_relayed": "بازپخش شد",
        "dm_sending": "در حال ارسال...",
        "verify_title": "تایید {nick}",
        "safety_fingerprint_title": "اثرانگشت امنیتی — {nick}",
        "node_id_prefix": "شناسه گره:",
        "verify_key_changed_warn": "⚠ کلید از اولین تماس تغییر کرده است! پیش از اعتماد حضوری تایید کنید.",
        "emoji_fp_label": "اثرانگشت 6 ایموجی",
        "safety_num_label": "شماره امنیتی 30 رقمی",
        "verify_compare_hint": "هر دو اثرانگشت را به صورت هم‌زمان با همتای خود مقایسه کنید.",
        "mark_verified": "تایید هویت ✓",
        "revoke_verification": "لغو تاییدیه",
        "close": "بستن",
        "reset_dlg_title": "بازنشانی هویت و پاک‌سازی داده‌ها",
        "reset_dlg_heading": "پاک کردن تمام داده‌ها و بازنشانی هویت؟",
        "reset_dlg_body": (
            "این کار کلیدهای رمزنگاری، نام مستعار، همتایان، سوابق اعتماد و تمام "
            "تاریخچه گفتگو را برای همیشه پاک می‌کند. به عنوان کاربر جدید به شبکه بازمی‌گردید."
        ),
        "cancel": "انصراف",
        "wipe_reset": "پاک کردن و بازنشانی",
    },
    "en": {
        "window_title": "LinkChat — Offline BLE Mesh Messenger",
        "app_name": "LinkChat",
        "id_prefix": "ID:",
        "mode_starting": "Starting...",
        "mode_dual_role": "Dual-Role",
        "mode_central_only": "Central-Only",
        "connecting": "Connecting...",
        "nickname_label": "Nickname:",
        "save": "Save",
        "lang_toggle": "فارسی",
        "inspector_btn": "Mesh Inspector",
        "reset_identity": "Reset Identity",
        "resetting": "Resetting...",
        "public_channel_btn": "#public  ·  Mesh Broadcast",
        "public_channel_title": "#public — Mesh Broadcast",
        "peer_radar_zero": "PEER RADAR (0)",
        "peer_radar_header": "PEER RADAR ({online}/{total})",
        "scanning_peers": "Scanning for LinkChat peers...",
        "verify_safety": "Verify Safety",
        "key_changed_banner": "⚠ Peer identity key changed since first contact. Verify fingerprint before sending sensitive DMs.",
        "msg_placeholder_public": "Message #public...",
        "msg_placeholder_dm": "Encrypted DM to {nick}...",
        "send": "Send",
        "inspector_header": "MESH INSPECTOR",
        "clear": "Clear",
        "dm_unknown_title": "DM · {short_id}",
        "verified": "Verified ✓",
        "unverified": "Unverified",
        "dm_header_title": "E2EE DM · {nick} ({tag}) · {status}",
        "hop_offline": "Offline",
        "hop_direct": "Direct",
        "hop_n": "{n} {unit}",
        "rssi_disconnected": "disconnected",
        "rssi_relay": "via mesh relay",
        "dm_delivered": "Delivered ✓",
        "dm_relayed": "Relayed",
        "dm_sending": "Sending...",
        "verify_title": "Verify {nick}",
        "safety_fingerprint_title": "Safety Fingerprint — {nick}",
        "node_id_prefix": "Node ID:",
        "verify_key_changed_warn": "⚠ Key changed since first contact! Verify in person before trusting.",
        "emoji_fp_label": "6-Emoji Fingerprint",
        "safety_num_label": "30-Digit Safety Number",
        "verify_compare_hint": "Compare both fingerprints side-by-side with your peer.",
        "mark_verified": "Mark Verified ✓",
        "revoke_verification": "Revoke Verification",
        "close": "Close",
        "reset_dlg_title": "Reset Identity & Wipe Data",
        "reset_dlg_heading": "Erase All Data & Reset Identity?",
        "reset_dlg_body": (
            "This permanently wipes your cryptographic keys, nickname, "
            "peers, trust records, and all chat history. You will rejoin "
            "the mesh as a brand-new user."
        ),
        "cancel": "Cancel",
        "wipe_reset": "Wipe & Reset",
    },
}


def normalize_lang(value: str | None) -> Lang:
    """Coerce arbitrary language code to a supported Lang, defaulting to Persian."""
    if value == "en":
        return "en"
    return DEFAULT_LANG


def tr(lang: Lang, key: str, **kwargs: object) -> str:
    """Look up a localized string for lang and optionally format placeholders."""
    template = STRINGS[lang][key]
    return template.format(**kwargs) if kwargs else template


def translate_mode_label(lang: Lang, central_only: bool, raw_label: str = "") -> str:
    """Localize transport mode labels while preserving unknown custom strings."""
    if central_only or raw_label == "Central-Only":
        return tr(lang, "mode_central_only")
    if raw_label in ("", "Dual-Role"):
        return tr(lang, "mode_dual_role")
    return raw_label


def is_persian_char(ch: str) -> bool:
    """Return True if ch belongs to Arabic/Persian Unicode presentation blocks."""
    code = ord(ch)
    return (
        0x0600 <= code <= 0x06FF
        or 0x0750 <= code <= 0x077F
        or 0x08A0 <= code <= 0x08FF
        or 0xFB50 <= code <= 0xFDFF
        or 0xFE70 <= code <= 0xFEFF
    )


def contains_persian(text: str) -> bool:
    """Return True when text contains at least one Persian/Arabic script character."""
    return any(is_persian_char(ch) for ch in text)


def detect_rtl(text: str, default_rtl: bool = False) -> bool:
    """Infer text direction from the first strong directional Unicode character."""
    for ch in text:
        bidi = unicodedata.bidirectional(ch)
        if bidi in ("AL", "R"):
            return True
        if bidi == "L":
            return False
    return default_rtl


def bidi_text(text: str, rtl: bool) -> str:
    """Apply subtle RTL embedding so mixed Persian + ASCII tokens order cleanly in Tk."""
    if not rtl or not text:
        return text
    if text.startswith((_RLE, _RLM)):
        return text
    if not detect_rtl(text):
        return f"{_RLE}{text}{_PDF}"
    return f"{_RLM}{text}"
