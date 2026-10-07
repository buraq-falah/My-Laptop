#!/usr/bin/env python3
"""
My Laptop - لابتوبي — اسأل عن مواصفات جهازك بأي لغة.
يعمل محلياً 100%: بدون إنترنت، بدون API، بدون فواتير.
- الواجهة: نافذة أنيقة (pywebview إن وُجد، وإلا المتصفح).
- الفهم: كلمات مفتاحية بـ 16 لغة تقريباً.
- ذكاء محلي (اختياري): عند أول تشغيل يسأل المستخدم، وبعد موافقته يُنزّل Ollama + نموذج خفيف
  للأسئلة التي لا تفهمها الكلمات المفتاحية. لتعطيله تماماً: python3 mac_specs.py --no-ai
"""
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# ------------------------------------------------------------------ جمع البيانات
MACOS_NAMES = {11: "Big Sur", 12: "Monterey", 13: "Ventura", 14: "Sonoma",
               15: "Sequoia", 26: "Tahoe"}
COND_AR = {"Good": "جيدة", "Normal": "طبيعية", "Fair": "مقبولة",
           "Service Recommended": "يُنصح بالصيانة", "Replace Soon": "استبدلها قريباً",
           "Replace Now": "استبدلها الآن", "Check Battery": "افحص البطارية"}

F = {}                      # بيانات ثابتة (تُحمَّل مرة واحدة)
READY = threading.Event()


def sh(cmd, timeout=15):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout).stdout
    except Exception:
        return ""


def sp(datatype):
    try:
        return json.loads(sh(["system_profiler", "-json", datatype], 45)).get(datatype, [])
    except Exception:
        return []


def fmt_bytes(b):
    return f"{b / 1e12:.2f} TB" if b >= 1e12 else f"{b / 1e9:.0f} GB"


def load_static():
    mver = platform.mac_ver()[0]
    F["macos"] = mver
    try:
        F["macos_name"] = MACOS_NAMES.get(int(mver.split(".")[0]), "")
    except Exception:
        F["macos_name"] = ""
    F["build"] = sh(["sw_vers", "-buildVersion"]).strip()
    F["arch"] = platform.machine()

    hw = (sp("SPHardwareDataType") or [{}])[0]
    F["model_name"] = hw.get("machine_name", "")
    F["model_id"] = hw.get("machine_model", "")
    F["model_number"] = hw.get("model_number", "")
    F["serial"] = hw.get("serial_number", "")
    F["activation"] = hw.get("activation_lock_status", "")
    F["chip"] = (hw.get("chip_type") or hw.get("cpu_type")
                 or sh(["sysctl", "-n", "machdep.cpu.brand_string"]).strip())
    F["memory"] = hw.get("physical_memory", "")
    F["cpu_speed"] = hw.get("current_processor_speed", "")
    procs = str(hw.get("number_processors", ""))
    m = re.match(r"proc (\d+):(\d+):(\d+)", procs)
    if m:
        F["cores"], F["perf"], F["eff"] = m.groups()
    else:
        F["cores"], F["perf"], F["eff"] = procs, "", ""

    gp = sp("SPDisplaysDataType")
    names = []
    F["displays"] = []
    for g in gp:
        n = g.get("sppci_model") or g.get("_name", "")
        if n and n not in names:
            names.append(n)
        for d in g.get("spdisplays_ndrvs", []):
            F["displays"].append((d.get("_name", ""),
                                  d.get("_spdisplays_resolution") or d.get("spdisplays_resolution", "")))
    F["gpu"] = " + ".join(names)
    if gp:
        F["gpu_cores"] = gp[0].get("sppci_cores", "")
        F["vram"] = gp[0].get("spdisplays_vram") or gp[0].get("spdisplays_vram_shared", "")

    for item in sp("SPPowerDataType"):
        info = item.get("sppower_battery_health_info")
        if info:
            F["bat_condition"] = info.get("sppower_battery_health", "")
            F["bat_maxcap"] = info.get("sppower_battery_health_maximum_capacity", "")
    READY.set()


def storage():
    try:
        u = shutil.disk_usage("/")
        return fmt_bytes(u.total), fmt_bytes(u.total - u.free), fmt_bytes(u.free)
    except Exception:
        return "", "", ""


def uptime(lang):
    m = re.search(r"sec = (\d+)", sh(["sysctl", "-n", "kern.boottime"]))
    if not m:
        return ""
    s = int(time.time()) - int(m.group(1))
    d, h, mi = s // 86400, s % 86400 // 3600, s % 3600 // 60
    return (f"{d} يوم، {h} ساعة، {mi} دقيقة" if lang == "ar" else f"{d}d {h}h {mi}m")


def battery():
    """بيانات البطارية الحيّة (سريعة). تُرجع {} إن لم توجد بطارية."""
    out = sh(["pmset", "-g", "batt"])
    m = re.search(r"(\d+)%", out)
    if not m:
        return {}
    B = {"percent": m.group(1) + "%"}
    st = re.search(r"\d+%;\s*([^;]+)", out)
    B["state"] = st.group(1).strip().lower() if st else ""
    io = sh(["ioreg", "-rn", "AppleSmartBattery"])

    def geti(k):
        mm = re.search(r'"%s"\s*=\s*(\d+)' % k, io)
        return int(mm.group(1)) if mm else None

    B["cycles"] = geti("CycleCount")
    B["design_cycles"] = geti("DesignCycleCount9C")
    t = geti("Temperature")
    B["temp"] = f"{t / 100:.1f}°C" if t and 0 < t < 10000 else ""
    raw = geti("AppleRawMaxCapacity") or (geti("MaxCapacity") if (geti("MaxCapacity") or 0) > 100 else None)
    design = geti("DesignCapacity")
    B["health_pct"] = f"{round(100 * raw / design)}%" if raw and design else ""
    B["raw_mah"], B["design_mah"] = raw, design
    return B


