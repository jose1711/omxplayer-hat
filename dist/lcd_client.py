#!/usr/bin/env python3
'''
Lightweight socket client for the omxplayer-hat LCD daemon
(lcd_display.LcdManager). Deliberately has no hardware dependencies (no
PIL/RPi.GPIO/spidev), so importing it is cheap on the common path where the
daemon is reachable and the caller never needs to touch the display
directly.
'''
import json
import socket
from getpass import getuser
from time import monotonic, sleep


def socket_path():
    return f'/tmp/lcd-hat.{getuser()}.sock'


def send_via_daemon(payload, timeout, connect_deadline=8, retry_delay=0.3):
    '''Forward a request to the running LcdManager over its socket. Blocks
    for `timeout` seconds on success, matching lcd_display.send_direct()'s
    contract, so callers can rely on it for boot-time sequencing regardless
    of whether the daemon is up. Returns False (without waiting) if it isn't.

    Retries connecting for up to `connect_deadline` seconds first: the
    daemon claims the LCD/GPIO hardware as soon as it starts, but its
    process needs a few seconds to get through its (PIL/dbus/GPIO) imports
    before its socket comes up — e.g. right after `sv restart`. Without
    this, a caller in that window would wrongly conclude the daemon is
    down and fall back to touching the hardware directly, colliding with
    the daemon that in fact already owns it.'''
    deadline = monotonic() + connect_deadline
    while True:
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
                s.settimeout(1)
                s.connect(socket_path())
                s.sendall(json.dumps(payload).encode())
            sleep(timeout)
            return True
        except OSError:
            if monotonic() >= deadline:
                return False
            sleep(retry_delay)
