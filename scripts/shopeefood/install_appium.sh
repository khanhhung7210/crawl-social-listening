#!/bin/bash
# Install Appium and dependencies for ShopeeFood Android crawling

set -e

echo "========================================="
echo "  ShopeeFood Appium Setup"
echo "========================================="
echo ""

# Check Node.js
if ! command -v node &> /dev/null; then
    echo "❌ Node.js not found"
    echo "Install Node.js first: brew install node"
    exit 1
fi

echo "✅ Node.js version: $(node --version)"
echo ""

# Check npm
if ! command -v npm &> /dev/null; then
    echo "❌ npm not found"
    exit 1
fi

echo "✅ npm version: $(npm --version)"
echo ""

# Check Android SDK
if [ -z "$ANDROID_HOME" ]; then
    echo "❌ ANDROID_HOME not set"
    echo "Add to ~/.zshrc or ~/.bashrc:"
    echo "  export ANDROID_HOME=\$HOME/Library/Android/sdk"
    echo "  export PATH=\$PATH:\$ANDROID_HOME/emulator:\$ANDROID_HOME/platform-tools"
    exit 1
fi

echo "✅ ANDROID_HOME: $ANDROID_HOME"
echo ""

# Check adb
if ! command -v adb &> /dev/null; then
    echo "❌ adb not found"
    echo "Make sure ANDROID_HOME/platform-tools is in PATH"
    exit 1
fi

echo "✅ adb version: $(adb version | head -1)"
echo ""

# Install Appium globally
echo "📦 Installing Appium..."
npm install -g appium

if [ $? -ne 0 ]; then
    echo "❌ Appium installation failed"
    exit 1
fi

echo "✅ Appium installed"
echo ""

# Install UiAutomator2 driver
echo "📦 Installing UiAutomator2 driver..."
appium driver install uiautomator2

if [ $? -ne 0 ]; then
    echo "❌ UiAutomator2 driver installation failed"
    exit 1
fi

echo "✅ UiAutomator2 driver installed"
echo ""

# Install Appium Python client
echo "📦 Installing Appium-Python-Client..."
pip3 install Appium-Python-Client

if [ $? -ne 0 ]; then
    echo "❌ Appium-Python-Client installation failed"
    exit 1
fi

echo "✅ Appium-Python-Client installed"
echo ""

# Verify installation
echo "🔍 Verifying installation..."
echo ""

echo "Appium version:"
appium --version

echo ""
echo "Installed drivers:"
appium driver list

echo ""
echo "Python packages:"
pip3 list | grep -i appium

echo ""
echo "========================================="
echo "  ✅ Installation Complete!"
echo "========================================="
echo ""
echo "Next steps:"
echo "  1. Start Android emulator:"
echo "     \$ANDROID_HOME/emulator/emulator -avd Pixel_6_Pro_API_34 &"
echo ""
echo "  2. Install ShopeeFood app:"
echo "     adb install ShopeeFood.apk"
echo ""
echo "  3. Login to ShopeeFood in emulator"
echo ""
echo "  4. Start Appium server:"
echo "     appium --allow-cors"
echo ""
echo "  5. Test connection:"
echo "     python3 scripts/shopeefood/test_appium_connection.py"
echo ""
