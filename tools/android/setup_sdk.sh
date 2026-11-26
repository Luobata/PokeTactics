#!/usr/bin/env bash
# Install what tools/android/build.sh needs into the user's home (no sudo), docs/73:
#   JDK 17 (Temurin)        ~/.local/share/jdk/jdk-17*
#   Android SDK             ~/.local/share/android-sdk  (cmdline-tools, platform-tools,
#                           build-tools 36.0.0, platforms;android-36)
# Idempotent; skips whatever is already there.
set -euo pipefail
SDK=${ANDROID_HOME:-$HOME/.local/share/android-sdk}
JDK_ROOT=$HOME/.local/share/jdk
CMDLINE_ZIP=${CMDLINE_ZIP:-commandlinetools-linux-16111833_latest.zip}
dl=$(mktemp -d)
trap 'rm -rf "$dl"' EXIT

if ! ls -d "$JDK_ROOT"/jdk-17* >/dev/null 2>&1; then
  mkdir -p "$JDK_ROOT"
  curl -fsSL -o "$dl/jdk.tar.gz" https://api.adoptium.net/v3/binary/latest/17/ga/linux/x64/jdk/hotspot/normal/eclipse
  tar -xzf "$dl/jdk.tar.gz" -C "$JDK_ROOT"
fi
JAVA_HOME=$(ls -d "$JDK_ROOT"/jdk-17* | sort -V | tail -1)
export JAVA_HOME

if [ ! -x "$SDK/cmdline-tools/latest/bin/sdkmanager" ]; then
  mkdir -p "$SDK/cmdline-tools"
  curl -fsSL -o "$dl/cmdline.zip" "https://dl.google.com/android/repository/$CMDLINE_ZIP"
  unzip -q "$dl/cmdline.zip" -d "$dl/x"
  rm -rf "$SDK/cmdline-tools/latest"
  mv "$dl/x/cmdline-tools" "$SDK/cmdline-tools/latest"
fi
yes | "$SDK/cmdline-tools/latest/bin/sdkmanager" --sdk_root="$SDK" --licenses >/dev/null || true
"$SDK/cmdline-tools/latest/bin/sdkmanager" --sdk_root="$SDK" \
  "platform-tools" "build-tools;36.0.0" "platforms;android-36" >/dev/null
echo "JAVA_HOME=$JAVA_HOME"
echo "ANDROID_HOME=$SDK"
