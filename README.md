# My Laptop - لابتوبي

اسأل عن مواصفات جهازك بأي لغة — يعمل محلياً بالكامل، لا حساب ولا اشتراك ولا إرسال بيانات.
Ask about your Mac's specs in any language — 100% local, no account, no subscription, no data leaves your Mac.

**ماذا يعرض؟ / What it shows:** فحص للشراء والبيع (قفل التنشيط، MDM، صحة البطارية والتخزين)، الجهاز، المعالج، الرام، GPU، الشاشة، التخزين، macOS، البطارية (الدورات، الحالة، السعة)، والتطبيقات الأكثر استهلاكاً.

## التثبيت / Install
1. نزّل `My-Laptop-x.y.z.dmg` من صفحة Releases وافتحه، ثم اسحب **My Laptop - لابتوبي** إلى Applications.
2. أول تشغيل (إن لم يكن التطبيق موثّقاً من Apple): انقر بالزر الأيمن على التطبيق ← **Open** ← Open.
   إذا ظهرت رسالة «damaged»: `xattr -cr "/Applications/My Laptop - لابتوبي.app"` في Terminal.
3. **الذكاء المحلي (اختياري):** عند أول تشغيل يسألك التطبيق إن كنت تريد تفعيله. عند الموافقة يُحمَّل
   [Ollama](https://ollama.com) ونموذج صغير (≈1GB) مرة واحدة. بدون ذلك يعمل التطبيق بفهم الكلمات المفتاحية.

## الخصوصية / Privacy
كل القراءة تتم على جهازك عبر أدوات macOS (system_profiler, ioreg, pmset, ps). لا شيء يُرسل إلى أي خادم.
الاتصال بالإنترنت يحدث فقط عند تحميل Ollama والنموذج بموافقتك.

## البناء من المصدر / Build
```
./build_mac.sh                      # ينتج dist/My-Laptop-1.0.0.dmg
TARGET_ARCH=universal2 ./build_mac.sh   # Apple Silicon + Intel
```
تشغيل مباشر بدون بناء: `pip3 install pywebview && python3 mac_specs.py`
