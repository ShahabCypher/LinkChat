"""Modal Safety Number and 6-Emoji Fingerprint verification dialog."""

from __future__ import annotations

from typing import Callable

import customtkinter as ctk

from linkchat_core import PeerInfo, SafetyFingerprint

from ..i18n import DEFAULT_LANG, Lang, bidi_text, tr
from . import theme


class VerifyDialog(ctk.CTkToplevel):
    """Displays symmetric 30-digit safety number and 6-emoji fingerprint."""

    def __init__(
        self,
        master: ctk.CTk,
        peer: PeerInfo,
        fingerprint: SafetyFingerprint,
        on_verify: Callable[[str, bool], None],
        lang: Lang = DEFAULT_LANG,
    ) -> None:
        super().__init__(master)
        theme.apply_window_icon(self)
        self._peer = peer
        self._on_verify = on_verify
        rtl = lang == "fa"
        edge_anchor = "e" if rtl else "w"

        self.title(tr(lang, "verify_title", nick=peer.nickname))
        self.geometry("460x400")
        self.resizable(False, False)
        self.configure(fg_color=theme.BG_ROOT)
        self.transient(master)
        self.grab_set()

        container = ctk.CTkFrame(
            self,
            fg_color=theme.BG_PANEL,
            corner_radius=12,
            border_width=1,
            border_color=theme.BORDER_SUBTLE,
        )
        container.pack(fill="both", expand=True, padx=16, pady=16)

        ctk.CTkLabel(
            container,
            text=bidi_text(tr(lang, "safety_fingerprint_title", nick=peer.nickname), rtl),
            font=theme.ui_font(lang, 16, "bold"),
            text_color=theme.TEXT_PRIMARY,
        ).pack(anchor=edge_anchor, padx=16, pady=(14, 2))

        id_row = ctk.CTkFrame(container, fg_color="transparent")
        id_row.pack(fill="x", padx=16, pady=(0, 10))
        ctk.CTkLabel(
            id_row,
            text=bidi_text(tr(lang, "node_id_prefix"), rtl),
            font=theme.ui_font(lang, 11),
            text_color=theme.TEXT_MUTED,
        ).pack(side="right" if rtl else "left", padx=(4 if rtl else 0, 0 if rtl else 4))
        ctk.CTkLabel(
            id_row,
            text=peer.node_id_hex,
            font=(theme.FONT_MONO, 11),
            text_color=theme.TEXT_MUTED,
        ).pack(side="right" if rtl else "left")

        if peer.key_changed:
            warn = ctk.CTkFrame(container, fg_color="#451A1A", corner_radius=8)
            warn.pack(fill="x", padx=16, pady=(0, 10))
            warn_lbl = ctk.CTkLabel(
                warn,
                text="",
                font=theme.ui_font(lang, 12, "bold"),
                text_color="#FCA5A5",
                wraplength=390,
                justify="right" if rtl else "left",
            )
            warn_lbl.configure(
                text=theme.bidi_label_text(
                    warn_lbl, tr(lang, "verify_key_changed_warn"), rtl
                )
            )
            warn_lbl.pack(padx=10, pady=8)

        emoji_box = ctk.CTkFrame(container, fg_color=theme.BG_CARD, corner_radius=10)
        emoji_box.pack(fill="x", padx=16, pady=(0, 10))
        ctk.CTkLabel(
            emoji_box,
            text=bidi_text(tr(lang, "emoji_fp_label"), rtl),
            font=theme.ui_font(lang, 11),
            text_color=theme.TEXT_MUTED,
        ).pack(pady=(8, 2))
        ctk.CTkLabel(
            emoji_box,
            text=fingerprint.emoji_hash,
            font=(theme.FONT_FAMILY, 26),
            text_color=theme.TEXT_PRIMARY,
        ).pack(pady=(0, 10))

        num_box = ctk.CTkFrame(container, fg_color=theme.BG_CARD, corner_radius=10)
        num_box.pack(fill="x", padx=16, pady=(0, 12))
        ctk.CTkLabel(
            num_box,
            text=bidi_text(tr(lang, "safety_num_label"), rtl),
            font=theme.ui_font(lang, 11),
            text_color=theme.TEXT_MUTED,
        ).pack(pady=(8, 2))
        line1 = "   ".join(fingerprint.groups[:3])
        line2 = "   ".join(fingerprint.groups[3:])
        ctk.CTkLabel(
            num_box,
            text=f"{line1}\n{line2}",
            font=(theme.FONT_MONO, 15, "bold"),
            text_color=theme.ACCENT_CYAN,
            justify="center",
        ).pack(pady=(0, 10))

        ctk.CTkLabel(
            container,
            text=bidi_text(tr(lang, "verify_compare_hint"), rtl),
            font=theme.ui_font(lang, 11),
            text_color=theme.TEXT_MUTED,
        ).pack(pady=(0, 10))

        btn_row = ctk.CTkFrame(container, fg_color="transparent")
        btn_row.pack(fill="x", padx=16, pady=(0, 14))

        next_verified = not peer.verified
        btn_text = tr(lang, "mark_verified") if next_verified else tr(lang, "revoke_verification")
        btn_color = theme.STATUS_GREEN if next_verified else theme.STATUS_AMBER

        ctk.CTkButton(
            btn_row,
            text=bidi_text(btn_text, rtl),
            fg_color=btn_color,
            hover_color=theme.ACCENT_BLUE_HOVER,
            text_color="#0B1117",
            font=theme.ui_font(lang, 12, "bold"),
            command=lambda: self._handle_verify(next_verified),
        ).pack(
            side="right" if rtl else "left",
            expand=True,
            fill="x",
            padx=(8 if rtl else 0, 0 if rtl else 8),
        )

        ctk.CTkButton(
            btn_row,
            text=bidi_text(tr(lang, "close"), rtl),
            width=90,
            fg_color=theme.BG_CARD,
            hover_color=theme.BG_CARD_ACTIVE,
            font=theme.ui_font(lang, 12),
            command=self.destroy,
        ).pack(side="left" if rtl else "right")

    def _handle_verify(self, verified: bool) -> None:
        self._on_verify(self._peer.node_id_hex, verified)
        self.destroy()
