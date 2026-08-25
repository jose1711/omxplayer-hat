#!/usr/bin/env python3
'''
Shared LCD rendering + hardware ownership for the omxplayer-hat display.

Used by omxplayer-hat.py (which owns the display for the whole time it
runs, showing a live "now playing" dashboard while a video is active) and
by write_lcd.py (a thin CLI which normally just forwards a message to the
running daemon, and only touches the hardware directly as a fallback when
the daemon isn't up).
'''
import json
import logging
import math
import os
import re
import socket
import subprocess
import threading
from datetime import datetime
from time import monotonic, sleep

from PIL import Image, ImageDraw, ImageFont
import RPi.GPIO as GPIO

import LCD_1in44

BACKLIGHT_PIN = 24
FONT_PATH = '/usr/share/fonts/TTF/DejaVuSans.ttf'
FONT_PATH_BOLD = '/usr/share/fonts/TTF/DejaVuSans-Bold.ttf'

_font_cache = {}


def _font(size, bold=False):
    key = (size, bold)
    if key not in _font_cache:
        path = FONT_PATH_BOLD if bold else FONT_PATH
        try:
            _font_cache[key] = ImageFont.truetype(path, size)
        except OSError:
            _font_cache[key] = ImageFont.truetype(FONT_PATH, size)
    return _font_cache[key]


