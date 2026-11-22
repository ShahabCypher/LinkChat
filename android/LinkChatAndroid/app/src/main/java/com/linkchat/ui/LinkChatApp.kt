package com.linkchat.ui

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.consumeWindowInsets
import androidx.compose.foundation.layout.exclude
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.ime
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawing
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Bluetooth
import androidx.compose.material.icons.filled.BugReport
import androidx.compose.material.icons.filled.DeleteForever
import androidx.compose.material.icons.filled.Edit
import androidx.compose.material.icons.filled.Forum
import androidx.compose.material.icons.filled.People
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Badge
import androidx.compose.material3.BadgedBox
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalLayoutDirection
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextDirection
import androidx.compose.ui.unit.LayoutDirection
import androidx.compose.ui.unit.dp
import com.linkchat.model.MainTab

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun LinkChatApp(
    viewModel: LinkChatViewModel,
    hasBlePermissions: Boolean,
    onRequestPermissions: () -> Unit,
    onStartMeshService: () -> Unit,
) {
    val state by viewModel.uiState.collectAsState()
    val strings = LocalStrings.current
    val snackbarHostState = remember { SnackbarHostState() }
    var showNickDialog by remember { mutableStateOf(false) }
    var showResetDialog by remember { mutableStateOf(false) }

    LaunchedEffect(state.lastError) {
        val err = state.lastError
        if (err != null) {
            snackbarHostState.showSnackbar(err)
            viewModel.dismissError()
        }
    }

    Scaffold(
        containerColor = LinkChatColors.BgRoot,
        contentWindowInsets = WindowInsets.safeDrawing.exclude(WindowInsets.ime),
        snackbarHost = { SnackbarHost(snackbarHostState) },
        topBar = {
            TopAppBar(
                colors = TopAppBarDefaults.topAppBarColors(
                    containerColor = LinkChatColors.BgPanel,
                    titleContentColor = LinkChatColors.TextPrimary,
                ),
                navigationIcon = {
                    if (state.activeDmPeerId != null) {
                        IconButton(onClick = viewModel::closeDm) {
                            Icon(
                                Icons.AutoMirrored.Filled.ArrowBack,
                                contentDescription = strings.back,
                            )
                        }
                    }
                },
                title = {
                    val dmPeer = state.activeDmPeer
                    if (dmPeer != null) {
                        Column {
                            Text(
                                text = styledBidiText(dmPeer.nickname),
                                style = MaterialTheme.typography.titleMedium,
                                fontWeight = FontWeight.Bold,
                            )
                            Row(verticalAlignment = Alignment.CenterVertically) {
                                CompositionLocalProvider(LocalLayoutDirection provides LayoutDirection.Ltr) {
                                    Text(
                                        text = "LC-${dmPeer.shortTag}",
                                        style = MaterialTheme.typography.labelSmall,
                                        color = LinkChatColors.TextMuted,
                                    )
                                }
                                Text(
                                    text = " • ${if (dmPeer.direct) strings.directLabel else strings.hopsLabel(dmPeer.hopCount)}",
                                    style = MaterialTheme.typography.labelSmall,
                                    color = LinkChatColors.TextMuted,
                                )
                            }
                        }
                    } else {
                        Column(
                            modifier = Modifier.clickable { showNickDialog = true }
                        ) {
                            Row(verticalAlignment = Alignment.CenterVertically) {
                                Text(
                                    text = strings.appName,
                                    style = MaterialTheme.typography.titleMedium,
                                    fontWeight = FontWeight.Bold,
                                    color = LinkChatColors.AccentCyan,
                                )
                                Spacer(modifier = Modifier.width(8.dp))
                                CompositionLocalProvider(LocalLayoutDirection provides LayoutDirection.Ltr) {
                                    Text(
                                        text = "LC-${state.shortTag}",
                                        style = MaterialTheme.typography.labelSmall,
                                        fontFamily = FontFamily.Monospace,
                                        color = LinkChatColors.TextMuted,
                                    )
                                }
                            }
                            Row(verticalAlignment = Alignment.CenterVertically) {
                                Text(
                                    text = styledBidiText(state.nickname),
                                    style = MaterialTheme.typography.labelMedium,
                                    color = LinkChatColors.TextPrimary,
                                )
                                Spacer(modifier = Modifier.width(4.dp))
                                Icon(
                                    imageVector = Icons.Default.Edit,
                                    contentDescription = strings.editNickname,
                                    tint = LinkChatColors.TextMuted,
                                    modifier = Modifier.size(12.dp),
                                )
                            }
                        }
                    }
                },
                actions = {
                    Surface(
                        color = LinkChatColors.BgCard,
                        shape = RoundedCornerShape(10.dp),
                        modifier = Modifier
                            .padding(end = 6.dp)
                            .clickable(onClick = viewModel::toggleLanguage),
                    ) {
                        Text(
                            text = strings.langToggleLabel,
                            style = MaterialTheme.typography.labelSmall,
                            fontFamily = if (state.language == AppLanguage.EN) VazirmatnFontFamily else null,
                            fontWeight = FontWeight.Bold,
                            color = LinkChatColors.TextPrimary,
                            modifier = Modifier.padding(horizontal = 8.dp, vertical = 4.dp),
                        )
                    }

                    val pillColor = when {
                        !hasBlePermissions -> LinkChatColors.WarningAmber
                        !state.bleStatus.bluetoothEnabled -> LinkChatColors.DangerRed
                        state.bleStatus.advertising && state.bleStatus.scanning -> LinkChatColors.VerifiedGreen
                        state.bleStatus.serviceRunning -> LinkChatColors.AccentCyan
                        else -> LinkChatColors.TextMuted
                    }
                    val pillLabel = when {
                        !hasBlePermissions -> strings.blePermissions
                        !state.bleStatus.bluetoothEnabled -> strings.bleBtOff
                        state.bleStatus.advertising -> strings.bleDualRole
                        state.bleStatus.scanning -> strings.bleCentral
                        else -> strings.bleIdle
                    }
                    Surface(
                        color = pillColor.copy(alpha = 0.16f),
                        shape = RoundedCornerShape(10.dp),
                        modifier = Modifier
                            .padding(end = 4.dp)
                            .clickable {
                                if (!hasBlePermissions) {
                                    onRequestPermissions()
                                } else if (!state.bleStatus.serviceRunning) {
                                    onStartMeshService()
                                }
                            },
                    ) {
                        Row(
                            modifier = Modifier.padding(horizontal = 8.dp, vertical = 4.dp),
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            Icon(
                                imageVector = Icons.Default.Bluetooth,
                                contentDescription = null,
                                tint = pillColor,
                                modifier = Modifier.size(14.dp),
                            )
                            Spacer(modifier = Modifier.width(4.dp))
                            Text(
                                text = pillLabel,
                                style = MaterialTheme.typography.labelSmall,
                                fontWeight = FontWeight.SemiBold,
                                color = pillColor,
                            )
                        }
                    }
                    IconButton(onClick = { showResetDialog = true }) {
                        Icon(
                            imageVector = Icons.Default.DeleteForever,
                            contentDescription = strings.resetIdentity,
                            tint = LinkChatColors.DangerRed,
                        )
                    }
                },
            )
        },
        bottomBar = {
            if (state.activeDmPeerId == null) {
                NavigationBar(containerColor = LinkChatColors.BgPanel) {
                    val publicUnread = state.unreadCounts["#public"] ?: 0
                    val connectedCount = state.peers.count { it.connected }
                    NavigationBarItem(
                        selected = state.activeTab == MainTab.PUBLIC,
                        onClick = { viewModel.selectTab(MainTab.PUBLIC) },
                        icon = {
                            BadgedBox(
                                badge = {
                                    if (publicUnread > 0) {
                                        Badge { Text("$publicUnread") }
                                    }
                                }
                            ) {
                                Icon(Icons.Default.Forum, contentDescription = strings.tabPublic)
                            }
                        },
                        label = { Text(strings.tabPublic) },
                    )
                    NavigationBarItem(
                        selected = state.activeTab == MainTab.PEERS,
                        onClick = { viewModel.selectTab(MainTab.PEERS) },
                        icon = {
                            BadgedBox(
                                badge = {
                                    if (state.totalUnreadDm > 0) {
                                        Badge { Text("${state.totalUnreadDm}") }
                                    } else if (connectedCount > 0) {
                                        Badge(containerColor = LinkChatColors.VerifiedGreen) {
                                            Text("$connectedCount", color = LinkChatColors.BgRoot)
                                        }
                                    }
                                }
                            ) {
                                Icon(Icons.Default.People, contentDescription = strings.tabPeers)
                            }
                        },
                        label = { Text(strings.tabPeers) },
                    )
                    NavigationBarItem(
                        selected = state.activeTab == MainTab.INSPECTOR,
                        onClick = { viewModel.selectTab(MainTab.INSPECTOR) },
                        icon = { Icon(Icons.Default.BugReport, contentDescription = strings.tabInspector) },
                        label = { Text(strings.tabInspector) },
                    )
                }
            }
        },
    ) { innerPadding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(innerPadding)
                .consumeWindowInsets(innerPadding)
                .imePadding(),
        ) {
            if (!hasBlePermissions) {
                Surface(
                    color = LinkChatColors.WarningAmber.copy(alpha = 0.14f),
                    modifier = Modifier.fillMaxWidth(),
                ) {
                    Row(
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(horizontal = 12.dp, vertical = 8.dp),
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.SpaceBetween,
                    ) {
                        Text(
                            text = strings.blePermissionsBanner,
                            style = MaterialTheme.typography.bodySmall,
                            color = LinkChatColors.TextPrimary,
                            modifier = Modifier.weight(1f),
                        )
                        Spacer(modifier = Modifier.width(8.dp))
                        Button(onClick = onRequestPermissions) {
                            Text(strings.grant)
                        }
                    }
                }
            }

            val isConnecting = state.isReady &&
                hasBlePermissions &&
                state.bleStatus.bluetoothEnabled &&
                (state.bleStatus.serviceRunning || state.bleStatus.scanning || state.bleStatus.advertising) &&
                state.peers.none { it.connected }
            if (isConnecting) {
                Surface(
                    color = LinkChatColors.AccentCyan.copy(alpha = 0.12f),
                    modifier = Modifier.fillMaxWidth(),
                ) {
                    Row(
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(horizontal = 14.dp, vertical = 6.dp),
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.Center,
                    ) {
                        CircularProgressIndicator(
                            modifier = Modifier.size(13.dp),
                            strokeWidth = 2.dp,
                            color = LinkChatColors.AccentCyan,
                        )
                        Spacer(modifier = Modifier.width(8.dp))
                        Text(
                            text = strings.connectingPeers,
                            style = MaterialTheme.typography.labelMedium,
                            color = LinkChatColors.AccentCyan,
                        )
                    }
                }
            }

            if (state.activeDmPeerId != null) {
                ChatScreen(
                    messages = state.activeMessages,
                    dmPeer = state.activeDmPeer,
                    onSendMessage = viewModel::sendMessage,
                    onOpenVerify = viewModel::openVerifySheet,
                    modifier = Modifier.weight(1f),
                )
            } else {
                when (state.activeTab) {
                    MainTab.PUBLIC -> ChatScreen(
                        messages = state.activeMessages,
                        dmPeer = null,
                        onSendMessage = viewModel::sendMessage,
                        onOpenVerify = viewModel::openVerifySheet,
                        modifier = Modifier.weight(1f),
                    )

                    MainTab.PEERS -> PeerRadarScreen(
                        peers = state.peers,
                        unreadCounts = state.unreadCounts,
                        blockedTags = state.blockedTags,
                        onOpenDm = { peer -> viewModel.openDm(peer.nodeIdHex) },
                        onOpenVerify = viewModel::openVerifySheet,
                        onToggleBlockTag = viewModel::toggleBlockedTag,
                        modifier = Modifier.weight(1f),
                    )

                    MainTab.INSPECTOR -> InspectorScreen(
                        logs = state.meshLogs,
                        blockedTags = state.blockedTags,
                        onToggleBlockedTag = viewModel::toggleBlockedTag,
                        onClearLogs = viewModel::clearLogs,
                        modifier = Modifier.weight(1f),
                    )
                }
            }
        }
    }

    val verifyState = state.verifyState
    if (verifyState != null) {
        VerifySheet(
            state = verifyState,
            onDismiss = viewModel::closeVerifySheet,
            onSetVerified = viewModel::verifyPeer,
        )
    }

    if (showNickDialog) {
        NicknameDialog(
            currentNickname = state.nickname,
            onDismiss = { showNickDialog = false },
            onSave = { newNick ->
                viewModel.setNickname(newNick)
                showNickDialog = false
            },
        )
    }

    if (showResetDialog) {
        ResetConfirmDialog(
            onDismiss = { showResetDialog = false },
            onConfirm = {
                showResetDialog = false
                viewModel.resetAllData()
            },
        )
    }
}

