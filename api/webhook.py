"""
WeatherEdge Telegram Bot — Vercel Webhook Version
──────────────────────────────────────────────────
This runs as a Vercel serverless function.
Telegram sends a POST request here for every message.

File: api/webhook.py
"""

import json
import os
import requests as req
from datetime import datetime, date, timedelta
from http.server import BaseHTTPRequestHandler

# ── Config (set these as Vercel environment variables) ───────────────────────
BOT_TOKEN  = os.environ.get("TELEGRAM_TOKEN", "")
VERCEL_URL = os.environ.get("WEATHER_VERCEL_URL", "https://weatheredge-weld.vercel.app")
TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"

# In-memory storage (resets on cold start — see note below)
# For persistent storage across requests, use Vercel KV or a free Redis
validated_users: dict[int, str] = {}
user_state: dict[int, dict] = {}  # {user_id: {"step": "waiting_city", "city": "..."}}

CITIES = [
    "Atlanta", "Chicago", "Dallas", "New York", "Los Angeles",
    "Miami", "London", "Wellington", "Seoul", "Buenos Aires",
    "Tokyo", "Sydney", "Toronto"
]


# ── Telegram helpers ──────────────────────────────────────────────────────────

def send_message(chat_id: int, text: str, reply_markup=None, parse_mode="Markdown"):
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode,
    }
    if reply_markup:
        payload["reply_markup"] = json.dumps(reply_markup)
    req.post(f"{TELEGRAM_API}/sendMessage", json=payload, timeout=10)


def send_keyboard(chat_id: int, text: str, buttons: list[list[str]]):
    keyboard = {
        "keyboard": [[{"text": b} for b in row] for row in buttons],
        "one_time_keyboard": True,
        "resize_keyboard": True
    }
    send_message(chat_id, text, reply_markup=keyboard)


def remove_keyboard(chat_id: int, text: str):
    keyboard = {"remove_keyboard": True}
    send_message(chat_id, text, reply_markup=keyboard)


# ── WeatherEdge API helpers ───────────────────────────────────────────────────

def validate_code(code: str) -> dict:
    try:
        r = req.post(
            f"{VERCEL_URL}/api/validate_code",
            json={"code": code},
            timeout=15
        )
        return r.json()
    except Exception as e:
        return {"ok": False, "error": str(e)}


def get_weather(city: str, date_str: str, code: str) -> dict:
    try:
        r = req.get(
            f"{VERCEL_URL}/api/weather/{req.utils.quote(city)}/{date_str}",
            headers={"X-Access-Code": code},
            timeout=15
        )
        return r.json()
    except Exception as e:
        return {"error": str(e)}


def format_weather(data: dict) -> str:
    city      = data.get("city", "")
    flag      = data.get("flag", "")
    dt        = data.get("date", "")
    sym       = data.get("unit_symbol", "°F")
    days_out  = data.get("days_out", 0)
    consensus = data.get("smart_consensus") or data.get("consensus_peak")
    intel_conf = data.get("intel_confidence", "") or data.get("confidence", "")

    if days_out == 0:   day_label = "Today"
    elif days_out == 1: day_label = "Tomorrow"
    elif days_out < 0:  day_label = f"{abs(days_out)}d ago"
    else:               day_label = f"In {days_out} days"

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
        f"⚡ *Weather Edge Analysis*",
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


# ── Message handler ───────────────────────────────────────────────────────────

def handle_message(message: dict):
    chat_id = message["chat"]["id"]
    user_id = message["from"]["id"]
    text    = message.get("text", "").strip()

    # Commands
    if text == "/start" or text.startswith("/start"):
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

    if text == "/analyze":
        if user_id not in validated_users:
            send_message(chat_id, "🔒 Please use /start to enter your access code first.")
            return
        user_state[user_id] = {"step": "waiting_city"}
        # Build city rows (2 per row)
        rows = [CITIES[i:i+2] for i in range(0, len(CITIES), 2)]
        send_keyboard(chat_id, "🌍 Select a city:", rows)
        return

    if text == "/cities":
        if user_id not in validated_users:
            send_message(chat_id, "🔒 Please use /start to enter your access code first.")
            return
        city_list = "\n".join([f"• {c}" for c in CITIES])
        send_message(chat_id, f"🌍 *Available Cities:*\n\n{city_list}")
        return

    if text == "/help":
        send_message(chat_id,
            "⚡ *Weather Edge Bot*\n\n"
            "/start — enter access code\n"
            "/analyze — get weather analysis\n"
            "/cities — list all cities\n"
            "/help — this message\n\n"
            "_No code? DM @NethulaRashvin on X_"
        )
        return

    # Conversation state handling
    state = user_state.get(user_id, {})
    step  = state.get("step")

    if step == "waiting_code":
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

    if step == "waiting_city":
        # Accept any city from the keyboard
        city = text
        user_state[user_id] = {"step": "waiting_date", "city": city}
        today = date.today()
        date_rows = [
            [today.strftime("%Y-%m-%d") + " (Today)"],
            [(today + timedelta(days=1)).strftime("%Y-%m-%d") + " (Tomorrow)"],
            [(today + timedelta(days=2)).strftime("%Y-%m-%d")],
            [(today + timedelta(days=3)).strftime("%Y-%m-%d")],
        ]
        send_keyboard(chat_id, f"📅 Select a date for *{city}*:", date_rows)
        return

    if step == "waiting_date":
        city     = state.get("city", "")
        date_str = text.split(" ")[0]  # strip "(Today)" etc
        code     = validated_users.get(user_id, "")

        try:
            datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            send_message(chat_id, "❌ Invalid date. Please use YYYY-MM-DD format.")
            return

        user_state.pop(user_id, None)
        remove_keyboard(chat_id, f"⏳ Fetching analysis for *{city}* on {date_str}...\n_Takes ~5 seconds_")

        data = get_weather(city, date_str, code)

        if "error" in data:
            if data.get("auth") is False:
                validated_users.pop(user_id, None)
                send_message(chat_id, "🔒 Your code has expired. Use /start to re-enter.")
            else:
                send_message(chat_id, f"❌ Error: {data['error']}")
            return

        send_message(chat_id, format_weather(data))
        return

    # Fallback
    send_message(chat_id, "Use /start to begin or /help for commands.")


# ── Vercel handler ────────────────────────────────────────────────────────────

class handler(BaseHTTPRequestHandler):

    def do_POST(self):
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length)

        try:
            update = json.loads(body)
            if "message" in update:
                handle_message(update["message"])
        except Exception as e:
            print(f"Error: {e}")

        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"WeatherEdge Bot is running.")
