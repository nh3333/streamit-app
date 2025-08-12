import requests, pandas as pd, streamlit as st
from datetime import datetime
import plotly.graph_objects as go

st.set_page_config(page_title="株価ビューア（ローソク足対応）", layout="wide")
st.title("Secrets × Cache で高速株価ビューア")

API_KEY = st.secrets.get("ALPHAVANTAGE_API_KEY")
if not API_KEY:
    st.error("Secrets に ALPHAVANTAGE_API_KEY を設定してください。")
    st.stop()

# ---------- 小道具 ----------
def normalize_symbol(raw: str) -> str:
    return (raw or "").strip().upper()

@st.cache_data(ttl=15*60)
def fetch_daily(symbol: str, api_key: str) -> pd.DataFrame:
    """Alpha VantageのTIME_SERIES_DAILY（adjustedでない）"""
    url = "https://www.alphavantage.co/query"
    params = {"function": "TIME_SERIES_DAILY", "symbol": symbol,
              "apikey": api_key, "outputsize": "compact"}
    r = requests.get(url, params=params, timeout=30)
    r.raise_for_status()
    data = r.json()
    if "Error Message" in data:
        raise RuntimeError("ティッカーが不正か、対応外です。")
    if "Note" in data:
        raise RuntimeError("API呼び出し制限に達しました（無料は1分5回）。少し待って再試行してください。")
    ts = data.get("Time Series (Daily)")
    if not ts:
        raise RuntimeError("データが見つかりませんでした。")
    df = (pd.DataFrame(ts).T.rename(columns={
            "1. open":"Open","2. high":"High","3. low":"Low","4. close":"Close","5. volume":"Volume"})
          .astype({"Open":float,"High":float,"Low":float,"Close":float,"Volume":int}))
    df.index = pd.to_datetime(df.index)
    return df.sort_index()

def resample_ohlc(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    """日足から週足/月足に集計（OHLCV）"""
    o = df["Open"].resample(rule).first()
    h = df["High"].resample(rule).max()
    l = df["Low"].resample(rule).min()
    c = df["Close"].resample(rule).last()
    v = df["Volume"].resample(rule).sum()
    out = pd.concat([o,h,l,c,v], axis=1)
    out.columns = ["Open","High","Low","Close","Volume"]
    return out.dropna(how="any")

# ---------- サイドバー ----------
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
        st.toast("キャッシュをクリアしました", icon="🧹")
    st.caption("※Alpha Vantage 無料キーは主に米株対応。日本株(.T)は取れないことがあります。")

# ---------- フォールバック保存（APIレート制限対策） ----------
if "last_ok" not in st.session_state:
    st.session_state.last_ok = {}

# ---------- 取得 ----------
if not symbol:
    st.stop()

try:
    with st.spinner("取得中…"):
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

# ---------- 時間足変換 ----------
if tf == "週足":
    dfp = resample_ohlc(df, "W")
elif tf == "月足":
    dfp = resample_ohlc(df, "M")
else:
    dfp = df.copy()

# 表示範囲を末尾から period 本（週足・月足でも同じ本数でスライス）
dfp = dfp.tail(period).copy()

# 移動平均
if show_sma:
    dfp["SMA20"] = dfp["Close"].rolling(20).mean()
    dfp["SMA50"] = dfp["Close"].rolling(50).mean()

st.subheader(f"{symbol} 価格（{tf}）")
st.caption(status_msg)

# ---------- 描画 ----------
if chart_kind == "折れ線":
    # 折れ線 + オプションMA
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=dfp.index, y=dfp["Close"], mode="lines", name="Close"))
    if show_sma and "SMA20" in dfp:
        fig.add_trace(go.Scatter(x=dfp.index, y=dfp["SMA20"], mode="lines", name="SMA20"))
        fig.add_trace(go.Scatter(x=dfp.index, y=dfp["SMA50"], mode="lines", name="SMA50"))
    fig.update_layout(height=480, margin=dict(l=10,r=10,t=10,b=10))
    st.plotly_chart(fig, use_container_width=True)
else:
    # ローソク足 + オプションMA
    fig = go.Figure(
        data=[go.Candlestick(x=dfp.index, open=dfp["Open"], high=dfp["High"],
                             low=dfp["Low"], close=dfp["Close"], name="Candle")]
    )
    if show_sma and "SMA20" in dfp:
        fig.add_trace(go.Scatter(x=dfp.index, y=dfp["SMA20"], mode="lines", name="SMA20"))
        fig.add_trace(go.Scatter(x=dfp.index, y=dfp["SMA50"], mode="lines", name="SMA50"))
    fig.update_layout(xaxis_rangeslider_visible=False, height=520,
                      margin=dict(l=10,r=10,t=10,b=10))
    st.plotly_chart(fig, use_container_width=True)

# 出来高 & 直近
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
