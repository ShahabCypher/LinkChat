"""Virtual BLE mesh simulator for testing LinkChat without physical hardware."""

from .virtual_transport import EdgeConfig, NetworkHub, VirtualTransport

__all__ = ["EdgeConfig", "NetworkHub", "VirtualTransport"]
