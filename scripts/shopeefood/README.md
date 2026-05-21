# ShopeeFood Android Crawler - Quick Start

## 🚀 Installation (One-time setup)

```bash
# Run install script
./scripts/shopeefood/install_appium.sh
```

This will install:
- Appium (Node.js package)
- UiAutomator2 driver (for Android)
- Appium-Python-Client

---

## 📱 Daily Usage

### Terminal 1: Start Emulator

```bash
./scripts/shopeefood/start_emulator.sh

# Or manually:
$ANDROID_HOME/emulator/emulator -avd Pixel_6_Pro_API_34 &
```

### Terminal 2: Start Appium Server

```bash
appium --allow-cors
```

### Terminal 3: Test Connection

```bash
python3 scripts/shopeefood/test_appium_connection.py
```

Should show:
```
✅ Connected successfully!
📲 Current activity: com.foody.vn/.ui.HomeActivity
📦 Current package: com.foody.vn
✅ Found 52 TextViews
```

### Terminal 4: Run Crawler

```bash
python3 scripts/shopeefood/shopeefood_review_crawler.py
```

---

## 🔧 Setup ShopeeFood App (One-time)

### Option A: Download APK

1. Download ShopeeFood APK từ [APKPure](https://apkpure.com/shopeefood/com.foody.vn)
2. Install:
   ```bash
   adb install ShopeeFood.apk
   ```

### Option B: Google Play Store

1. Trong emulator → Settings → Accounts
2. Add Google account
3. Open Play Store → Search "ShopeeFood" → Install

### Login ShopeeFood

1. Open ShopeeFood app trong emulator
2. Login với tài khoản của bạn
3. Grant permissions (location, storage, etc.)
4. Navigate đến 1 restaurant để verify app works

---

## 🔍 Finding Element IDs with Appium Inspector

### Install Appium Inspector

Download từ: https://github.com/appium/appium-inspector/releases

### Connect to Emulator

1. Start emulator + Appium server (như trên)
2. Open Appium Inspector
3. Configure connection:
   - **Remote Host:** `127.0.0.1`
   - **Remote Port:** `4723`
   - **Desired Capabilities:**
     ```json
     {
       "platformName": "Android",
       "appium:deviceName": "emulator-5554",
       "appium:appPackage": "com.foody.vn",
       "appium:appActivity": ".ui.HomeActivity",
       "appium:noReset": true,
       "appium:automationName": "UiAutomator2"
     }
     ```
4. Click **Start Session**

### Find Review Elements

1. Navigate to restaurant page with reviews in emulator
2. In Inspector, click refresh icon to capture UI
3. Click on review elements to see their properties:
   - `resource-id`: Best selector if available
   - `content-desc`: Alternative selector
   - `text`: Can use for matching
   - `class`: Last resort (e.g., `android.widget.TextView`)

### Update Crawler

Edit `scripts/shopeefood/shopeefood_review_crawler.py`:

```python
# Replace placeholder XPath with real values from Inspector
REVIEW_TEXT_XPATH = '//android.widget.TextView[@resource-id="com.foody.vn:id/review_text"]'
REVIEW_AUTHOR_XPATH = '//android.widget.TextView[@resource-id="com.foody.vn:id/author_name"]'
# etc.
```

---

## 🐛 Troubleshooting

### Emulator not starting

```bash
# List available emulators
$ANDROID_HOME/emulator/emulator -list-avds

# Cold boot (if stuck)
$ANDROID_HOME/emulator/emulator -avd Pixel_6_Pro_API_34 -no-snapshot-load
```

### ADB not detecting emulator

```bash
# Restart adb
adb kill-server
adb start-server
adb devices
```

### Appium connection failed

```bash
# Check Appium is running
lsof -i :4723

# Restart Appium
killall node
appium --allow-cors
```

### ShopeeFood app not found

```bash
# Check if installed
adb shell pm list packages | grep foody

# If not: install APK
adb install ShopeeFood.apk
```

### App crashes or requires login

```bash
# Clear app data and re-login
adb shell pm clear com.foody.vn

# Then open app in emulator and login again
```

---

## 📝 Workflow Summary

```bash
# Terminal 1: Emulator
./scripts/shopeefood/start_emulator.sh

# Terminal 2: Appium
appium --allow-cors

# Terminal 3: Crawler
python3 scripts/shopeefood/test_appium_connection.py  # Test first
python3 scripts/shopeefood/shopeefood_review_crawler.py  # Then crawl
```

---

## 📚 Documentation

- Full setup guide: `SHOPEEFOOD_ANDROID_SETUP.md`
- Appium docs: https://appium.io/docs/en/2.0/
- Python client: https://github.com/appium/python-client

---

## 💡 Tips

1. **Keep emulator running** - Faster for subsequent crawls
2. **Stay logged in** - Use `noReset: true` capability
3. **Use Appium Inspector** - Essential for finding correct selectors
4. **Test small first** - Crawl 1 restaurant before running all
5. **Monitor battery** - Emulator can drain MacBook battery

---

**Ready to start?**

```bash
# 1. Install
./scripts/shopeefood/install_appium.sh

# 2. Start emulator
./scripts/shopeefood/start_emulator.sh

# 3. Open ShopeeFood in emulator and login

# 4. Start Appium (new terminal)
appium --allow-cors

# 5. Test connection
python3 scripts/shopeefood/test_appium_connection.py
```
