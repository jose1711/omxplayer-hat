#!/bin/bash
# Build omxplayer and rpi-userland(-devel) from the templates in build/srcpkgs
# using a void-packages checkout.
#
# usage: build/build.sh [-a ARCH] [-d DIR] [-r]
#   -a ARCH  cross-compile for ARCH (e.g. armv6l); default is a native build
#   -d DIR   void-packages checkout to use, cloned if missing
#            (default: void-packages next to this repository)
#   -r       copy the built packages into repo/ and regenerate its index
#            (needs xbps-rindex on the host)
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
top="$(dirname "${here}")"
vp="$(dirname "${top}")/void-packages"
arch=""
update_repo=0

while getopts "a:d:r" opt
do
  case "${opt}" in
    a) arch="${OPTARG}" ;;
    d) vp="${OPTARG}" ;;
    r) update_repo=1 ;;
    *) sed -n '5,10p' "$0"; exit 1 ;;
  esac
done

[ -d "${vp}" ] || git clone --depth 1 https://github.com/void-linux/void-packages.git "${vp}"
cd "${vp}"

# upstream has omxplayer and rpi-userland as symlinks to other packages
# (vlc, rpi-utils), so replace them with our templates
for pkg in omxplayer rpi-userland rpi-userland-devel
do
  rm -rf "srcpkgs/${pkg}"
  cp -a "${here}/srcpkgs/${pkg}" srcpkgs/
done

# register shlibs provided by rpi-userland (skipping those already present)
while read -r line
do
  grep -qxF "${line}" common/shlibs || echo "${line}" >> common/shlibs
done < "${here}/common/shlibs"

compgen -G 'masterdir*/' >/dev/null || ./xbps-src binary-bootstrap

./xbps-src ${arch:+-a "${arch}"} pkg omxplayer

echo "Built packages are in ${vp}/hostdir/binpkgs"

if [ "${update_repo}" -eq 1 ]
then
  target="${arch:-$(xbps-uhelper arch)}"
  for pkg in omxplayer rpi-userland rpi-userland-devel
  do
    version="$(./xbps-src show "${pkg}" | sed -n 's/^version:\s*//p')"
    revision="$(./xbps-src show "${pkg}" | sed -n 's/^revision:\s*//p')"
    cp "hostdir/binpkgs/${pkg}-${version}_${revision}.${target}.xbps" "${top}/repo/"
  done
  export XBPS_TARGET_ARCH="${target}"
  # -f: a rebuild with unchanged version/revision must still replace the
  # index entry, or its sha256 no longer matches the file
  xbps-rindex -f -a "${top}"/repo/*."${target}".xbps
  # drop superseded versions from the index and from disk
  xbps-rindex -r "${top}/repo"
fi
