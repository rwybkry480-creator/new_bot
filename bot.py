import os
import logging
import asyncio
from threading import Thread
from flask import Flask
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from binance.client import Client
import pandas as pd
import pandas_ta as ta

# --- الإعدادات الأساسية ---
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# --- إعداد خادم الويب لـ Render ---
app = Flask(__name__)

@app.route('/')
def health_check():
    return "Breakout Strategy Bot (v2.0 - 1h) is Live on Render!", 200

def run_server():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

# --- إعدادات Binance ---
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY")
BINANCE_SECRET_KEY = os.getenv("BINANCE_SECRET_KEY")
client = Client(BINANCE_API_KEY, BINANCE_SECRET_KEY)

# --- دوال التحليل الفني ---
def get_binance_klines(symbol, interval='1h', limit=100):
    try:
        klines = client.get_klines(symbol=symbol, interval=interval, limit=limit)
        return klines
    except Exception as e:
        logger.error(f"Error fetching klines for {symbol}: {e}")
        return None

def analyze_breakout_strategy(df):
    try:
        # حساب المؤشرات
        df['volume_ma'] = ta.sma(df['vol'], length=20)
        df['ma20'] = ta.sma(df['close'], length=20)
        df['ma50'] = ta.sma(df['close'], length=50)
        df['rsi_14'] = ta.rsi(df['close'], length=14)

        df.dropna(inplace=True)
        if df.empty: return None, None

        current = df.iloc[-1]

        # شراء: السعر فوق MA20 و MA50 + حجم قوي + RSI > 55
        if current['close'] > current['ma20'] and current['close'] > current['ma50'] and current['vol'] > current['volume_ma'] and current['rsi_14'] > 55:
            return 'BUY', current

        # بيع: السعر تحت MA20 و MA50 + حجم قوي + RSI < 45
        elif current['close'] < current['ma20'] and current['close'] < current['ma50'] and current['vol'] > current['volume_ma'] and current['rsi_14'] < 45:
            return 'SELL', current

    except Exception as e:
        logger.error(f"Breakout Strategy error: {e}")
    return None, None

async def scan_market(context: ContextTypes.DEFAULT_TYPE):
    job_name = "Manual Scan" if context.job.name.startswith("scan_") else "Scheduled Scan"
    chat_id = context.job.data['chat_id']

    if job_name == "Manual Scan":
        await context.bot.send_message(chat_id=chat_id, text="⏳ جاري فحص السوق (استراتيجية الاختراق - 1ساعة)...")

    try:
        all_tickers = client.get_ticker()
        symbols = [t['symbol'] for t in all_tickers if t['symbol'].endswith('USDT') and float(t.get('lastPrice', 0)) < 100]
    except Exception as e:
        logger.error(f"Ticker fetch error: {e}")
        return

    found_signals = 0
    for symbol in symbols[:50]:  # تقليل عدد العملات الممسوحة إلى 50 فقط
        klines = get_binance_klines(symbol)
        if not klines: continue

        df = pd.DataFrame(klines, columns=['ts','open','high','low','close','vol','ct','qav','tr','tbba','tbqa','ig'])
        df['close'] = pd.to_numeric(df['close'])
        df['high'] = pd.to_numeric(df['high'])
        df['low'] = pd.to_numeric(df['low'])
        df['vol'] = pd.to_numeric(df['vol'])

        signal_type, data = analyze_breakout_strategy(df)

        if signal_type == 'BUY':
            found_signals += 1
            msg = (f"🚀 **إشارة شراء (اختراق + RSI)**\n\n"
                   f"• العملة: `{symbol}`\n"
                   f"• السعر: `{data['close']:.5f}`\n"
                   f"• MA20: `{data['ma20']:.5f}` | MA50: `{data['ma50']:.5f}`\n"
                   f"• RSI14: `{data['rsi_14']:.2f}`\n"
                   f"• الحجم الحالي: `{data['vol']:.2f}`\n"
                   f"• الحالة: **اختراق صاعد مع سيولة قوية** ✅")
            await context.bot.send_message(chat_id=chat_id, text=msg, parse_mode='Markdown')

        elif signal_type == 'SELL':
            found_signals += 1
            msg = (f"⚠️ **إشارة بيع (اختراق + RSI)**\n\n"
                   f"• العملة: `{symbol}`\n"
                   f"• السعر: `{data['close']:.5f}`\n"
                   f"• MA20: `{data['ma20']:.5f}` | MA50: `{data['ma50']:.5f}`\n"
                   f"• RSI14: `{data['rsi_14']:.2f}`\n"
                   f"• الحجم الحالي: `{data['vol']:.2f}`\n"
                   f"• الحالة: **اختراق هابط مع سيولة قوية** ❌")
            await context.bot.send_message(chat_id=chat_id, text=msg, parse_mode='Markdown')

        await asyncio.sleep(0.1)

    if job_name == "Manual Scan":
        await context.bot.send_message(chat_id=chat_id, text=f"✅ اكتمل الفحص. تم العثور على {found_signals} إشارة.")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    await update.message.reply_text("مرحباً! بوت استراتيجية الاختراق (1h) يعمل الآن على Render.\nاستخدم /scan للفحص اليدوي.")

    for job in context.job_queue.get_jobs_by_name("auto_scan"):
        job.schedule_removal()
    context.job_queue.run_repeating(scan_market, interval=3600, first=10, data={'chat_id': chat_id}, name="auto_scan")

async def scan_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    context.job_queue.run_once(scan_market, 1, data={'chat_id': chat_id}, name=f"scan_{chat_id}")

def run_bot():
    TOKEN = os.getenv("TELEGRAM_TOKEN")
    application = Application.builder().token(TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("scan", scan_cmd))

    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if chat_id:
        application.job_queue.run_repeating(scan_market, interval=3600, first=10, data={'chat_id': chat_id}, name="auto_scan")

    application.run_polling()

if __name__ == "__main__":
    server_thread = Thread(target=run_server)
    server_thread.daemon = True
    server_thread.start()
    run_bot()
