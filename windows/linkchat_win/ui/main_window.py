"""CustomTkinter main desktop window for LinkChat."""

from __future__ import annotations

from collections import deque
import queue
from typing import TYPE_CHECKING, Any

import customtkinter as ctk

from linkchat_core import LogEntry, MessageRecord, PeerInfo

from .. import prefs
from ..i18n import (
    Lang,
    bidi_text,
    contains_persian,
    detect_rtl,
    tr,
    translate_mode_label,
)
from . import theme
from .verify_dialog import VerifyDialog

if TYPE_CHECKING:
    from ..app import BackendBridge

POLL_INTERVAL_MS = 50
MAX_INSPECTOR_LINES = 300


class MainWindow:
    """LinkChat Windows desktop UI driven by BackendBridge events."""

    def __init__(self, bridge: BackendBridge) -> None:
        self.bridge = bridge
        theme.load_bundled_fonts()

        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        self._lang: Lang = prefs.load_language(bridge.data_dir)

        self.root = ctk.CTk()
        theme.apply_window_icon(self.root)
        self.root.title(tr(self._lang, "window_title"))
        self.root.geometry("1120x680")
        self.root.minsize(920, 560)
        self.root.configure(fg_color=theme.BG_ROOT)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        self._own_node_id = ""
        self._short_tag = ""
        self._nickname = ""
        self._central_only = False
        self._raw_mode_label = ""
        self._resetting = False
        self._active_channel = "#public"
        self._inspector_visible = False
        self._peers: dict[str, PeerInfo] = {}
        self._messages: dict[str, list[MessageRecord]] = {"#public": []}
        self._seen_msg_ids: dict[str, set[str]] = {"#public": set()}
        self._unread_counts: dict[str, int] = {}
        self._loaded_channels: set[str] = set()
        self._status_labels: dict[str, ctk.CTkLabel] = {}
        self._inspector_lines_buf: deque[str] = deque(maxlen=MAX_INSPECTOR_LINES)
        self._verify_dialog: VerifyDialog | None = None
        self._reset_dialog: ctk.CTkToplevel | None = None

        self._build_layout()
        self._poll_job = self.root.after(POLL_INTERVAL_MS, self._poll_events)

    def run(self) -> None:
        self.root.mainloop()

    # ------------------------------------------------------------------
    # Layout construction
    # ------------------------------------------------------------------

    @property
    def _is_rtl(self) -> bool:
        return self._lang == "fa"

    def _build_layout(self) -> None:
        self.root.grid_rowconfigure(0, weight=0)
        self.root.grid_rowconfigure(1, weight=1)
        self.root.grid_columnconfigure(0, weight=0)
        self.root.grid_columnconfigure(1, weight=1)
        self.root.grid_columnconfigure(2, weight=0)

        self._build_profile_bar()
        self._build_peer_sidebar(column=2 if self._is_rtl else 0)
        self._build_chat_workspace(column=1)
        self._build_inspector_drawer(column=0 if self._is_rtl else 2)

    def _build_profile_bar(self) -> None:
        lang = self._lang
        rtl = self._is_rtl

        bar = ctk.CTkFrame(
            self.root,
            fg_color=theme.BG_PANEL,
            corner_radius=0,
            border_width=1,
            border_color=theme.BORDER_SUBTLE,
            height=56,
        )
        bar.grid(row=0, column=0, columnspan=3, sticky="ew")

        spacer_col = 4 if rtl else 3
        for col in range(8):
            bar.grid_columnconfigure(col, weight=1 if col == spacer_col else 0)

        brand_lbl = ctk.CTkLabel(
            bar,
            text=tr(lang, "app_name"),
            font=theme.ui_font(lang, 17, "bold"),
            text_color=theme.ACCENT_CYAN,
        )
        brand_lbl.grid(
            row=0,
            column=7 if rtl else 0,
            padx=(12, 16) if rtl else (16, 12),
            pady=12,
        )

        self._id_label = ctk.CTkLabel(
            bar,
            text=self._format_id_text(),
            font=(theme.FONT_MONO, 12),
            text_color=theme.TEXT_MUTED,
        )
        self._id_label.grid(
            row=0,
            column=6 if rtl else 1,
            padx=(12, 0) if rtl else (0, 12),
        )

        self._mode_badge = ctk.CTkLabel(
            bar,
            text=self._format_mode_text(),
            font=theme.ui_font(lang, 11, "bold"),
            text_color="#0B1117",
            fg_color=self._mode_badge_color(),
            corner_radius=8,
            padx=10,
            pady=3,
        )
        self._mode_badge.grid(
            row=0,
            column=5 if rtl else 2,
            padx=(8, 0) if rtl else (0, 8),
        )

        self._connecting_badge = ctk.CTkLabel(
            bar,
            text=tr(lang, "connecting"),
            font=theme.ui_font(lang, 11, "bold"),
            text_color=theme.ACCENT_CYAN,
            fg_color=theme.BG_CARD,
            corner_radius=8,
            padx=10,
            pady=3,
        )
        self._connecting_badge.grid(
            row=0,
            column=spacer_col,
            sticky="e" if rtl else "w",
            padx=(12, 0) if rtl else (0, 12),
        )
        self._connecting_badge.grid_remove()

        nick_wrap = ctk.CTkFrame(bar, fg_color="transparent")
        nick_wrap.grid(
            row=0,
            column=3 if rtl else 4,
            padx=(12, 0) if rtl else (0, 12),
        )

        nick_lbl = ctk.CTkLabel(
            nick_wrap,
            text=tr(lang, "nickname_label"),
            font=theme.ui_font(lang, 12),
            text_color=theme.TEXT_MUTED,
        )
        self._nick_entry = ctk.CTkEntry(
            nick_wrap,
            width=155,
            fg_color=theme.BG_INPUT,
            border_color=theme.BORDER_SUBTLE,
            font=theme.ui_font(lang, 12),
            justify="right" if rtl else "left",
        )
        if self._nickname:
            self._nick_entry.insert(0, self._nickname)
        self._nick_entry.bind("<Return>", lambda _e: self._save_nickname())

        save_btn = ctk.CTkButton(
            nick_wrap,
            text=tr(lang, "save"),
            width=64,
            fg_color=theme.BG_CARD,
            hover_color=theme.BG_CARD_ACTIVE,
            font=theme.ui_font(lang, 12),
            command=self._save_nickname,
        )

        if rtl:
            save_btn.pack(side="left")
            self._nick_entry.pack(side="left", padx=(6, 6))
            nick_lbl.pack(side="left", padx=(0, 0))
        else:
            nick_lbl.pack(side="left", padx=(0, 6))
            self._nick_entry.pack(side="left", padx=(0, 6))
            save_btn.pack(side="left")

        self._lang_btn = ctk.CTkButton(
            bar,
            text=tr(lang, "lang_toggle"),
            width=58,
            fg_color=theme.BG_CARD,
            hover_color=theme.BG_CARD_ACTIVE,
            font=theme.ui_font("en" if rtl else "fa", 12, "bold"),
            command=self._toggle_language,
        )
        self._lang_btn.grid(
            row=0,
            column=2 if rtl else 5,
            padx=(8, 0) if rtl else (0, 8),
        )

        self._inspector_btn = ctk.CTkButton(
            bar,
            text=tr(lang, "inspector_btn"),
            width=120,
            fg_color=theme.ACCENT_BLUE if self._inspector_visible else theme.BG_CARD,
            hover_color=theme.BG_CARD_ACTIVE,
            font=theme.ui_font(lang, 12),
            command=self._toggle_inspector,
        )
        self._inspector_btn.grid(
            row=0,
            column=1 if rtl else 6,
            padx=(8, 0) if rtl else (0, 8),
        )

        self._reset_btn = ctk.CTkButton(
            bar,
            text=tr(lang, "resetting" if self._resetting else "reset_identity"),
            width=116,
            fg_color="#7F1D1D",
            hover_color="#991B1B",
            text_color="#FEE2E2",
            font=theme.ui_font(lang, 12),
            state="disabled" if self._resetting else "normal",
            command=self._open_reset_confirm,
        )
        self._reset_btn.grid(
            row=0,
            column=0 if rtl else 7,
            padx=(16, 0) if rtl else (0, 16),
        )

    def _build_peer_sidebar(self, column: int) -> None:
        lang = self._lang
        rtl = self._is_rtl

        sidebar = ctk.CTkFrame(
            self.root,
            fg_color=theme.BG_PANEL,
            corner_radius=0,
            border_width=1,
            border_color=theme.BORDER_SUBTLE,
            width=270,
        )
        sidebar.grid(row=1, column=column, sticky="nsew")
        sidebar.grid_propagate(False)
        sidebar.grid_rowconfigure(2, weight=1)
        sidebar.grid_columnconfigure(0, weight=1)

        self._public_btn = ctk.CTkButton(
            sidebar,
            text=tr(lang, "public_channel_btn"),
            anchor="w",
            height=40,
            fg_color=theme.ACCENT_BLUE,
            hover_color=theme.ACCENT_BLUE_HOVER,
            font=theme.ui_font("en", 13, "bold"),
            command=lambda: self._select_channel("#public"),
        )
        self._public_btn.grid(row=0, column=0, sticky="ew", padx=12, pady=(12, 8))

        header = ctk.CTkFrame(sidebar, fg_color="transparent")
        header.grid(row=1, column=0, sticky="ew", padx=14, pady=(4, 4))
        self._radar_title = ctk.CTkLabel(
            header,
            text=bidi_text(tr(lang, "peer_radar_zero"), rtl),
            font=theme.ui_font(lang, 11, "bold"),
            text_color=theme.TEXT_MUTED,
        )
        self._radar_title.pack(side="right" if rtl else "left")

        self._peer_list_frame = ctk.CTkScrollableFrame(
            sidebar,
            fg_color="transparent",
        )
        self._peer_list_frame.grid(row=2, column=0, sticky="nsew", padx=8, pady=(0, 8))
        self._peer_list_frame.grid_columnconfigure(0, weight=1)

    def _build_chat_workspace(self, column: int) -> None:
        lang = self._lang
        rtl = self._is_rtl

        workspace = ctk.CTkFrame(self.root, fg_color=theme.BG_ROOT, corner_radius=0)
        workspace.grid(row=1, column=column, sticky="nsew")
        workspace.grid_rowconfigure(2, weight=1)
        workspace.grid_columnconfigure(0, weight=1)

        header = ctk.CTkFrame(
            workspace,
            fg_color=theme.BG_PANEL,
            corner_radius=0,
            border_width=1,
            border_color=theme.BORDER_SUBTLE,
            height=48,
        )
        header.grid(row=0, column=0, sticky="ew")
        header.grid_columnconfigure(1 if rtl else 0, weight=1)

        self._channel_title = ctk.CTkLabel(
            header,
            text=tr(lang, "public_channel_title"),
            font=theme.ui_font("en", 14, "bold"),
            text_color=theme.TEXT_PRIMARY,
        )
        self._channel_title.grid(
            row=0,
            column=1 if rtl else 0,
            sticky="e" if rtl else "w",
            padx=16,
            pady=10,
        )

        self._verify_btn = ctk.CTkButton(
            header,
            text=tr(lang, "verify_safety"),
            width=110,
            height=28,
            fg_color=theme.BG_CARD,
            hover_color=theme.BG_CARD_ACTIVE,
            font=theme.ui_font(lang, 12),
            command=self._open_verify_for_active,
        )
        self._verify_btn.grid(row=0, column=0 if rtl else 1, padx=14, pady=8)
        self._verify_btn.grid_remove()

        self._key_warning_banner = ctk.CTkFrame(
            workspace, fg_color="#451A1A", corner_radius=0
        )
        self._key_warning_banner.grid(row=1, column=0, sticky="ew")
        ctk.CTkLabel(
            self._key_warning_banner,
            text=bidi_text(tr(lang, "key_changed_banner"), rtl),
            font=theme.ui_font(lang, 12, "bold"),
            text_color="#FCA5A5",
            justify="right" if rtl else "left",
        ).pack(side="right" if rtl else "left", padx=14, pady=6)
        self._key_warning_banner.grid_remove()

        self._chat_scroll = ctk.CTkScrollableFrame(
            workspace, fg_color=theme.BG_ROOT
        )
        self._chat_scroll.grid(row=2, column=0, sticky="nsew", padx=10, pady=8)
        self._chat_scroll.grid_columnconfigure(0, weight=1)

        composer = ctk.CTkFrame(
            workspace,
            fg_color=theme.BG_PANEL,
            corner_radius=0,
            border_width=1,
            border_color=theme.BORDER_SUBTLE,
        )
        composer.grid(row=3, column=0, sticky="ew")
        composer.grid_columnconfigure(1 if rtl else 0, weight=1)

        self._msg_entry = ctk.CTkEntry(
            composer,
            placeholder_text=tr(lang, "msg_placeholder_public"),
            height=38,
            fg_color=theme.BG_INPUT,
            border_color=theme.BORDER_SUBTLE,
            font=theme.ui_font(lang, 13),
            justify="right" if rtl else "left",
        )
        self._msg_entry.grid(
            row=0,
            column=1 if rtl else 0,
            sticky="ew",
            padx=(8, 12) if rtl else (12, 8),
            pady=10,
        )
        self._msg_entry.bind("<Return>", lambda _e: self._send_message())
        self._msg_entry.bind("<KeyRelease>", lambda _e: self._sync_entry_bidi())

        ctk.CTkButton(
            composer,
            text=tr(lang, "send"),
            width=88,
            height=38,
            fg_color=theme.ACCENT_BLUE,
            hover_color=theme.ACCENT_BLUE_HOVER,
            font=theme.ui_font(lang, 13, "bold"),
            command=self._send_message,
        ).grid(
            row=0,
            column=0 if rtl else 1,
            padx=(12, 0) if rtl else (0, 12),
            pady=10,
        )

    def _build_inspector_drawer(self, column: int) -> None:
        lang = self._lang
        rtl = self._is_rtl

        self._inspector_frame = ctk.CTkFrame(
            self.root,
            fg_color=theme.BG_PANEL,
            corner_radius=0,
            border_width=1,
            border_color=theme.BORDER_SUBTLE,
            width=330,
        )
        self._inspector_frame.grid(row=1, column=column, sticky="nsew")
        self._inspector_frame.grid_propagate(False)
        self._inspector_frame.grid_rowconfigure(1, weight=1)
        self._inspector_frame.grid_columnconfigure(0, weight=1)

        hdr = ctk.CTkFrame(self._inspector_frame, fg_color="transparent")
        hdr.grid(row=0, column=0, sticky="ew", padx=12, pady=(10, 4))
        ctk.CTkLabel(
            hdr,
            text=tr(lang, "inspector_header"),
            font=theme.ui_font(lang, 11, "bold"),
            text_color=theme.TEXT_MUTED,
        ).pack(side="right" if rtl else "left")
        ctk.CTkButton(
            hdr,
            text=tr(lang, "clear"),
            width=64,
            height=24,
            fg_color=theme.BG_CARD,
            hover_color=theme.BG_CARD_ACTIVE,
            font=theme.ui_font(lang, 11),
            command=self._clear_inspector,
        ).pack(side="left" if rtl else "right")

        self._inspector_text = ctk.CTkTextbox(
            self._inspector_frame,
            fg_color=theme.BG_INPUT,
            text_color=theme.TEXT_PRIMARY,
            font=(theme.FONT_MONO, 11),
            wrap="word",
            state="disabled",
        )
        self._inspector_text.grid(row=1, column=0, sticky="nsew", padx=10, pady=(4, 10))
        if self._inspector_lines_buf:
            self._inspector_text.configure(state="normal")
            self._inspector_text.insert("end", "\n".join(self._inspector_lines_buf) + "\n")
            self._inspector_text.see("end")
            self._inspector_text.configure(state="disabled")
        if not self._inspector_visible:
            self._inspector_frame.grid_remove()

    # ------------------------------------------------------------------
    # Language switching
    # ------------------------------------------------------------------

    def _toggle_language(self) -> None:
        new_lang: Lang = "en" if self._lang == "fa" else "fa"
        self._set_language(new_lang)

    def _set_language(self, new_lang: Lang) -> None:
        if new_lang == self._lang:
            return

        draft_msg = ""
        if not getattr(self._msg_entry, "_placeholder_text_active", False):
            draft_msg = self._msg_entry.get()
        draft_nick = self._nick_entry.get()
        if draft_nick:
            self._nickname = draft_nick

        if self._verify_dialog is not None and self._verify_dialog.winfo_exists():
            self._verify_dialog.destroy()
        self._verify_dialog = None
        if self._reset_dialog is not None and self._reset_dialog.winfo_exists():
            self._reset_dialog.destroy()
        self._reset_dialog = None

        self._lang = new_lang
        prefs.save_language(self.bridge.data_dir, new_lang)
        self.root.title(tr(new_lang, "window_title"))

        self._status_labels.clear()
        for child in self.root.winfo_children():
            child.destroy()

        self._build_layout()
        self._refresh_peer_radar()
        self._update_channel_header()
        self._render_active_chat()
        if draft_msg:
            self._msg_entry._deactivate_placeholder()
            self._msg_entry.insert(0, draft_msg)
            self._sync_entry_bidi()

    def _sync_entry_bidi(self) -> None:
        if getattr(self._msg_entry, "_placeholder_text_active", False):
            return
        text = self._msg_entry.get()
        if not text:
            rtl = self._is_rtl
            target_font = theme.ui_font(self._lang, 13)
        else:
            rtl = detect_rtl(text, default_rtl=self._is_rtl)
            target_font = theme.message_font(text, self._lang, 13)
        target_justify = "right" if rtl else "left"
        if self._msg_entry.cget("justify") != target_justify:
            self._msg_entry.configure(justify=target_justify)
        if self._msg_entry.cget("font") != target_font:
            self._msg_entry.configure(font=target_font)

    # ------------------------------------------------------------------
    # Event polling & dispatch
    # ------------------------------------------------------------------

    def _poll_events(self) -> None:
        from ..app import (
            DmReceivedEvent,
            DmStatusChangedEvent,
            ErrorEvent,
            FingerprintReadyEvent,
            HistoryLoadedEvent,
            MeshLogEvent,
            ModeChangedEvent,
            NodeReadyEvent,
            NodeResetEvent,
            PeerUpdatedEvent,
            PublicMessageEvent,
        )

        try:
            while True:
                ev = self.bridge.events.get_nowait()
                if isinstance(ev, NodeReadyEvent):
                    self._on_node_ready(ev)
                elif isinstance(ev, NodeResetEvent):
                    self._on_node_reset(ev)
                elif isinstance(ev, ModeChangedEvent):
                    self._update_mode_badge(ev.central_only, ev.mode_label)
                elif isinstance(ev, PeerUpdatedEvent):
                    self._on_peer_updated(ev.peer)
                elif isinstance(ev, PublicMessageEvent):
                    self._on_message("#public", ev.record)
                elif isinstance(ev, DmReceivedEvent):
                    self._on_message(ev.record.channel, ev.record)
                elif isinstance(ev, DmStatusChangedEvent):
                    self._on_dm_status(ev.msg_id, ev.status)
                elif isinstance(ev, MeshLogEvent):
                    self._append_inspector_log(ev.entry)
                elif isinstance(ev, HistoryLoadedEvent):
                    self._on_history_loaded(ev.channel, ev.messages)
                elif isinstance(ev, FingerprintReadyEvent):
                    self._on_fingerprint_ready(ev.peer, ev.fingerprint)
                elif isinstance(ev, ErrorEvent):
                    self._resetting = False
                    self._reset_btn.configure(
                        state="normal", text=tr(self._lang, "reset_identity")
                    )
                    self._append_raw_inspector(f"[ERROR] {ev.message}")
        except queue.Empty:
            pass
        finally:
            self._poll_job = self.root.after(POLL_INTERVAL_MS, self._poll_events)

    def _format_id_text(self) -> str:
        prefix = tr(self._lang, "id_prefix")
        if not self._own_node_id:
            return f"{prefix} ----"
        return f"{prefix} {self._short_tag} ({self._own_node_id[:8]}…)"

    def _format_mode_text(self) -> str:
        if not self._own_node_id and not self._raw_mode_label:
            return tr(self._lang, "mode_starting")
        return translate_mode_label(self._lang, self._central_only, self._raw_mode_label)

    def _mode_badge_color(self) -> str:
        if not self._own_node_id and not self._raw_mode_label:
            return theme.TEXT_MUTED
        return theme.STATUS_AMBER if self._central_only else theme.STATUS_GREEN

    def _on_node_ready(self, ev: Any) -> None:
        self._own_node_id = ev.node_id_hex
        self._short_tag = ev.short_tag
        self._nickname = ev.nickname
        self._id_label.configure(text=self._format_id_text())
        self._nick_entry.delete(0, "end")
        self._nick_entry.insert(0, ev.nickname)
        self._update_mode_badge(ev.central_only, ev.mode_label)

        for peer in ev.initial_peers:
            self._peers[peer.node_id_hex] = peer
        self._refresh_peer_radar()

        self._loaded_channels.add("#public")
        self._messages["#public"] = list(ev.public_history)
        self._seen_msg_ids["#public"] = {m.msg_id for m in ev.public_history}
        if self._active_channel == "#public":
            self._render_active_chat()

    def _update_mode_badge(self, central_only: bool, label: str) -> None:
        self._central_only = central_only
        self._raw_mode_label = label
        self._mode_badge.configure(
            text=self._format_mode_text(),
            fg_color=self._mode_badge_color(),
        )

    def _on_peer_updated(self, peer: PeerInfo) -> None:
        self._peers[peer.node_id_hex] = peer
        self._refresh_peer_radar()
        if self._active_channel == peer.node_id_hex:
            self._update_channel_header()

    def _on_message(self, channel: str, record: MessageRecord) -> None:
        seen = self._seen_msg_ids.setdefault(channel, set())
        if record.msg_id in seen:
            return
        seen.add(record.msg_id)
        msgs = self._messages.setdefault(channel, [])
        msgs.append(record)

        if channel == self._active_channel:
            self._append_message_bubble(record, len(msgs) - 1)
            self._scroll_chat_to_bottom()
        else:
            self._unread_counts[channel] = self._unread_counts.get(channel, 0) + 1
            self._refresh_peer_radar()

    def _on_dm_status(self, msg_id: str, status: str) -> None:
        for msg_list in self._messages.values():
            for idx, rec in enumerate(msg_list):
                if rec.msg_id == msg_id:
                    msg_list[idx] = MessageRecord(
                        msg_id=rec.msg_id,
                        channel=rec.channel,
                        origin_id=rec.origin_id,
                        target_id=rec.target_id,
                        sender_nick=rec.sender_nick,
                        text=rec.text,
                        timestamp_ms=rec.timestamp_ms,
                        is_outgoing=rec.is_outgoing,
                        status=status,
                        hop_count=rec.hop_count,
                    )
        lbl = self._status_labels.get(msg_id)
        if lbl is not None and lbl.winfo_exists():
            text, color = theme.format_dm_status(status, self._lang)
            lbl.configure(text=text, text_color=color)

    def _on_history_loaded(self, channel: str, messages: list[MessageRecord]) -> None:
        self._loaded_channels.add(channel)
        existing = self._messages.get(channel, [])
        by_id = {m.msg_id: m for m in messages}
        for m in existing:
            by_id.setdefault(m.msg_id, m)
        merged = sorted(by_id.values(), key=lambda m: m.timestamp_ms)
        self._messages[channel] = merged
        self._seen_msg_ids[channel] = {m.msg_id for m in merged}
        if self._active_channel == channel:
            self._render_active_chat()

    def _on_fingerprint_ready(self, peer: PeerInfo, fingerprint: Any) -> None:
        if self._verify_dialog is not None and self._verify_dialog.winfo_exists():
            self._verify_dialog.destroy()
        self._verify_dialog = VerifyDialog(
            self.root,
            peer=peer,
            fingerprint=fingerprint,
            on_verify=self.bridge.verify_peer,
            lang=self._lang,
        )

    def _on_node_reset(self, ev: Any) -> None:
        if self._verify_dialog is not None and self._verify_dialog.winfo_exists():
            self._verify_dialog.destroy()
        self._verify_dialog = None
        if self._reset_dialog is not None and self._reset_dialog.winfo_exists():
            self._reset_dialog.destroy()
        self._reset_dialog = None

        self._resetting = False
        self._reset_btn.configure(state="normal", text=tr(self._lang, "reset_identity"))
        self._own_node_id = ev.node_id_hex
        self._short_tag = ev.short_tag
        self._nickname = ev.nickname
        self._active_channel = "#public"
        self._peers.clear()
        self._messages = {"#public": []}
        self._seen_msg_ids = {"#public": set()}
        self._unread_counts.clear()
        self._loaded_channels = {"#public"}
        self._status_labels.clear()
        self._clear_inspector()

        self._id_label.configure(text=self._format_id_text())
        self._nick_entry.delete(0, "end")
        self._nick_entry.insert(0, ev.nickname)
        self._msg_entry.delete(0, "end")
        self._update_mode_badge(ev.central_only, ev.mode_label)
        self._refresh_peer_radar()
        self._update_channel_header()
        self._render_active_chat()

    # ------------------------------------------------------------------
    # Rendering helpers
    # ------------------------------------------------------------------

    def _refresh_peer_radar(self) -> None:
        lang = self._lang
        rtl = self._is_rtl

        for child in self._peer_list_frame.winfo_children():
            child.destroy()

        peers = sorted(
            self._peers.values(),
            key=lambda p: (
                not p.connected,
                not p.direct,
                p.hop_count,
                -p.last_seen,
            ),
        )
        online = sum(1 for p in peers if p.connected)
        radar_txt = (
            tr(lang, "peer_radar_header", online=online, total=len(peers))
            if self._own_node_id or peers
            else tr(lang, "peer_radar_zero")
        )
        self._radar_title.configure(text=bidi_text(radar_txt, rtl))
        if self._own_node_id and online == 0:
            self._connecting_badge.grid()
        else:
            self._connecting_badge.grid_remove()

        if self._active_channel == "#public":
            self._public_btn.configure(fg_color=theme.ACCENT_BLUE)
        else:
            self._public_btn.configure(fg_color=theme.BG_CARD)

        pub_unread = self._unread_counts.get("#public", 0)
        pub_suffix = f"  ({pub_unread})" if pub_unread else ""
        self._public_btn.configure(
            text=f"{tr(lang, 'public_channel_btn')}{pub_suffix}"
        )

        if not peers:
            ctk.CTkLabel(
                self._peer_list_frame,
                text=tr(lang, "scanning_peers"),
                font=theme.ui_font(lang, 12),
                text_color=theme.TEXT_DIM,
            ).grid(row=0, column=0, pady=18)
            return

        for idx, peer in enumerate(peers):
            self._render_peer_card(idx, peer)

    def _render_peer_card(self, row_idx: int, peer: PeerInfo) -> None:
        lang = self._lang
        rtl = self._is_rtl
        is_selected = self._active_channel == peer.node_id_hex
        card_bg = theme.BG_CARD_ACTIVE if is_selected else theme.BG_CARD
        card = ctk.CTkFrame(
            self._peer_list_frame,
            fg_color=card_bg,
            corner_radius=8,
            border_width=1,
            border_color=theme.ACCENT_BLUE if is_selected else theme.BORDER_SUBTLE,
        )
        card.grid(row=row_idx, column=0, sticky="ew", pady=(0, 6))
        card.grid_columnconfigure(0, weight=1)

        trust_icon, trust_color = self._trust_badge(peer)
        unread = self._unread_counts.get(peer.node_id_hex, 0)
        unread_text = f" [{unread}]" if unread else ""

        top = ctk.CTkFrame(card, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew", padx=10, pady=(8, 2))
        top.grid_columnconfigure(1 if rtl else 0, weight=1)

        name_text = f"{peer.nickname} ({peer.node_id_hex[:4]}){unread_text}"
        name_lbl = ctk.CTkLabel(
            top,
            text=bidi_text(name_text, rtl),
            font=theme.message_font(peer.nickname, lang, 12, "bold"),
            text_color=theme.TEXT_PRIMARY,
            anchor="e" if rtl else "w",
        )
        name_lbl.grid(
            row=0,
            column=1 if rtl else 0,
            sticky="e" if rtl else "w",
        )

        trust_lbl = ctk.CTkLabel(
            top,
            text=trust_icon,
            font=theme.ui_font(lang, 12, "bold"),
            text_color=trust_color,
        )
        trust_lbl.grid(
            row=0,
            column=0 if rtl else 1,
            sticky="w" if rtl else "e",
        )

        bottom = ctk.CTkFrame(card, fg_color="transparent")
        bottom.grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 8))
        bottom.grid_columnconfigure(0 if rtl else 1, weight=1)

        hop_text, hop_color = theme.format_hop_badge(peer, lang)
        hop_lbl = ctk.CTkLabel(
            bottom,
            text=hop_text,
            font=theme.ui_font(lang, 10, "bold"),
            text_color=hop_color,
        )
        hop_lbl.grid(
            row=0,
            column=1 if rtl else 0,
            sticky="e" if rtl else "w",
        )

        rssi_lbl = ctk.CTkLabel(
            bottom,
            text=theme.format_rssi(peer.rssi, peer.direct, peer.connected, lang),
            font=theme.ui_font(lang, 10),
            text_color=theme.TEXT_MUTED,
        )
        rssi_lbl.grid(
            row=0,
            column=0 if rtl else 1,
            sticky="w" if rtl else "e",
        )

        for widget in (card, top, bottom, name_lbl, trust_lbl, hop_lbl, rssi_lbl):
            widget.bind(
                "<Button-1>",
                lambda _e, pid=peer.node_id_hex: self._select_channel(pid),
            )

    @staticmethod
    def _trust_badge(peer: PeerInfo) -> tuple[str, str]:
        if peer.key_changed:
            return "!", theme.STATUS_RED
        if peer.verified:
            return "✓", theme.STATUS_GREEN
        return "○", theme.TEXT_DIM

    def _set_msg_placeholder(self, text: str) -> None:
        if self._msg_entry.cget("placeholder_text") == text:
            return
        try:
            focused = self.root.focus_get() is self._msg_entry._entry
        except KeyError:
            focused = False
        self._msg_entry.configure(placeholder_text=text)
        if focused:
            self._msg_entry._deactivate_placeholder()

    def _update_channel_header(self) -> None:
        lang = self._lang
        rtl = self._is_rtl

        if self._active_channel == "#public":
            self._channel_title.configure(
                text=tr(lang, "public_channel_title"),
                font=theme.ui_font("en", 14, "bold"),
            )
            self._set_msg_placeholder(tr(lang, "msg_placeholder_public"))
            self._verify_btn.grid_remove()
            self._key_warning_banner.grid_remove()
            return

        peer = self._peers.get(self._active_channel)
        if peer is None:
            self._channel_title.configure(
                text=bidi_text(
                    tr(lang, "dm_unknown_title", short_id=self._active_channel[:8]),
                    rtl,
                ),
                font=theme.ui_font(lang, 14, "bold"),
            )
            self._verify_btn.grid_remove()
            self._key_warning_banner.grid_remove()
            return

        status = tr(lang, "verified" if peer.verified else "unverified")
        self._channel_title.configure(
            text=bidi_text(
                tr(
                    lang,
                    "dm_header_title",
                    nick=peer.nickname,
                    tag=peer.node_id_hex[:4],
                    status=status,
                ),
                rtl,
            ),
            font=theme.ui_font(lang, 14, "bold"),
        )
        self._set_msg_placeholder(tr(lang, "msg_placeholder_dm", nick=peer.nickname))
        self._verify_btn.grid()
        if peer.key_changed:
            self._key_warning_banner.grid()
        else:
            self._key_warning_banner.grid_remove()

    def _render_active_chat(self) -> None:
        self._status_labels.clear()
        for child in self._chat_scroll.winfo_children():
            child.destroy()

        msgs = self._messages.get(self._active_channel, [])
        for idx, rec in enumerate(msgs):
            self._append_message_bubble(rec, idx)
        self._scroll_chat_to_bottom()

    def _append_message_bubble(self, rec: MessageRecord, row_idx: int) -> None:
        lang = self._lang
        rtl = self._is_rtl
        wrapper = ctk.CTkFrame(self._chat_scroll, fg_color="transparent", height=0)
        wrapper.grid(row=row_idx, column=0, sticky="ew", pady=2)
        wrapper.grid_columnconfigure(0, weight=1)

        bubble_bg = theme.BG_MSG_OUT if rec.is_outgoing else theme.BG_MSG_IN
        # Outgoing bubbles stay on the right ("e") in both LTR and RTL.
        bubble_anchor = "e" if rec.is_outgoing else "w"

        bubble = ctk.CTkFrame(
            wrapper,
            fg_color=bubble_bg,
            corner_radius=10,
            border_width=1,
            border_color=theme.BORDER_SUBTLE,
            height=0,
        )
        bubble.pack(anchor=bubble_anchor, padx=8, pady=1)

        hop_note = f" · {rec.hop_count}h" if rec.hop_count > 1 else ""
        meta = (
            f"{rec.sender_nick} ({rec.origin_id[:4]})  ·  "
            f"{theme.format_timestamp(rec.timestamp_ms)}{hop_note}"
        )
        meta_rtl = rtl or contains_persian(rec.sender_nick)
        ctk.CTkLabel(
            bubble,
            text=bidi_text(meta, meta_rtl),
            font=theme.message_font(rec.sender_nick, lang, 10, "bold"),
            text_color=theme.TEXT_MUTED,
            height=0,
        ).pack(anchor="e" if meta_rtl else "w", padx=10, pady=(6, 1))

        msg_rtl = detect_rtl(rec.text, default_rtl=rtl)
        ctk.CTkLabel(
            bubble,
            text=bidi_text(rec.text, msg_rtl),
            font=theme.message_font(rec.text, lang, 13),
            text_color=theme.TEXT_PRIMARY,
            wraplength=520,
            justify="right" if msg_rtl else "left",
            height=0,
        ).pack(
            anchor="e" if msg_rtl else "w",
            padx=10,
            pady=(0, 2 if rec.is_outgoing else 6),
        )

        if rec.is_outgoing:
            status_text, status_color = theme.format_dm_status(rec.status, lang)
            status_lbl = ctk.CTkLabel(
                bubble,
                text=status_text,
                font=theme.ui_font(lang, 10),
                text_color=status_color,
                height=0,
            )
            status_lbl.pack(anchor="e", padx=10, pady=(0, 5))
            self._status_labels[rec.msg_id] = status_lbl

    def _scroll_chat_to_bottom(self) -> None:
        def _apply() -> None:
            if not self._chat_scroll.winfo_exists():
                return
            self._chat_scroll.update_idletasks()
            canvas = self._chat_scroll._parent_canvas
            bbox = canvas.bbox("all")
            canvas.configure(scrollregion=bbox if bbox else (0, 0, 0, 0))
            if self._chat_scroll.winfo_reqheight() <= canvas.winfo_height():
                canvas.yview_moveto(0.0)
            else:
                canvas.yview_moveto(1.0)

        self.root.after_idle(_apply)

    def _append_inspector_log(self, entry: LogEntry) -> None:
        ts = theme.format_log_timestamp(entry.timestamp_ms)
        extras: list[str] = []
        if entry.pkt_type:
            extras.append(entry.pkt_type)
        if entry.hop or entry.ttl:
            extras.append(f"hop={entry.hop} ttl={entry.ttl}")
        suffix = f" ({', '.join(extras)})" if extras else ""
        self._append_raw_inspector(f"[{ts}] [{entry.event_type}] {entry.message}{suffix}")

    def _append_raw_inspector(self, line: str) -> None:
        self._inspector_lines_buf.append(line)
        self._inspector_text.configure(state="normal")
        if int(float(self._inspector_text.index("end-1c"))) > MAX_INSPECTOR_LINES:
            self._inspector_text.delete("1.0", "2.0")
        self._inspector_text.insert("end", line + "\n")
        self._inspector_text.see("end")
        self._inspector_text.configure(state="disabled")

    # ------------------------------------------------------------------
    # User actions
    # ------------------------------------------------------------------

    def _select_channel(self, channel: str) -> None:
        self._active_channel = channel
        self._unread_counts[channel] = 0
        self._refresh_peer_radar()
        self._update_channel_header()
        if channel not in self._loaded_channels:
            self.bridge.request_history(channel)
        self._render_active_chat()

    def _send_message(self) -> None:
        text = self._msg_entry.get().strip()
        if not text:
            return
        self._msg_entry.delete(0, "end")
        self._sync_entry_bidi()
        if self._active_channel == "#public":
            self.bridge.send_public(text)
        else:
            self.bridge.send_dm(self._active_channel, text)

    def _save_nickname(self) -> None:
        name = self._nick_entry.get().strip()
        if name:
            self._nickname = name
            self.bridge.set_nickname(name)

    def _open_verify_for_active(self) -> None:
        if self._active_channel != "#public":
            self.bridge.request_fingerprint(self._active_channel)

    def _toggle_inspector(self) -> None:
        self._inspector_visible = not self._inspector_visible
        if self._inspector_visible:
            self._inspector_frame.grid()
            self._inspector_btn.configure(fg_color=theme.ACCENT_BLUE)
        else:
            self._inspector_frame.grid_remove()
            self._inspector_btn.configure(fg_color=theme.BG_CARD)

    def _clear_inspector(self) -> None:
        self._inspector_lines_buf.clear()
        self._inspector_text.configure(state="normal")
        self._inspector_text.delete("1.0", "end")
        self._inspector_text.configure(state="disabled")

    def _open_reset_confirm(self) -> None:
        if self._reset_dialog is not None and self._reset_dialog.winfo_exists():
            self._reset_dialog.focus()
            return

        lang = self._lang
        rtl = self._is_rtl
        dlg = ctk.CTkToplevel(self.root)
        theme.apply_window_icon(dlg)
        self._reset_dialog = dlg
        dlg.title(tr(lang, "reset_dlg_title"))
        dlg.geometry("440x230")
        dlg.resizable(False, False)
        dlg.configure(fg_color=theme.BG_ROOT)
        dlg.transient(self.root)
        dlg.grab_set()

        box = ctk.CTkFrame(
            dlg,
            fg_color=theme.BG_PANEL,
            corner_radius=12,
            border_width=1,
            border_color=theme.BORDER_SUBTLE,
        )
        box.pack(fill="both", expand=True, padx=16, pady=16)

        ctk.CTkLabel(
            box,
            text=tr(lang, "reset_dlg_heading"),
            font=theme.ui_font(lang, 15, "bold"),
            text_color="#FCA5A5",
        ).pack(anchor="e" if rtl else "w", padx=16, pady=(14, 6))

        ctk.CTkLabel(
            box,
            text=bidi_text(tr(lang, "reset_dlg_body"), rtl),
            font=theme.ui_font(lang, 12),
            text_color=theme.TEXT_MUTED,
            wraplength=375,
            justify="right" if rtl else "left",
        ).pack(anchor="e" if rtl else "w", padx=16, pady=(0, 16))

        actions = ctk.CTkFrame(box, fg_color="transparent")
        actions.pack(fill="x", padx=16, pady=(0, 12))

        ctk.CTkButton(
            actions,
            text=tr(lang, "cancel"),
            width=100,
            fg_color=theme.BG_CARD,
            hover_color=theme.BG_CARD_ACTIVE,
            font=theme.ui_font(lang, 12),
            command=dlg.destroy,
        ).pack(side="right" if rtl else "left")

        ctk.CTkButton(
            actions,
            text=tr(lang, "wipe_reset"),
            width=140,
            fg_color="#DC2626",
            hover_color="#B91C1C",
            text_color="#FFFFFF",
            font=theme.ui_font(lang, 12, "bold"),
            command=self._confirm_reset,
        ).pack(side="left" if rtl else "right")

    def _confirm_reset(self) -> None:
        if self._reset_dialog is not None and self._reset_dialog.winfo_exists():
            self._reset_dialog.destroy()
        self._reset_dialog = None
        self._resetting = True
        self._reset_btn.configure(state="disabled", text=tr(self._lang, "resetting"))
        self.bridge.reset_all()

    def _on_close(self) -> None:
        if hasattr(self, "_poll_job"):
            self.root.after_cancel(self._poll_job)
        self.bridge.stop()
        self.root.destroy()
