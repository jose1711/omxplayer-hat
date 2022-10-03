#!/bin/bash
# set -x
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

groupadd gpio
usermod -a -G video $user
usermod -a -G gpio $user

chsh -s /bin/bash root
chsh -s /bin/bash "${user}"

install -o "${user}" -m755 -d /home/${user}/videos
ln -sf /media /home/${user}/videos/media

# install prerequisites
xbps-install -yu tmux \
                 omxplayer \
                 vifm \
								 udevil \
                 vim \
                 python3-Pillow \
                 python3-RPi.GPIO \
                 python3-pip \
                 python3-devel \
                 gcc \
                 terminus-font

# install spidev from pip
su - "${user}" -c 'pip3 install spidev'

# enable SPI interface
grep -q '^dtparam=spi=on' /boot/config.txt || {
  echo dtparam=spi=on >> /boot/config.txt
}

# configure autologin
# (https://dudik.github.io/posts/void-linux-agetty-login-without-username-just-password.html)
cp -R /etc/sv/agetty-tty1 /etc/sv/agetty-autologin-tty1
cat > /etc/sv/agetty-autologin-tty1/conf <<HERE
GETTY_ARGS="--autologin ${user} --noclear"
BAUD_RATE=38400
TERM_NAME=linux
HERE
rm /var/service/agetty-tty1 2>/dev/null
ln -sf /etc/sv/agetty-autologin-tty1 /var/service

# copy system files
install -Dm644 dist/raspberrypi.rules /etc/udev/rules.d/raspberrypi.rules
install -Dm755 dist/40-show_ip /usr/libexec/dhcpcd-hooks/40-show_ip

# copy user files
install -o "${user}" -Dm755 dist/.bashrc /home/${user}/.bashrc
install -o "${user}" -Dm644 dist/vifmrc /home/${user}/.vifm/vifmrc
install -o "${user}" -Dm755 dist/service-run /home/${user}/service/omxplayer-hat/run
install -o "${user}" -d /home/${user}/service/omxplayer-hat
install -o "${user}" -d /home/${user}/vifm
install -o "${user}" -Dm755 dist/omxplayer.sh /home/${user}/bin/omxplayer.sh
install -o "${user}" -Dm755 dist/omxplayer-hat.py /home/${user}/bin/omxplayer-hat.py
install -o "${user}" -Dm755 dist/mount_all.sh /home/${user}/bin/mount_all.sh
install -o "${user}" -Dm755 dist/LCD_1in44.py /home/${user}/bin/LCD_1in44.py
install -o "${user}" -Dm755 dist/LCD_Config.py /home/${user}/bin/LCD_Config.py
install -o "${user}" -Dm755 dist/write_lcd.py /home/${user}/bin/write_lcd.py
install -o "${user}" -Dm755 dist/show_help.sh /home/${user}/bin/show_help.sh

# replace placeholder with string
sed -i "s/{{user}}/${user}/g" /home/${user}/bin/mount_all.sh \
                              /usr/libexec/dhcpcd-hooks/40-show_ip

# add sudoers entry
cat >/etc/sudoers.d/${user}_nopasswd <<HERE
${user} ALL=(ALL:ALL) NOPASSWD: ALL
HERE

grep -q bin/mount_all.sh /etc/rc.local || {
  echo "~${user}/bin/mount_all.sh" >> /etc/rc.local
}

grep -q bin/show_help.sh /etc/rc.local || {
  echo "su ${user} -c '~/bin/show_help.sh' &" >> /etc/rc.local
}

# configure per-user services
# https://docs.voidlinux.org/config/services/user-services.html
install -Dm755 dist/run /etc/sv/runsvdir-${user}/run
sed -i "s/{{user}}/${user}/" /etc/sv/runsvdir-${user}/run
ln -sf "/etc/sv/runsvdir-${user}" /var/service

# set terminal font
sed -i 's/^ *FONT=.*/FONT=ter-u32n/' /etc/rc.conf
egrep -q '^ *FONT=ter-u32n' /etc/rc.conf || {
  echo 'FONT=ter-u32n' >> /etc/rc.conf
}

egrep -q "write_lcd.py 'SHUTTING DOWN'" /etc/rc.shutdown || {
  cat >> /etc/rc.shutdown <<HERE
su - ${user} -c "~/bin/write_lcd.py 'SHUTTING DOWN'"
HERE
}

# clear package cache 
xbps-remove -Oo

# disable fsck on boot
sed -i '/^[[:space:]]*[^#]/s/\(.*\)[[:space:]][[:space:]]*[0-9][0-9]*[[:space:]][[:space:]]*[0-9][0-9]*/\1 0 0/' /etc/fstab
