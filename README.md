# LinkChat

Offline, decentralized Bluetooth Low Energy (BLE) mesh messenger for **Windows** and **Android**, inspired by BitChat.

## Key Features
- **Public Group Chat**: Multi-hop BLE broadcast messaging across connected peers (`Ed25519`-signed).
- **Encrypted Direct Messages**: End-to-end encrypted 1-to-1 messaging (`X25519` + `HKDF-SHA256` + `ChaCha20-Poly1305`) with `DM_ACK` delivery receipts.
- **Multi-Hop Mesh Relay**: TTL-bounded flooding with `(origin_id, msg_id)` deduplication (`Phone A <-> Laptop B <-> Phone C`).
- **Live Peer Radar**: Discovered peers with `Direct` / `N hops` badges, RSSI signal strength, and verification status.
- **Identity & Safety Fingerprints**: Zero-account `Ed25519` identity with TOFU key-change detection and symmetric 6-emoji / 30-digit safety verification.
- **Store-and-Forward Sync**: Local SQLite history plus `SYNC_DIGEST` / `SYNC_REQ` catch-up sync for reconnecting peers and queued offline DMs.
- **Local Mesh Simulator**: Virtual Python radio simulator (`linkchat_sim`) for testing 5+ node topologies without physical Bluetooth hardware.

## Tech Stack
- **Shared Core (`core/linkchat_core`)**: Pure Python 3.12/3.13 (`cryptography`, `sqlite3`, `asyncio`)
- **Windows App (`windows/linkchat_win`)**: Python (`CustomTkinter` UI + `bleak` Central / `bless` or WinRT Peripheral with automatic Central-Only fallback)
- **Android App (`android/LinkChatAndroid`)**: Kotlin (`Jetpack Compose` + native Android BLE GATT Foreground Service) + `Chaquopy` embedding `core/linkchat_core`

## Setup & Installation

### 1. Python Environment (Core, Simulator, & Windows App)
Requires **Python 3.12 or 3.13** on Windows 10/11 (with a BLE-capable Bluetooth adapter for hardware demos).

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev,windows]"
```

If you only want the pure-Python core, simulator, and tests (without Windows GUI/BLE dependencies):

```powershell
pip install -e ".[dev]"
```

### 2. Android App (`android/LinkChatAndroid`)
Requires **Android Studio** (or Android SDK Platform 35 + JDK 17+) and a physical Android 10+ device with BLE enabled (emulators do not expose real BLE advertising/scanning).

- **Android Studio**: Open `android/LinkChatAndroid`, let Gradle sync Chaquopy + Python `cryptography`, and click **Run** to deploy to connected Android phones.
- **Command Line** (from `android/LinkChatAndroid`, using Android Studio's JBR if system `JAVA_HOME` is older than JDK 17):

```powershell
$env:JAVA_HOME = "D:\Program Files\Android\Android Studio\jbr"
.\gradlew.bat assembleDebug
```

Install the generated APK (`app\build\outputs\apk\debug\app-debug.apk`) onto two Android phones via `adb install -r ...` or Android Studio.

## Running & Verification

### Automated Tests
Run the full Python core, simulator, Windows transport/bridge, and cross-platform 3-node multi-hop test suite:

```powershell
pytest
```

Run the Android Kotlin unit tests:

```powershell
cd android\LinkChatAndroid
.\gradlew.bat testDebugUnitTest
```

### 5-Node Local Simulator Demo (No Hardware Needed)
Runs both the 5-node linear chain (`Alice - Bob - Carol - Dave - Eve`, showing 4-hop public chat and encrypted DMs unread by intermediate nodes) and the partition/reconnect `SYNC_DIGEST` catch-up scenario:

```powershell
python -m linkchat_sim.cli_demo
```

Run a single scenario with `--scenario chain` or `--scenario partition`.

### Windows Desktop App
Launch the Windows GUI:

```powershell
python -m linkchat_win --nickname WinLaptop
```

Useful CLI flags:
- `--nickname <name>`: Set/update local display nickname.
- `--data-dir <path>`: Use an isolated SQLite directory (defaults to `%LOCALAPPDATA%\LinkChat`).
- `--central-only`: Force Central-Only mode (disables BLE Peripheral GATT Server).

> [!NOTE]
> If the Windows Bluetooth adapter rejects BLE Peripheral advertising, `WindowsBleTransport` automatically switches to **Central-Only** mode (amber badge in the top bar) and connects to nearby Android Peripherals as Central.

## Cross-Platform Hardware Demo Walkthrough

### A. Direct Windows <-> Android Test
1. Start **LinkChat** on the Windows laptop (`python -m linkchat_win --nickname WinLaptop`) and on **Phone A** (grant Bluetooth/Notification permissions when prompted).
2. Wait a few seconds for **Peer Radar** on both devices to show the peer as `Direct` with live RSSI.
3. Send messages in `#public` from both sides and verify real-time delivery.
4. Click/tap the peer to open an **Encrypted DM** thread:
   - Open **Verify Safety** / **Verify** on both screens and confirm the **6-emoji fingerprint** and **30-digit safety number** match symmetrically, then click **Mark Verified**.
   - Send a DM and confirm the sender's status transitions `Sending...` -> `Relayed` -> `Delivered` upon `DM_ACK`.

### B. 3-Node Multi-Hop Relay Demo (`Phone A <-> Windows Laptop <-> Phone B`)
To demonstrate 2-hop relaying in the same room without walking two phones out of BLE range:
1. Start **LinkChat** on **Phone A**, **Windows Laptop**, and **Phone B**.
2. Open **Peer Radar** on **Phone A** and tap the **Block** icon on **Phone B**'s card (or enter Phone B's 4-hex `LC-xxxx` tag in **Inspector -> Block LC tag**). Do the same on **Phone B** to block **Phone A**'s tag if desired.
3. Blocking drops any direct Phone A <-> Phone B link and rejects new direct BLE connections between them while leaving both connected to **Windows Laptop**.
4. Within a moment, **Peer Radar** on both phones updates the other phone to **`2 hops`**.
5. On Windows, open **Mesh Inspector** to watch live relay events:
   - Send a `#public` message from **Phone A**: **Phone B** receives it with `• 2h` (`hop_count = 2`).
   - Send an encrypted DM from **Phone A** to **Phone B**: Windows **Mesh Inspector** logs `RELAY_DM` and `RELAY_ACK`, Windows has **zero** plaintext DM history for that thread, and **Phone A** receives `Delivered ✓✓`.

## Project Status & Architecture
All four phases from [PROJECT.md](PROJECT.md) are complete:
- **Phase 1**: Pure-Python `linkchat_core`, `linkchat_sim`, and unit tests.
- **Phase 2**: Windows desktop app (`windows/linkchat_win` with `CustomTkinter` + `bleak` / WinRT Peripheral + Central-Only fallback).
- **Phase 3**: Android app (`android/LinkChatAndroid` with Jetpack Compose, Chaquopy `bridge.py`, and BLE GATT Foreground Service).
- **Phase 4**: Cross-platform Windows <-> Android BLE interop fixes, 3-node multi-hop recovery & verification, and setup/demo documentation.

See [PROJECT.md](PROJECT.md) for the complete binary wire protocol, BLE GATT UUIDs, cryptographic specification, and architecture diagrams.