# ------------------------------------------------------------------ فهم السؤال
INTENTS = [
    ("cycles", ["دورات", "دورة", "عدد الشحن", "cycle", "ciclo", "zyklen", "zyklus", "döngü", "цикл",
                "循环", "充电次数", "サイクル", "사이클", "चक्र", "siklus", "cicli", "دوره"]),
    ("health", ["حالة البطارية", "صحة", "health", "condition", "capacity", "santé", "état de la batt",
                "salud", "estado de la bat", "zustand", "sağlık", "здоровь", "состояние", "健康",
                "容量", "状態", "건강", "saúde", "stato", "kesehatan", "سلامت", "kapazität"]),
    ("battery", ["بطارية", "بطاريه", "battery", "batterie", "batería", "bateria", "batteria", "akku",
                 "pil$", "батаре", "аккумулятор", "电池", "電池", "バッテリー", "배터리", "बैटरी",
                 "baterai", "باتری"]),
    ("gpu", ["gpu", "كرت$", "بطاقة الرسوم", "رسوم", "graphi", "graphique", "gráfic", "grafik",
             "grafica", "ekran kartı", "видеокарт", "графич", "显卡", "显示卡", "グラフィック",
             "그래픽", "ग्राफ", "گرافیک"]),
    ("ram", ["رام$", "ذاكر", "ram$", "memory", "mémoire", "memoria", "arbeitsspeicher", "bellek",
             "памят", "内存", "メモリ", "메모리", "मेमोरी", "memori", "حافظه"]),
    ("cpu", ["معالج", "cpu", "processor", "processeur", "procesador", "prozessor", "işlemci",
             "процессор", "处理器", "プロセッサ", "프로세서", "प्रोसेसर", "prosesor", "chip", "پردازنده"]),
    ("storage", ["تخزين", "قرص", "مساحة", "storage", "disk", "ssd", "stockage", "almacenamiento",
                 "armazenamento", "festplatte", "depolama", "диск", "хранилищ", "硬盘", "存储",
                 "ストレージ", "저장", "स्टोरेज", "penyimpanan", "ذخیره"]),
    ("macos", ["اصدار", "إصدار", "نسخة", "نظام التشغيل", "macos", "version", "versión", "versão",
               "sürüm", "версия", "版本", "バージョン", "버전", "betriebssystem", "système d"]),
    ("model", ["موديل", "طراز", "نوع الجهاز", "model", "modèle", "modelo", "modell", "serial",
               "سيريال", "تسلسلي", "型号", "モデル", "모델", "модель"]),
    ("display", ["شاشة", "دقة", "display", "screen", "resolution", "écran", "pantalla", "bildschirm",
                 "ekran", "экран", "屏幕", "画面", "화면"]),
    ("uptime", ["uptime", "مدة التشغيل", "منذ متى", "تشغيل منذ", "tiempo encendido", "çalışma süresi",
                "开机", "稼働", "en marche"]),
    ("apps", ["تطبيق", "برنامج", "برامج", "عملية", "عمليات", "يستهلك", "تستهلك", "استهلاك", "apps",
              "app$", "application", "process$", "processes", "consum", "consomm", "aplicacion", "aplicaç",
              "anwendung", "verbrauch", "uygulama", "tüket", "приложен", "процесс", "потребл", "应用",
              "占用", "アプリ", "앱", "ऐप", "aplikasi", "برنامه"]),
    ("inspect", ["فحص", "للشراء", "شراء", "مستعمل", "اشتري", "بيع", "سليم", "جودة", "inspect", "buyer",
                 "buying", "used laptop", "second hand", "secondhand", "before buy", "quality", "gebraucht",
                 "occasion", "usado", "inspecci", "ضعف", "عيوب", "weak", "flaw", "تنصحني", "انصحني",
                 "should i buy"]),
    ("price", ["سعر", "سوقي", "يساوي", "price", "worth$", "market value", "resale", "precio", "prix", "preis",
               "价格", "価格"]),
    ("help", ["اسئلة التي", "أسئلة التي", "ماذا يمكنك", "ماذا تستطيع", "ماذا تفعل", "مساعدة", "what can you",
              "help$", "what do you do", "how to use"]),
    ("all", ["مواصفات", "ملخص", "كل شيء", "specs", "specification", "overview", "summary", "everything",
             "caractéristiques", "especificaciones", "规格", "スペック"]),
]


AR = r"\u0600-\u06FF"


def _match(k, ql):
    """k$ = كلمة كاملة. العربية: يسمح ببادئات (ال، لل، و، ب، ل، ف، ك) ولا يطابق وسط الكلمة."""
    end = k.endswith("$")
    k = k[:-1] if end else k
    if k.isascii():
        return re.search(r"\b" + re.escape(k) + (r"\b" if end else ""), ql)
    if re.search("[" + AR + "]", k):
        return re.search("(?<![" + AR + "])(?:لل|[وفبلك]?(?:ال)?)" + re.escape(k)
                         + ("(?![" + AR + "])" if end else ""), ql)
    return k in ql


def detect(q):
    ql = q.lower()
    hits = [name for name, kws in INTENTS if any(_match(k, ql) for k in kws)]
    if "all" in hits:
        return ["all"]
    for special in ("inspect", "price"):
        if special in hits:
            return [special]
    if "help" in hits and len(hits) == 1:
        return ["help"]
    hits = [h for h in hits if h != "help"]
    if "apps" in hits:
        if "cpu" in hits or "battery" in hits:
            return ["apps:cpu"]
        return ["apps:mem"] if "ram" in hits else ["apps:mem", "apps:cpu"]
    if "cycles" in hits or "health" in hits:
        hits = [h for h in hits if h != "battery"]
    return hits


PRETTY = {"com.apple.WebKit.WebContent": "Safari / WebKit", "com.apple.WebKit.GPU": "Safari / WebKit",
          "com.apple.WebKit.Networking": "Safari / WebKit"}


