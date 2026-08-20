#!/usr/bin/env python3
from getpass import getuser
from subprocess import run, Popen
from time import sleep, monotonic
import RPi.GPIO as GPIO
import dbus
import shlex
import threading
from dbus.exceptions import DBusException
import logging
import logging.handlers
import os.path
import signal
import sys


shutdown_cmd = 'sudo shutdown -h now'
reboot_cmd = 'sudo reboot'


def _exit_handler(signum, frame):
    GPIO.cleanup()
    sys.exit(0)

signal.signal(signal.SIGTERM, _exit_handler)
signal.signal(signal.SIGINT, _exit_handler)


GPIO.setmode(GPIO.BCM)
logging.basicConfig(
    level=logging.DEBUG,
    handlers=[logging.handlers.RotatingFileHandler(
        '/tmp/control.log', maxBytes=1_000_000, backupCount=2
    )]
)
bounce_time = 250
bus_lock = threading.Lock()
_modifier_lock = threading.Lock()
_modifier_active = threading.Event()

VOLUME_UP = 2
VOLUME_DOWN = 1
SUB_DELAY_DEC = 24
SUB_DELAY_INC = 25
JOY_UP = 6
JOY_DOWN = 19
JOY_LEFT = 5
JOY_RIGHT = 26


def _modifier_logic(channel):
    if not _modifier_lock.acquire(blocking=False):
        logging.debug('modifier already active, ignoring')
        return
    _modifier_active.set()
    try:
        start = monotonic()
        while not GPIO.input(channel):
            sleep(0.05)
            if not GPIO.input(btn2):
                run(shlex.split(shutdown_cmd))
                return
            if not GPIO.input(btn1) or not GPIO.input(btn3):
                run(shlex.split(reboot_cmd))
                return
            if not GPIO.input(JOY_UP):
                with bus_lock:
                    omxplayer_bus.send(VOLUME_UP)
                sleep(0.3)
                show_volume_lcd()
            elif not GPIO.input(JOY_DOWN):
                with bus_lock:
                    omxplayer_bus.send(VOLUME_DOWN)
                sleep(0.3)
                show_volume_lcd()
            elif not GPIO.input(JOY_LEFT):
                with bus_lock:
                    omxplayer_bus.send(SUB_DELAY_DEC)
                sleep(0.3)
            elif not GPIO.input(JOY_RIGHT):
                with bus_lock:
                    omxplayer_bus.send(SUB_DELAY_INC)
                sleep(0.3)
        elapsed = monotonic() - start
    finally:
        _modifier_active.clear()
        _modifier_lock.release()
    if elapsed > 1.5:
        tmux_send('f2')
    elif elapsed > 0.5:
        show_omx_info()


def modifier_callback(channel):
    threading.Thread(target=_modifier_logic, args=(channel,), daemon=True).start()


def button_callback(channel):
    if _modifier_active.is_set():
        return
    logging.debug(f'button {channel} pressed')
    with bus_lock:
        if omxplayer_bus.refresh():
            logging.debug(['omxplayer_send', btn_action[channel][0]])
            omxplayer_bus.send(btn_action[channel][0])
        else:
            logging.debug(['tmux_send', btn_action[channel][1]])
            tmux_send(btn_action[channel][1])


_tmux_session = None
_write_lcd = os.path.expanduser('~/bin/write_lcd.py')
_lcd_proc = None
_lcd_lock = threading.Lock()


def _show_lcd_async(text, timeout=5):
    global _lcd_proc
    with _lcd_lock:
        if _lcd_proc and _lcd_proc.poll() is None:
            _lcd_proc.terminate()
        _lcd_proc = Popen([_write_lcd, text, str(timeout)])


