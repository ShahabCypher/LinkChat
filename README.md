# LinkChat

Offline, decentralized Bluetooth Low Energy (BLE) mesh messenger for **Windows** and **Android**, inspired by BitChat.

## Key Features
- **Public Group Chat**: Multi-hop BLE broadcast messaging across connected peers.
- **Encrypted Direct Messages**: End-to-end encrypted 1-to-1 messaging (`X25519` + `HKDF-SHA256` + `ChaCha20-Poly1305`) with delivery acknowledgments.
- **Multi-Hop Mesh Relay**: TTL-bounded forwarding with packet deduplication (`Phone A <-> Laptop B <-> Phone C`).
- **Live Peer Radar**: Discovered peers with hop count, signal strength (RSSI), and verification badges.
- **Identity & Safety Fingerprints**: Zero-account `Ed25519` identity with TOFU key tracking and 6-emoji / numeric safety verification.
- **Store-and-Forward Sync**: Local message caching and catch-up sync for reconnecting peers.
- **Local Mesh Simulator**: Virtual Python radio simulator for testing 5+ node topologies without physical Bluetooth hardware.

## Tech Stack
- **Shared Core (`linkchat_core`)**: Python 3.12/3.13 (`cryptography`, `sqlite3`, `asyncio`)
- **Windows App**: Full Python (`CustomTkinter` UI + `bleak` / `bless` BLE transport)
- **Android App**: Kotlin (`Jetpack Compose` + native Android BLE GATT) + `Chaquopy` embedding `linkchat_core`

## Project Status & Architecture
Phase 1 (`linkchat_core`, `linkchat_sim`, `tests/`) and Phase 2 (`windows/linkchat_win`) complete. See [PROJECT.md](PROJECT.md) for the complete architecture, binary wire protocol, BLE GATT specification, cryptographic design, and phased implementation roadmap.