def top_apps():
    """يجمع الاستهلاك حسب التطبيق (عمليات Chrome Helper وغيرها تُجمع تحت التطبيق نفسه)."""
    mem, cpu = {}, {}
    for line in sh(["ps", "-axo", "rss=,pcpu=,comm="]).splitlines():
        parts = line.strip().split(None, 2)
        if len(parts) < 3:
            continue
        try:
            rss, pc = int(parts[0]), float(parts[1])
        except ValueError:
            continue
        m = re.search(r"/([^/]+)\.app/", parts[2])
        name = PRETTY.get(*(2 * [m.group(1) if m else os.path.basename(parts[2])]))
        mem[name] = mem.get(name, 0) + rss
        cpu[name] = cpu.get(name, 0) + pc
    return mem, cpu


def fmt_kb(kb):
    return f"{kb / 1048576:.1f} GB" if kb >= 1048576 else f"{kb / 1024:.0f} MB"


def rows(*pairs):
    return [(a, str(b)) for a, b in pairs if b not in (None, "", "None")]


STATES = {"charging": ("يشحن", "Charging"), "discharging": ("يعمل على البطارية", "On battery"),
          "charged": ("مشحونة بالكامل", "Fully charged"),
          "finishing charge": ("يكمل الشحن", "Finishing charge"),
          "not charging": ("متصل بالكهرباء (لا يشحن)", "Plugged in (not charging)"),
          "ac attached": ("متصل بالكهرباء", "Plugged in")}


def section(intent, lang):
    t = lambda a, e: a if lang == "ar" else e
    if intent.startswith("apps:"):
        mem, cpu = top_apps()
        if intent == "apps:mem":
            top = sorted(mem.items(), key=lambda x: -x[1])[:6]
            return (t("📊 أكثر التطبيقات استهلاكاً للذاكرة", "📊 Top apps by memory"),
                    rows(*[(n, fmt_kb(v)) for n, v in top]))
        top = sorted(cpu.items(), key=lambda x: -x[1])[:6]
        return (t("🔥 أكثر التطبيقات استهلاكاً للمعالج", "🔥 Top apps by CPU"),
                rows(*[(n, f"{v:.0f}%") for n, v in top]))
    B = battery() if intent in ("cycles", "health", "battery") else {}
    if intent in ("cycles", "health", "battery") and not B:
        return (t("🔋 البطارية", "🔋 Battery"), rows((t("الحالة", "Status"), t("لا توجد بطارية في هذا الجهاز", "No battery found"))))
    cond = F.get("bat_condition", "")
    cond = COND_AR.get(cond, cond) if lang == "ar" else cond
    maxcap = F.get("bat_maxcap") or B.get("health_pct", "")

    if intent == "cycles":
        c, d = B.get("cycles"), B.get("design_cycles")
        used = f"{c / d * 100:.0f}%" if c is not None and d else ""
        return (t("🔄 دورات البطارية", "🔄 Battery cycles"),
                rows((t("عدد الدورات", "Cycle count"), c), (t("الحد التصميمي", "Rated for"), d),
                     (t("المستهلك من العمر", "Of rated lifespan used"), used)))
    if intent == "health":
        return (t("🔋 صحة البطارية", "🔋 Battery health"),
                rows((t("الحالة", "Condition"), cond), (t("السعة القصوى", "Maximum capacity"), maxcap),
                     (t("عدد الدورات", "Cycle count"), B.get("cycles"))))
    if intent == "battery":
        s = STATES.get(B.get("state", ""), (B.get("state", ""),) * 2)[0 if lang == "ar" else 1]
        return (t("🔋 البطارية", "🔋 Battery"),
                rows((t("الشحن", "Charge"), B["percent"]), (t("الوضع", "State"), s),
                     (t("عدد الدورات", "Cycle count"), B.get("cycles")), (t("الحالة", "Condition"), cond),
                     (t("السعة القصوى", "Maximum capacity"), maxcap),
                     (t("الحرارة", "Temperature"), B.get("temp"))))
    if intent == "gpu":
        return (t("🎮 كرت الشاشة", "🎮 Graphics"),
                rows((t("النوع", "GPU"), F.get("gpu")), (t("أنوية GPU", "GPU cores"), F.get("gpu_cores")),
                     ("VRAM", F.get("vram"))))
    if intent == "ram":
        apple = F.get("chip", "").startswith("Apple")
        return (t("🧠 الرام", "🧠 Memory"),
                rows((t("الحجم", "Size"), F.get("memory")),
                     (t("النوع", "Type"), t("ذاكرة موحّدة", "Unified memory") if apple else "")))
    if intent == "cpu":
        cores = F.get("cores", "")
        if F.get("perf"):
            cores = f"{cores} ({F['perf']} {t('أداء', 'performance')} + {F['eff']} {t('كفاءة', 'efficiency')})"
        return (t("⚙️ المعالج", "⚙️ Processor"),
                rows((t("المعالج", "Chip"), F.get("chip")), (t("الأنوية", "Cores"), cores),
                     (t("السرعة", "Speed"), F.get("cpu_speed")), (t("المعمارية", "Architecture"), F.get("arch"))))
    if intent == "storage":
        total, used, free = storage()
        return (t("💾 التخزين", "💾 Storage"),
                rows((t("السعة", "Total"), total), (t("المستخدم", "Used"), used), (t("المتاح", "Free"), free)))
    if intent == "macos":
        return ("macOS", rows((t("الإصدار", "Version"), f"{F.get('macos_name', '')} {F.get('macos', '')}".strip()),
                              (t("رقم البناء", "Build"), F.get("build"))))
    if intent == "model":
        return (t("💻 الجهاز", "💻 Mac"),
                rows((t("الاسم", "Name"), F.get("model_name")), (t("المعرّف", "Identifier"), F.get("model_id")),
                     (t("رقم الموديل", "Model number"), F.get("model_number")),
                     (t("الرقم التسلسلي", "Serial"), F.get("serial"))))
    if intent == "display":
        return (t("🖥️ الشاشة", "🖥️ Display"),
                rows(*[(n or t("شاشة", "Display"), r) for n, r in F.get("displays", [])]))
    if intent == "uptime":
        return (t("⏱️ مدة التشغيل", "⏱️ Uptime"), rows((t("منذ آخر إقلاع", "Since last boot"), uptime(lang))))
    return None


