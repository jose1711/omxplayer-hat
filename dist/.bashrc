# .bashrc

export SVDIR=~/service
export PATH=$PATH:~/.local/bin

# If not running interactively, don't do anything
[[ $- != *i* ]] && return

alias ls='ls --color=auto'
PS1='[\u@\h \W]\$ '


if [ $(tty) = /dev/tty1 ]
then
  while :
  do
    tmux new-session -s vifm vifm -c 'cd ~/videos'
  done
fi
