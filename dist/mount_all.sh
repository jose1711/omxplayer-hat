#!/bin/sh
# mount all partitions on sda device
udevil clean
lsblk -l | awk '$1 ~ /^sda[0-9]/{printf "/dev/%s\n", $1}' | while read i
do
  su - {{user}} -c "udevil mount $i"
done