def smart_status():
    out = sh(["diskutil", "info", "/"])
    m = re.search(r"SMART Status:\s*(.+)", out)
    v = m.group(1).strip() if m else ""
    if not v or "not supported" in v.lower():
        try:
            for ctrl in sp("SPNVMeDataType"):
                for d in ctrl.get("_items", []):
                    if d.get("spnvme_smart_status"):
                        return d["spnvme_smart_status"]
        except Exception:
            pass
    return v


def inspect_sections(lang):
    """فحص للشراء/البيع: خلاصة بعلامات ✅/⚠️ + تفاصيل + قائمة فحص يدوي."""
    t = lambda a, e: a if lang == "ar" else e
    L = lambda x: f"\u2066{x}\u2069" if lang == "ar" else str(x)   # يمنع انعكاس الأرقام داخل النص العربي
    B = battery()
    mdm = sh(["profiles", "status", "-type", "enrollment"])
    smart = smart_status()
    total, used, free = storage()
    flags = []

    def add(icon, ar, en):
        flags.append((icon, t(ar, en)))

    act = F.get("activation", "").lower()
    if "enabled" in act:
        add("⚠️", "قفل التنشيط (Find My) مفعّل — طبيعي لجهازك، أما عند الشراء فاطلب من البائع إزالته قبل الدفع",
            "Activation Lock is ON — normal for your own Mac; when buying, make the seller remove it before you pay")
    elif "disabled" in act:
        add("✅", "قفل التنشيط معطّل", "Activation Lock is off")
    if re.search(r"(MDM enrollment|Enrolled via DEP):\s*Yes", mdm, re.I):
        add("⚠️", "الجهاز مسجّل في إدارة شركة أو مؤسسة (MDM) وقد يكون مقيّداً أو مقفلاً عن بُعد",
            "Enrolled in company/school management (MDM) — may be restricted or remotely locked")
    elif "MDM enrollment" in mdm:
        add("✅", "غير مسجّل في إدارة مؤسسية (MDM)", "Not enrolled in MDM")

    if B:
        cap = F.get("bat_maxcap") or B.get("health_pct", "")
        m = re.search(r"(\d+)", cap or "")
        if m:
            pct = int(m.group(1))
            if pct >= 90:
                add("✅", f"سعة البطارية ممتازة: {L(f'{pct}%')}", f"Battery capacity is excellent ({pct}%)")
            elif pct >= 80:
                add("ℹ️", f"سعة البطارية مقبولة: {L(f'{pct}%')}", f"Battery capacity is fair ({pct}%)")
            else:
                add("⚠️", f"سعة البطارية منخفضة: {L(f'{pct}%')} وقد تحتاج استبدالاً",
                    f"Battery capacity is low ({pct}%) — may need replacement")
        c, d = B.get("cycles"), (B.get("design_cycles") or 1000)
        if c is not None:
            if c / d > 0.8:
                add("⚠️", f"عدد دورات البطارية مرتفع: {L(c)} من {L(d)}", f"High battery cycle count ({c} of {d})")
            else:
                add("✅", f"عدد دورات البطارية منخفض: {L(c)} من {L(d)}", f"Low battery cycle count ({c} of {d})")
        cond = F.get("bat_condition", "")
        if cond and cond not in ("Normal", "Good"):
            add("⚠️", f"حالة البطارية: {COND_AR.get(cond, cond)}", f"Battery condition: {cond}")

    sl = smart.lower()
    if "verified" in sl:
        add("✅", "صحة قرص التخزين (SMART): سليمة", "Storage health (SMART): Verified")
    elif smart and "not supported" not in sl:
        add("⚠️", f"صحة قرص التخزين (SMART): {smart}", f"Storage health (SMART): {smart}")
    else:
        add("ℹ️", "تعذّر قراءة صحة قرص التخزين (SMART)", "Couldn't read storage health (SMART)")

    secs = [(t("🧾 خلاصة الفحص", "🧾 Inspection summary"), flags)]
    batt = ""
    if B.get("raw_mah") and B.get("design_mah"):
        batt = f"{B['raw_mah']} / {B['design_mah']} mAh"
    secs.append((t("💻 تفاصيل الجهاز", "💻 Device details"), rows(
        (t("الجهاز", "Mac"), f"{F.get('model_name', '')} ({F.get('model_id', '')})"),
        (t("الرقم التسلسلي", "Serial"), F.get("serial")), (t("المعالج", "Chip"), F.get("chip")),
        (t("الرام", "Memory"), F.get("memory")), (t("التخزين", "Storage"), f"{total} ({free} {t('متاح', 'free')})" if total else ""),
        ("macOS", f"{F.get('macos_name', '')} {F.get('macos', '')}".strip()),
        (t("سعة البطارية الفعلية", "Battery capacity"), batt), (t("الحرارة", "Battery temp"), B.get("temp")))))
    secs.append((t("🖐️ افحصها يدوياً (لا يستطيع التطبيق فحصها)", "🖐️ Check by hand (the app can't test these)"), [
        ("☐", t("الشاشة: بكسلات ميتة أو بقع (اعرض ألواناً صلبة)", "Screen: dead pixels or stains (show solid colors)")),
        ("☐", t("لوحة المفاتيح ولوحة اللمس: جرّب كل المفاتيح والنقر", "Keyboard & trackpad: try every key and click")),
        ("☐", t("المنافذ والشاحن: جرّب كل منفذ وتأكد من الشحن", "Ports & charger: test every port and charging")),
        ("☐", t("السماعات والميكروفون والكاميرا", "Speakers, microphone and camera")),
        ("☐", t("Wi-Fi وBluetooth: اتصل بشبكة وجهاز", "Wi-Fi & Bluetooth: connect to a network and a device")),
        ("☐", t("الهيكل: خدوش، مفصلات، آثار سوائل", "Body: dents, hinges, signs of liquid")),
        ("☐", t("فحص العتاد (Apple Silicon): اضغط مطولاً زر التشغيل ثم Command+D", "Hardware test (Apple Silicon): hold the power button, then Command+D")),
        ("☐", t("فحص العتاد (Intel): اضغط D أثناء التشغيل", "Hardware test (Intel): hold D at startup")),
        ("☐", t("عند البيع: سجّل الخروج من iCloud وامسح الجهاز قبل التسليم",
                "If selling: sign out of iCloud and erase the Mac before handing it over"))]))
    return secs


