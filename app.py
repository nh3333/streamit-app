import requests
import pandas as pd
import streamlit as st   # ← これが関数デコレータより前に必要
from datetime import datetime
import plotly.graph_objects as go

@st.cache_data(ttl=15*60)
def fetch_daily(symbol: str, api_key: str) -> pd.DataFrame:
    """Alpha Vantage 日足取得。Adjustedにも対応し、制限時は短いリトライを行う。"""
    import time, requests, pandas as pd

    def _call(func: str):
        url = "https://www.alphavantage.co/query"
        params = {
            "function": func,          # "TIME_SERIES_DAILY" / "TIME_SERIES_DAILY_ADJUSTED"
            "symbol": symbol,
            "apikey": api_key,
            "outputsize": "compact",
        }
        r = requests.get(url, params=params, timeout=30)
        r.raise_for_status()
        return r.json()

    # まず通常のDaily
    data = _call("TIME_SERIES_DAILY")

    # レート制限なら数秒だけ待って1回リトライ
    if "Note" in data:
        time.sleep(12)
        data = _call("TIME_SERIES_DAILY")

    # 通常Dailyで無ければAdjustedも試す
    ts = data.get("Time Series (Daily)")
    if not ts:
        # 調整後の日足
        data2 = _call("TIME_SERIES_DAILY_ADJUSTED")
        if "Note" in data2:
            time.sleep(12)
            data2 = _call("TIME_SERIES_DAILY_ADJUSTED")
        ts = data2.get("Time Series (Daily)") or data2.get("Time Series (Daily Adjusted)")

    if not ts:
        # 空データをキャッシュに残さない工夫：例外で抜ける
        raise RuntimeError("APIは応答しましたが、日足データが見つかりませんでした。少し待って再試行してください。")

    df = (pd.DataFrame(ts).T.rename(columns={
        "1. open":"Open","2. high":"High","3. low":"Low","4. close":"Close","5. volume":"Volume",
        # Adjusted側のキーにも念のため対応
        "5. adjusted close":"Close", "6. volume":"Volume"
    }))
    # 数値化（文字列→float/int）
    for col in ["Open","High","Low","Close","Volume"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    df.index = pd.to_datetime(df.index)
    return df.sort_index()
