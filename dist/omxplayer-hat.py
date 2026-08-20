#!/usr/bin/env python3
from getpass import getuser
from subprocess import run
from time import sleep, monotonic
import RPi.GPIO as GPIO
import dbus
import shlex
import threading
from dbus.exceptions import DBusException
import logging
import os.path
import sys


shutdown_cmd = 'sudo shutdown -h now'
reboot_cmd = 'sudo reboot'


GPIO.setmode(GPIO.BCM)
logging.basicConfig(level=logging.DEBUG,
                    filename='/tmp/control.log')
bounce_time = 250
bus_lock = threading.Lock()
_modifier_lock = threading.Lock()


def _modifier_logic(channel):
    if not _modifier_lock.acquire(blocking=False):
        return
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
        if monotonic() - start > 1.5:
            tmux_send('f2')
    finally:
        _modifier_lock.release()


def modifier_callback(channel):
    threading.Thread(target=_modifier_logic, args=(channel,), daemon=True).start()


def button_callback(channel):
    logging.debug(f'button {channel} pressed')
    with bus_lock:
        if omxplayer_bus.refresh():
            logging.debug(['omxplayer_send', btn_action[channel][0]])
            omxplayer_bus.send(btn_action[channel][0])
        else:
            logging.debug(['tmux_send', btn_action[channel][1]])
            tmux_send(btn_action[channel][1])


def tmux_send(action):
    result = run(['tmux', 'list-sessions', '-F', '#{session_name}'],
                 capture_output=True, text=True)
    if result.returncode != 0:
        logging.warning('no tmux session found')
        return
    session = result.stdout.strip().splitlines()[0]
    run(['tmux', 'send-keys', '-t', session, action])


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

        bus_address = open(self.bus_file).read().strip()
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
    logging.debug('main loop')
    sleep(120)

GPIO.cleanup()
