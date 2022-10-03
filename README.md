# omxplayer-hat

Control OMXPlayer using joystick + buttons of a 1.44" LCD Display Module (https://www.waveshare.com/Pico-LCD-1.44.htm). 
Note that LCD screen is turned off most of the time to conserve power. It is only used to indicate:
  - current IP address (when being assigned by DHCP)
  - startup help (key - action assignment)
  - system shutdown

## Instructions

* get at least a 16GB microSD card and make sure it is empty (or contains data you no longer need)
* download the latest `void-rpi-*.img.xz` from https://repo-default.voidlinux.org/live/current/
* follow Installation section of Void Handbook (https://docs.voidlinux.org/installation/index.html)
* boot system (default password for `root` is `voidlinux`) and change the password using `passwd` command
  * configure timezone
  ```
  ln -sf /usr/share/zoneinfo/<timezone> /etc/localtime
  ```
* (optional) configure network as per https://docs.voidlinux.org/config/network/index.html
  ```
  ip link
  # wlan adapter name shows up at wlan0 hence we'll use it in the command below
  wpa_passphrase 'MYSSID' 'MYPASS' >> /etc/wpa_supplicant/wpa_supplicant-wlan0.conf
  ln -s /etc/sv/wpa_supplicant /etc/runit/runsvdir/default/
  # wait a minute
  ip a
  # ip address should appear and device should also be available through SSH
  ```
* perform a system update
  ```
  xbps-install -yu xbps
  xbps-install -Suy
  ```
* reboot
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
* shutdown, remove SD card and expand partition using GParted, then reinsert into Pi and boot it again
* prohibit `root` login via SSH
  ```
  # login via ssh
  sudo su -
  sed -i '/PermitRootLogin/d' /etc/ssh/sshd_config
  echo 'PermitRootLogin no' >> /etc/ssh/sshd_config
  sv restart sshd
  ```

## License

`LCD_1in44.py` and `LCD_Config.py` use a custom license from Waveshare (code was slightly modified
to improve performance) and everything else here is under GPL-v3.
