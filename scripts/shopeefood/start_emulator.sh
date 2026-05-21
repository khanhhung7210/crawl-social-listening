#!/bin/bash
# Start Android emulator for ShopeeFood crawling

if [ -z "$ANDROID_HOME" ]; then
    echo "❌ ANDROID_HOME not set"
    echo "Add to ~/.zshrc or ~/.bashrc:"
    echo "  export ANDROID_HOME=\$HOME/Library/Android/sdk"
    echo "  export PATH=\$PATH:\$ANDROID_HOME/emulator:\$ANDROID_HOME/platform-tools"
    exit 1
fi

AVD_NAME="Pixel_6_Pro_API_34"

echo "📱 Starting Android emulator: $AVD_NAME"
echo ""

# Check if emulator is already running
RUNNING=$(adb devices | grep emulator | wc -l)
if [ "$RUNNING" -gt 0 ]; then
    echo "⚠️  Emulator already running:"
    adb devices
    echo ""
    echo "To restart, kill it first: adb emu kill"
    exit 0
fi

# Start emulator in background
$ANDROID_HOME/emulator/emulator -avd $AVD_NAME &

echo "⏳ Waiting for emulator to start..."
adb wait-for-device

echo ""
echo "✅ Emulator started!"
adb devices

echo ""
echo "💡 Next steps:"
echo "  1. Wait for emulator to fully boot (~30 seconds)"
echo "  2. Install ShopeeFood if not installed:"
echo "     adb install ShopeeFood.apk"
echo "  3. Login to ShopeeFood in emulator"
echo "  4. Start Appium server:"
echo "     appium --allow-cors"
echo "  5. Test connection:"
echo "     python3 scripts/shopeefood/test_appium_connection.py"
echo ""