def help_sections(lang):
    t = lambda a, e: a if lang == "ar" else e
    return [(t("💡 ماذا يمكنني أن أفعل؟", "💡 What can I do?"), [
        ("💻", t("مواصفات جهازك: الموديل، المعالج، الرام، الـ GPU، الشاشة، التخزين، macOS",
                 "Your specs: model, chip, RAM, GPU, display, storage, macOS")),
        ("🔋", t("البطارية: النسبة، عدد الدورات، الحالة، السعة القصوى، الحرارة",
                 "Battery: charge, cycles, condition, max capacity, temperature")),
        ("📊", t("أكثر التطبيقات استهلاكاً للذاكرة أو المعالج", "Which apps use the most memory or CPU")),
        ("🔍", t("فحص الجهاز للشراء أو البيع: قفل التنشيط، صحة البطارية والتخزين",
                 "Buyer check for buying or selling: Activation Lock, battery & storage health")),
        ("💰", t("العوامل التي تحدد سعر جهازك عند البيع", "What sets your Mac's resale price")),
        ("🌍", t("اسألني بأي لغة، مثلاً: كم رام عندي؟ أو battery cycles",
                 "Ask in any language, e.g. “How much RAM?” or كم دورة للبطارية؟"))])]


def price_sections(lang):
    t = lambda a, e: a if lang == "ar" else e
    B = battery()
    total = storage()[0]
    cap = F.get("bat_maxcap") or B.get("health_pct", "")
    r = [("ℹ️", t("لا أستطيع معرفة الأسعار الحالية لأن التطبيق يعمل دون إنترنت. هذه العوامل التي تحدد سعر جهازك:",
                  "I can't see live prices because the app works offline. These are the factors that set your Mac's price:"))]
    r += rows((t("الجهاز", "Mac"), f"{F.get('model_name', '')} ({F.get('model_id', '')})"),
              (t("المعالج", "Chip"), F.get("chip")), (t("الرام", "Memory"), F.get("memory")),
              (t("التخزين", "Storage"), total), (t("سعة البطارية", "Battery capacity"), cap),
              (t("عدد الدورات", "Cycles"), B.get("cycles")), ("macOS", F.get("macos")))
    r.append(("🔎", t("ابحث عن نفس الموديل والمواصفات في eBay أو Facebook Marketplace، وقارنه مع Apple Trade In، ثم خذ متوسط الأسعار المعروضة. كلما كانت البطارية أفضل والدورات أقل ارتفع السعر.",
                      "Search the same model and specs on eBay or Facebook Marketplace, compare with Apple Trade In, and take the average listing. Better battery health and fewer cycles raise the price.")))
    return [(t("💰 تقدير القيمة السوقية", "💰 Estimating market value"), r)]


ALL_ORDER = ["model", "cpu", "ram", "gpu", "storage", "macos", "display", "battery"]


def facts_text():
    out = []
    for i in ALL_ORDER + ["uptime", "cycles", "health"]:
        s = section(i, "en")
        if s:
            out.append(s[0] + ": " + "; ".join(f"{a}={b}" for a, b in s[1]))
    mem, _ = top_apps()
    out.append("Top apps by memory: " + "; ".join(f"{n}={fmt_kb(v)}" for n, v in sorted(mem.items(), key=lambda x: -x[1])[:5]))
    out.append("Uptime: " + uptime("en"))
    return "\n".join(out)


MODELS = ["gemma3:1b", "qwen2.5:1.5b", "qwen2.5:0.5b"]  # بالترتيب: يُستخدم أول نموذج متوفر أو قابل للتحميل
OLLAMA = "http://127.0.0.1:11434"
AI = {"stage": "off", "pct": 0, "msg": "", "model": ""}  # off|checking|installing|starting|downloading|ready|error
LOCAL = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # يتجاهل أي Proxy/VPN للاتصال المحلي
_setup_lock = threading.Lock()


def _get(path, timeout=1.5):
    return json.load(LOCAL.open(OLLAMA + path, timeout=timeout))


def ollama_up():
    try:
        _get("/api/tags")
        return True
    except Exception:
        return False


def ollama_bin():
    for p in (shutil.which("ollama"), "/Applications/Ollama.app/Contents/Resources/ollama",
              os.path.expanduser("~/Applications/Ollama.app/Contents/Resources/ollama"),
              "/opt/homebrew/bin/ollama", "/usr/local/bin/ollama"):
        if p and os.path.exists(p):
            return p
    return None


def install_ollama():
    AI.update(stage="installing", pct=0, msg="")
    tmp = tempfile.mkdtemp()
    z = os.path.join(tmp, "Ollama.zip")
    url = "https://ollama.com/download/Ollama-darwin.zip"
    try:
        r = urllib.request.urlopen(url, timeout=60)
        total, done = int(r.headers.get("Content-Length") or 0), 0
        with open(z, "wb") as f:
            while True:
                b = r.read(1 << 20)
                if not b:
                    break
                f.write(b)
                done += len(b)
                if total:
                    AI["pct"] = int(done * 100 / total)
    except Exception:
        # شهادات Python قد تكون ناقصة على macOS؛ curl يستخدم شهادات النظام
        subprocess.run(["curl", "-fL", "-o", z, url], check=True)
    dest = os.path.expanduser("~/Applications")
    os.makedirs(dest, exist_ok=True)
    subprocess.run(["ditto", "-x", "-k", z, dest], check=True)
    subprocess.run(["xattr", "-dr", "com.apple.quarantine", os.path.join(dest, "Ollama.app")])
    shutil.rmtree(tmp, ignore_errors=True)


