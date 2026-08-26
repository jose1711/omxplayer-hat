#!/usr/bin/env python3
from getpass import getuser
from subprocess import run
from time import sleep, monotonic
from urllib.parse import unquote, urlparse
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

import lcd_client
import lcd_display


shutdown_cmd = 'sudo shutdown -h now'
reboot_cmd = 'sudo reboot'

lcd = None  # assigned once LcdManager is up; guarded below since a signal
            # can arrive during startup, before that has happened


def _exit_handler(signum, frame):
    if lcd is not None:
        lcd.stop()
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


# action codes from omxplayer's KeyConfig.h (the DBus Action() method takes
# the same integers as its internal key-action enum)
VOLUME_DOWN = 17
VOLUME_UP = 18
SUB_DELAY_DEC = 13
SUB_DELAY_INC = 14
JOY_UP = 6
JOY_DOWN = 19
JOY_LEFT = 5
JOY_RIGHT = 26


def _confirmed_low(pin, checks=3, delay=0.03):
    '''Extra debounce for the shutdown/reboot combo specifically: these are
    destructive/hard-to-reverse, so a single noisy GPIO read must not be
    enough to trigger one — require it to read low consistently.'''
    for _ in range(checks):
        if GPIO.input(pin):
            return False
        sleep(delay)
    return True


def _modifier_logic(channel):
    if not _modifier_lock.acquire(blocking=False):
        logging.debug('modifier already active, ignoring')
        return
    _modifier_active.set()
    try:
        start = monotonic()
        while not GPIO.input(channel):
            sleep(0.05)
            # check both buttons before acting on either: if electrical
            # crosstalk (or a genuine double-press) makes both the shutdown
            # and reboot buttons read low at once, committing to whichever
            # was checked first would silently pick the wrong (and harder
            # to reverse) action, so treat that as ambiguous and do nothing
            btn1_low = not GPIO.input(btn1) and _confirmed_low(btn1)
            btn2_low = not GPIO.input(btn2) and _confirmed_low(btn2)
            btn3_low = not GPIO.input(btn3) and _confirmed_low(btn3)
            if btn1_low or btn2_low or btn3_low:
                logging.debug('combo poll: btn1=%s btn2=%s btn3=%s', btn1_low, btn2_low, btn3_low)
            shutdown_wanted = btn2_low or btn3_low
            reboot_wanted = btn1_low
            if shutdown_wanted and reboot_wanted:
                logging.warning('ambiguous shutdown/reboot combo (btn1=%s btn2=%s btn3=%s), ignoring',
                                 btn1_low, btn2_low, btn3_low)
            elif shutdown_wanted:
                logging.info('shutdown combo confirmed: btn2(GPIO%d)=%s btn3(GPIO%d)=%s',
                             btn2, btn2_low, btn3, btn3_low)
                lcd.request_splash('shutdown', timeout=30)
                run(shlex.split(shutdown_cmd))
                return
            elif reboot_wanted:
                logging.info('reboot combo confirmed on btn1 (GPIO%d)', btn1)
                lcd.request_splash('reboot', timeout=30)
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
                lcd.request_message('Subtitle delay -', timeout=1.5)
            elif not GPIO.input(JOY_RIGHT):
                with bus_lock:
                    omxplayer_bus.send(SUB_DELAY_INC)
                sleep(0.3)
                lcd.request_message('Subtitle delay +', timeout=1.5)
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


# short LCD labels shown immediately after a button sends an omxplayer
# action, keyed by the same action codes as btn_action's first element.
# ACTION_PLAYPAUSE (16) isn't here: its label depends on the state being
# switched to, so it's computed in _action_feedback instead.
ACTION_LABELS = {
    22: 'Seek »» +10:00',   # ACTION_SEEK_FORWARD_LARGE
    21: 'Seek «« -10:00',   # ACTION_SEEK_BACK_LARGE
    19: 'Seek « -0:30',     # ACTION_SEEK_BACK_SMALL
    20: 'Seek » +0:30',     # ACTION_SEEK_FORWARD_SMALL
    11: 'Subtitles: next',  # ACTION_NEXT_SUBTITLE
    15: 'Quit',             # ACTION_EXIT
}


def _action_feedback(action, state_before):
    if action == 16:  # ACTION_PLAYPAUSE: label the state we're switching to
        if state_before is not None:
            return 'Paused' if not state_before['paused'] else 'Playing'
        return 'Play/Pause'
    return ACTION_LABELS.get(action)


