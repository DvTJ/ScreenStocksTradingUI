#!/bin/sh
# Lets the Linux build keep Qt WebEngine's sandbox where AppArmor restricts unprivileged user namespaces
# (Ubuntu 23.10 and newer). Without it the app runs its web view unsandboxed there.
#   sudo ./install-apparmor-profile.sh            (from the unpacked ScreenStocksTradingBot folder)
#   sudo ./install-apparmor-profile.sh --remove
# Run it again after moving the folder: the profile names the executables by path.
set -e

name=screenstocks-trading-bot
profile=/etc/apparmor.d/$name

if [ "$1" = "--remove" ]; then
    if [ -f "$profile" ]; then
        apparmor_parser -R "$profile" || true
        rm -f "$profile"
    fi
    echo "AppArmor profile $name removed"
    exit 0
fi

if [ "$(cat /proc/sys/kernel/apparmor_restrict_unprivileged_userns 2>/dev/null)" != "1" ]; then
    echo "This system does not restrict user namespaces - nothing to do."
    exit 0
fi
if [ "$(id -u)" != "0" ]; then
    echo "Run it with sudo: sudo $0" >&2
    exit 1
fi

dir=$(cd "$(dirname "$0")" && pwd)
app="$dir/ScreenStocksTradingBot"
engine=$(find "$dir" -name QtWebEngineProcess -type f | head -n 1)
if [ ! -x "$app" ] || [ -z "$engine" ]; then
    echo "Run this script from the unpacked ScreenStocksTradingBot folder ($app or QtWebEngineProcess not found)." >&2
    exit 1
fi

cat > "$profile" <<EOF
# ScreenStocks Trading Bot: allow the user namespaces Qt WebEngine's sandbox needs (written by $0)
abi <abi/4.0>,
include <tunables/global>

profile $name "$app" flags=(unconfined) {
  userns,
  include if exists <local/$name>
}

profile $name-webengine "$engine" flags=(unconfined) {
  userns,
  include if exists <local/$name-webengine>
}
EOF
apparmor_parser -r "$profile"
echo "AppArmor profile $name installed for $app"