def start_ollama():
    AI.update(stage="starting", pct=0)
    subprocess.Popen([ollama_bin(), "serve"], stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, start_new_session=True)
    for _ in range(60):
        if ollama_up():
            return True
        time.sleep(0.5)
    return False


def pull(model):
    req = urllib.request.Request(OLLAMA + "/api/pull", headers={"content-type": "application/json"},
                                 data=json.dumps({"model": model, "stream": True}).encode())
    with LOCAL.open(req, timeout=300) as r:
        for line in r:
            d = json.loads(line)
            if d.get("error"):
                raise RuntimeError(d["error"])
            if d.get("total"):
                AI["pct"] = int(d.get("completed", 0) * 100 / d["total"])


def setup_ai():
    """يعمل في الخلفية: يثبّت Ollama ويحمّل نموذجاً خفيفاً إن لزم؛ والتطبيق يعمل خلال ذلك."""
    if not _setup_lock.acquire(blocking=False):
        return
    try:
        AI.update(stage="checking", pct=0, msg="")
        if not ollama_up():
            if not ollama_bin():
                install_ollama()
            if not start_ollama():
                raise RuntimeError("Ollama did not start")
        have = [n[:-7] if n.endswith(":latest") else n for n in (m["name"] for m in _get("/api/tags")["models"])]
        pick, errors = next((m for m in MODELS if m in have), None), []
        for m in ([] if pick else MODELS):
            try:
                AI.update(stage="downloading", pct=0, model=m)
                pull(m)
                pick = m
                break
            except Exception as e:
                errors.append(f"{m}: {e}")
        if not pick:
            raise RuntimeError(" | ".join(errors))
        AI.update(stage="ready", pct=100, model=pick, msg="")
    except Exception as e:
        AI.update(stage="error", msg=str(e)[:200])
    finally:
        _setup_lock.release()


def ollama(q):
    """يجيب النموذج المحلي بلغة السؤال اعتماداً على مواصفات الجهاز فقط."""
    if AI["stage"] != "ready":
        return None
    try:
        body = json.dumps({"model": AI["model"], "stream": False, "keep_alive": "15m",
                           "options": {"temperature": 0.2, "num_predict": 220},
                           "messages": [
            {"role": "system", "content": "You are 'My Laptop', a friendly assistant inside a laptop app. You understand "
             "and speak Arabic, English and many other languages: ALWAYS reply in the same language as the "
             "user's message. For questions about this Mac use the MAC DATA below and never invent numbers. "
             "Never claim anything about this Mac that is not in the data. For other questions answer briefly and helpfully. Keep replies to 1-3 sentences.\n\nMAC DATA:\n"
             + facts_text()},
            {"role": "user", "content": q}]}).encode()
        req = urllib.request.Request(OLLAMA + "/api/chat", data=body,
                                     headers={"content-type": "application/json"})
        out = json.load(LOCAL.open(req, timeout=180))["message"]["content"].strip()
        AI["msg"] = ""
        return out
    except Exception as e:
        AI["msg"] = f"chat: {e}"[:200]
        return None


SETTINGS = os.path.expanduser("~/.mac_specs.json")


def get_setting(k):
    try:
        with open(SETTINGS) as f:
            return json.load(f).get(k)
    except Exception:
        return None


def set_setting(k, v):
    try:
        with open(SETTINGS) as f:
            d = json.load(f)
    except Exception:
        d = {}
    d[k] = v
    try:
        with open(SETTINGS, "w") as f:
            json.dump(d, f)
    except Exception:
        pass


def already_have():
    """هل Ollama يعمل وفيه نموذج جاهز؟ عندها لا حاجة لتحميل شيء."""
    try:
        have = [n[:-7] if n.endswith(":latest") else n for n in (m["name"] for m in _get("/api/tags")["models"])]
        return any(m in have for m in MODELS)
    except Exception:
        return False


def answer(q):
    READY.wait(20)
    lang = "ar" if re.search(r"[\u0600-\u06FF]", q) else "en"
    hits = detect(q)
    if hits == ["inspect"]:
        secs = inspect_sections(lang)
    elif hits == ["price"]:
        secs = price_sections(lang)
    elif hits == ["help"]:
        secs = help_sections(lang)
    else:
        if hits == ["all"]:
            hits = ALL_ORDER
        secs = [s for s in (section(i, lang) for i in hits) if s]
    if secs:
        return {"sections": [{"title": t, "rows": r} for t, r in secs]}
    txt = ollama(q)
    if txt:
        return {"text": txt}
    busy = AI["stage"] in ("checking", "installing", "starting", "downloading")
    if lang == "ar":
        msg = "لم أفهم سؤالك. جرّب: «كم رام عندي؟» أو «عدد دورات البطارية» أو «ما نوع الـ GPU؟»"
        if busy:
            msg += f"\n\n⏳ الذكاء المحلي قيد التجهيز ({AI['pct']}%) وسيفهم أسئلة أكثر بعد انتهائه."
    else:
        msg = "I didn't catch that. Try: “How much RAM?”, “Battery cycle count”, or “What GPU?”"
        if busy:
            msg += f"\n\n⏳ Local AI is getting ready ({AI['pct']}%) and will understand more once done."
    if AI["stage"] == "off":
        msg += "\n\nℹ️ الذكاء المحلي معطّل (--no-ai)." if lang == "ar" else "\n\nℹ️ Local AI is disabled (--no-ai)."
    elif AI["msg"] and not busy:
        msg += f"\n\n⚠️ AI: {AI['msg']}"
    return {"text": msg}


