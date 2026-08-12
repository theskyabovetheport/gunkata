#!/usr/bin/env bash
# Boots a local Android emulator so `pytest -m emulator` has a device to
# target. Installs the emulator package, a system image, and the AVD itself
# on first run -- all of that lands under $ANDROID_HOME, which the SDK
# install already owns, so no sudo is required. Leaves the emulator running
# in the background; run `adb -s <serial> emu kill` when done with it.
set -euo pipefail

ANDROID_HOME="${ANDROID_HOME:-$HOME/Android/Sdk}"
AVD_NAME="${GUNKATA_AVD_NAME:-gunkata}"
SYSTEM_IMAGE="${GUNKATA_SYSTEM_IMAGE:-system-images;android-34;google_apis;x86_64}"

SDKMANAGER="$ANDROID_HOME/cmdline-tools/latest/bin/sdkmanager"
AVDMANAGER="$ANDROID_HOME/cmdline-tools/latest/bin/avdmanager"
EMULATOR="$ANDROID_HOME/emulator/emulator"
ADB="$ANDROID_HOME/platform-tools/adb"

if [[ ! -x "$SDKMANAGER" ]]; then
    echo "sdkmanager not found at $SDKMANAGER -- install the Android cmdline-tools first" >&2
    exit 1
fi

echo "installing emulator + system image (skipped once already present)..."
# yes's write end closes the moment sdkmanager stops reading (all licenses
# already accepted, or none left to show); that's a SIGPIPE for yes, not a
# real failure, so it must not trip set -e via pipefail.
yes | "$SDKMANAGER" --licenses >/dev/null || true
"$SDKMANAGER" "emulator" "$SYSTEM_IMAGE" "platform-tools" >/dev/null

if [[ ! -d "$HOME/.android/avd/${AVD_NAME}.avd" ]]; then
    echo "creating AVD '$AVD_NAME'..."
    echo "no" | "$AVDMANAGER" create avd -n "$AVD_NAME" -k "$SYSTEM_IMAGE" --force
fi

echo "starting emulator '$AVD_NAME'..."
"$EMULATOR" -avd "$AVD_NAME" -no-window -no-audio -no-boot-anim >/tmp/gunkata-emulator.log 2>&1 &
disown

echo "waiting for the device to appear..."
"$ADB" wait-for-device

echo "waiting for boot to finish..."
until [[ "$("$ADB" shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')" == "1" ]]; do
    sleep 2
done

serial="$("$ADB" devices | awk 'NR==2 {print $1}')"
echo "emulator ready: $serial"
echo "run: uv run pytest -m emulator"