@Composable
private fun ResetConfirmDialog(
    onDismiss: () -> Unit,
    onConfirm: () -> Unit,
) {
    val strings = LocalStrings.current
    val layoutDirection = LocalLayoutDirection.current
    AlertDialog(
        onDismissRequest = onDismiss,
        containerColor = LinkChatColors.BgPanel,
        title = {
            CompositionLocalProvider(LocalLayoutDirection provides layoutDirection) {
                Text(
                    text = strings.resetDialogTitle,
                    color = LinkChatColors.DangerRed,
                    fontWeight = FontWeight.Bold,
                )
            }
        },
        text = {
            CompositionLocalProvider(LocalLayoutDirection provides layoutDirection) {
                Text(
                    text = strings.resetDialogBody,
                    color = LinkChatColors.TextMuted,
                )
            }
        },
        confirmButton = {
            Button(
                onClick = onConfirm,
                colors = ButtonDefaults.buttonColors(
                    containerColor = LinkChatColors.DangerRed,
                    contentColor = LinkChatColors.TextPrimary,
                ),
            ) {
                Text(strings.wipeAndReset)
            }
        },
        dismissButton = {
            TextButton(onClick = onDismiss) {
                Text(strings.cancel)
            }
        },
    )
}

@Composable
private fun NicknameDialog(
    currentNickname: String,
    onDismiss: () -> Unit,
    onSave: (String) -> Unit,
) {
    val strings = LocalStrings.current
    val layoutDirection = LocalLayoutDirection.current
    var draft by remember(currentNickname) { mutableStateOf(currentNickname) }
    AlertDialog(
        onDismissRequest = onDismiss,
        containerColor = LinkChatColors.BgPanel,
        title = {
            CompositionLocalProvider(LocalLayoutDirection provides layoutDirection) {
                Text(strings.changeNicknameTitle)
            }
        },
        text = {
            CompositionLocalProvider(LocalLayoutDirection provides layoutDirection) {
                OutlinedTextField(
                    value = draft,
                    onValueChange = { draft = it },
                    singleLine = true,
                    label = { Text(strings.nicknameLabel) },
                    textStyle = MaterialTheme.typography.bodyLarge.copy(
                        textDirection = TextDirection.Content,
                        fontFamily = if (draft.any { isPersianChar(it) } || layoutDirection == LayoutDirection.Rtl) {
                            VazirmatnFontFamily
                        } else {
                            null
                        },
                    ),
                )
            }
        },
        confirmButton = {
            Button(
                onClick = { onSave(draft) },
                enabled = draft.isNotBlank(),
            ) {
                Text(strings.save)
            }
        },
        dismissButton = {
            TextButton(onClick = onDismiss) {
                Text(strings.cancel)
            }
        },
    )
}
