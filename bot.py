# -----------------------------------------------------------------------------
# ema_cross_bot_v1.1.py - (EMA Crossover Bot v1.1 - Corrected Cross Logic)
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
    return "EMA Crossover Bot Service (v1.1) is Running!", 200
def run_server():
    port = int(os.environ.get("PORT", 10001))
    app.run(host='0.0.0.0', port=port)

# --- دوال التحليل (استراتيجية تقاطع EMA المصححة) ---
def get_binance_klines(symbol, interval='15m', limit=120):
    try:
        klines = client.get_klines(symbol=symbol, interval=interval, limit=limit)
        return klines
    except Exception as e:
        logger.error(f"Error fetching klines for {symbol}: {e}")
        return None

def analyze_symbol_ema_cross(df):
    try:
        df.ta.ema(length=7, append=True)
        df.ta.ema(length=99, append=True)

        required_cols = ['EMA_7', 'EMA_99']
        if not all(col in df.columns for col in required_cols): return None, None
        df.dropna(inplace=True)
        if len(df) < 2: return None, None

        # --- المنطق الصحيح للتقاطع (بدون استخدام .cross) ---
        previous = df.iloc[-2] # الشمعة السابقة
        current = df.iloc[-1]  # الشمعة الحالية

        # إشارة الشراء (Golden Cross)
        if current['EMA_7'] > current['EMA_99'] and previous['EMA_7'] < previous['EMA_99']:
            return 'BUY', current
        
        # إشارة البيع (Death Cross)
        if current['EMA_7'] < current['EMA_99'] and previous['EMA_7'] > previous['EMA_99']:
            return 'SELL', current
            
    except Exception as e:
        # تغيير رسالة الخطأ لتكون أكثر تحديدًا
        logger.error(f"Error in analyze_symbol_ema_cross for symbol: {e}")
    return None, None

# --- بقية الكود يبقى كما هو ---
async def scan_market(context: ContextTypes.DEFAULT_TYPE):
    job_name = "Manual Scan" if context.job.name.startswith("scan_") else "Scheduled Scan"
    logger.info(f"--- Starting {job_name} (EMA Cross 15m - v1.1) ---")
    chat_id = context.job.data['chat_id']
    if job_name == "Manual Scan":
        await context.bot.send_message(chat_id=chat_id, text=f"⏳ جاري {job_name} للسوق (تقاطع EMA 7/99، فريم 15 دقيقة)...")
    
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
        
        signal_type, signal_data = analyze_symbol_ema_cross(df)
        
        if signal_type:
            found_signals += 1
            signal_emoji = "📈" if signal_type == 'BUY' else "📉"
            action_text = "تقاطع ذهبي (شراء)" if signal_type == 'BUY' else "تقاطع الموت (بيع)"
            message = (f"{signal_emoji} *[EMA 7/99 Cross - 15m]*\n"
                       f"إشارة **{action_text}**!\n\n"
                       f"• **العملة:** `{symbol}`\n"
                       f"• **السعر:** `{signal_data['close']:.5f}`\n\n"
                       f"• **السبب:**\n"
                       f"  - اخترق `EMA(7)` خط `EMA(99)`.\n"
                       f"  - EMA(7): `{signal_data['EMA_7']:.5f}`\n"
                       f"  - EMA(99): `{signal_data['EMA_99']:.5f}`")
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
                                    f"أنا بوت **EMA Crossover (v1.1)**.\n\n"
                                    f"أقوم بالبحث عن تقاطعات `EMA(7)` و `EMA(99)` على فريم **15 دقيقة**.\n"
                                    f"سيتم إجراء فحص تلقائي كل 15 دقيقة.")
    
    current_jobs = context.job_queue.get_jobs_by_name("scheduled_scan_ema")
    for job in current_jobs:
        job.schedule_removal()
        
    context.job_queue.run_repeating(scan_market, interval=900, first=10, data={'chat_id': chat_id}, name="scheduled_scan_ema")

async def scan_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_message.chat_id
    context.job_queue.run_once(scan_market, 1, data={'chat_id': chat_id}, name=f"scan_ema_{chat_id}")

def run_bot():
    TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
    TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("scan", scan_command))
    
    job_data = {'chat_id': TELEGRAM_CHAT_ID}
    application.job_queue.run_repeating(scan_market, interval=900, first=10, data=job_data, name="scheduled_scan_ema")
    
    logger.info("--- [EMA Crossover Bot v1.1] Bot is ready and running autonomously. ---")
    application.run_polling()

if __name__ == "__main__":
    logger.info("--- [EMA Crossover Bot v1.1] Starting Main Application ---")
    server_thread = Thread(target=run_server)
    server_thread.daemon = True
    server_thread.start()
    logger.info("--- [EMA Crossover Bot v1.1] Web Server has been started. ---")
    run_bot()
