"""Modal Safety Number and 6-Emoji Fingerprint verification dialog."""

from __future__ import annotations

from typing import Callable

import customtkinter as ctk

from linkchat_core import PeerInfo, SafetyFingerprint

from . import theme


class VerifyDialog(ctk.CTkToplevel):
    """Displays symmetric 30-digit safety number and 6-emoji fingerprint."""

    def __init__(
        self,
        master: ctk.CTk,
        peer: PeerInfo,
        fingerprint: SafetyFingerprint,
        on_verify: Callable[[str, bool], None],
    ) -> None:
        super().__init__(master)
        self._peer = peer
        self._on_verify = on_verify

        self.title(f"Verify {peer.nickname}")
        self.geometry("460x390")
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
            text=f"Safety Fingerprint — {peer.nickname}",
            font=(theme.FONT_FAMILY, 16, "bold"),
            text_color=theme.TEXT_PRIMARY,
        ).pack(anchor="w", padx=16, pady=(14, 2))

        ctk.CTkLabel(
            container,
            text=f"Node ID: {peer.node_id_hex}",
            font=(theme.FONT_MONO, 11),
            text_color=theme.TEXT_MUTED,
        ).pack(anchor="w", padx=16, pady=(0, 10))

        if peer.key_changed:
            warn = ctk.CTkFrame(container, fg_color="#451A1A", corner_radius=8)
            warn.pack(fill="x", padx=16, pady=(0, 10))
            ctk.CTkLabel(
                warn,
                text="⚠ Key changed since first contact! Verify in person before trusting.",
                font=(theme.FONT_FAMILY, 12, "bold"),
                text_color="#FCA5A5",
                wraplength=390,
                justify="left",
            ).pack(padx=10, pady=8)

        emoji_box = ctk.CTkFrame(container, fg_color=theme.BG_CARD, corner_radius=10)
        emoji_box.pack(fill="x", padx=16, pady=(0, 10))
        ctk.CTkLabel(
            emoji_box,
            text="6-Emoji Fingerprint",
            font=(theme.FONT_FAMILY, 11),
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
            text="30-Digit Safety Number",
            font=(theme.FONT_FAMILY, 11),
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
            text="Compare both fingerprints side-by-side with your peer.",
            font=(theme.FONT_FAMILY, 11),
            text_color=theme.TEXT_MUTED,
        ).pack(pady=(0, 10))

        btn_row = ctk.CTkFrame(container, fg_color="transparent")
        btn_row.pack(fill="x", padx=16, pady=(0, 14))

        next_verified = not peer.verified
        btn_text = "Mark Verified ✓" if next_verified else "Revoke Verification"
        btn_color = theme.STATUS_GREEN if next_verified else theme.STATUS_AMBER

        ctk.CTkButton(
            btn_row,
            text=btn_text,
            fg_color=btn_color,
            hover_color=theme.ACCENT_BLUE_HOVER,
            text_color="#0B1117",
            font=(theme.FONT_FAMILY, 12, "bold"),
            command=lambda: self._handle_verify(next_verified),
        ).pack(side="left", expand=True, fill="x", padx=(0, 8))

        ctk.CTkButton(
            btn_row,
            text="Close",
            width=90,
            fg_color=theme.BG_CARD,
            hover_color=theme.BG_CARD_ACTIVE,
            command=self.destroy,
        ).pack(side="right")

    def _handle_verify(self, verified: bool) -> None:
        self._on_verify(self._peer.node_id_hex, verified)
        self.destroy()
