# WeatherEdge Telegram Bot — Vercel Setup Guide

## Step 1 — Create your Telegram bot
1. Open Telegram → search @BotFather
2. Send /newbot
3. Choose a name e.g. "Weather Edge"
4. Choose a username e.g. "weatheredge_bot"
5. Copy the TOKEN it gives you

## Step 2 — Deploy to Vercel
1. Push this folder to a new GitHub repo (e.g. "weatheredge-bot")
2. Go to vercel.com → New Project → import that repo
3. Add these Environment Variables:
   - TELEGRAM_TOKEN = your bot token from BotFather
   - WEATHER_VERCEL_URL = https://weatheredge-weld.vercel.app
4. Click Deploy
5. Note your bot's Vercel URL e.g. https://weatheredge-bot.vercel.app

## Step 3 — Register the webhook with Telegram
After deploying, run this command ONCE in your terminal
(replace YOUR_BOT_TOKEN and YOUR_VERCEL_URL):

curl -X POST https://api.telegram.org/botYOUR_BOT_TOKEN/setWebhook \
  -H "Content-type: application/json" \
  -d '{"url": "https://YOUR_VERCEL_URL/api/webhook"}'

You should see: {"ok":true,"result":true,"description":"Webhook was set"}

## Step 4 — Test it
1. Open Telegram → search your bot username
2. Send /start
3. Enter a subscriber access code
4. Use /analyze to get weather analysis

## Important note about user sessions
Because Vercel is serverless, user sessions (validated codes) are stored
in memory and reset on cold starts. This means users may need to re-enter
their code occasionally (every few hours of inactivity).

This is normal for serverless bots. If you want persistent sessions,
you can upgrade to use Vercel KV (free tier available).

## How customers use it
1. They find your bot on Telegram (share the t.me/yourbotusername link)
2. Send /start → enter their access code
3. /analyze → pick city → pick date → get analysis in ~5 seconds
4. Same access codes work for both website and bot
