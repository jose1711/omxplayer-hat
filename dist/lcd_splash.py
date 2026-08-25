#!/home/{{user}}/.venv/bin/python3
'''
show a full-screen splash graphic on the LCD

  arg1 = splash kind: boot | shutdown | reboot
[ arg2 = timeout (seconds), default 6 ]

Tries the omxplayer-hat daemon's socket first, so a running "now playing"
dashboard doesn't get fought over the SPI bus. Falls back to driving the
display directly if the daemon isn't up (e.g. early boot, or after
shutdown has already stopped it) — that fallback path is the only one
that needs the heavy PIL/GPIO imports, so they're deferred until then.
'''
import sys

import lcd_client

if __name__ == '__main__':
    if len(sys.argv) < 2:
        sys.exit()

    kind = sys.argv[1]
    timeout = int(sys.argv[2]) if len(sys.argv) >= 3 else 6

    payload = {'splash': kind, 'timeout': timeout}
    if not lcd_client.send_via_daemon(payload, timeout):
        import lcd_display
        lcd_display.send_direct(lambda d: d.show_splash(kind), timeout)
