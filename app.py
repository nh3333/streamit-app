import os, requests, pandas as pd, streamlit as st
from datetime import datetime

st.set_page_config(page_title="Secrets+Cache デモ", layout="wide")
st.title("Secrets × Cache で高速株価ビューア")

# ---- Secrets（APIキー） ----
API_KEY = st.secrets.get("ALPHAVANTAGE_API_KEY", None)

# ---- データ取得（キャッシュ） ----
@st.cache_data(ttl=15*60)  # 15分キャッシュ
def fetch_daily(symbol: str, api_key: str):
    """Alpha Vantage TIME_SERIES_DAILY"""
    url = "https://www.alphavantage.co/query"
    params = {"function":"TIME_SERIES_DAILY","symbol":symbol,"apikey":api_key, "outputsize":"compact"}
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    data = r.json()

    # API制限・エラーメッセージの扱い
    if "Error Message" in data:
        raise RuntimeError("ティッカーが不正か、データがありません。")
    if "Note" in data:
        raise RuntimeError("APIの呼び出し制限に達しました。少し待って再試行してください。")

    ts = data["Time Series (Daily)"]
    df = (pd.DataFrame(ts).T
            .rename(columns={"1. open":"Open","2. high":"High","3. low":"Low","4. close":"Close","5. volume":"Volume"})
            .astype({"Open":float,"High":float,"Low":float,"Close":float,"Volume":int}))
    df.index = pd.to_datetime(df.index)
    df = df.sort_index()
    return df

# ---- UI ----
symbol = st.sidebar.text_input("ティッカー（例：AAPL / MSFT / 7203.T は不可※）", "AAPL")
st.sidebar.caption("※Alpha Vantage無料キーのデイリーは主に米株ティッカー対応")

# ---- 実行 ----
if not API_KEY:
    st.error("Secrets に ALPHAVANTAGE_API_KEY を設定してください。")
    st.stop()

try:
    df = fetch_daily(symbol, API_KEY)
except Exception as e:
    st.warning(str(e))
    st.stop()

# ---- 表示 ----
st.subheader(f"{symbol} 価格（Daily）")
st.line_chart(df["Close"])
col1, col2 = st.columns(2)
with col1: st.bar_chart(df["Volume"])
with col2: st.dataframe(df.tail(10))

# ---- ダウンロード ----
st.download_button("CSVをダウンロード", df.to_csv().encode("utf-8-sig"),
                   file_name=f"{symbol}_{datetime.now().date()}.csv", mime="text/csv")

st.caption("データ提供: Alpha Vantage / キャッシュ: st.cache_data(ttl=15分)")
