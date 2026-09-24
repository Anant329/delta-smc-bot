import os
import time
import pandas as pd
import requests
import matplotlib.pyplot as plt
import mplfinance as mpf

# ================= Configuration =================
DELTA_API_URL = "https://api.india.delta.exchange/v2/history/candles"
WATCHLIST = ["BTCUSD", "ETHUSD"]

TELEGRAM_BOT_TOKEN = "8897649002:AAHAhP3ILJO88FeZiEHN9A35E6CpMkS6N7I"
TELEGRAM_CHAT_ID = "7575594318"

def send_telegram_alert(image_path, caption):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
    try:
        with open(image_path, "rb") as img:
            payload = {"chat_id": TELEGRAM_CHAT_ID, "caption": caption, "parse_mode": "Markdown"}
            res = requests.post(url, data=payload, files={"photo": img}, timeout=25)
            print(f"Telegram Delivery Status: {res.status_code}")
    except Exception as e:
        print(f"Telegram Error: {e}")
    finally:
        if os.path.exists(image_path):
            os.remove(image_path)

def fetch_candles(symbol, resolution):
    try:
        end_time = int(time.time())
        # 60 dino ka data taaki daily candles 20 se zyada hon
        start_time = end_time - (3600 * 24 * 60)
        
        params = {
            "symbol": symbol,
            "resolution": resolution,
            "start": start_time,
            "end": end_time
        }
        res = requests.get(DELTA_API_URL, params=params, timeout=12).json()
        candles = res.get("result", [])
        if not candles:
            print(f"No candle data for {symbol} ({resolution})")
            return None
        
        df = pd.DataFrame(candles)
        for col in ["open", "high", "low", "close", "volume"]:
            df[col] = df[col].astype(float)
        
        df = df.iloc[::-1].reset_index(drop=True)
        df["time"] = pd.to_datetime(df["time"], unit="s")
        df.set_index("time", inplace=True)
        return df
    except Exception as e:
        print(f"Fetch Error ({symbol} {resolution}): {e}")
        return None

def calculate_rsi(series, period=14):
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / (loss + 1e-9)
    return 100 - (100 / (1 + rs))

def analyze_smc_setup(df_15m, df_1h, df_4h, df_1d):
    # Dynamic safe indexing
    d1_look = min(10, len(df_1d) - 1)
    h4_look = min(15, len(df_4h) - 1)
    
    d1_bull = df_1d['close'].iloc[-1] > df_1d['close'].iloc[-d1_look] if d1_look > 0 else True
    h4_bull = df_4h['close'].iloc[-1] > df_4h['close'].iloc[-h4_look] if h4_look > 0 else True
    macro_bias = "BULLISH" if (d1_bull and h4_bull) else ("BEARISH" if (not d1_bull and not h4_bull) else "NEUTRAL")
    
    # 15m Key Highs/Lows
    lookback = min(25, len(df_15m) - 5)
    recent = df_15m.iloc[-(lookback + 2) : -2]
    trigger_c = df_15m.iloc[-2]
    curr_c = df_15m.iloc[-1]
    
    swing_high = recent['high'].max()
    swing_low = recent['low'].min()
    
    # SMC Liquidity Sweep
    sweep_detected = None
    invalidation = None
    
    if trigger_c['low'] < swing_low and trigger_c['close'] > swing_low and (min(trigger_c['open'], trigger_c['close']) - trigger_c['low']) > abs(trigger_c['close'] - trigger_c['open']):
        sweep_detected = "BULLISH_SWEEP (Liquidity Grabbed)"
        invalidation = trigger_c['low']
    elif trigger_c['high'] > swing_high and trigger_c['close'] < swing_high and (trigger_c['high'] - max(trigger_c['open'], trigger_c['close'])) > abs(trigger_c['close'] - trigger_c['open']):
        sweep_detected = "BEARISH_SWEEP (Liquidity Grabbed)"
        invalidation = trigger_c['high']
        
    # FVG Check
    fvg_zone = None
    if len(df_15m) >= 5:
        c1 = df_15m.iloc[-4]
        c3 = df_15m.iloc[-2]
        if c3['low'] > c1['high']:
            fvg_zone = ("BULLISH_FVG", c1['high'], c3['low'])
        elif c3['high'] < c1['low']:
            fvg_zone = ("BEARISH_FVG", c3['high'], c1['low'])
            
    df_15m['rsi'] = calculate_rsi(df_15m['close'], 14)
    curr_rsi = df_15m['rsi'].iloc[-1]
    reversal_signal = None
    
    if sweep_detected and "BULLISH" in sweep_detected and curr_rsi < 42:
        reversal_signal = "CHoCH / REVERSAL BUY SIGNAL"
    elif sweep_detected and "BEARISH" in sweep_detected and curr_rsi > 58:
        reversal_signal = "CHoCH / REVERSAL SELL SIGNAL"
        
    return {
        "macro_bias": macro_bias,
        "sweep": sweep_detected,
        "fvg": fvg_zone,
        "reversal": reversal_signal,
        "swing_high": swing_high,
        "swing_low": swing_low,
        "invalidation": invalidation,
        "current_price": curr_c['close']
    }

