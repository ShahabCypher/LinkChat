"""CustomTkinter main desktop window for LinkChat."""

from __future__ import annotations

import queue
from typing import TYPE_CHECKING, Any

import customtkinter as ctk

from linkchat_core import LogEntry, MessageRecord, PeerInfo

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

        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        self.root = ctk.CTk()
        theme.apply_window_icon(self.root)
        self.root.title("LinkChat — Offline BLE Mesh Messenger")
        self.root.geometry("1120x680")
        self.root.minsize(920, 560)
        self.root.configure(fg_color=theme.BG_ROOT)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        self._own_node_id = ""
        self._active_channel = "#public"
        self._inspector_visible = False
        self._peers: dict[str, PeerInfo] = {}
        self._messages: dict[str, list[MessageRecord]] = {"#public": []}
        self._seen_msg_ids: dict[str, set[str]] = {"#public": set()}
        self._unread_counts: dict[str, int] = {}
        self._loaded_channels: set[str] = set()
        self._status_labels: dict[str, ctk.CTkLabel] = {}
        self._inspector_lines = 0
        self._verify_dialog: VerifyDialog | None = None
        self._reset_dialog: ctk.CTkToplevel | None = None

        self._build_layout()
        self._poll_job = self.root.after(POLL_INTERVAL_MS, self._poll_events)

    def run(self) -> None:
        self.root.mainloop()

    # ------------------------------------------------------------------
    # Layout construction
    # ------------------------------------------------------------------

    def _build_layout(self) -> None:
        self.root.grid_rowconfigure(1, weight=1)
        self.root.grid_columnconfigure(1, weight=1)

        self._build_profile_bar()
        self._build_peer_sidebar()
        self._build_chat_workspace()
        self._build_inspector_drawer()

    def _build_profile_bar(self) -> None:
        bar = ctk.CTkFrame(
            self.root,
            fg_color=theme.BG_PANEL,
            corner_radius=0,
            border_width=1,
            border_color=theme.BORDER_SUBTLE,
            height=56,
        )
        bar.grid(row=0, column=0, columnspan=3, sticky="ew")
        bar.grid_columnconfigure(3, weight=1)

        ctk.CTkLabel(
            bar,
            text="LinkChat",
            font=(theme.FONT_FAMILY, 17, "bold"),
            text_color=theme.ACCENT_CYAN,
        ).grid(row=0, column=0, padx=(16, 12), pady=12)

        self._id_label = ctk.CTkLabel(
            bar,
            text="ID: ----",
            font=(theme.FONT_MONO, 12),
            text_color=theme.TEXT_MUTED,
        )
        self._id_label.grid(row=0, column=1, padx=(0, 12))

        self._mode_badge = ctk.CTkLabel(
            bar,
            text="Starting...",
            font=(theme.FONT_FAMILY, 11, "bold"),
            text_color="#0B1117",
            fg_color=theme.TEXT_MUTED,
            corner_radius=8,
            padx=10,
            pady=3,
        )
        self._mode_badge.grid(row=0, column=2, padx=(0, 8))

        self._connecting_badge = ctk.CTkLabel(
            bar,
            text="Connecting...",
            font=(theme.FONT_FAMILY, 11, "bold"),
            text_color=theme.ACCENT_CYAN,
            fg_color=theme.BG_CARD,
            corner_radius=8,
            padx=10,
            pady=3,
        )
        self._connecting_badge.grid(row=0, column=3, sticky="w", padx=(0, 12))
        self._connecting_badge.grid_remove()

        nick_wrap = ctk.CTkFrame(bar, fg_color="transparent")
        nick_wrap.grid(row=0, column=4, padx=(0, 12))

        ctk.CTkLabel(
            nick_wrap,
            text="Nickname:",
            font=(theme.FONT_FAMILY, 12),
            text_color=theme.TEXT_MUTED,
        ).pack(side="left", padx=(0, 6))

        self._nick_entry = ctk.CTkEntry(
            nick_wrap,
            width=160,
            fg_color=theme.BG_INPUT,
            border_color=theme.BORDER_SUBTLE,
        )
        self._nick_entry.pack(side="left", padx=(0, 6))
        self._nick_entry.bind("<Return>", lambda _e: self._save_nickname())

        ctk.CTkButton(
            nick_wrap,
            text="Save",
            width=64,
            fg_color=theme.BG_CARD,
            hover_color=theme.BG_CARD_ACTIVE,
            command=self._save_nickname,
        ).pack(side="left")

        self._inspector_btn = ctk.CTkButton(
            bar,
            text="Mesh Inspector",
            width=120,
            fg_color=theme.BG_CARD,
            hover_color=theme.BG_CARD_ACTIVE,
            command=self._toggle_inspector,
        )
        self._inspector_btn.grid(row=0, column=5, padx=(0, 8))

        self._reset_btn = ctk.CTkButton(
            bar,
            text="Reset Identity",
            width=116,
            fg_color="#7F1D1D",
            hover_color="#991B1B",
            text_color="#FEE2E2",
            command=self._open_reset_confirm,
        )
        self._reset_btn.grid(row=0, column=6, padx=(0, 16))

    def _build_peer_sidebar(self) -> None:
        sidebar = ctk.CTkFrame(
            self.root,
            fg_color=theme.BG_PANEL,
            corner_radius=0,
            border_width=1,
            border_color=theme.BORDER_SUBTLE,
            width=270,
        )
        sidebar.grid(row=1, column=0, sticky="nsew")
        sidebar.grid_propagate(False)
        sidebar.grid_rowconfigure(2, weight=1)
        sidebar.grid_columnconfigure(0, weight=1)

        self._public_btn = ctk.CTkButton(
            sidebar,
            text="#public  ·  Mesh Broadcast",
            anchor="w",
            height=40,
            fg_color=theme.ACCENT_BLUE,
            hover_color=theme.ACCENT_BLUE_HOVER,
            font=(theme.FONT_FAMILY, 13, "bold"),
            command=lambda: self._select_channel("#public"),
        )
        self._public_btn.grid(row=0, column=0, sticky="ew", padx=12, pady=(12, 8))

        header = ctk.CTkFrame(sidebar, fg_color="transparent")
        header.grid(row=1, column=0, sticky="ew", padx=14, pady=(4, 4))
        self._radar_title = ctk.CTkLabel(
            header,
            text="PEER RADAR (0)",
            font=(theme.FONT_FAMILY, 11, "bold"),
            text_color=theme.TEXT_MUTED,
        )
        self._radar_title.pack(side="left")

        self._peer_list_frame = ctk.CTkScrollableFrame(
            sidebar,
            fg_color="transparent",
        )
        self._peer_list_frame.grid(row=2, column=0, sticky="nsew", padx=8, pady=(0, 8))
        self._peer_list_frame.grid_columnconfigure(0, weight=1)

    def _build_chat_workspace(self) -> None:
        workspace = ctk.CTkFrame(self.root, fg_color=theme.BG_ROOT, corner_radius=0)
        workspace.grid(row=1, column=1, sticky="nsew")
        workspace.grid_rowconfigure(2, weight=1)
        workspace.grid_columnconfigure(0, weight=1)

        # Channel header
        header = ctk.CTkFrame(
            workspace,
            fg_color=theme.BG_PANEL,
            corner_radius=0,
            border_width=1,
            border_color=theme.BORDER_SUBTLE,
            height=48,
        )
        header.grid(row=0, column=0, sticky="ew")
        header.grid_columnconfigure(0, weight=1)

        self._channel_title = ctk.CTkLabel(
            header,
            text="#public — Mesh Broadcast",
            font=(theme.FONT_FAMILY, 14, "bold"),
            text_color=theme.TEXT_PRIMARY,
        )
        self._channel_title.grid(row=0, column=0, sticky="w", padx=16, pady=10)

        self._verify_btn = ctk.CTkButton(
            header,
            text="Verify Safety",
            width=110,
            height=28,
            fg_color=theme.BG_CARD,
            hover_color=theme.BG_CARD_ACTIVE,
            command=self._open_verify_for_active,
        )
        self._verify_btn.grid(row=0, column=1, padx=14, pady=8)
        self._verify_btn.grid_remove()

        # Key-changed warning banner (hidden unless active peer has key_changed)
        self._key_warning_banner = ctk.CTkFrame(
            workspace, fg_color="#451A1A", corner_radius=0
        )
        self._key_warning_banner.grid(row=1, column=0, sticky="ew")
        ctk.CTkLabel(
            self._key_warning_banner,
            text="⚠ Peer identity key changed since first contact. Verify fingerprint before sending sensitive DMs.",
            font=(theme.FONT_FAMILY, 12, "bold"),
            text_color="#FCA5A5",
        ).pack(side="left", padx=14, pady=6)
        self._key_warning_banner.grid_remove()

        # Message scroll feed
        self._chat_scroll = ctk.CTkScrollableFrame(
            workspace, fg_color=theme.BG_ROOT
        )
        self._chat_scroll.grid(row=2, column=0, sticky="nsew", padx=10, pady=8)
        self._chat_scroll.grid_columnconfigure(0, weight=1)

        # Composer bar
        composer = ctk.CTkFrame(
            workspace,
            fg_color=theme.BG_PANEL,
            corner_radius=0,
            border_width=1,
            border_color=theme.BORDER_SUBTLE,
        )
        composer.grid(row=3, column=0, sticky="ew")
        composer.grid_columnconfigure(0, weight=1)

        self._msg_entry = ctk.CTkEntry(
            composer,
            placeholder_text="Message #public...",
            height=38,
            fg_color=theme.BG_INPUT,
            border_color=theme.BORDER_SUBTLE,
            font=(theme.FONT_FAMILY, 13),
        )
        self._msg_entry.grid(row=0, column=0, sticky="ew", padx=(12, 8), pady=10)
        self._msg_entry.bind("<Return>", lambda _e: self._send_message())

        ctk.CTkButton(
            composer,
            text="Send",
            width=88,
            height=38,
            fg_color=theme.ACCENT_BLUE,
            hover_color=theme.ACCENT_BLUE_HOVER,
            font=(theme.FONT_FAMILY, 13, "bold"),
            command=self._send_message,
        ).grid(row=0, column=1, padx=(0, 12), pady=10)

    def _build_inspector_drawer(self) -> None:
        self._inspector_frame = ctk.CTkFrame(
            self.root,
            fg_color=theme.BG_PANEL,
            corner_radius=0,
            border_width=1,
            border_color=theme.BORDER_SUBTLE,
            width=330,
        )
        self._inspector_frame.grid(row=1, column=2, sticky="nsew")
        self._inspector_frame.grid_propagate(False)
        self._inspector_frame.grid_rowconfigure(1, weight=1)
        self._inspector_frame.grid_columnconfigure(0, weight=1)

        hdr = ctk.CTkFrame(self._inspector_frame, fg_color="transparent")
        hdr.grid(row=0, column=0, sticky="ew", padx=12, pady=(10, 4))
        ctk.CTkLabel(
            hdr,
            text="MESH INSPECTOR",
            font=(theme.FONT_FAMILY, 11, "bold"),
            text_color=theme.TEXT_MUTED,
        ).pack(side="left")
        ctk.CTkButton(
            hdr,
            text="Clear",
            width=56,
            height=24,
            fg_color=theme.BG_CARD,
            hover_color=theme.BG_CARD_ACTIVE,
            command=self._clear_inspector,
        ).pack(side="right")

        self._inspector_text = ctk.CTkTextbox(
            self._inspector_frame,
            fg_color=theme.BG_INPUT,
            text_color=theme.TEXT_PRIMARY,
            font=(theme.FONT_MONO, 11),
            wrap="word",
            state="disabled",
        )
        self._inspector_text.grid(row=1, column=0, sticky="nsew", padx=10, pady=(4, 10))
        self._inspector_frame.grid_remove()

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
                    self._reset_btn.configure(state="normal", text="Reset Identity")
                    self._append_raw_inspector(f"[ERROR] {ev.message}")
        except queue.Empty:
            pass
        finally:
            self._poll_job = self.root.after(POLL_INTERVAL_MS, self._poll_events)

    def _on_node_ready(self, ev: Any) -> None:
        self._own_node_id = ev.node_id_hex
        self._id_label.configure(text=f"ID: {ev.short_tag} ({ev.node_id_hex[:8]}…)")
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
        color = theme.STATUS_AMBER if central_only else theme.STATUS_GREEN
        self._mode_badge.configure(text=label, fg_color=color)

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
            text, color = theme.format_dm_status(status)
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
        )

    def _on_node_reset(self, ev: Any) -> None:
        if self._verify_dialog is not None and self._verify_dialog.winfo_exists():
            self._verify_dialog.destroy()
        self._verify_dialog = None
        if self._reset_dialog is not None and self._reset_dialog.winfo_exists():
            self._reset_dialog.destroy()
        self._reset_dialog = None

        self._reset_btn.configure(state="normal", text="Reset Identity")
        self._own_node_id = ev.node_id_hex
        self._active_channel = "#public"
        self._peers.clear()
        self._messages = {"#public": []}
        self._seen_msg_ids = {"#public": set()}
        self._unread_counts.clear()
        self._loaded_channels = {"#public"}
        self._status_labels.clear()
        self._clear_inspector()

        self._id_label.configure(text=f"ID: {ev.short_tag} ({ev.node_id_hex[:8]}…)")
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
        self._radar_title.configure(text=f"PEER RADAR ({online}/{len(peers)})")
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
        self._public_btn.configure(text=f"#public  ·  Mesh Broadcast{pub_suffix}")

        if not peers:
            ctk.CTkLabel(
                self._peer_list_frame,
                text="Scanning for LinkChat peers...",
                font=(theme.FONT_FAMILY, 12),
                text_color=theme.TEXT_DIM,
            ).grid(row=0, column=0, pady=18)
            return

        for idx, peer in enumerate(peers):
            self._render_peer_card(idx, peer)

    def _render_peer_card(self, row_idx: int, peer: PeerInfo) -> None:
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
        top.grid_columnconfigure(0, weight=1)

        name_lbl = ctk.CTkLabel(
            top,
            text=f"{peer.nickname} ({peer.node_id_hex[:4]}){unread_text}",
            font=(theme.FONT_FAMILY, 12, "bold"),
            text_color=theme.TEXT_PRIMARY,
            anchor="w",
        )
        name_lbl.grid(row=0, column=0, sticky="w")

        trust_lbl = ctk.CTkLabel(
            top,
            text=trust_icon,
            font=(theme.FONT_FAMILY, 12, "bold"),
            text_color=trust_color,
        )
        trust_lbl.grid(row=0, column=1, sticky="e")

        bottom = ctk.CTkFrame(card, fg_color="transparent")
        bottom.grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 8))
        bottom.grid_columnconfigure(1, weight=1)

        hop_text, hop_color = theme.format_hop_badge(peer)
        hop_lbl = ctk.CTkLabel(
            bottom,
            text=hop_text,
            font=(theme.FONT_FAMILY, 10, "bold"),
            text_color=hop_color,
        )
        hop_lbl.grid(row=0, column=0, sticky="w")

        rssi_lbl = ctk.CTkLabel(
            bottom,
            text=theme.format_rssi(peer.rssi, peer.direct, peer.connected),
            font=(theme.FONT_FAMILY, 10),
            text_color=theme.TEXT_MUTED,
        )
        rssi_lbl.grid(row=0, column=1, sticky="e")

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
            # CTkEntry.configure(placeholder_text=...) activates placeholder even
            # when focused if empty, leaving _placeholder_text_active=True so get() returns "".
            self._msg_entry._deactivate_placeholder()

    def _update_channel_header(self) -> None:
        if self._active_channel == "#public":
            self._channel_title.configure(text="#public — Mesh Broadcast")
            self._set_msg_placeholder("Message #public...")
            self._verify_btn.grid_remove()
            self._key_warning_banner.grid_remove()
            return

        peer = self._peers.get(self._active_channel)
        if peer is None:
            self._channel_title.configure(text=f"DM · {self._active_channel[:8]}")
            self._verify_btn.grid_remove()
            self._key_warning_banner.grid_remove()
            return

        status = "Verified ✓" if peer.verified else "Unverified"
        self._channel_title.configure(
            text=f"E2EE DM · {peer.nickname} ({peer.node_id_hex[:4]}) · {status}"
        )
        self._set_msg_placeholder(f"Encrypted DM to {peer.nickname}...")
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
        wrapper = ctk.CTkFrame(self._chat_scroll, fg_color="transparent", height=0)
        wrapper.grid(row=row_idx, column=0, sticky="ew", pady=2)
        wrapper.grid_columnconfigure(0, weight=1)

        bubble_bg = theme.BG_MSG_OUT if rec.is_outgoing else theme.BG_MSG_IN
        anchor = "e" if rec.is_outgoing else "w"

        bubble = ctk.CTkFrame(
            wrapper,
            fg_color=bubble_bg,
            corner_radius=10,
            border_width=1,
            border_color=theme.BORDER_SUBTLE,
            height=0,
        )
        bubble.pack(anchor=anchor, padx=8, pady=1)

        hop_note = f" · {rec.hop_count}h" if rec.hop_count > 1 else ""
        meta = (
            f"{rec.sender_nick} ({rec.origin_id[:4]})  ·  "
            f"{theme.format_timestamp(rec.timestamp_ms)}{hop_note}"
        )
        ctk.CTkLabel(
            bubble,
            text=meta,
            font=(theme.FONT_FAMILY, 10, "bold"),
            text_color=theme.TEXT_MUTED,
            height=0,
        ).pack(anchor="w", padx=10, pady=(6, 1))

        ctk.CTkLabel(
            bubble,
            text=rec.text,
            font=(theme.FONT_FAMILY, 13),
            text_color=theme.TEXT_PRIMARY,
            wraplength=520,
            justify="left",
            height=0,
        ).pack(anchor="w", padx=10, pady=(0, 2 if rec.is_outgoing else 6))

        if rec.is_outgoing:
            status_text, status_color = theme.format_dm_status(rec.status)
            status_lbl = ctk.CTkLabel(
                bubble,
                text=status_text,
                font=(theme.FONT_FAMILY, 10),
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
        self._inspector_text.configure(state="normal")
        if self._inspector_lines >= MAX_INSPECTOR_LINES:
            self._inspector_text.delete("1.0", "2.0")
        else:
            self._inspector_lines += 1
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
        if self._active_channel == "#public":
            self.bridge.send_public(text)
        else:
            self.bridge.send_dm(self._active_channel, text)

    def _save_nickname(self) -> None:
        name = self._nick_entry.get().strip()
        if name:
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
        self._inspector_text.configure(state="normal")
        self._inspector_text.delete("1.0", "end")
        self._inspector_lines = 0
        self._inspector_text.configure(state="disabled")

    def _open_reset_confirm(self) -> None:
        if self._reset_dialog is not None and self._reset_dialog.winfo_exists():
            self._reset_dialog.focus()
            return

        dlg = ctk.CTkToplevel(self.root)
        theme.apply_window_icon(dlg)
        self._reset_dialog = dlg
        dlg.title("Reset Identity & Wipe Data")
        dlg.geometry("430x220")
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
            text="Erase All Data & Reset Identity?",
            font=(theme.FONT_FAMILY, 15, "bold"),
            text_color="#FCA5A5",
        ).pack(anchor="w", padx=16, pady=(14, 6))

        ctk.CTkLabel(
            box,
            text=(
                "This permanently wipes your cryptographic keys, nickname, "
                "peers, trust records, and all chat history. You will rejoin "
                "the mesh as a brand-new user."
            ),
            font=(theme.FONT_FAMILY, 12),
            text_color=theme.TEXT_MUTED,
            wraplength=365,
            justify="left",
        ).pack(anchor="w", padx=16, pady=(0, 16))

        actions = ctk.CTkFrame(box, fg_color="transparent")
        actions.pack(fill="x", padx=16, pady=(0, 12))

        ctk.CTkButton(
            actions,
            text="Cancel",
            width=100,
            fg_color=theme.BG_CARD,
            hover_color=theme.BG_CARD_ACTIVE,
            command=dlg.destroy,
        ).pack(side="left")

        ctk.CTkButton(
            actions,
            text="Wipe & Reset",
            width=130,
            fg_color="#DC2626",
            hover_color="#B91C1C",
            text_color="#FFFFFF",
            command=self._confirm_reset,
        ).pack(side="right")

    def _confirm_reset(self) -> None:
        if self._reset_dialog is not None and self._reset_dialog.winfo_exists():
            self._reset_dialog.destroy()
        self._reset_dialog = None
        self._reset_btn.configure(state="disabled", text="Resetting...")
        self.bridge.reset_all()

    def _on_close(self) -> None:
        if hasattr(self, "_poll_job"):
            self.root.after_cancel(self._poll_job)
        self.bridge.stop()
        self.root.destroy()