def summary():
    b = battery()
    total, used, free = storage()
    d = F.get("displays", [])
    ph = "…"
    cores = F.get("cores", "")
    cards = [
        ("💻", "Mac · الجهاز", F.get("model_name") or ph, F.get("model_id", "")),
        ("⚙️", "Chip · المعالج", F.get("chip") or ph, f"{cores} cores" if cores else ""),
        ("🧠", "Memory · الرام", F.get("memory") or ph, ""),
        ("🎮", "Graphics · الرسوميات", F.get("gpu") or ph, f"{F['gpu_cores']} cores" if F.get("gpu_cores") else ""),
        ("🔋", "Battery · البطارية", b.get("percent", "—"),
         f"{b['cycles']} cycles" if b.get("cycles") is not None else ""),
        ("💾", "Storage · التخزين", f"{free} free" if free else ph, f"of {total}" if total else ""),
        ("", "macOS", f"{F.get('macos_name', '')} {F.get('macos', '')}".strip() or ph, F.get("build", "")),
        ("🖥️", "Display · الشاشة", d[0][0] if d else ph, d[0][1] if d else ""),
    ]
    return {"ready": READY.is_set(),
            "cards": [{"icon": i or "", "label": l, "value": v, "sub": s} for i, l, v, s in cards]}


# ------------------------------------------------------------------ الخادم المحلي
class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, body, ctype="application/json; charset=utf-8"):
        if not isinstance(body, bytes):
            body = json.dumps(body, ensure_ascii=False).encode()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/api/summary":
            self._send(summary())
        elif self.path == "/api/ai":
            self._send(AI)
        else:
            self._send(HTML.encode(), "text/html; charset=utf-8")

    def do_POST(self):
        if self.path == "/api/ai/retry":          # تفعيل / إعادة محاولة
            set_setting("ai", "yes")
            threading.Thread(target=setup_ai, daemon=True).start()
            self._send({"ok": True})
        elif self.path == "/api/ai/no":
            set_setting("ai", "no")
            AI.update(stage="off", msg="")
            self._send({"ok": True})
        elif self.path == "/api/ask":
            n = int(self.headers.get("Content-Length", 0))
            q = json.loads(self.rfile.read(n) or b"{}").get("q", "")
            self._send(answer(q))


