#!/bin/bash
# set -x
set -euo pipefail
user="CONFIGUREME"

if [ $(id -u) -ne 0 ]
then
  echo "Rerun the script as root"
  exit 1
fi

if [ "${user}" = "CONFIGUREME" ]
then
  echo "Be sure to edit deploy.sh - modify user variable, then rerun"
  exit 1 
fi

# create user if it does not exist already
getent passwd "${user}" >/dev/null 2>&1 || {
  useradd -m "${user}"
  passwd "${user}"
}

getent group gpio >/dev/null 2>&1 || groupadd gpio
usermod -a -G video $user
usermod -a -G gpio $user

chsh -s /bin/bash root
chsh -s /bin/bash "${user}"

install -o "${user}" -m755 -d /home/${user}/videos
ln -sf /run/media/${user} /home/${user}/videos/media

# install prerequisites
xbps-install -Syu tmux \
             vifm \
             udevil \
             vim \
             iw \
             dejavu-fonts-ttf \
             python3-Pillow \
             python3-pip \
             make \
             python3-dbus \
             unzip \
             python3-setuptools \
             swig \
             wget \
             python3-devel \
             gcc \
             htop \
             swig \
             terminus-font

# copy udevil configuration
install -Dm644 dist/udevil.conf /etc/udevil/udevil.conf

[ -f lg.zip ] || wget http://abyz.me.uk/lg/lg.zip
unzip -o lg.zip
pushd lg
make
sudo make install
popd

# install spidev and rpi-lgpio (drop-in RPi.GPIO replacement) from pip into a venv
# (Pillow comes from xbps via --system-site-packages)
su - "${user}" -c 'python3 -m venv --system-site-packages ~/.venv && ~/.venv/bin/pip install spidev rpi-lgpio'

# enable SPI interface
grep -q '^dtparam=spi=on' /boot/config.txt || {
  echo dtparam=spi=on >> /boot/config.txt
}

# disable KMS
grep -q '^dtoverlay=vc4-kms-v3d' /boot/config.txt && {
  sed -i 's/dtoverlay=vc4-kms-v3d/#&/' /boot/config.txt
}

# configure autologin
# (https://dudik.github.io/posts/void-linux-agetty-login-without-username-just-password.html)
[ -d /etc/sv/agetty-autologin-tty1 ] || cp -R /etc/sv/agetty-tty1 /etc/sv/agetty-autologin-tty1
cat > /etc/sv/agetty-autologin-tty1/conf <<HERE
GETTY_ARGS="--autologin ${user} --noclear"
BAUD_RATE=38400
TERM_NAME=linux
HERE
rm -f /var/service/agetty-tty1
ln -sf /etc/sv/agetty-autologin-tty1 /var/service

# copy system files
install -Dm644 dist/raspberrypi.rules /etc/udev/rules.d/raspberrypi.rules
install -Dm755 dist/40-show_ip /usr/libexec/dhcpcd-hooks/40-show_ip

# copy user files
install -o "${user}" -Dm755 dist/.bashrc /home/${user}/.bashrc
install -o "${user}" -Dm644 dist/vifmrc /home/${user}/.vifm/vifmrc
install -o "${user}" -d /home/${user}/service/omxplayer-hat
install -o "${user}" -Dm755 dist/service-run /home/${user}/service/omxplayer-hat/run
install -o "${user}" -Dm755 dist/omxplayer.sh /home/${user}/bin/omxplayer.sh
install -o "${user}" -Dm755 dist/omxplayer-hat.py /home/${user}/bin/omxplayer-hat.py
install -o "${user}" -Dm755 dist/mount_all.sh /home/${user}/bin/mount_all.sh
install -o "${user}" -Dm755 dist/LCD_1in44.py /home/${user}/bin/LCD_1in44.py
install -o "${user}" -Dm755 dist/LCD_Config.py /home/${user}/bin/LCD_Config.py
install -o "${user}" -Dm755 dist/lcd_client.py /home/${user}/bin/lcd_client.py
install -o "${user}" -Dm755 dist/lcd_display.py /home/${user}/bin/lcd_display.py
install -o "${user}" -Dm755 dist/write_lcd.py /home/${user}/bin/write_lcd.py
install -o "${user}" -Dm755 dist/lcd_splash.py /home/${user}/bin/lcd_splash.py
install -o "${user}" -Dm755 dist/show_help.sh /home/${user}/bin/show_help.sh
chown "${user}" /home/${user} /home/${user}/.vifm
chown "${user}" /home/${user}/bin

# make services work with read-only /
ln -sf "/run/runit/supervise.omxplayer-hat" "/home/${user}/service/omxplayer-hat/supervise"

grep -q '^mkdir /run/runit/supervise.omxplayer-hat' /etc/runit/core-services/03-filesystems.sh || {
sed -i '/^msg "Mounting rootfs read-write/i \
mkdir /run/runit/supervise.omxplayer-hat && chown '"${user}"' /run/runit/supervise.omxplayer-hat' \
      /etc/runit/core-services/03-filesystems.sh; }

# leave "/" mounted as read-only
# sed -i 's%mount -o remount,rw /%mount -o remount,ro /%' /etc/runit/core-services/03-filesystems.sh

# replace placeholder with string
sed -i "s/{{user}}/${user}/g" /home/${user}/bin/mount_all.sh \
                              /home/${user}/bin/write_lcd.py \
                              /home/${user}/bin/lcd_splash.py \
                              /usr/libexec/dhcpcd-hooks/40-show_ip

# add sudoers entry
cat >/etc/sudoers.d/${user}_nopasswd <<HERE
${user} ALL=(ALL:ALL) NOPASSWD: ALL
HERE

grep -q bin/mount_all.sh /etc/rc.local || {
  echo "/home/${user}/bin/mount_all.sh" >> /etc/rc.local
}

grep -q bin/show_help.sh /etc/rc.local || {
  echo "su ${user} -c '/home/${user}/bin/lcd_splash.py boot 4 && /home/${user}/bin/show_help.sh' &" >> /etc/rc.local
}

# configure per-user services
# https://docs.voidlinux.org/config/services/user-services.html
install -Dm755 dist/run /etc/sv/runsvdir-${user}/run
sed -i "s/{{user}}/${user}/" /etc/sv/runsvdir-${user}/run
ln -sf "/run/runit/supervise.runsvdir-${user}" "/etc/sv/runsvdir-${user}/supervise"
ln -sf "/etc/sv/runsvdir-${user}" /var/service

# set terminal font
sed -i 's/^ *FONT=.*/FONT=ter-u32n/' /etc/rc.conf
grep -qE '^ *FONT=ter-u32n' /etc/rc.conf || {
  echo 'FONT=ter-u32n' >> /etc/rc.conf
}

grep -qE "lcd_splash.py shutdown" /etc/rc.shutdown || {
  cat >> /etc/rc.shutdown <<HERE
su - ${user} -c "~/bin/lcd_splash.py shutdown 6"
HERE
}

# install rpi-userland libraries and omxplayer
xbps-install -yR repo rpi-userland rpi-userland-devel omxplayer

# stick to the installed versions
xbps-pkgdb -m hold omxplayer rpi-userland rpi-userland-devel

# clear package cache 
xbps-remove -Oo

# disable fsck on boot
sed -i '/^[[:space:]]*[^#]/s/\(.*\)[[:space:]][[:space:]]*[0-9][0-9]*[[:space:]][[:space:]]*[0-9][0-9]*/\1 0 0/' /etc/fstab
