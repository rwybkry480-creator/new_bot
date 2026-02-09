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
    return "Breakout Strategy Bot (v1.0 - 1h) is Live on Render!", 200

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
        # حساب متوسط الحجم
        df['volume_ma'] = ta.sma(df['vol'], length=20)

        # حساب متوسطات متحركة للسعر
        df['ma20'] = ta.sma(df['close'], length=20)
        df['ma50'] = ta.sma(df['close'], length=50)

        df.dropna(inplace=True)
        if df.empty: return None, None

        current = df.iloc[-1]

        # شروط شراء: السعر فوق MA20 و MA50 مع حجم تداول قوي
        if current['close'] > current['ma20'] and current['close'] > current['ma50'] and current['vol'] > current['volume_ma']:
            return 'BUY', current

        # شروط بيع: السعر تحت MA20 و MA50 مع حجم تداول قوي
        elif current['close'] < current['ma20'] and current['close'] < current['ma50'] and current['vol'] > current['volume_ma']:
            return 'SELL', current

    except Exception as e:
        logger.error(f"Breakout Strategy error: {e}")
    return None, None

async def scan_market(context: ContextTypes.DEFAULT_TYPE):
    job_name = "Manual Scan" if context.job.name
