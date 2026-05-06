from __future__ import annotations

AGENT_HOST = "127.0.0.1"
AGENT_PORT_BASE = 51240
AGENT_PORT_COUNT = 32
AGENT_IDENTITY_SERVICE = "rotunda-agent"
HEARTBEAT_INTERVAL_SECONDS = 5.0


def agent_ports(port_base: int = AGENT_PORT_BASE, port_count: int = AGENT_PORT_COUNT) -> range:
    return range(port_base, port_base + port_count)
