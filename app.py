import time
import requests
import pandas as pd
import streamlit as st
from datetime import datetime

# ---- 画面設定 ----
st.set_page_config(page_title="Secrets×Cache 高速株価ビューア", layout="wide")
st.title("Secrets × Cache で高速株価ビューア")

# ---- APIキー ----
API_KEY = st.secrets.get("ALPHAVANTAGE_API_KEY")
if not API_KEY:
    st.error("Secrets に ALPHAVANTAGE_API_KEY を設定してください。")
    st.stop()

# ---- ユーティリティ ----
def normalize_symbol(raw: str) -> str:
    """入力の余分な空白を取り、大文字に統一。米株の想定で拡張子なしを基本に。"""
    if not raw:
        return ""
    s = raw.strip().upper()
    # 日本株(.T)などはこのAPIだと返らないことが多いのでその旨を注意
    if s.endswith(".T"):
        st.warning("無料キーのDailyは主に米株対応です（.Tは取得できない場合があります）。")
    return s

@st.cache_data(ttl=15 * 60)  # 15分キャッシュ
def fetch_daily(symbol: str, api_key: str) -> pd.DataFrame:
    """Alpha Vantageから日足を取得（成功時は昇順）。"""
    url = "https://www.alphavantage.co/query"
    params = {
        "function": "TIME_SERIES_DAILY",
        "symbol": symbol,
        "apikey": api_key,
        "outputsize": "compact",
    }
    r = requests.get(url, params=params, timeout=30)
    r.raise_for_status()
    data = r.json()

    # 典型的なエラーパターンを検出
    if "Error Message" in data:
        raise RuntimeError("ティッカーが不正か、対応外です。")
    if "Note" in data:
        # レート制限（1分5回/日500回）
        raise RuntimeError("API呼び出し制限に達しました。少し待って再試行してください。")

    ts = data.get("Time Series (Daily)")
    if not ts:
        raise RuntimeError("データが見つかりませんでした。")

    df = (
        pd.DataFrame(ts).T.rename(
            columns={
                "1. open": "Open",
                "2. high": "High",
                "3. low": "Low",
                "4. close": "Close",
                "5. volume": "Volume",
            }
        )
        .astype({"Open": float, "High": float, "Low": float, "Close": float, "Volume": int})
    )
    df.index = pd.to_datetime(df.index)
    df = df.sort_index()
    return df

# ---- サイドバー ----
with st.sidebar:
    st.header("ティッカー入力（米株）")
    raw = st.text_input("例: AAPL / MSFT / GOOGL", "AAPL")
    symbol = normalize_symbol(raw)
    st.caption("※Alpha Vantage 無料キーのDailyは主に米株に対応。レート制限あり（1分5回）。")
    refresh = st.button("キャッシュをクリアして再取得")

if refresh:
    st.cache_data.clear()
    st.toast("キャッシュをクリアしました。再取得します。", icon="🔄")

# ---- フォールバック用ストア ----
if "last_ok" not in st.session_state:
    st.session_state.last_ok = {}  # {symbol: df}

# ---- 取得＆フォールバック表示 ----
if not symbol:
    st.stop()

try:
    with st.spinner("データ取得中…"):
        df = fetch_daily(symbol, API_KEY)
    st.session_state.last_ok[symbol] = df  # 成功したら保存
    status_msg = "最新データ（APIから取得）"
except Exception as e:
    # 失敗時は前回の成功結果を使う
    if symbol in st.session_state.last_ok:
        df = st.session_state.last_ok[symbol]
        status_msg = f"フォールバック表示：{e}"
        st.warning(str(e))
        st.info("直近の成功データを表示しています（キャッシュ/前回取得）。")
    else:
        st.error(str(e))
        st.stop()

# ---- 表示 ----
st.subheader(f"{symbol} 価格（Daily）")
st.caption(status_msg)
st.line_chart(df["Close"])
c1, c2 = st.columns(2)
with c1:
    st.caption("出来高")
    st.bar_chart(df["Volume"])
with c2:
    st.caption("直近の行")
    st.dataframe(df.tail(10))

st.download_button(
    "CSVをダウンロード",
    df.to_csv().encode("utf-8-sig"),
    file_name=f"{symbol}_{datetime.now().date()}.csv",
    mime="text/csv",
)
