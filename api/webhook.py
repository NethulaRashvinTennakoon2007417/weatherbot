"""
WeatherEdge Telegram Bot — Vercel Webhook Version
Uses inline buttons for city and date selection.
"""

import json
import os
import requests as req
from datetime import datetime, date, timedelta
from http.server import BaseHTTPRequestHandler

BOT_TOKEN    = os.environ.get("TELEGRAM_TOKEN", "")
VERCEL_URL   = os.environ.get("WEATHER_VERCEL_URL", "https://weatheredge-weld.vercel.app")
TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"

validated_users: dict = {}
user_state: dict      = {}

CITIES = [
    "Atlanta", "Chicago", "Dallas", "New York", "Los Angeles",
    "Miami", "London", "Wellington", "Seoul", "Buenos Aires",
    "Tokyo", "Sydney", "Toronto"
]


def send_message(chat_id, text, reply_markup=None, parse_mode="Markdown"):
    payload = {"chat_id": chat_id, "text": text, "parse_mode": parse_mode}
    if reply_markup:
        payload["reply_markup"] = json.dumps(reply_markup)
    req.post(f"{TELEGRAM_API}/sendMessage", json=payload, timeout=10)


def answer_callback(callback_id, text=""):
    req.post(f"{TELEGRAM_API}/answerCallbackQuery",
             json={"callback_query_id": callback_id, "text": text}, timeout=5)


def send_city_buttons(chat_id):
    rows = []
    for i in range(0, len(CITIES), 2):
        row = [{"text": c, "callback_data": f"city:{c}"} for c in CITIES[i:i+2]]
        rows.append(row)
    markup = {"inline_keyboard": rows}
    send_message(chat_id, "🌍 *Select a city:*", reply_markup=markup)


def send_date_buttons(chat_id, city):
    today = date.today()
    dates = [
        (today,                     "Today"),
        (today + timedelta(days=1), "Tomorrow"),
        (today + timedelta(days=2), (today + timedelta(days=2)).strftime("%b %d")),
        (today + timedelta(days=3), (today + timedelta(days=3)).strftime("%b %d")),
        (today + timedelta(days=4), (today + timedelta(days=4)).strftime("%b %d")),
        (today + timedelta(days=5), (today + timedelta(days=5)).strftime("%b %d")),
    ]
    rows = []
    for i in range(0, len(dates), 3):
        row = [
            {"text": label, "callback_data": f"date:{d.strftime('%Y-%m-%d')}"}
            for d, label in dates[i:i+3]
        ]
        rows.append(row)
    markup = {"inline_keyboard": rows}
    send_message(chat_id, f"📅 *Select a date for {city}:*", reply_markup=markup)


def validate_code(code):
    try:
        r = req.post(f"{VERCEL_URL}/api/validate_code",
                     json={"code": code}, timeout=15)
        return r.json()
    except Exception as e:
        return {"ok": False, "error": str(e)}


