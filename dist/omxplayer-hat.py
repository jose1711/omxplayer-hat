#!/usr/bin/env python3
from getpass import getuser
from subprocess import run
from time import sleep, monotonic
import RPi.GPIO as GPIO
import dbus
import shlex
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


# joystick button serves as a modifier
def modifier_callback(event):
    start = monotonic()
    while not GPIO.input(event):
        if not GPIO.input(btn2):
            GPIO.remove_event_detect(btn2)
            run(shlex.split(shutdown_cmd))
        if not GPIO.input(btn1) or not GPIO.input(btn3):
            GPIO.remove_event_detect(btn1)
            GPIO.remove_event_detect(btn3)
            run(shlex.split(reboot_cmd))
    if monotonic() - start > 1.5:
        tmux_send('f2')


def button_callback(event):
    logging.debug(f'button {event} pressed')

    if omxplayer_bus.refresh():
        logging.debug(['omxplayer_send', btn_action[event][0]])
        omxplayer_bus.send(btn_action[event][0])
    else:
        logging.debug(['tmux_send', btn_action[event][1]])
        tmux_send(btn_action[event][1])


def tmux_send(action):
    cmd = ['tmux', 'send']
    run(cmd + [action])


class OMXPlayer_bus():
    def __init__(self):
        ''' populate prop and key globals '''
        self.bus_file = f'/tmp/omxplayerdbus.{getuser()}'
        self.connection = None
        self.refresh()


    def refresh(self):
        if not os.path.exists(self.bus_file):
            logging.info('No bus file exists!')
            self.proxy = None
            return False
        if not self.connection:
            self.connection = dbus.bus.BusConnection(open(self.bus_file).read().strip())
        try:
            self.proxy = self.connection.get_object('org.mpris.MediaPlayer2.omxplayer',
                                                   '/org/mpris/MediaPlayer2',
                                                   introspect=False)
        except:
            self.proxy = None
            return False
        return True


    def fix(self):
        try:
            self.proxy = self.proxy.get_object('org.mpris.MediaPlayer2.omxplayer',
                                               '/org/mpris/MediaPlayer2',
                                               introspect=False)
        except Exception as e:
            logging.critical(e)
            return False


    def send(self, action):
        prop = dbus.Interface(self.proxy, 'org.freedesktop.DBus.Properties')
        key = dbus.Interface(self.proxy, 'org.mpris.MediaPlayer2.Player')
        try:
            status = str(self.proxy.Get(dbus.String('org.mpris.MediaPlayer2.Player'), dbus.String('PlaybackStatus')))
        except (DBusException, AttributeError):
            # try to reacquire the bus connection
            if not self.fix():
                logging.critical('could not send action')
                return
        key.Action(dbus.Int32(action))  # https://github.com/popcornmix/omxplayer/blob/master/KeyConfig.h


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
