#!/bin/bash
# يبني "My Laptop - لابتوبي.app" + ملف DMG للتوزيع.   الاستخدام:  ./build_mac.sh
# متغيرات اختيارية:
#   VERSION=1.0.0            رقم الإصدار
#   PYTHON=مسار              نسخة Python (يلزم 3.10.1 أو أحدث، يُفضّل 3.12)
#   TARGET_ARCH=universal2   لدعم Apple Silicon وIntel معاً (يتطلب Python من python.org نسخة universal2)
#   SIGN_ID="Developer ID Application: Name (TEAMID)"   توقيع رسمي (يتطلب حساب Apple Developer)
#   NOTARY_PROFILE=اسم      ملف اعتماد notarytool المحفوظ في keychain (للتوثيق عند Apple)
set -euo pipefail
cd "$(dirname "$0")"
APP="MyLaptop"                    # اسم داخلي بحروف لاتينية (أسلم للأدوات)
SHOW="My Laptop - لابتوبي"        # الاسم الظاهر للمستخدم
VERSION="${VERSION:-1.0.0}"
PY="${PYTHON:-python3}"

if ! $PY -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10, 1) else 1)'; then
  echo "✗ نسخة Python الحالية ($($PY --version 2>&1)) قديمة وفيها خلل يكسر PyInstaller."
  echo "  ثبّت Python 3.12 أو أحدث من python.org ثم شغّل:"
  echo "  PYTHON=/Library/Frameworks/Python.framework/Versions/3.12/bin/python3.12 ./build_mac.sh"
  exit 1
fi

echo "→ تجهيز بيئة البناء"
rm -rf .buildenv
$PY -m venv .buildenv
# shellcheck disable=SC1091
source .buildenv/bin/activate
pip install --quiet --upgrade pip
pip install --quiet pywebview pyinstaller pillow

echo "→ توليد الأيقونة"
python make_icon.py

echo "→ بناء التطبيق"
rm -rf build dist *.spec
EXTRA=()
[ -n "${TARGET_ARCH:-}" ] && EXTRA+=(--target-arch "$TARGET_ARCH")
pyinstaller --noconfirm --windowed --name "$APP" --icon icon.icns \
  --osx-bundle-identifier com.mylaptop.app \
  --collect-submodules webview \
  ${EXTRA[@]+"${EXTRA[@]}"} mac_specs.py

PLIST="dist/$APP.app/Contents/Info.plist"
setp() {
  /usr/libexec/PlistBuddy -c "Set :$1 \"$2\"" "$PLIST" 2>/dev/null \
    || /usr/libexec/PlistBuddy -c "Add :$1 string \"$2\"" "$PLIST"
}
setp CFBundleShortVersionString "$VERSION"
setp CFBundleName "$SHOW"
setp CFBundleDisplayName "$SHOW"
mv "dist/$APP.app" "dist/$SHOW.app"

echo "→ التوقيع"
if [ -n "${SIGN_ID:-}" ]; then
  codesign --force --deep --options runtime --timestamp --sign "$SIGN_ID" "dist/$SHOW.app"
else
  codesign --force --deep --sign - "dist/$SHOW.app"      # توقيع محلي (ad-hoc)
fi

echo "→ إنشاء DMG"
mkdir -p dist/dmg
cp -R "dist/$SHOW.app" dist/dmg/
ln -sf /Applications dist/dmg/Applications
DMG="dist/My-Laptop-$VERSION.dmg"
hdiutil create -volname "$SHOW" -srcfolder dist/dmg -ov -format UDZO "$DMG" >/dev/null
rm -rf dist/dmg

if [ -n "${SIGN_ID:-}" ] && [ -n "${NOTARY_PROFILE:-}" ]; then
  echo "→ التوثيق لدى Apple (notarization)"
  codesign --sign "$SIGN_ID" --timestamp "$DMG"
  xcrun notarytool submit "$DMG" --keychain-profile "$NOTARY_PROFILE" --wait
  xcrun stapler staple "$DMG"
fi

echo "✅ جاهز: $DMG"
