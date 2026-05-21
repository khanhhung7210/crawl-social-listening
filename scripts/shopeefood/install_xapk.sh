#!/bin/bash
# Extract and install XAPK/APKC file

if [ $# -eq 0 ]; then
    echo "Usage: ./install_xapk.sh <path-to-xapk-or-apkc-file>"
    echo ""
    echo "Example:"
    echo "  ./install_xapk.sh ~/Downloads/ShopeeFood*.apkc"
    exit 1
fi

XAPK_FILE="$1"

if [ ! -f "$XAPK_FILE" ]; then
    echo "❌ File not found: $XAPK_FILE"
    exit 1
fi

echo "📦 Extracting XAPK/APKC file..."
TEMP_DIR="/tmp/xapk_extracted_$$"
mkdir -p "$TEMP_DIR"

# XAPK/APKC are ZIP files
unzip -q "$XAPK_FILE" -d "$TEMP_DIR"

if [ $? -ne 0 ]; then
    echo "❌ Failed to extract XAPK"
    rm -rf "$TEMP_DIR"
    exit 1
fi

echo "✅ Extracted successfully"
echo ""

# Find base APK
BASE_APK=$(find "$TEMP_DIR" -name "base.apk" -o -name "*.apk" | head -1)

if [ -z "$BASE_APK" ]; then
    echo "❌ No APK found inside XAPK"
    rm -rf "$TEMP_DIR"
    exit 1
fi

echo "📱 Installing APK: $(basename $BASE_APK)"
adb install "$BASE_APK"

if [ $? -eq 0 ]; then
    echo "✅ Installation successful!"
else
    echo "❌ Installation failed"
    rm -rf "$TEMP_DIR"
    exit 1
fi

# Install split APKs if any
SPLIT_APKS=$(find "$TEMP_DIR" -name "split_*.apk")
if [ -n "$SPLIT_APKS" ]; then
    echo ""
    echo "📦 Installing split APKs..."
    for apk in $SPLIT_APKS; do
        echo "  Installing $(basename $apk)..."
        adb install-multiple "$BASE_APK" "$apk"
    done
fi

# Cleanup
rm -rf "$TEMP_DIR"

echo ""
echo "🎉 ShopeeFood installed!"
echo ""
echo "Verify:"
echo "  adb shell pm list packages | grep foody"
