# omxplayer-hat

Control OMXPlayer using joystick + buttons of a 1.44" LCD Display Module (https://www.waveshare.com/Pico-LCD-1.44.htm).
While a video is playing, the LCD shows a live "now playing" dashboard: title, elapsed/remaining time with a
progress bar, current time of day and wifi status (signal-strength icon + IP). Whenever nothing is playing, it
shows an idle screen instead (dimmed backlight): wifi status + IP address and a compact key-binding cheat
sheet, at a glance any time. A dedicated splash screen is shown briefly on boot and on shutdown/reboot.

`omxplayer-hat.py` owns the display for as long as it runs (it's a boot-time service), driving it through
`lcd_display.py`. The one-off scripts (`write_lcd.py`, `lcd_splash.py`, `rc.local`/`rc.shutdown`) hand their
message to that running daemon over a local socket, so the SPI bus is never touched by two processes at
once; they only fall back to drawing directly if the daemon isn't up yet (e.g. very early boot or after
shutdown has already stopped it).

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

## Changelog

### 2026-08-27

- Added a per-user `devmon` service (`~/service/devmon`) so USB drives plugged in after boot get
  automounted (under `/run/media/${user}`) without needing a reboot or a manual `mount_all.sh` run.
- Added `ntfs-3g` as a dependency: without it, `mount` falls back to the kernel's `ntfs3` driver,
  which doesn't understand the `utf8` option udevil passes, and NTFS drives failed to automount.
- Added a USB icon (the classic "trident" logo, sideways) to the LCD's wifi/IP status row,
  shown whenever a drive is mounted under `/run/media/${user}`.

### 2026-08-26

- Replaced the "backlight off while idle" behavior with an idle screen: wifi status + IP address
  and a compact key-binding cheat sheet, shown (at a dimmed backlight) any time nothing is playing.
- Removed the now-redundant one-off boot-time help text (`show_help.sh`) and the dhcpcd IP-address
  popup (`40-show_ip`), since the idle screen already shows both continuously.
- Fixed the LCD backlight sometimes staying lit after shutdown: the shutdown/reboot splash no
  longer expires back into the idle screen (which stays lit) once the machine is on its way down;
  the backlight is explicitly turned off and kept off instead.
- Fixed the JOY+KEY1/KEY2/KEY3 reboot/shutdown combos: both were checked independently, so a noisy
  read of the shutdown button while the reboot combo was held (or vice versa) would silently win
  and fire the wrong one; that case is now detected and ignored instead. JOY+KEY3 was an
  undocumented, unwanted alias for reboot — it's now, together with JOY+KEY2, a shutdown shortcut,
  leaving JOY+KEY1 as the only reboot shortcut.

### 2026-08-25

- LCD handling rewritten around a persistent `lcd_display.py`/`LcdManager` daemon owned by
  `omxplayer-hat.py`, replacing the old approach of spawning a fresh `write_lcd.py` process (and
  re-initializing the SPI/GPIO hardware) for every update.
- Added a live "now playing" dashboard shown on the LCD while a video plays: title, progress bar,
  elapsed/remaining time, current time of day, and a wifi signal-strength icon + IP address.
- Added vector splash screens (`lcd_splash.py`) for boot, shutdown and reboot.
- `write_lcd.py`/`lcd_splash.py` now forward requests to the running daemon over a local Unix
  socket (via the new lightweight `lcd_client.py`) and only draw directly on the hardware as a
  fallback when the daemon isn't reachable, so the SPI bus is never driven by two processes at once.
- Added immediate LCD feedback for every joystick/button press (seek amount, subtitle track,
  play/pause, quit, volume, subtitle delay) instead of waiting for the next dashboard refresh.
- Fixed the volume and subtitle-delay button actions, which were sending the wrong OMXPlayer
  DBus action codes (they were adjusting playback speed instead of volume, and doing nothing
  useful instead of adjusting subtitle delay).