def get_weather(city, date_str, code):
    try:
        r = req.get(
            f"{VERCEL_URL}/api/weather/{req.utils.quote(city)}/{date_str}",
            headers={"X-Access-Code": code},
            timeout=15
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
    intel_conf = data.get("intel_confidence", "") or data.get("confidence", "")

    if days_out == 0:    day_label = "Today"
    elif days_out == 1:  day_label = "Tomorrow"
    elif days_out < 0:   day_label = f"{abs(days_out)}d ago"
    else:                day_label = f"In {days_out} days"

    om_peak   = data.get("om_peak")
    nws_peak  = data.get("nws_peak")
    vc_peak   = data.get("vc_peak")
    wu_peak   = data.get("wu_peak")
    intl_peak = data.get("intl_peak")
    mm        = data.get("multi_model_peaks") or {}
    eq        = data.get("ensemble_quantiles") or {}
    brackets  = data.get("brackets") or []
    precip    = data.get("precip_risk", 0)
    wind      = data.get("wind_max", 0)

    lines = [
        "⚡ *Weather Edge Analysis*",
        f"{flag} *{city}* — {dt} _{day_label}_",
        "",
    ]

    if consensus:
        conf_emoji = {"high": "🟢", "medium": "🟡", "low": "🔴"}.get(intel_conf, "⚪")
        lines.append(f"🎯 *Consensus Peak: {consensus}{sym}*  {conf_emoji} {intel_conf.upper()}")

    lines.append("")
    lines.append("📡 *Sources:*")
    if wu_peak:   lines.append(f"  • WU: `{wu_peak}{sym}`")
    if om_peak:   lines.append(f"  • Open-Meteo: `{om_peak}{sym}`")
    if nws_peak:  lines.append(f"  • NWS: `{nws_peak}{sym}`")
    if vc_peak:   lines.append(f"  • Visual Crossing: `{vc_peak}{sym}`")
    if intl_peak: lines.append(f"  • Intl: `{intl_peak}{sym}`")

    if mm:
        lines.append("")
        lines.append("🤖 *Multi-Model:*")
        for model, val in mm.items():
            if val: lines.append(f"  • {model}: `{val}{sym}`")
        agreement = data.get("intel_agreement", "")
        spread    = data.get("intel_spread")
        if agreement:
            agree_emoji = {"strong": "✅", "moderate": "⚠️", "poor": "❌"}.get(agreement, "")
            lines.append(f"  {agree_emoji} {agreement.upper()}" + (f" · spread {spread}{sym}" if spread else ""))

    p10 = eq.get("p10"); p50 = eq.get("p50"); p90 = eq.get("p90")
    if p10 and p50 and p90:
        lines.append("")
        lines.append(f"📊 *Ensemble:* P10 `{p10}{sym}` · P50 `{p50}{sym}` · P90 `{p90}{sym}`")

    if precip or wind:
        lines.append("")
        if precip: lines.append(f"🌧 Precip risk: {precip}%")
        if wind:   lines.append(f"💨 Max wind: {wind} mph")

    if brackets:
        lines.append("")
        lines.append("🎲 *Top Brackets:*")
        for b in sorted(brackets, key=lambda x: x.get("prob", 0), reverse=True)[:3]:
            lines.append(f"  `{b.get('label')}` → {b.get('prob', 0):.1f}%")

    lines.append("")
    lines.append("_Use /analyze for another city_")
    return "\n".join(lines)


def handle_message(message):
    chat_id = message["chat"]["id"]
    user_id = message["from"]["id"]
    text    = message.get("text", "").strip()

    if text.startswith("/start"):
        if user_id in validated_users:
            send_message(chat_id,
                "✅ You're already logged in!\n\n"
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
        if user_id not in validated_users:
            send_message(chat_id, "🔒 Please use /start to enter your access code first.")
            return
        user_state[user_id] = {"step": "waiting_city"}
        send_city_buttons(chat_id)
        return

    if text.startswith("/cities"):
        if user_id not in validated_users:
            send_message(chat_id, "🔒 Please use /start to enter your access code first.")
            return
        city_list = "\n".join([f"• {c}" for c in CITIES])
        send_message(chat_id, f"🌍 *Available Cities:*\n\n{city_list}")
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
            validated_users[user_id] = text
            user_state.pop(user_id, None)
            send_message(chat_id,
                f"✅ *Access granted!*\n\n"
                f"👤 `{result.get('subscriber_id')}`\n"
                f"📅 Expires: {result.get('expires_at')} ({result.get('days_left')}d left)\n\n"
                f"Use /analyze to get started!"
            )
        else:
            send_message(chat_id,
                f"❌ *Invalid code:* {result.get('error', 'Unknown error')}\n\n"
                f"Try again or DM @NethulaRashvin on X."
            )
        return

    send_message(chat_id, "Use /analyze to get a weather analysis or /help for commands.")


def handle_callback(callback):
    query_id = callback["id"]
    user_id  = callback["from"]["id"]
    chat_id  = callback["message"]["chat"]["id"]
    data     = callback.get("data", "")

    answer_callback(query_id)

    if user_id not in validated_users:
        send_message(chat_id, "🔒 Please use /start to enter your access code first.")
        return

    if data.startswith("city:"):
        city = data[5:]
        user_state[user_id] = {"step": "waiting_date", "city": city}
        send_date_buttons(chat_id, city)
        return

    if data.startswith("date:"):
        date_str  = data[5:]
        state     = user_state.get(user_id, {})
        city      = state.get("city", "")
        code      = validated_users.get(user_id, "")

        if not city:
            send_message(chat_id, "Please use /analyze to start again.")
            return

        user_state.pop(user_id, None)
        send_message(chat_id,
            f"⏳ Fetching analysis for *{city}* on {date_str}...\n_Takes ~5 seconds_"
        )

        data_resp = get_weather(city, date_str, code)

        if "error" in data_resp:
            if data_resp.get("auth") is False:
                validated_users.pop(user_id, None)
                send_message(chat_id, "🔒 Your code has expired. Use /start to re-enter.")
            else:
                send_message(chat_id, f"❌ Error: {data_resp['error']}")
            return

        send_message(chat_id, format_weather(data_resp))
        return


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
            print(f"Error: {e}")
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"WeatherEdge Bot is running.")