def button_callback(channel):
    if _modifier_active.is_set():
        return
    logging.debug(f'button {channel} pressed')
    action = btn_action[channel][0]
    # only ACTION_PLAYPAUSE's label depends on the state being switched
    # FROM, so only fetch it (a dbus round trip) when actually needed
    state_before = get_playback_state() if action == 16 else None
    with bus_lock:
        active = omxplayer_bus.refresh()
        if active:
            logging.debug(['omxplayer_send', action])
            omxplayer_bus.send(action)
    if not active:
        logging.debug(['tmux_send', btn_action[channel][1]])
        tmux_send(btn_action[channel][1])
        return
    label = _action_feedback(action, state_before)
    if label:
        lcd.request_message(label, timeout=1.5)


_tmux_session = None


def get_playback_state():
    '''Snapshot of the active omxplayer track, or None if nothing plays.
    Used by the LcdManager render loop to draw the "now playing" dashboard.'''
    with bus_lock:
        if not omxplayer_bus.refresh():
            return None
        try:
            props = dbus.Interface(omxplayer_bus.proxy, 'org.freedesktop.DBus.Properties')
            pos_us = int(props.Get('org.mpris.MediaPlayer2.Player', 'Position'))
            metadata = props.Get('org.mpris.MediaPlayer2.Player', 'Metadata')
            url = str(metadata.get('xesam:url', ''))
            dur_us = int(metadata.get('mpris:length', 0))
            try:
                paused = str(props.Get('org.mpris.MediaPlayer2.Player', 'PlaybackStatus')) != 'Playing'
            except DBusException:
                paused = False
        except Exception as e:
            logging.error(f'Failed to get omx info: {e}')
            return None
    filename = os.path.basename(unquote(urlparse(url).path))
    return {
        'title': lcd_display.display_title(filename),
        'pos_s': pos_us / 1_000_000,
        'dur_s': dur_us / 1_000_000,
        'paused': paused,
    }


def show_omx_info():
    state = get_playback_state()
    if state is None:
        return
    elapsed = lcd_display.fmt_hms(state['pos_s'])
    if state['dur_s'] > 0:
        pct = state['pos_s'] / state['dur_s']
        filled = int(pct * 9)
        bar = '=' * filled + '>' + ' ' * (9 - filled)
        progress = f'[{bar}]{int(pct * 100):3d}%'
    else:
        progress = elapsed
    lcd.request_message(f'{state["title"]}\n{elapsed}\n{progress}', timeout=5)


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
    lcd.request_message(f'Volume\n[{bar}]\n{vol_pct}%', timeout=2)


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
        self._last_connected = None  # tri-state, so the render loop's frequent
                                      # polling only logs on actual transitions
        self.refresh()

    def _finish(self, connected):
        if connected != self._last_connected:
            logging.info('omxplayer bus available' if connected
                          else 'omxplayer bus unavailable')
            self._last_connected = connected
        return connected

    def refresh(self):
        if not os.path.exists(self.bus_file):
            self.proxy = None
            self.connection = None
            self.last_bus_address = None
            return self._finish(False)

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
                return self._finish(False)

        try:
            if not self.connection.name_has_owner('org.mpris.MediaPlayer2.omxplayer'):
                self.proxy = None
                self.connection = None
                return self._finish(False)
        except DBusException as e:
            logging.error(f'Failed to check bus ownership: {e}')
            self.proxy = None
            self.connection = None
            return self._finish(False)

        if self.proxy is None:
            try:
                self.proxy = self.connection.get_object('org.mpris.MediaPlayer2.omxplayer',
                                                        '/org/mpris/MediaPlayer2',
                                                        introspect=False)
            except Exception as e:
                logging.warning(f'Failed to get proxy: {e}')
                self.proxy = None
                self.connection = None
                return self._finish(False)
        return self._finish(True)

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
            self.proxy = None


omxplayer_bus = OMXPlayer_bus()


class _NullLcd:
    '''Stand-in used if the LCD hardware fails to initialize, so a flaky
    display doesn't take down joystick/button control with it.'''
    def request_message(self, *args, **kwargs):
        pass

    def request_splash(self, *args, **kwargs):
        pass

    def stop(self):
        pass


try:
    lcd = lcd_display.LcdManager(get_playback_state, lcd_client.socket_path())
    lcd.start()
except Exception as e:
    logging.error(f'LCD init failed, continuing without display: {e}')
    lcd = _NullLcd()

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