def fmt_hms(seconds):
    seconds = max(0, int(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f'{h}:{m:02d}:{s:02d}'
    return f'{m:02d}:{s:02d}'


def _wrap_text(draw, text, font, max_width, max_lines=2):
    words = text.split() or ['']
    lines = []
    cur = ''
    for w in words:
        candidate = f'{cur} {w}'.strip()
        if draw.textlength(candidate, font=font) <= max_width:
            cur = candidate
        else:
            lines.append(cur)
            cur = w
            if len(lines) == max_lines:
                cur = ''
                break
    if cur:
        lines.append(cur)
    lines = lines[:max_lines]
    if lines and draw.textlength(lines[-1], font=font) > max_width:
        s = lines[-1]
        while s and draw.textlength(s + '…', font=font) > max_width:
            s = s[:-1]
        lines[-1] = s + '…'
    return lines


def display_title(filename):
    name = os.path.splitext(filename)[0]
    return re.sub(r'[._]+', ' ', name).strip()


def _detect_wifi_iface():
    try:
        out = subprocess.run(['iw', 'dev'], capture_output=True, text=True, timeout=2).stdout
        m = re.search(r'Interface (\w+)', out)
        if m:
            return m.group(1)
    except Exception:
        pass
    return 'wlan0'


def get_wifi_status(iface=None):
    '''Best-effort wifi status: (connected, ssid, ip, signal_dbm).'''
    iface = iface or _detect_wifi_iface()
    ip = None
    ssid = None
    signal = None
    try:
        out = subprocess.run(['ip', '-4', '-o', 'addr', 'show', iface],
                             capture_output=True, text=True, timeout=2).stdout
        m = re.search(r'inet (\d+\.\d+\.\d+\.\d+)', out)
        ip = m.group(1) if m else None
    except Exception:
        pass
    try:
        out = subprocess.run(['iw', 'dev', iface, 'link'],
                             capture_output=True, text=True, timeout=2).stdout
        m = re.search(r'SSID: (.+)', out)
        ssid = m.group(1).strip() if m else None
        m = re.search(r'signal: (-?\d+) dBm', out)
        signal = int(m.group(1)) if m else None
    except Exception:
        pass
    return (ip is not None, ssid, ip, signal)


def draw_wifi_icon(draw, x, y, connected, signal_dbm):
    bar_w = 3
    gap = 2
    heights = [4, 7, 10]
    if not connected:
        level = 0
        color = (130, 130, 130)
    elif signal_dbm is None:
        level, color = 2, (0, 200, 0)
    elif signal_dbm >= -55:
        level, color = 3, (0, 200, 0)
    elif signal_dbm >= -70:
        level, color = 2, (0, 200, 0)
    elif signal_dbm >= -80:
        level, color = 1, (230, 160, 0)
    else:
        level, color = 0, (200, 0, 0)
    base_y = y + heights[-1]
    for i, h in enumerate(heights):
        bx = x + i * (bar_w + gap)
        by = base_y - h
        fill = color if i < level else (50, 50, 50)
        draw.rectangle([bx, by, bx + bar_w - 1, base_y], fill=fill)
    if not connected:
        draw.line([x - 1, base_y + 1, x + len(heights) * (bar_w + gap), by - 1],
                   fill=(200, 0, 0), width=2)


def send_direct(render_fn, timeout):
    '''Draw directly on the hardware. Only used as a fallback when the
    daemon isn't reachable (e.g. early boot, or after shutdown has already
    stopped it) — two processes must never do this at the same time. If the
    daemon turns out to hold the hardware after all (a race send_via_daemon's
    retries didn't cover), fail quietly rather than a raw traceback.'''
    try:
        display = Display()
    except Exception as e:
        logging.error(f'LCD fallback render failed: {e}')
        return
    try:
        render_fn(display)
        sleep(timeout)
    finally:
        display.cleanup()


def _gradient(w, h, top, bottom):
    image = Image.new('RGB', (w, h))
    draw = ImageDraw.Draw(image)
    for y in range(h):
        t = y / (h - 1)
        draw.line([(0, y), (w, y)], fill=tuple(
            int(top[i] + (bottom[i] - top[i]) * t) for i in range(3)))
    return image, draw


def _centered_text(draw, width, y, text, font, fill):
    _, _, w, _ = draw.textbbox((0, 0), text, font=font)
    draw.text(((width - w) / 2, y), text, fill=fill, font=font)


class Display:
    '''Owns the physical LCD + backlight. Not thread-safe on its own —
    callers must serialize access (LcdManager does this with a lock).'''

    def __init__(self):
        self.lcd = LCD_1in44.LCD()
        self.lcd.LCD_Init(LCD_1in44.SCAN_DIR_DFT)
        GPIO.setup(BACKLIGHT_PIN, GPIO.OUT)
        self.backlight = GPIO.PWM(BACKLIGHT_PIN, 1000)
        self.backlight.start(0)
        self._lit = False

    def _set_backlight(self, duty):
        self.backlight.ChangeDutyCycle(duty)
        self._lit = duty > 0

    def off(self):
        if self._lit:
            self._set_backlight(0)

    def show_image(self, image, backlight=80):
        self.lcd.LCD_ShowImage(image, 0, 0)
        if not self._lit:
            self._set_backlight(backlight)

    def show_text(self, text, color='yellow', backlight=80):
        image = Image.new('RGB', (self.lcd.width, self.lcd.height), 'BLACK')
        draw = ImageDraw.Draw(image)
        font = _font(12)
        _, _, w, h = draw.multiline_textbbox((0, 0), text, font=font)
        x = (self.lcd.width - w) / 2
        y = (self.lcd.height - h) / 2
        draw.multiline_text((x, y), text, fill=color, font=font, align='center')
        self.show_image(image, backlight=backlight)

    def render_now_playing(self, *, title, pos_s, dur_s, paused, wifi):
        W, H = self.lcd.width, self.lcd.height
        image = Image.new('RGB', (W, H), 'BLACK')
        draw = ImageDraw.Draw(image)

        connected, ssid, ip, signal = wifi
        draw_wifi_icon(draw, 4, 4, connected, signal)

        now_str = datetime.now().strftime('%H:%M')
        f_small = _font(11)
        _, _, tw, _ = draw.textbbox((0, 0), now_str, font=f_small)
        draw.text((W - tw - 4, 3), now_str, fill='white', font=f_small)

        f_title = _font(12, bold=True)
        ty = 24
        for line in _wrap_text(draw, title, f_title, W - 8):
            draw.text((4, ty), line, fill='white', font=f_title)
            ty += 15

        bar_y, bar_h = 80, 8
        draw.rectangle([4, bar_y, W - 4, bar_y + bar_h], outline=(120, 120, 120))
        if dur_s > 0:
            pct = max(0.0, min(1.0, pos_s / dur_s))
            fill_w = int((W - 10) * pct)
            color = (200, 160, 0) if paused else (0, 180, 0)
            if fill_w > 0:
                draw.rectangle([5, bar_y + 1, 5 + fill_w, bar_y + bar_h - 1], fill=color)

        f_time = _font(11)
        elapsed = fmt_hms(pos_s)
        draw.text((4, bar_y + bar_h + 3), elapsed, fill='white', font=f_time)
        if dur_s > 0:
            remaining = f'-{fmt_hms(dur_s - pos_s)}'
            _, _, rw, _ = draw.textbbox((0, 0), remaining, font=f_time)
            draw.text((W - rw - 4, bar_y + bar_h + 3), remaining, fill='white', font=f_time)
        if paused:
            status = 'PAUSED'
            _, _, sw, _ = draw.textbbox((0, 0), status, font=f_time)
            draw.text(((W - sw) / 2, bar_y + bar_h + 18), status, fill=(230, 160, 0), font=f_time)

        if ip:
            f_ip = _font(9)
            draw.text((4, H - 12), ip, fill=(150, 150, 150), font=f_ip)

        self.show_image(image)

    def show_splash(self, kind):
        renderer = getattr(self, f'_render_splash_{kind}', None)
        if renderer is None:
            raise ValueError(f'unknown splash kind: {kind}')
        renderer()

    def _render_splash_boot(self):
        W, H = self.lcd.width, self.lcd.height
        image, draw = _gradient(W, H, (10, 25, 45), (0, 0, 0))
        cx, cy, r = W // 2, 46, 26
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(0, 150, 95))
        draw.polygon([(cx - 9, cy - 14), (cx - 9, cy + 14), (cx + 15, cy)], fill='white')
        _centered_text(draw, W, 86, 'omxplayer-hat', _font(14, bold=True), 'white')
        _centered_text(draw, W, 105, 'starting…', _font(10), (150, 170, 160))
        self.show_image(image)

    def _render_splash_shutdown(self):
        W, H = self.lcd.width, self.lcd.height
        image, draw = _gradient(W, H, (45, 12, 12), (0, 0, 0))
        cx, cy, r = W // 2, 46, 22
        draw.arc([cx - r, cy - r, cx + r, cy + r], start=125, end=55, fill=(230, 70, 70), width=5)
        draw.line([(cx, cy - r - 3), (cx, cy - 4)], fill=(230, 70, 70), width=5)
        _centered_text(draw, W, 86, 'Shutting down', _font(13, bold=True), 'white')
        _centered_text(draw, W, 105, 'see you soon', _font(10), (180, 140, 140))
        self.show_image(image)

    def _render_splash_reboot(self):
        W, H = self.lcd.width, self.lcd.height
        image, draw = _gradient(W, H, (45, 33, 5), (0, 0, 0))
        cx, cy, r = W // 2, 46, 22
        draw.arc([cx - r, cy - r, cx + r, cy + r], start=-30, end=210, fill=(235, 165, 45), width=5)
        ang = math.radians(210)
        ax, ay = cx + r * math.cos(ang), cy + r * math.sin(ang)
        draw.polygon([(ax - 5, ay - 5), (ax + 7, ay), (ax - 5, ay + 5)], fill=(235, 165, 45))
        _centered_text(draw, W, 86, 'Rebooting', _font(13, bold=True), 'white')
        _centered_text(draw, W, 105, 'back in a moment', _font(10), (190, 165, 120))
        self.show_image(image)

    def cleanup(self):
        try:
            self.backlight.stop()
        except Exception:
            pass


class LcdManager:
    '''Owns the Display and arbitrates between the continuous "now
    playing" dashboard and short-lived override messages (button
    feedback, IP/help/shutdown notices delivered over the socket).'''

    def __init__(self, get_playback_state, socket_path):
        self.display = Display()
        self.get_playback_state = get_playback_state
        self.socket_path = socket_path
        self._lock = threading.Lock()
        self._override = None  # (render_fn, expire_monotonic)
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._threads = []

    def request_message(self, text, timeout=5, color='yellow'):
        self._set_override(lambda: self.display.show_text(text, color=color), timeout)

    def request_splash(self, kind, timeout=6):
        self._set_override(lambda: self.display.show_splash(kind), timeout)

    def _set_override(self, render_fn, timeout):
        with self._lock:
            self._override = (render_fn, monotonic() + timeout)
        self._wake.set()

    def start(self):
        for target in (self._socket_server, self._render_loop):
            t = threading.Thread(target=target, daemon=True)
            t.start()
            self._threads.append(t)

    def stop(self):
        self._stop.set()
        self._wake.set()
        for t in self._threads:
            t.join(timeout=2)
        self.display.cleanup()

    def _render_loop(self):
        while not self._stop.is_set():
            self._wake.clear()
            with self._lock:
                override = self._override
                if override and override[1] <= monotonic():
                    override = None
                    self._override = None
            try:
                if override:
                    render_fn, expire = override
                    render_fn()
                    self._wake.wait(max(0.0, expire - monotonic()))
                    continue
                state = self.get_playback_state()
                if state is None:
                    self.display.off()
                    self._wake.wait(1.5)
                    continue
                wifi = get_wifi_status()
                self.display.render_now_playing(wifi=wifi, **state)
            except Exception as e:
                # a single bad frame (e.g. an unknown splash kind from a
                # malformed socket request) must not permanently wedge the
                # dashboard, since this loop runs for the daemon's whole life
                logging.error(f'LCD render failed, skipping frame: {e}')
                self._wake.wait(1)
                continue
            self._wake.wait(1)

    def _socket_server(self):
        try:
            os.unlink(self.socket_path)
        except FileNotFoundError:
            pass
        try:
            srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            srv.bind(self.socket_path)
            os.chmod(self.socket_path, 0o600)
            srv.settimeout(1)
            srv.listen(4)
        except OSError as e:
            logging.error(f'LCD socket server could not start: {e}')
            return
        try:
            while not self._stop.is_set():
                try:
                    conn, _ = srv.accept()
                except socket.timeout:
                    continue
                except OSError:
                    break
                with conn:
                    data = conn.recv(4096)
                    if not data:
                        continue
                    try:
                        msg = json.loads(data.decode())
                        if 'splash' in msg:
                            self.request_splash(msg['splash'], msg.get('timeout', 6))
                        else:
                            self.request_message(msg['text'], msg.get('timeout', 5),
                                                  msg.get('color', 'yellow'))
                    except Exception:
                        pass
        finally:
            srv.close()
            try:
                os.unlink(self.socket_path)
            except FileNotFoundError:
                pass
