import json
import os
import requests as req
from datetime import datetime, date, timedelta
from http.server import BaseHTTPRequestHandler
try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo

BOT_TOKEN     = os.environ.get("TELEGRAM_TOKEN", "")
VERCEL_URL    = os.environ.get("WEATHER_VERCEL_URL", "https://weatheredge-weld.vercel.app")
TELEGRAM_API  = f"https://api.telegram.org/bot{BOT_TOKEN}"
KV_URL   = os.environ.get("KV_REST_API_URL", "")
KV_TOKEN = os.environ.get("KV_REST_API_TOKEN", "")

user_state: dict = {}

# ── Persistent storage via HTTP REST API ────────────────────────────────────────

def _kv(method, *args):
    try:
        parts = "/".join(str(a) for a in args)
        url = f"{KV_URL}/{method}/{parts}"
        r = req.get(url, headers={"Authorization": f"Bearer {KV_TOKEN}"}, timeout=5)
        return r.json().get("result")
    except:
        return None

def get_user_code(user_id):
    return _kv("get", f"user:{user_id}:code") or ""

def set_user_code(user_id, code):
    _kv("set", f"user:{user_id}:code", code)

def del_user_code(user_id):
    _kv("del", f"user:{user_id}:code")

# ── City config ───────────────────────────────────────────────────────────────

CITY_GROUPS = {
    "🌍 Top Liquidity":   ["London", "Wellington"],
    "🇺🇸 United States": ["Atlanta", "New York", "Miami", "Chicago", "Dallas", "Seattle"],
    "🌐 International":   ["Seoul", "Buenos Aires", "Shenzhen", "Warsaw"],
}
CITIES = [city for group in CITY_GROUPS.values() for city in group]

CITY_TIMEZONES = {
    "London":       "Europe/London",
    "Wellington":   "Pacific/Auckland",
    "Atlanta":      "America/New_York",
    "New York":     "America/New_York",
    "Miami":        "America/New_York",
    "Chicago":      "America/Chicago",
    "Dallas":       "America/Chicago",
    "Seattle":      "America/Los_Angeles",
    "Seoul":        "Asia/Seoul",
    "Buenos Aires": "America/Argentina/Buenos_Aires",
    "Shenzhen":     "Asia/Shanghai",
    "Warsaw":       "Europe/Warsaw",
}

CITY_API_NAMES = {
    "New York": "New York (LaGuardia)",
    "Shenzhen": "Shenzhen",
}

def get_city_time(city):
    try:
        tz = ZoneInfo(CITY_TIMEZONES.get(city, "UTC"))
        return datetime.now(tz).strftime("%H:%M")
    except:
        return ""

def get_city_today(city):
    try:
        tz = ZoneInfo(CITY_TIMEZONES.get(city, "UTC"))
        return datetime.now(tz).date()
    except:
        return date.today()

# ── Telegram helpers ──────────────────────────────────────────────────────────

def send_message(chat_id, text, reply_markup=None, parse_mode="Markdown"):
    payload = {"chat_id": chat_id, "text": text, "parse_mode": parse_mode}
    if reply_markup:
        payload["reply_markup"] = json.dumps(reply_markup)
    try:
        req.post(f"{TELEGRAM_API}/sendMessage", json=payload, timeout=10)
    except Exception as e:
        print(f"sendMessage error: {e}")

def answer_callback(callback_id, text=""):
    try:
        req.post(f"{TELEGRAM_API}/answerCallbackQuery",
                 json={"callback_query_id": callback_id, "text": text}, timeout=5)
    except:
        pass

# ── Button builders ───────────────────────────────────────────────────────────

def send_city_buttons(chat_id):
    rows = []
    for group_name, cities in CITY_GROUPS.items():
        rows.append([{"text": f"── {group_name} ──", "callback_data": "noop"}])
        for city in cities:
            t = get_city_time(city)
            label = f"{city}  –  {t} 🕐" if t else city
            rows.append([{"text": label, "callback_data": f"city:{city}"}])
    send_message(chat_id, "🌍 *Select a city:*", reply_markup={"inline_keyboard": rows})

def send_date_buttons(chat_id, city):
    today = get_city_today(city)
    entries = [
        (today,                      "📅   Today"),
        (today + timedelta(days=1),  "📅   Tomorrow"),
        (today + timedelta(days=2),  "📅   " + (today + timedelta(days=2)).strftime("%A, %b %d")),
        (today + timedelta(days=3),  "📅   " + (today + timedelta(days=3)).strftime("%A, %b %d")),
        (today + timedelta(days=4),  "📅   " + (today + timedelta(days=4)).strftime("%A, %b %d")),
        (today + timedelta(days=5),  "📅   " + (today + timedelta(days=5)).strftime("%A, %b %d")),
    ]
    rows = [[{"text": lbl, "callback_data": f"date:{d.strftime('%Y-%m-%d')}"}] for d, lbl in entries]
    rows.append([{"text": "◀️   Back to Cities", "callback_data": "back_to_cities"}])
    send_message(chat_id, f"📅 *Select a date for {city}:*", reply_markup={"inline_keyboard": rows})