HTML = r"""<!doctype html><html><head><meta charset="utf-8"><title>My Laptop - لابتوبي</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
:root{--bg:#f5f5f7;--card:#fff;--text:#1d1d1f;--mut:#6e6e73;--line:#e5e5ea;--acc:#0a84ff;--acc2:#5e5ce6}
@media(prefers-color-scheme:dark){:root{--bg:#0b0b0d;--card:#1c1c1e;--text:#f5f5f7;--mut:#98989d;--line:#2c2c2e}}
*{box-sizing:border-box}
body{margin:0;height:100vh;display:flex;background:var(--bg);color:var(--text);
 font-family:-apple-system,BlinkMacSystemFont,"SF Pro Text","Segoe UI",sans-serif;-webkit-font-smoothing:antialiased}
aside{width:290px;flex:none;padding:22px 16px;overflow:auto;border-inline-end:1px solid var(--line)}
aside h1{font-size:20px;margin:0 6px 4px;letter-spacing:-.3px}
aside p{margin:0 6px 16px;color:var(--mut);font-size:12.5px}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:11px 13px;margin-bottom:9px;
 display:flex;gap:11px;align-items:center;animation:in .4s both}
.card .i{font-size:22px;width:28px;text-align:center}
.card .l{font-size:11px;color:var(--mut)}
.card .v{font-size:14px;font-weight:600;margin-top:1px}
.card .s{font-size:11.5px;color:var(--mut)}
main{flex:1;display:flex;flex-direction:column;min-width:0}
#chat{flex:1;overflow:auto;padding:26px 8% 10px;display:flex;flex-direction:column;gap:12px}
.msg{max-width:78%;padding:11px 15px;border-radius:18px;font-size:15px;line-height:1.5;animation:in .25s both;white-space:pre-wrap}
.user{align-self:flex-end;color:#fff;background:linear-gradient(135deg,var(--acc),var(--acc2));border-bottom-right-radius:6px}
.bot{align-self:flex-start;background:var(--card);border:1px solid var(--line);border-bottom-left-radius:6px;white-space:normal}
.sec+.sec{margin-top:12px;padding-top:10px;border-top:1px solid var(--line)}
.sec h4{margin:0 0 6px;font-size:13px}
.row{display:flex;justify-content:space-between;gap:18px;padding:3px 0;font-size:14px}
.row span:first-child{color:var(--mut)}.row span:last-child{font-weight:600;text-align:end}
.chips{display:flex;flex-wrap:wrap;gap:8px;padding:6px 8% 0}
.chip{border:1px solid var(--line);background:var(--card);color:var(--text);padding:7px 13px;border-radius:99px;
 font-size:13px;cursor:pointer;transition:.15s}
.chip:hover{border-color:var(--acc);color:var(--acc);transform:translateY(-1px)}
form{display:flex;gap:10px;padding:14px 8% 22px}
input{flex:1;padding:14px 18px;border-radius:99px;border:1px solid var(--line);background:var(--card);
 color:var(--text);font-size:15px;outline:none;transition:.15s}
input:focus{border-color:var(--acc);box-shadow:0 0 0 4px rgba(10,132,255,.15)}
button.send{width:48px;border:0;border-radius:50%;color:#fff;font-size:18px;cursor:pointer;
 background:linear-gradient(135deg,var(--acc),var(--acc2))}
.dots span{display:inline-block;width:7px;height:7px;margin:0 2px;border-radius:50%;background:var(--mut);animation:b 1s infinite}
.dots span:nth-child(2){animation-delay:.15s}.dots span:nth-child(3){animation-delay:.3s}
@keyframes b{0%,60%,100%{opacity:.3}30%{opacity:1;transform:translateY(-3px)}}
@keyframes in{from{opacity:0;transform:translateY(6px)}to{opacity:1;transform:none}}
#ai{margin:0 4px 16px;font-size:12px;color:var(--mut)}
#aierr{color:#ff453a;font-size:11px;margin-top:6px;word-break:break-word}
#retry,#no{display:none;margin-top:8px;margin-inline-end:6px;border:1px solid var(--line);background:var(--card);color:var(--text);
 padding:5px 12px;border-radius:99px;font-size:12px;cursor:pointer}
#bar{height:5px;border-radius:9px;background:var(--line);margin-top:7px;overflow:hidden;display:none}
#bar i{display:block;height:100%;width:0;background:linear-gradient(90deg,var(--acc),var(--acc2));transition:width .4s}
@media(max-width:760px){aside{display:none}}
</style></head><body>
<aside><h1>My Laptop</h1><p>لابتوبي · يعمل محلياً · Fully offline</p><div id="ai"><div id="aitxt"></div><div id="bar"><i></i></div><div id="aierr" dir="auto"></div><button id="retry" type="button"></button><button id="no" type="button">لاحقاً · Not now</button></div><div id="cards"></div></aside>
<main>
<div id="chat"><div class="msg bot" dir="auto">أهلاً 👋 اسألني عن جهازك بأي لغة.<br>Hi! Ask me anything about your Mac, in any language.</div></div>
<div class="chips" id="chips"></div>
<form id="f"><input id="q" dir="auto" autocomplete="off" placeholder="اكتب سؤالك… / Ask about your Mac…" autofocus>
<button class="send" aria-label="send">➤</button></form>
</main>
<script>
const $=s=>document.querySelector(s), chat=$('#chat'), inp=$('#q');
const SUG=["🔍 فحص الجهاز للشراء · Buyer check","ما إصدار macOS؟","كم رام عندي؟","ما نوع الـ GPU؟","عدد دورات البطارية","ما حالة البطارية؟","How much storage is free?","ملخص المواصفات","Battery health"];
SUG.forEach(s=>{const b=document.createElement('button');b.type='button';b.className='chip';b.textContent=s;b.onclick=()=>ask(s);$('#chips').append(b)});
function el(t,c,x){const e=document.createElement(t);if(c)e.className=c;if(x!==undefined)e.textContent=x;return e}
async function cards(){
  const r=await (await fetch('/api/summary')).json(), box=$('#cards');box.replaceChildren();
  r.cards.forEach(c=>{const d=el('div','card'),t=el('div');
    d.append(el('div','i',c.icon),t);t.append(el('div','l',c.label),el('div','v',c.value));
    if(c.sub)t.append(el('div','s',c.sub));box.append(d)});
  if(!r.ready)setTimeout(cards,900)
}
function bot(data){
  const m=el('div','msg bot');m.dir='auto';
  if(data.text)m.textContent=data.text;
  (data.sections||[]).forEach(s=>{const d=el('div','sec');d.append(el('h4','',s.title));
    s.rows.forEach(([a,b])=>{const r=el('div','row'),x=el('span','',a),y=el('span','',b);x.dir=y.dir='auto';r.append(x,y);d.append(r)});m.append(d)});
  chat.append(m);chat.scrollTop=chat.scrollHeight
}
async function ask(q){
  const u=el('div','msg user',q);u.dir='auto';chat.append(u);
  const t=el('div','msg bot');t.innerHTML='<div class="dots"><span></span><span></span><span></span></div>';
  chat.append(t);chat.scrollTop=chat.scrollHeight;
  try{const r=await fetch('/api/ask',{method:'POST',body:JSON.stringify({q})});t.remove();bot(await r.json())}
  catch(e){t.remove();bot({text:'⚠️ '+e})}
  cards()
}
$('#f').onsubmit=e=>{e.preventDefault();const q=inp.value.trim();if(q){inp.value='';ask(q)}};
cards();
const AIT={checking:"🤖 جارٍ فحص الذكاء المحلي… · Checking local AI…",
 installing:"⬇️ تثبيت Ollama · Installing Ollama",starting:"🚀 تشغيل Ollama · Starting Ollama",
 downloading:"⬇️ تحميل النموذج · Downloading model",ready:"🤖 الذكاء المحلي جاهز · Local AI ready",
 error:"⚠️ وضع الكلمات المفتاحية فقط · Keyword mode only",off:"وضع الكلمات المفتاحية · Keyword mode",
 ask:"🤖 تفعيل الذكاء المحلي؟ تحميل لمرة واحدة ≈1GB · Enable local AI? One-time ≈1GB download"};
async function ai(){
  const r=await (await fetch('/api/ai')).json(),busy=['installing','downloading'].includes(r.stage);
  $('#aitxt').textContent=AIT[r.stage]+(r.stage==='ready'&&r.model?' ('+r.model+')':'')+(busy?' '+r.pct+'%':'');
  $('#bar').style.display=busy?'block':'none';$('#bar i').style.width=r.pct+'%';
  $('#aierr').textContent=r.msg||'';
  const show=['error','off','ask'].includes(r.stage);
  $('#retry').style.display=show?'inline-block':'none';
  $('#retry').textContent=r.stage==='error'?'إعادة المحاولة · Retry':'تفعيل · Enable';
  $('#no').style.display=r.stage==='ask'?'inline-block':'none';
  if(!['ready','error','off','ask'].includes(r.stage))setTimeout(ai,1200)
}
$('#retry').onclick=async()=>{await fetch('/api/ai/retry',{method:'POST'});setTimeout(ai,400)};
$('#no').onclick=async()=>{await fetch('/api/ai/no',{method:'POST'});ai()};
ai();
</script></body></html>"""


def main():
    threading.Thread(target=load_static, daemon=True).start()
    if "--no-ai" not in sys.argv:
        choice = get_setting("ai") or ("yes" if already_have() else None)
        if choice == "yes":
            threading.Thread(target=setup_ai, daemon=True).start()
        elif choice is None:
            AI["stage"] = "ask"          # يسأل المستخدم في الواجهة قبل أي تحميل
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    url = f"http://127.0.0.1:{srv.server_port}"
    try:
        import webview  # pip3 install pywebview  (مجاني)
    except ImportError:
        print(f"My Laptop يعمل على {url}  (ثبّت pywebview لنافذة مستقلة)")
        webbrowser.open(url)
        srv.serve_forever()
        return
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    webview.create_window("My Laptop - لابتوبي", url, width=1020, height=700, min_size=(760, 520))
    webview.start()


if __name__ == "__main__":
    main()
