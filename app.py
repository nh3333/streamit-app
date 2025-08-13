# ---- imports ----
import streamlit as st
import time
import requests
import pandas as pd
import streamlit as st
from datetime import datetime
import plotly.graph_objects as go

# ---- page config ----
st.set_page_config(page_title="株価ビューア（ローソク足対応）", layout="wide")
st.title("Secrets × Cache で高速株価ビューア")

# ---- secrets ----
API_KEY = st.secrets.get("ALPHAVANTAGE_API_KEY")
if not API_KEY:
    st.error("Secrets に ALPHAVANTAGE_API_KEY を設定してください。")
    st.stop()

# ---- helpers ----
def normalize_symbol(raw: str) -> str:
    return (raw or "").strip().upper()

@st.cache_data(ttl=15 * 60)
def fetch_daily(symbol: str, api_key: str) -> pd.DataFrame:
    """Alpha Vantage 日足取得。Adjustedにも対応、制限時は短いリトライ。"""
    def _call(func: str):
        url = "https://www.alphavantage.co/query"
        params = {"function": func, "symbol": symbol, "apikey": api_key, "outputsize": "compact"}
        r = requests.get(url, params=params, timeout=30)
        r.raise_for_status()
        return r.json()

    # 普通の日足
    data = _call("TIME_SERIES_DAILY")
    if "Note" in data:
        time.sleep(12)
        data = _call("TIME_SERIES_DAILY")

    ts = data.get("Time Series (Daily)")
    if not ts:
        # 調整後も試す
        data2 = _call("TIME_SERIES_DAILY_ADJUSTED")
        if "Note" in data2:
            time.sleep(12)
            data2 = _call("TIME_SERIES_DAILY_ADJUSTED")
        ts = data2.get("Time Series (Daily)") or data2.get("Time Series (Daily Adjusted)")

    if not ts:
        raise RuntimeError("APIは応答しましたが日足データが見つかりません。少し待って再試行してください。")

    df = pd.DataFrame(ts).T.rename(columns={
        "1. open":"Open","2. high":"High","3. low":"Low","4. close":"Close","5. volume":"Volume",
        "5. adjusted close":"Close","6. volume":"Volume"
    })
    for col in ["Open","High","Low","Close","Volume"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    df.index = pd.to_datetime(df.index)
    return df.sort_index()

def resample_ohlc(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    o = df["Open"].resample(rule).first()
    h = df["High"].resample(rule).max()
    l = df["Low"].resample(rule).min()
    c = df["Close"].resample(rule).last()
    v = df["Volume"].resample(rule).sum()
    out = pd.concat([o,h,l,c,v], axis=1)
    out.columns = ["Open","High","Low","Close","Volume"]
    return out.dropna(how="any")

# ---- sidebar ----
with st.sidebar:
    st.header("ティッカー（米株）")
    raw_symbol = st.text_input("例: AAPL / MSFT / GOOGL", "MSFT")
    symbol = normalize_symbol(raw_symbol)
    period = st.slider("表示本数（日足換算）", 60, 250, 180)
    tf = st.selectbox("足種", ["日足", "週足", "月足"])
    chart_kind = st.radio("チャート種類", ["折れ線", "ローソク足"], horizontal=True)
    show_sma = st.checkbox("SMA20/50 を表示", value=True)
    if st.button("キャッシュをクリアして再取得"):
        st.cache_data.clear()
        st.toast("キャッシュをクリアしました。1分空けると成功率が上がります。", icon="🧹")
    st.caption("※Alpha Vantage 無料キーは主に米株対応。日本株(.T)は不可/不安定。")

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
        st.error(str(e)); st.stop()

# ---- timeframe ----
if tf == "週足":
    dfp = resample_ohlc(df, "W")
elif tf == "月足":
    dfp = resample_ohlc(df, "M")
else:
    dfp = df.copy()
dfp = dfp.tail(period).copy()

if show_sma:
    dfp["SMA20"] = dfp["Close"].rolling(20).mean()
    dfp["SMA50"] = dfp["Close"].rolling(50).mean()

# ---- chart ----
st.subheader(f"{symbol} 価格（{tf}）")
st.caption(status_msg)

if chart_kind == "折れ線":
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=dfp.index, y=dfp["Close"], mode="lines", name="Close"))
    if show_sma and "SMA20" in dfp:
        fig.add_trace(go.Scatter(x=dfp.index, y=dfp["SMA20"], mode="lines", name="SMA20"))
        fig.add_trace(go.Scatter(x=dfp.index, y=dfp["SMA50"], mode="lines", name="SMA50"))
    fig.update_layout(height=480, margin=dict(l=10,r=10,t=10,b=10))
    st.plotly_chart(fig, use_container_width=True)
else:
    fig = go.Figure([go.Candlestick(
        x=dfp.index, open=dfp["Open"], high=dfp["High"], low=dfp["Low"], close=dfp["Close"], name="Candle"
    )])
    if show_sma and "SMA20" in dfp:
        fig.add_trace(go.Scatter(x=dfp.index, y=dfp["SMA20"], mode="lines", name="SMA20"))
        fig.add_trace(go.Scatter(x=dfp.index, y=dfp["SMA50"], mode="lines", name="SMA50"))
    fig.update_layout(xaxis_rangeslider_visible=False, height=520, margin=dict(l=10,r=10,t=10,b=10))
    st.plotly_chart(fig, use_container_width=True)

# ---- volume & table ----
c1, c2 = st.columns([2,1])
with c1:
    st.caption("出来高")
    st.bar_chart(dfp["Volume"])
with c2:
    st.caption("直近の行")
    st.dataframe(dfp.tail(10))

st.download_button(
    "CSVをダウンロード",
    dfp.to_csv().encode("utf-8-sig"),
    file_name=f"{symbol}_{tf}_{datetime.now().date()}.csv",
    mime="text/csv",
)
