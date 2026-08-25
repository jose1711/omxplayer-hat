# omxplayer-hat

Control OMXPlayer using joystick + buttons of a 1.44" LCD Display Module (https://www.waveshare.com/Pico-LCD-1.44.htm). 
Note that the LCD backlight is turned off whenever nothing is playing, to conserve power. While a video is
playing it shows a live "now playing" dashboard: title, elapsed/remaining time with a progress bar, current
time of day and wifi status (signal-strength icon + IP). The rest of the time it lights up briefly to show:
  - current IP address (when being assigned by DHCP)
  - startup help (key - action assignment)
  - system shutdown/reboot

`omxplayer-hat.py` owns the display for as long as it runs (it's a boot-time service), driving it through
`lcd_display.py`. The one-off scripts (`write_lcd.py`, `lcd_splash.py`, the dhcpcd IP hook, `rc.local`/
`rc.shutdown`) hand their message to that running daemon over a local socket, so the SPI bus is never
touched by two processes at once; they only fall back to drawing directly if the daemon isn't up yet
(e.g. very early boot or after shutdown has already stopped it).

## Instructions

* get at least a 16GB microSD card and make sure it is empty (or contains data you no longer need)
* download the latest `void-rpi-*.img.xz` from https://repo-default.voidlinux.org/live/current/
  * for Pi Zero W use `void-rpi-armv6l`. For other models refer to https://docs.voidlinux.org/installation/guides/arm-devices/raspberry-pi.html#supported-models. Make sure to use glibc version (not musl).
* use Rpi-Imager to write the image to the SD card
* mount the 2nd partition on /mnt
  ```
  mount /dev/sdX2 /mnt
  cd /mnt
  ```

* edit `etc/wpa_supplicant/wpa_supplicant.conf` add the following section
  ```
  network={
   scan_ssid=1
   ssid="MyNetwork"
   psk="MyPassword"
  }
  ```
  you can add multiple network blocks.

* create the following symlink to make wpa supplicant start automatically
  ```
  ln -s /etc/sv/wpa_supplicant etc/runit/runsvdir/default
  ```

* umount the SD card, insert it into the Raspberry Pi and boot it.

* login as `root` with password `voidlinux`, change the password immediately

* perform the system update
  ```
  xbps-install -S
  xbps-install -yu xbps
  xbps-install -Suy
  ```

* configure timezone
  ```
  ln -sf /usr/share/zoneinfo/<timezone> /etc/localtime
  ```

* reboot the system
* install git
  ```
  xbps-install -y git
  ```
* clone this repository
  ```
  git clone https://github.com/jose1711/omxplayer-hat
  cd omxplayer-hat/
  ```

* edit `deploy.sh` - set username based on your preference
* run `deploy.sh`
  ```
  cd omxplayer-hat
  ./deploy.sh
  # type new password for user when prompted
  ```
* set password for user set in `deploy.sh`
* prohibit `root` login via SSH
  ```
  # login via ssh
  sudo su -
  sed -i '/PermitRootLogin/d' /etc/ssh/sshd_config
  echo 'PermitRootLogin no' >> /etc/ssh/sshd_config
  sv restart sshd
  ```
* reboot one last time

## License

`LCD_1in44.py` and `LCD_Config.py` use a custom license from Waveshare (code was slightly modified
to improve performance) and everything else here is under GPL-v3.

## Manual compilation

If you do not trust built packages in `repo/`, you may want to compile them manually - see `build/` which
contains files to help you with this task. https://github.com/void-linux/void-packages#quick-start is a nice
starting point.
