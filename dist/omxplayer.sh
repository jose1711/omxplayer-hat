#!/bin/bash
# playback file using omxplayer-dbus, will prompt user
# if a previously stored last playback position is found
#
# if subtitles are found in the same directory as the video file,
# player will be executed multiple times - each time with a different
# subtitle file

function seconds_hmc {
  hours=$(($1/3600))
  minutes=$(($1 % 3600 / 60))
  seconds=$(($1 % 60))
  echo $hours:$minutes:$seconds
}

function seconds_hmc_formatted {
  hours=$(($1/3600))
  minutes=$(($1 % 3600 / 60))
  seconds=$(($1 % 60))
  printf "%02d:%02d:%02d\n" $hours $minutes $seconds
}

file="$1"
shift
if [ -z "${file}" ]
then
  echo "Argument required"
  exit 1
fi
dbfile=~/positions.sqlite

cd $(dirname "${file}")
file_full=$(readlink -f "${file}")
stored_position=$(echo "select position from positions where name = \"${file_full}\"" | sqlite3 "${dbfile}")

EXTRAARG=""
if [ -n "${stored_position}" ]
then
  # resume or start from beginning?
  hms=$(seconds_hmc stored_position)
  hms_formatted=$(seconds_hmc_formatted stored_position)
  clear
  cat <<HERE

Found a stored playback position. What to do?

^  - start playback from beginning (default, autoselected in 5 seconds)
v  - start from last position (${hms_formatted})
HERE
  read -s -n1 -t5 -r ans
  if [ "${ans}" = "j" ]
  then
    EXTRAARG=" --pos ${hms}"
  fi
fi

for subs in *.srt *.sub
do
  omxplayer-dbus $EXTRAARG "$@" --subtitles "${subs}" "${file}"
done
omxplayer-dbus $EXTRAARG "$@" "${file}"
