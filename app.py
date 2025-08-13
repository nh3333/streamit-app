# ---- imports ----
import time
import requests
import pandas as pd
import streamlit as st
from datetime import datetime

# ---- page config ----
st.set_page_config(page_title="株価ビューア（学習用シンプル版）", layout="wide")
st.title("Secrets × Cache で高速株価ビューア（シンプル版）")

# ---- secrets ----
API_KEY = st.secrets.get("ALPHAVANTAGE_API_KEY")
if not API_KEY:
    st.error("Secrets に ALPHAVANTAGE_API_KEY を設定してください。")
    st.stop()

# ---- helpers ----
def normalize_symbol(raw: str) -> str:
    """入力の余分な空白を取り、大文字に統一（米株想定）。"""
    return (raw or "").strip().upper()

@st.cache_data(ttl=15 * 60)
def fetch_daily(symbol: str, api_key: str) -> pd.DataFrame:
    """
    Alpha Vantage の日足データを取得。
    失敗/レート制限時は短い待ちを挟んで1回だけリトライ。
    """
    def _call(func: str):
        url = "https://www.alphavantage.co/query"
        params = {
            "function": func,                 # "TIME_SERIES_DAILY" or "TIME_SERIES_DAILY_ADJUSTED"
            "symbol": symbol,
            "apikey": api_key,
            "outputsize": "compact",          # 直近100営業日程度
        }
        r = requests.get(url, params=params, timeout=30)
        r.raise_for_status()
        return r.json()

    # まず通常のDaily
    data = _call("TIME_SERIES_DAILY")
    if "Note" in data:              # レート制限
        time.sleep(12)
        data = _call("TIME_SERIES_DAILY")

    ts = data.get("Time Series (Daily)")
    if not ts:
        # 調整後(Adjusted)でも試す
        data2 = _call("TIME_SERIES_DAILY_ADJUSTED")
        if "Note" in data2:
            time.sleep(12)
            data2 = _call("TIME_SERIES_DAILY_ADJUSTED")
        ts = data2.get("Time Series (Daily)") or data2.get("Time Series (Daily Adjusted)")

    if not ts:
        raise RuntimeError("APIは応答しましたが、日足データが見つかりません。少し待って再試行してください。")

    df = pd.DataFrame(ts).T.rename(columns={
        "1. open": "Open",
        "2. high": "High",
        "3. low":  "Low",
        "4. close":"Close",
        "5. volume":"Volume",
        # Adjustedのキーにも一応対応
        "5. adjusted close": "Close",
        "6. volume": "Volume",
    })

    # 数値化
    for col in ["Open", "High", "Low", "Close", "Volume"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # 日付をIndex化して昇順に
    df.index = pd.to_datetime(df.index)
    df = df.sort_index()
    return df

# ---- sidebar ----
with st.sidebar:
    st.header("ティッカー（米株）")
    raw_symbol = st.text_input("例: AAPL / MSFT / GOOGL", "MSFT")
    symbol = normalize_symbol(raw_symbol)
    period = st.slider("表示本数（日足換算）", 30, 200, 120)

    if st.button("キャッシュをクリアして再取得"):
        st.cache_data.clear()
        st.toast("キャッシュをクリアしました。少し待ってから再取得してください。", icon="🧹")

    st.caption("※Alpha Vantage 無料キーは主に米株対応（日本株 .T は不可/不安定）")

# ---- fallback store ----
if "last_ok" not in st.session_state:
    st.session_state.last_ok = {}

# ---- fetch ----
if not symbol:
    st.stop()

try:
    with st.spinner("データ取得中…"):
        df = fetch_daily(symbol, API_KEY)
    st.session_state.last_ok[symbol] = df
    status_msg = "最新データ（APIから取得）"
except Exception as e:
    if symbol in st.session_state.last_ok:
        df = st.session_state.last_ok[symbol]
        status_msg = f"フォールバック表示：{e}"
        st.warning(str(e))
    else:
        st.error(str(e))
        st.stop()

# ---- 最終の表示対象（直近 period 本）
dfp = df.tail(period).copy()

# ---- charts ----
st.subheader(f"{symbol} 価格（終値）")
st.caption(status_msg)
st.line_chart(dfp["Close"])

st.subheader("出来高")
st.bar_chart(dfp["Volume"])

# ---- table & CSV ----
st.subheader("直近の行")
st.dataframe(dfp.tail(10))

st.download_button(
    "CSVをダウンロード",
    dfp.to_csv().encode("utf-8-sig"),
    file_name=f"{symbol}_{datetime.now().date()}.csv",
    mime="text/csv",
)