def show_omx_info():
    with bus_lock:
        if not omxplayer_bus.refresh():
            return
        try:
            props = dbus.Interface(omxplayer_bus.proxy, 'org.freedesktop.DBus.Properties')
            pos_us = int(props.Get('org.mpris.MediaPlayer2.Player', 'Position'))
            metadata = props.Get('org.mpris.MediaPlayer2.Player', 'Metadata')
            url = str(metadata.get('xesam:url', ''))
            dur_us = int(metadata.get('mpris:length', 0))
        except Exception as e:
            logging.error(f'Failed to get omx info: {e}')
            return
    filename = os.path.basename(url)
    pos_s = pos_us // 1_000_000
    pos_str = f'{pos_s // 3600:02d}:{(pos_s % 3600) // 60:02d}:{pos_s % 60:02d}'
    if dur_us > 0:
        pct = pos_us / dur_us
        filled = int(pct * 9)
        bar = '=' * filled + '>' + ' ' * (9 - filled)
        progress = f'[{bar}]{int(pct * 100):3d}%'
    else:
        progress = pos_str
    text = f'{filename}\n{pos_str}\n{progress}'
    _show_lcd_async(text, 5)


def show_volume_lcd():
    with bus_lock:
        if not omxplayer_bus.refresh():
            return
        try:
            props = dbus.Interface(omxplayer_bus.proxy, 'org.freedesktop.DBus.Properties')
            vol = float(props.Get('org.mpris.MediaPlayer2.Player', 'Volume'))
        except Exception as e:
            logging.error(f'Failed to get volume: {e}')
            return
    vol_pct = int(vol * 100)
    filled = min(10, int(vol * 10))
    bar = '|' * filled + ' ' * (10 - filled)
    _show_lcd_async(f'Volume\n[{bar}]\n{vol_pct}%', 2)


def tmux_send(action):
    global _tmux_session
    if _tmux_session is None:
        result = run(['tmux', 'list-sessions', '-F', '#{session_name}'],
                     capture_output=True, text=True)
        if result.returncode != 0:
            logging.warning('no tmux session found')
            return
        _tmux_session = result.stdout.strip().splitlines()[0]
    run(['tmux', 'send-keys', '-t', _tmux_session, action])


class OMXPlayer_bus():
    def __init__(self):
        self.bus_file = f'/tmp/omxplayerdbus.{getuser()}'
        self.connection = None
        self.last_bus_address = None
        self.proxy = None
        self.refresh()

    def refresh(self):
        if not os.path.exists(self.bus_file):
            logging.info('No bus file exists!')
            self.proxy = None
            self.connection = None
            self.last_bus_address = None
            return False

        with open(self.bus_file) as f:
            bus_address = f.read().strip()
        if bus_address != self.last_bus_address:
            logging.info(f'Bus address changed: {bus_address}')
            self.connection = None
            self.proxy = None
            self.last_bus_address = bus_address

        if not self.connection:
            try:
                self.connection = dbus.bus.BusConnection(bus_address)
            except Exception as e:
                logging.error(f'Failed to connect to bus: {e}')
                self.connection = None
                return False

        if self.proxy is None:
            try:
                self.proxy = self.connection.get_object('org.mpris.MediaPlayer2.omxplayer',
                                                        '/org/mpris/MediaPlayer2',
                                                        introspect=False)
            except Exception as e:
                logging.warning(f'Failed to get proxy: {e}')
                self.proxy = None
                self.connection = None
                return False
        return True

    def send(self, action):
        if self.proxy is None:
            logging.warning('No proxy, cannot send action')
            return
        key = dbus.Interface(self.proxy, 'org.mpris.MediaPlayer2.Player')
        try:
            key.Action(dbus.Int32(action))
        except (DBusException, AttributeError) as e:
            logging.error(f'send failed: {e}')
            self.connection = None


omxplayer_bus = OMXPlayer_bus()

# button = (omxplayer_action, vifm_key)
btn_action = {
  6: (22, 'k'),  # up
  19: (21, 'j'),  # down
  5: (19, 'h'),  # left
  26: (20, 'enter'),  # right
  21: (11, 'H'),   # btn1
  20: (16, 'enter'),  # btn2
  16: (15, 'L')  # btn3
}

btn1 = 21
btn2 = 20
btn3 = 16
btn_joy = 13

for btn in btn_action:
    GPIO.setup(btn, GPIO.IN, GPIO.PUD_UP)
    GPIO.add_event_detect(btn, GPIO.FALLING, callback=button_callback, bouncetime=bounce_time)

GPIO.setup(btn_joy, GPIO.IN, GPIO.PUD_UP)
GPIO.add_event_detect(btn_joy, GPIO.FALLING, callback=modifier_callback, bouncetime=bounce_time)

logging.debug('started')

while True:
    sleep(120)

GPIO.cleanup()