def send_post_result_buttons(chat_id, city):
    today = get_city_today(city)
    entries = [
        (today,                      "Today"),
        (today + timedelta(days=1),  "Tomorrow"),
        (today + timedelta(days=2),  (today + timedelta(days=2)).strftime("%b %d")),
        (today + timedelta(days=3),  (today + timedelta(days=3)).strftime("%b %d")),
    ]
    rows = []
    for i in range(0, len(entries), 2):
        row = [{"text": f"🔄 {lbl}", "callback_data": f"date:{d.strftime('%Y-%m-%d')}"}
               for d, lbl in entries[i:i+2]]
        rows.append(row)
    rows.append([{"text": "🏙   Choose a Different City", "callback_data": "new_city"}])
    send_message(chat_id,
        f"*Check another date for {city}* or pick a new city:",
        reply_markup={"inline_keyboard": rows}
    )

# ── WeatherEdge API ───────────────────────────────────────────────────────────

def validate_code(code):
    try:
        r = req.post(f"{VERCEL_URL}/api/validate_code",
                     json={"code": code}, timeout=15)
        return r.json()
    except Exception as e:
        return {"ok": False, "error": str(e)}

def get_weather(city, date_str, code):
    try:
        api_city = CITY_API_NAMES.get(city, city)
        encoded  = api_city.replace(" ", "%20")
        r = req.get(
            f"{VERCEL_URL}/api/weather/{encoded}/{date_str}",
            headers={"X-Access-Code": code},
            timeout=20
        )
        return r.json()
    except Exception as e:
        return {"error": str(e)}

def format_weather(data):
    city       = data.get("city", "")
    flag       = data.get("flag", "")
    dt         = data.get("date", "")
    sym        = data.get("unit_symbol", "°F")
    days_out   = data.get("days_out", 0)
    consensus  = data.get("smart_consensus") or data.get("consensus_peak")
    intel_conf = (data.get("intel_confidence") or data.get("confidence") or "").lower()

    if days_out == 0:    day_label = "Today"
    elif days_out == 1:  day_label = "Tomorrow"
    elif days_out < 0:   day_label = f"{abs(days_out)}d ago"
    else:                day_label = f"In {days_out} days"

    conf_emoji = {"high": "🟢", "medium": "🟡", "low": "🔴"}.get(intel_conf, "⚪")
    om_peak    = data.get("om_peak")
    nws_peak   = data.get("nws_peak")
    vc_peak    = data.get("vc_peak")
    wu_peak    = data.get("wu_peak")
    intl_peak  = data.get("intl_peak")
    mm         = data.get("multi_model_peaks") or {}
    eq         = data.get("ensemble_quantiles") or {}
    brackets   = data.get("brackets") or []
    precip     = data.get("precip_risk", 0)
    wind       = data.get("wind_max", 0)
    vc_cond    = data.get("vc_conditions", "")

    lines = ["⚡ *Weather Edge Analysis*", f"{flag} *{city}* — {dt} _{day_label}_", ""]
    if consensus:
        lines.append(f"🎯 *Consensus Peak: {consensus}{sym}*  {conf_emoji} {intel_conf.upper()}")

    lines += ["", "📡 *Sources:*"]
    if wu_peak:   lines.append(f"  • WU: `{wu_peak}{sym}`")
    if om_peak:   lines.append(f"  • Open-Meteo: `{om_peak}{sym}`")
    if nws_peak:  lines.append(f"  • NWS: `{nws_peak}{sym}`")
    if vc_peak:   lines.append(f"  • Visual Crossing: `{vc_peak}{sym}`")
    if intl_peak: lines.append(f"  • Intl: `{intl_peak}{sym}`")

    if mm:
        lines += ["", "🤖 *Multi-Model:*"]
        for model, val in mm.items():
            if val: lines.append(f"  • {model}: `{val}{sym}`")
        agreement = data.get("intel_agreement", "")
        spread    = data.get("intel_spread")
        if agreement:
            ae = {"strong": "✅", "moderate": "⚠️", "poor": "❌"}.get(agreement, "")
            lines.append(f"  {ae} {agreement.upper()}" + (f" · spread {spread}{sym}" if spread else ""))

    p10 = eq.get("p10"); p50 = eq.get("p50"); p90 = eq.get("p90")
    if p10 and p50 and p90:
        lines += ["", f"📊 *Ensemble:* P10 `{p10}{sym}` · P50 `{p50}{sym}` · P90 `{p90}{sym}`"]

    if vc_cond: lines += ["", f"🌤 {vc_cond}"]
    if precip:  lines.append(f"🌧 Precip risk: {precip}%")
    if wind:    lines.append(f"💨 Max wind: {wind} mph")

    if brackets:
        lines += ["", "🎲 *Top Brackets:*"]
        for b in sorted(brackets, key=lambda x: x.get("prob", 0), reverse=True)[:3]:
            lines.append(f"  `{b.get('label')}` → {b.get('prob', 0):.1f}%")

    return "\n".join(lines)

