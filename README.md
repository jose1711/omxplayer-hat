# omxplayer-hat

Control OMXPlayer using joystick + buttons of a 1.44" LCD Display Module (https://www.waveshare.com/Pico-LCD-1.44.htm). 
Note that LCD screen is turned off most of the time to conserve power. It is only used to indicate:
  - current IP address (when being assigned by DHCP)
  - startup help (key - action assignment)
  - system shutdown

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