def draw_smc_chart(df, symbol, setup_data, filename="temp_chart.png"):
    chart_slice = df.iloc[-40:].copy()
    chart_slice['ema20'] = chart_slice['close'].ewm(span=20).mean()
    chart_slice['ema50'] = chart_slice['close'].ewm(span=50).mean()
    
    hlines = [setup_data["swing_high"], setup_data["swing_low"]]
    hcolors = ['red', 'green']
    
    apds = [
        mpf.make_addplot(chart_slice['ema20'], color='#2962FF', width=1.2),
        mpf.make_addplot(chart_slice['ema50'], color='#FF6D00', width=1.2)
    ]
    
    fig, axlist = mpf.plot(
        chart_slice,
        type='candle',
        style='binance',
        addplot=apds,
        hlines=dict(hlines=hlines, colors=hcolors, linestyle='--', linewidths=1.2),
        title=f"Delta Futures: {symbol} (15m) - SMC Structure",
        returnfig=True,
        figsize=(9, 5)
    )
    
    if setup_data["fvg"]:
        _, bottom, top = setup_data["fvg"]
        ax = axlist[0]
        ax.axhspan(bottom, top, color='purple', alpha=0.25)
        
    out_name = f"{symbol}_{filename}"
    fig.savefig(out_name, bbox_inches='tight')
    plt.close(fig)
    return out_name

def run_scanner():
    print("🚀 Delta Futures SMC AI Scanner Started.")
    print("Fetching data and generating live charts...")
    
    first_run = True
    
    while True:
        for symbol in WATCHLIST:
            try:
                print(f"Analyzing {symbol}...")
                df_15m = fetch_candles(symbol, "15m")
                df_1h = fetch_candles(symbol, "1h")
                df_4h = fetch_candles(symbol, "4h")
                df_1d = fetch_candles(symbol, "1d")
                
                if any(x is None for x in [df_15m, df_1h, df_4h, df_1d]):
                    print(f"Skipping {symbol} due to missing data.")
                    continue
                    
                analysis = analyze_smc_setup(df_15m, df_1h, df_4h, df_1d)
                
                if first_run or analysis["sweep"] or analysis["reversal"]:
                    print(f"Drawing chart for {symbol}...")
                    img_file = draw_smc_chart(df_15m, symbol, analysis)
                    safe_hold = "45 to 90 Minutes (4-6 candles)"
                    
                    tag = "INITIAL SYNC" if first_run else "LIVE SMC ALERT"
                    
                    caption = (
                        f"🧠 *DELTA FUTURES SMC REPORT: {symbol}* [{tag}]\n\n"
                        f"• *Contract:* `{symbol}` (Futures)\n"
                        f"• *Macro Trend (1D/4H):* `{analysis['macro_bias']}`\n"
                        f"• *Current Price:* `${analysis['current_price']}`\n"
                        f"• *Structure:* `{analysis['sweep'] or 'RANGE MONITORING'}`\n"
                        f"• *Signal:* `{analysis['reversal'] or 'NORMAL FLOW'}`\n\n"
                        f"📍 *Liquidity Pools:*\n"
                        f"  - Buy-Side (Resistance): `${analysis['swing_high']}`\n"
                        f"  - Sell-Side (Support): `${analysis['swing_low']}`\n\n"
                        f"🛡️ *Invalidation / Ref SL:* `${analysis['invalidation'] or analysis['swing_low']}`\n"
                        f"⏱️ *Max Safe Holding Window:* `{safe_hold}`"
                    )
                    
                    send_telegram_alert(img_file, caption)
                    time.sleep(2)
            except Exception as err:
                print(f"Error on {symbol}: {err}")
                
        first_run = False
        print("Cycle finished. Monitoring for next candle (15 min)...")
        time.sleep(900)

if __name__ == "__main__":
    run_scanner()
