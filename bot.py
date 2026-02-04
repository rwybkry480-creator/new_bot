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
    return "Momentum Sniper Bot (v1.0 - 1h) is Live on Render!", 200

def run_server():
    # Render يزودنا بالمنفذ عبر متغير البيئة PORT
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

def analyze_momentum_strategy(df):
    try:
        # 1. حساب StochRSI
        stoch_rsi = ta.stochrsi(df['close'], length=14, rsi_length=14, k=3, d=3)
        df = pd.concat([df, stoch_rsi], axis=1)
        
        # 2. حساب SuperTrend (10, 3)
        supertrend = ta.supertrend(df['high'], df['low'], df['close'], length=10, multiplier=3)
        df = pd.concat([df, supertrend], axis=1)
        
        # 3. حساب RSI(6)
        df['rsi_6'] = ta.rsi(df['close'], length=6)
        
        df.dropna(inplace=True)
        if df.empty: return None, None

        current = df.iloc[-1]
        
        # تسميات الأعمدة
        stoch_k = 'STOCHRSIk_14_14_3_3'
        st_direction = 'SUPERTd_10_3.0'
        
        # الشروط المطلوبة
        if current[stoch_k] > 70 and current[st_direction] == 1 and current['rsi_6'] > 50:
            return 'BUY', current
            
    except Exception as e:
        logger.error(f"Analysis error: {e}")
    return None, None

async def scan_market(context: ContextTypes.DEFAULT_TYPE):
    job_name = "Manual Scan" if context.job.name.startswith("scan_") else "Scheduled Scan"
    chat_id = context.job.data['chat_id']
    
    if job_name == "Manual Scan":
        await context.bot.send_message(chat_id=chat_id, text="⏳ جاري فحص السوق (قناص الزخم - 1ساعة)...")
    
    try:
        all_tickers = client.get_ticker()
        symbols = [t['symbol'] for t in all_tickers if t['symbol'].endswith('USDT') and float(t.get('lastPrice', 0)) < 100]
    except Exception as e:
        logger.error(f"Ticker fetch error: {e}")
        return

    found_signals = 0
    for symbol in symbols[:150]:
        klines = get_binance_klines(symbol)
        if not klines: continue
        
        df = pd.DataFrame(klines, columns=['ts','open','high','low','close','vol','ct','qav','tr','tbba','tbqa','ig'])
        df['close'] = pd.to_numeric(df['close'])
        df['high'] = pd.to_numeric(df['high'])
        df['low'] = pd.to_numeric(df['low'])
        
        signal_type, data = analyze_momentum_strategy(df)
        
        if signal_type == 'BUY':
            found_signals += 1
            msg = (f"🚀 **إشارة قناص الزخم (1ساعة)**\n\n"
                   f"• العملة: `{symbol}`\n"
                   f"• السعر: `{data['close']:.5f}`\n"
                   f"• StochRSI: `{data['STOCHRSIk_14_14_3_3']:.2f}`\n"
                   f"• الحالة: **زخم صاعد مؤكد** ✅")
            await context.bot.send_message(chat_id=chat_id, text=msg, parse_mode='Markdown')
        await asyncio.sleep(0.1)

    if job_name == "Manual Scan":
        await context.bot.send_message(chat_id=chat_id, text=f"✅ اكتمل الفحص. تم العثور على {found_signals} إشارة.")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    await update.message.reply_text("مرحباً! بوت قناص الزخم (1h) يعمل الآن على Render.\nاستخدم /scan للفحص اليدوي.")
    
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
    # تشغيل خادم الويب في خيط منفصل لـ Render
    server_thread = Thread(target=run_server)
    server_thread.daemon = True
    server_thread.start()
    
    # تشغيل البوت
    run_bot()