# ── Message handler ───────────────────────────────────────────────────────────

def handle_message(message):
    chat_id = message["chat"]["id"]
    user_id = message["from"]["id"]
    text    = message.get("text", "").strip()

    if text.startswith("/start"):
        if get_user_code(user_id):
            send_message(chat_id,
                "✅ *You're already logged in!*\n\n"
                "/analyze — get weather analysis\n"
                "/cities — list cities\n"
                "/help — help"
            )
        else:
            user_state[user_id] = {"step": "waiting_code"}
            send_message(chat_id,
                "⚡ *Welcome to Weather Edge Bot*\n\n"
                "Enter your access code to continue:"
            )
        return

    if text.startswith("/analyze"):
        if not get_user_code(user_id):
            send_message(chat_id, "🔒 Please use /start to enter your access code first.")
            return
        user_state[user_id] = {"step": "waiting_city"}
        send_city_buttons(chat_id)
        return

    if text.startswith("/cities"):
        if not get_user_code(user_id):
            send_message(chat_id, "🔒 Please use /start to enter your access code first.")
            return
        lines = ["🌍 *Available Cities:*\n"]
        for group_name, cities in CITY_GROUPS.items():
            lines.append(f"*{group_name}*")
            for city in cities:
                t = get_city_time(city)
                lines.append(f"  • {city}" + (f"  🕐 {t}" if t else ""))
            lines.append("")
        send_message(chat_id, "\n".join(lines))
        return

    if text.startswith("/help"):
        send_message(chat_id,
            "⚡ *Weather Edge Bot*\n\n"
            "/start — enter access code\n"
            "/analyze — get weather analysis\n"
            "/cities — list all cities\n"
            "/help — this message\n\n"
            "_No code? DM @NethulaRashvin on X_"
        )
        return

    state = user_state.get(user_id, {})
    if state.get("step") == "waiting_code":
        send_message(chat_id, "🔄 Validating your code...")
        result = validate_code(text)
        if result.get("ok"):
            set_user_code(user_id, text)
            user_state.pop(user_id, None)
            send_message(chat_id,
                f"✅ *Access granted!*\n\n"
                f"👤 `{result.get('subscriber_id')}`\n"
                f"📅 Expires: {result.get('expires_at')} ({result.get('days_left')} days left)\n\n"
                f"Use /analyze to get started!"
            )
        else:
            send_message(chat_id,
                f"❌ *Invalid code:* {result.get('error', 'Unknown error')}\n\n"
                f"Try again or DM @NethulaRashvin on X."
            )
        return

    if not get_user_code(user_id):
        send_message(chat_id, "👋 Use /start to begin.")
    else:
        send_message(chat_id, "Use /analyze to get a weather analysis or /help for commands.")

# ── Callback handler ──────────────────────────────────────────────────────────

def handle_callback(callback):
    query_id = callback["id"]
    user_id  = callback["from"]["id"]
    chat_id  = callback["message"]["chat"]["id"]
    data     = callback.get("data", "")

    answer_callback(query_id)

    if not get_user_code(user_id):
        send_message(chat_id, "🔒 Session expired. Please use /start to log in again.")
        return

    if data == "noop":
        return

    if data in ("back_to_cities", "new_city"):
        user_state[user_id] = {"step": "waiting_city"}
        send_city_buttons(chat_id)
        return

    if data.startswith("city:"):
        city = data[5:]
        user_state[user_id] = {"step": "waiting_date", "city": city}
        send_date_buttons(chat_id, city)
        return

    if data.startswith("date:"):
        date_str = data[5:]
        state    = user_state.get(user_id, {})
        city     = state.get("city", "")
        code     = get_user_code(user_id)

        if not city:
            send_message(chat_id, "⚠️ Session lost. Please use /analyze to start again.")
            return

        user_state[user_id] = {"step": "has_result", "city": city}
        send_message(chat_id,
            f"⏳ Fetching analysis for *{city}* on {date_str}...\n_Takes ~5 seconds_"
        )

        data_resp = get_weather(city, date_str, code)

        if "error" in data_resp:
            if data_resp.get("auth") is False:
                del_user_code(user_id)
                user_state.pop(user_id, None)
                send_message(chat_id, "🔒 Your access code has expired. Use /start to re-enter.")
            else:
                send_message(chat_id, f"❌ Error: {data_resp['error']}")
                send_post_result_buttons(chat_id, city)
            return

        send_message(chat_id, format_weather(data_resp))
        send_post_result_buttons(chat_id, city)

# ── Vercel serverless handler ─────────────────────────────────────────────────

class handler(BaseHTTPRequestHandler):

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body   = self.rfile.read(length)
        try:
            update = json.loads(body)
            if "message" in update:
                handle_message(update["message"])
            elif "callback_query" in update:
                handle_callback(update["callback_query"])
        except Exception as e:
            print(f"Webhook error: {e}")
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"WeatherEdge Bot is running.")

    def log_message(self, format, *args):
        pass
