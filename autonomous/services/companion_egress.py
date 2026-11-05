"""Route Autonomous VM traffic through the paired companion, or cut it.

Rules only match containers labeled autonomous.bot. Other Docker containers
on the host are left alone. The chain names are owned by this process and
removed whenever the policy is off.
"""

from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path

log = logging.getLogger("autonomous.companion")

NAT_CHAIN = "AUTONOMOUS_EGRESS"
FILTER_CHAIN = "AUTONOMOUS_EGRESS_FILTER"


def build_commands(
    *,
    rules: list[dict],
    subnets: list[str],
    filter_hook: str,
) -> list[list[str]]:
    """iptables argv list. Each rule is one bot IP: redirect or kill."""
    commands: list[list[str]] = [
        ["iptables", "-t", "nat", "-D", "PREROUTING", "-j", NAT_CHAIN],
        ["iptables", "-t", "nat", "-F", NAT_CHAIN],
        ["iptables", "-t", "nat", "-X", NAT_CHAIN],
        ["iptables", "-D", filter_hook, "-j", FILTER_CHAIN],
        ["iptables", "-F", FILTER_CHAIN],
        ["iptables", "-X", FILTER_CHAIN],
    ]
    active = [rule for rule in rules if rule.get("ip") and rule.get("mode") in {"redirect", "kill"}]
    if not active:
        return commands
    commands.extend(
        [
            ["iptables", "-t", "nat", "-N", NAT_CHAIN],
            ["iptables", "-N", FILTER_CHAIN],
        ]
    )
    for subnet in subnets:
        commands.append(
            ["iptables", "-t", "nat", "-A", NAT_CHAIN, "-d", subnet, "-j", "RETURN"]
        )
        commands.append(
            ["iptables", "-A", FILTER_CHAIN, "-d", subnet, "-j", "RETURN"]
        )
    for rule in active:
        ip = rule["ip"]
        if rule["mode"] == "redirect":
            commands.append(
                [
                    "iptables", "-t", "nat", "-A", NAT_CHAIN,
                    "-s", ip, "-p", "tcp", "-j", "REDIRECT",
                    "--to-ports", str(rule["tcp_port"]),
                ]
            )
            commands.append(
                [
                    "iptables", "-t", "nat", "-A", NAT_CHAIN,
                    "-s", ip, "-p", "udp", "--dport", "53",
                    "-j", "REDIRECT", "--to-ports", str(rule["dns_port"]),
                ]
            )
            # QUIC and other UDP would skip the TCP tunnel and leave via the server.
            commands.append(
                [
                    "iptables", "-A", FILTER_CHAIN,
                    "-s", ip, "-p", "udp", "!", "--dport", "53", "-j", "DROP",
                ]
            )
        else:
            commands.append(
                ["iptables", "-A", FILTER_CHAIN, "-s", ip, "-j", "DROP"]
            )
    commands.extend(
        [
            ["iptables", "-t", "nat", "-I", "PREROUTING", "1", "-j", NAT_CHAIN],
            ["iptables", "-I", filter_hook, "1", "-j", FILTER_CHAIN],
        ]
    )
    return commands


def plan(
    assignments: list[dict],
    *,
    ips_by_bot: dict[str, str],
    sessions: dict[str, tuple[int, int] | None],
) -> list[dict]:
    """One rule per bot whose traffic must leave through its companion.

    `sessions[device_id]` is (socks_port, dns_port) when that PC is connected,
    otherwise None. Offline + killswitch drops only that bot. Offline without
    killswitch leaves the bot on the server path (no rule).
    """
    rules: list[dict] = []
    for row in assignments:
        if not row.get("egress"):
            continue
        ip = ips_by_bot.get(str(row.get("name") or ""))
        if not ip:
            continue
        ports = sessions.get(str(row.get("companion_id") or ""))
        if ports:
            tcp_port, dns_port = ports
            rules.append(
                {
                    "ip": ip,
                    "mode": "redirect",
                    "tcp_port": tcp_port,
                    "dns_port": dns_port,
                }
            )
        elif row.get("killswitch"):
            rules.append({"ip": ip, "mode": "kill", "tcp_port": 0, "dns_port": 0})
    return rules


