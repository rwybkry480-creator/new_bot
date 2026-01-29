# -----------------------------------------------------------------------------
# smc_bot_v14.2.py - (Falcon KDJ Sniper v14.2: Unfiltered & Aggressive)
# -----------------------------------------------------------------------------

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
app = Flask(__name__)

# --- إعدادات Binance ---
BINANCE_API_KEY = os.getenv("BINANCE_API_KEY")
BINANCE_SECRET_KEY = os.getenv("BINANCE_SECRET_KEY")
client = Client(BINANCE_API_KEY, BINANCE_SECRET_KEY)

# --- خادم الويب ---
@app.route('/')
def health_check():
    return "Falcon KDJ Sniper Bot Service (v14.2 - Unfiltered) is Running!", 200
def run_server():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

# --- دوال التحليل (معدلة بدون فلتر EMA 200) ---
def get_binance_klines(symbol, interval='15m', limit=30): # لم نعد بحاجة لشموع كثيرة
    try:
        klines = client.get_klines(symbol=symbol, interval=interval, limit=limit)
        return klines
    except Exception as e:
        logger.error(f"Error fetching klines for {symbol}: {e}")
        return None

def analyze_symbol_kdj(df):
    try:
        df.ta.kdj(append=True)

        required_cols = ['J_14_3_3', 'K_14_3_3', 'D_14_3_3']
        if not all(col in df.columns for col in required_cols):
            return None, None

        df.dropna(inplace=True)
        if len(df) < 2: return None, None
        previous, current = df.iloc[-2], df.iloc[-1]
        
        # --- الشرط الجديد والمبسط ---
        j_was_below = previous['J_14_3_3'] < previous['K_14_3_3'] or previous['J_14_3_3'] < previous['D_14_3_3']
        j_is_above = current['J_14_3_3'] > current['K_14_3_3'] and current['J_14_3_3'] > current['D_14_3_3']

        if j_was_below and j_is_above:
            return 'BUY', current
            
        j_was_above = previous['J_14_3_3'] > previous['K_14_3_3'] or previous['J_14_3_3'] > previous['D_14_3_3']
        j_is_below = current['J_14_3_3'] < current['K_14_3_3'] and current['J_14_3_3'] < current['D_14_3_3']

        if j_was_above and j_is_below:
            return 'SELL', current
            
    except Exception as e:
        logger.error(f"An unexpected error occurred during analysis: {e}")
    return None, None

# --- بقية الكود (scan_market, start, etc.) تبقى كما هي مع تعديل بسيط في الرسائل ---
async def scan_market(context: ContextTypes.DEFAULT_TYPE):
    job_name = "Manual Scan" if context.job.name.startswith("scan_") else "Scheduled Scan"
    logger.info(f"--- Starting {job_name} (Unfiltered) ---")
    chat_id = context.job.data['chat_id']
    if job_name == "Manual Scan":
        await context.bot.send_message(chat_id=chat_id, text=f"⏳ جاري {job_name} للسوق (فريم 15 دقيقة، بدون فلتر)...")
    try:
        all_tickers = client.get_ticker()
        symbols_to_scan = [t['symbol'] for t in all_tickers if t['symbol'].endswith('USDT') and float(t.get('lastPrice', 0)) < 100]
        logger.info(f"Found {len(symbols_to_scan)} symbols under $100 to analyze.")
    except Exception as e:
        logger.error(f"Failed to fetch tickers for filtering: {e}")
        return
    found_signals = 0
    for symbol in symbols_to_scan:
        klines = get_binance_klines(symbol)
        if not klines: continue
        df = pd.DataFrame(klines, columns=['timestamp','open','high','low','close','volume','close_time','quote_av','trades','tb_base_av','tb_quote_av','ignore'])
        df['close'] = pd.to_numeric(df['close'])
        signal_type, signal_data = analyze_symbol_kdj(df)
        if signal_type:
            found_signals += 1
            signal_emoji = "📈" if signal_type == 'BUY' else "📉"
            action_text = "شراء" if signal_type == 'BUY' else "بيع"
            message = (f"{signal_emoji} *[KDJ 15m - Unfiltered]* إشارة {action_text}!\n\n"
                       f"• **العملة:** `{symbol}`\n"
                       f"• **السعر:** `{signal_data['close']:.5f}`\n\n"
                       f"• **السبب:**\n"
                       f"  - خط J اخترق خطي K و D.")
            await context.bot.send_message(chat_id=chat_id, text=message, parse_mode='Markdown')
        await asyncio.sleep(0.1)
    logger.info(f"--- {job_name} complete. Found {found_signals} signals. ---")
    if job_name == "Manual Scan":
        summary_message = f"✅ **اكتمل الفحص اليدوي.**\nتم تحليل {len(symbols_to_scan)} عملة. تم العثور على {found_signals} إشارة."
        await context.bot.send_message(chat_id=chat_id, text=summary_message)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat_id = update.effective_message.chat_id
    await update.message.reply_html(f"👋 أهلاً بك يا {user.mention_html()}!\n\n"
                                    f"أنا بوت **Falcon KDJ Sniper (v14.2 - Unfiltered)**.\n\n"
                                    f"يقوم البوت الآن بالفحص التلقائي **كل 15 دقيقة** بدون فلتر EMA 200.")
    current_jobs = context.job_queue.get_jobs_by_name("scheduled_scan")
    for job in current_jobs:
        job.schedule_removal()
    context.job_queue.run_repeating(scan_market, interval=900, first=10, data={'chat_id': chat_id}, name="scheduled_scan")

async def scan_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_message.chat_id
    context.job_queue.run_once(scan_market, 1, data={'chat_id': chat_id}, name=f"scan_{chat_id}")

def run_bot():
    TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
    TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("scan", scan_command))
    job_data = {'chat_id': TELEGRAM_CHAT_ID}
    application.job_queue.run_repeating(scan_market, interval=900, first=10, data=job_data, name="scheduled_scan")
    logger.info("--- [Falcon KDJ Sniper v14.2] Bot is ready and running autonomously. ---")
    application.run_polling()

if __name__ == "__main__":
    logger.info("--- [Falcon KDJ Sniper v14.2] Starting Main Application ---")
    server_thread = Thread(target=run_server)
    server_thread.daemon = True
    server_thread.start()
    logger.info("--- [Falcon KDJ Sniper v14.2] Web Server has been started. ---")
    run_bot()
