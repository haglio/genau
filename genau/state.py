from __future__ import annotations

import logging
import socket
import threading
from dataclasses import dataclass, field


@dataclass
class SharedState:
    lock: threading.Lock = field(default_factory=threading.Lock)
    auto_active: bool = False
    raw_bpm: float | None = None
    sync_pulse_id: int = 0


# How long to wait between bind attempts.  The port is usually held by the
# session that just ended, so the first retry is short and the last is long
# enough to outlast a slow teardown.
_BIND_RETRY_DELAYS = (0.5, 1.0, 2.0)

# How long a read waits before looking at the stop flag again.  Short enough
# that a quit is not felt, long enough that an idle listener is not a spin.
_READ_TIMEOUT_S = 0.2


def apply_udp_line(state: SharedState, line: str, logger: logging.Logger) -> None:
    """Act on one datagram from the broker.

    Genau acts on three of the eight verbs the broker sends.  The other five --
    SHOW, HIDE, BEATS, STROKE, PATTERN -- arrive and fall through exactly as an
    unrecognized line does; whether the broker should stop sending them is the
    broker's call, not this reader's.

    Split out of the socket loop so a verb can be tested without binding a
    port: thirteen of the fifteen slowest tests in the repo used to be this
    parsing, reached through a real socket.
    """
    said = line.split(" ", 1)
    verb = said[0].upper()
    arg = said[1].strip() if len(said) > 1 else ""

    with state.lock:
        if verb == "AUTO":
            state.auto_active = arg == "1"
            logger.info("Received AUTO %s", 1 if state.auto_active else 0)
        elif verb == "BPM":
            try:
                state.raw_bpm = float(arg)
            except ValueError:
                logger.warning("Invalid BPM payload: %s", line)
        elif verb == "SYNC":
            state.sync_pulse_id += 1


def bind_with_retry(
    sock: socket.socket,
    host: str,
    port: int,
    stop_event: threading.Event,
    logger: logging.Logger,
) -> bool:
    """Take the port, waiting for it if something else still has it.

    Returns False only when the wait was cut short by a quit; a port that never
    frees raises on the last attempt, which is the caller's to report.
    """
    for attempt, delay in enumerate(_BIND_RETRY_DELAYS, 1):
        try:
            sock.bind((host, port))
            return True
        except OSError as exc:
            logger.warning(
                "UDP bind attempt %d failed on %s:%s: %s — retrying in %.1fs",
                attempt, host, port, exc, delay,
            )
            if stop_event.wait(delay):
                return False
    # Out of retries — let this one raise, so the reason reaches the log.
    sock.bind((host, port))
    return True


def udp_reader(host: str, port: int, state: SharedState, stop_event: threading.Event, logger: logging.Logger) -> None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        if not bind_with_retry(sock, host, port, stop_event, logger):
            return

        sock.settimeout(_READ_TIMEOUT_S)
        logger.info("Genau UDP listener bound on %s:%s", host, port)

        while not stop_event.is_set():
            try:
                data, _addr = sock.recvfrom(4096)
            except socket.timeout:
                continue
            apply_udp_line(
                state, data.decode("utf-8", errors="replace").strip(), logger)
    except Exception:
        logger.exception("UDP reader failed")
    finally:
        sock.close()