def bot_endpoints() -> tuple[dict[str, str], list[str]]:
    """Bot slug → container IP, plus bridge subnets of running autonomous desks."""
    try:
        import docker
    except ImportError:
        return {}, []
    try:
        client = docker.from_env()
        containers = client.containers.list(filters={"label": "autonomous.bot"})
    except Exception as exc:
        log.warning("docker listing for companion egress failed: %s", exc)
        return {}, []
    ips: dict[str, str] = {}
    subnets: list[str] = []
    seen_nets: set[str] = set()
    for container in containers:
        bot = str((container.labels or {}).get("autonomous.bot") or "")
        networks = (container.attrs.get("NetworkSettings") or {}).get("Networks") or {}
        for net_name, net in networks.items():
            ip = (net or {}).get("IPAddress") or ""
            if bot and ip and bot not in ips:
                ips[bot] = ip
            if net_name in seen_nets:
                continue
            seen_nets.add(net_name)
            try:
                network = client.networks.get(net_name)
                for cfg in (network.attrs.get("IPAM") or {}).get("Config") or []:
                    subnet = cfg.get("Subnet")
                    if subnet:
                        subnets.append(subnet)
            except Exception:
                continue
    return ips, subnets


def policy(home: Path | None) -> tuple[list[dict], list[str]]:
    """Per-bot redirect/kill rules and the bridge subnets to leave alone."""
    from autonomous.services import bots as bots_svc
    from autonomous.services import companion_link as link_svc

    assignments = bots_svc.companion_routes(home=home)
    if not assignments:
        return [], []
    ips_by_bot, subnets = bot_endpoints()
    hub = link_svc.hub_for(home)
    sessions: dict[str, tuple[int, int] | None] = {}
    for row in assignments:
        device_id = str(row.get("companion_id") or "")
        if not device_id or device_id in sessions:
            continue
        session = hub.session_for(device_id)
        if (
            session is not None
            and not session.closed
            and session.socks_port
            and session.dns_port
        ):
            sessions[device_id] = (session.socks_port, session.dns_port)
        else:
            sessions[device_id] = None
    return plan(assignments, ips_by_bot=ips_by_bot, sessions=sessions), subnets


def _filter_hook() -> str:
    probe = subprocess.run(
        ["iptables", "-L", "DOCKER-USER", "-n"],
        capture_output=True,
        text=True,
    )
    return "DOCKER-USER" if probe.returncode == 0 else "FORWARD"


def _status(rules: list[dict]) -> str:
    if any(rule.get("mode") == "redirect" for rule in rules):
        return "redirect"
    if any(rule.get("mode") == "kill" for rule in rules):
        return "kill"
    return "off"


def refresh(home: Path | None = None) -> str:
    """Install or remove iptables rules. Failures are logged, not raised."""
    rules, subnets = policy(home)
    mode = _status(rules)
    if os.environ.get("AUTONOMOUS_COMPANION_IPTABLES") == "0":
        return mode
    try:
        hook = _filter_hook()
        commands = build_commands(rules=rules, subnets=subnets, filter_hook=hook)
    except FileNotFoundError:
        log.warning("iptables is not installed; companion egress stays inactive")
        return "off"
    for argv in commands:
        try:
            subprocess.run(argv, capture_output=True, text=True, timeout=8)
        except FileNotFoundError:
            log.warning("iptables is not installed; companion egress stays inactive")
            return "off"
        except Exception as exc:
            log.warning("iptables %s failed: %s", argv, exc)
    log.info("companion egress mode=%s rules=%s", mode, len(rules))
    return mode
