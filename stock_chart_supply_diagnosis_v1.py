
import time
import pandas as pd
import requests
import streamlit as st

start_time = time.time()

st.set_page_config(page_title="個別診断（チャートと需給）", page_icon="📈", layout="wide")
st.title("📈 個別診断（チャートと需給） Ver.1")
st.subheader("移動平均線 5・25・75・200日 × 5日・25日需給")

st.info(
    "価格トレンドは移動平均線、需給は5日と25日の売買代金・出来高で判定します。"
    "Ver.1では空売り・信用残を混ぜず、価格と市場売買データだけで診断します。"
)

JQUANTS_API_KEY = st.secrets["JQUANTS_API_KEY"]
HEADERS = {"x-api-key": JQUANTS_API_KEY}

PRESET_STOCKS = {
    "72030": "トヨタ自動車",
    "285A0": "キオクシアホールディングス",
    "77510": "キヤノン",
    "83060": "三菱UFJフィナンシャル・グループ",
    "62640": "マルマエ",
}

@st.cache_data(ttl=3600, show_spinner=False)
def fetch_daily(code):
    url = "https://api.jquants.com/v2/equities/bars/daily"
    r = requests.get(url, headers=HEADERS, params={"code": code}, timeout=30)
    if r.status_code != 200:
        raise RuntimeError(f"J-Quants取得エラー：{r.status_code}")
    data = r.json().get("data", [])
    if not data:
        raise RuntimeError("日足データが取得できませんでした。")
    df = pd.DataFrame(data)
    for col in ["AdjC", "AdjVo"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    return (
        df.dropna(subset=["Date", "AdjC", "AdjVo"])
          .sort_values("Date")
          .drop_duplicates("Date", keep="last")
          .reset_index(drop=True)
    )

@st.cache_data(ttl=86400, show_spinner=False)
def fetch_master():
    url = "https://api.jquants.com/v2/equities/master"
    r = requests.get(url, headers=HEADERS, timeout=30)
    if r.status_code != 200:
        return pd.DataFrame()
    data = r.json().get("data", [])
    if not data:
        return pd.DataFrame()
    df = pd.DataFrame(data)
    if "Code" in df.columns:
        df["Code"] = df["Code"].astype(str).str.zfill(5)
    return df

def calculate_metrics(df):
    out = df.copy()

    for w in [5, 25, 75, 200]:
        out[f"MA{w}"] = out["AdjC"].rolling(w, min_periods=w).mean()

    out["TradingValue"] = out["AdjC"] * out["AdjVo"]

    out["Value5"] = out["TradingValue"].rolling(5, min_periods=5).mean()
    out["Value25"] = out["TradingValue"].rolling(25, min_periods=25).mean()
    out["ValueRatio5_25"] = out["Value5"] / out["Value25"]

    out["VolMedian5"] = out["AdjVo"].rolling(5, min_periods=5).median()
    out["VolMedian25"] = out["AdjVo"].rolling(25, min_periods=25).median()
    out["MedianVolumeRatio5_25"] = out["VolMedian5"] / out["VolMedian25"]

    out["Return1"] = out["AdjC"] / out["AdjC"].shift(1) - 1
    out["Return5"] = out["AdjC"] / out["AdjC"].shift(5) - 1
    out["Return25"] = out["AdjC"] / out["AdjC"].shift(25) - 1

    return out

def judge_demand(row):
    v = row["ValueRatio5_25"]
    m = row["MedianVolumeRatio5_25"]

    if v > 1.30 and m > 1.15:
        return "🟢 強い改善"
    elif v > 1.10:
        return "🟢 改善"
    elif v >= 0.90:
        return "⚪ 中立"
    else:
        return "🔴 悪化"

def judge_trend(row):
    c = row["AdjC"]
    ma5 = row["MA5"]
    ma25 = row["MA25"]
    ma75 = row["MA75"]
    ma200 = row["MA200"]

    if c > ma5 > ma25 > ma75 > ma200:
        return "🟢 強い上昇"
    if c > ma25 > ma75:
        return "🟢 上昇"
    if c < ma25 and c > ma75:
        return "🟡 調整"
    if c > ma25 and ma25 <= ma75:
        return "👀 反転候補"
    if c < ma75:
        return "🔴 弱い"
    return "⚪ 中立"

def final_judgement(trend, demand):
    strong = trend in ["🟢 強い上昇", "🟢 上昇"]
    weak = trend in ["🔴 弱い", "🟡 調整"]
    demand_good = demand in ["🟢 強い改善", "🟢 改善"]

    if strong and demand_good:
        return "🟢 BUY候補"
    if strong and demand == "⚪ 中立":
        return "🔵 HOLD"
    if strong and demand == "🔴 悪化":
        return "🟡 WATCH"
    if weak and demand_good:
        return "👀 反転待ち"
    if weak and demand == "🔴 悪化":
        return "🔴 SELL / 回避"
    return "⚪ WAIT"

def diagnose_stock(code, company_name):
    df = calculate_metrics(fetch_daily(code))

    if len(df) < 205:
        return None, f"データ不足：{len(df)}営業日"

    latest = df.iloc[-1]
    needed = ["MA5", "MA25", "MA75", "MA200", "ValueRatio5_25", "MedianVolumeRatio5_25"]
    if latest[needed].isna().any():
        return None, "最新日の計算データが不足しています。"

    demand = judge_demand(latest)
    trend = judge_trend(latest)
    final = final_judgement(trend, demand)

    result = {
        "Code": code[:4],
        "Company": company_name,
        "Date": latest["Date"],
        "Close": latest["AdjC"],
        "MA5": latest["MA5"],
        "MA25": latest["MA25"],
        "MA75": latest["MA75"],
        "MA200": latest["MA200"],
        "Return1": latest["Return1"] * 100,
        "Return5": latest["Return5"] * 100,
        "Return25": latest["Return25"] * 100,
        "ValueRatio": latest["ValueRatio5_25"],
        "MedianVolumeRatio": latest["MedianVolumeRatio5_25"],
        "Trend": trend,
        "Demand": demand,
        "Final": final,
    }

    chart_df = (
        df[["Date", "AdjC", "MA5", "MA25", "MA75", "MA200"]]
        .tail(250)
        .set_index("Date")
    )

    return result, chart_df

def normalize_code(code):
    code = str(code).strip().upper()
    if len(code) == 4:
        return code + "0"
    if len(code) == 5:
        return code
    return None

def get_company_name(master_df, code):
    if master_df.empty or "Code" not in master_df.columns:
        return "個別入力銘柄"
    hit = master_df[master_df["Code"] == code]
    if hit.empty:
        return "個別入力銘柄"
    if "CoName" in hit.columns:
        return str(hit.iloc[0]["CoName"])
    return "個別入力銘柄"

# UI
st.sidebar.header("📈 診断対象")

preset_labels = [f"{c[:4]} {n}" for c, n in PRESET_STOCKS.items()]
selected = st.sidebar.selectbox("固定5銘柄", preset_labels)
custom = st.sidebar.text_input("任意の銘柄コード", placeholder="例：6976 / 6525 / 285A")

master_df = fetch_master()

if custom.strip():
    target_code = normalize_code(custom)
    if target_code is None:
        st.error("銘柄コードは4桁またはJ-Quants形式5桁で入力してください。")
        st.stop()
    target_name = get_company_name(master_df, target_code)
else:
    code4 = selected.split(" ")[0]
    target_code = code4 + "0"
    target_name = PRESET_STOCKS[target_code]

with st.spinner(f"📈 {target_code[:4]} {target_name} を診断中..."):
    diagnosis = diagnose_stock(target_code, target_name)

if diagnosis[0] is None:
    st.error(diagnosis[1])
    st.stop()

result, chart_df = diagnosis

st.divider()
st.header(f"{result['Code']} {result['Company']}")
st.write("📅 最新取引日：", result["Date"].date())

c1, c2, c3 = st.columns(3)
c1.metric("総合判定", result["Final"])
c2.metric("価格トレンド", result["Trend"])
c3.metric("需給", result["Demand"])

st.subheader("📊 価格トレンド")
ma_table = pd.DataFrame([{
    "終値": result["Close"],
    "5日線": result["MA5"],
    "25日線": result["MA25"],
    "75日線": result["MA75"],
    "200日線": result["MA200"],
    "1日騰落率(%)": result["Return1"],
    "5日騰落率(%)": result["Return5"],
    "25日騰落率(%)": result["Return25"],
}]).round(2)
st.dataframe(ma_table, use_container_width=True)

st.line_chart(chart_df)

st.subheader("💧 5日・25日需給")
supply_table = pd.DataFrame([{
    "5日平均売買代金 / 25日平均売買代金": round(result["ValueRatio"], 2),
    "5日出来高中央値 / 25日出来高中央値": round(result["MedianVolumeRatio"], 2),
    "需給判定": result["Demand"],
}])
st.dataframe(supply_table, use_container_width=True)

st.subheader("🧭 判定の読み方")
messages = {
    "🟢 BUY候補": "価格トレンドが上向きで、需給も改善しています。",
    "🔵 HOLD": "価格トレンドは強く、需給は中立です。",
    "🟡 WATCH": "価格はまだ強い一方、需給が悪化しています。",
    "👀 反転待ち": "価格はまだ弱い一方、需給が改善しています。",
    "🔴 SELL / 回避": "価格トレンドと需給の両方が弱い状態です。",
    "⚪ WAIT": "価格と需給の方向がまだ明確にそろっていません。",
}
st.write(messages[result["Final"]])

with st.expander("📘 需給判定ルール"):
    st.markdown("""
### 🟢 強い改善
- 5日平均売買代金 ÷ 25日平均売買代金 > **1.30**
- かつ
- 5日出来高中央値 ÷ 25日出来高中央値 > **1.15**

### 🟢 改善
- 5日平均売買代金 ÷ 25日平均売買代金 > **1.10**

### ⚪ 中立
- 売買代金倍率 **0.90 ～ 1.10**

### 🔴 悪化
- 売買代金倍率 **0.90未満**
""")

st.divider()
st.header("📋 固定5銘柄 一括診断")

if st.button("固定5銘柄を一括診断"):
    rows = []
    bar = st.progress(0)

    for i, (code, company) in enumerate(PRESET_STOCKS.items()):
        try:
            d = diagnose_stock(code, company)
            if d[0] is not None:
                r = d[0]
                rows.append({
                    "コード": r["Code"],
                    "銘柄名": r["Company"],
                    "終値": round(r["Close"], 1),
                    "価格トレンド": r["Trend"],
                    "需給": r["Demand"],
                    "総合判定": r["Final"],
                    "売買代金5/25": round(r["ValueRatio"], 2),
                    "出来高中央値5/25": round(r["MedianVolumeRatio"], 2),
                })
        except Exception:
            pass
        bar.progress((i + 1) / len(PRESET_STOCKS))

    bar.empty()

    if rows:
        batch_df = pd.DataFrame(rows)
        st.dataframe(batch_df, use_container_width=True)
        csv_data = batch_df.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")
        st.download_button(
            "📥 固定5銘柄診断をCSV保存",
            data=csv_data,
            file_name="stock_chart_supply_diagnosis.csv",
            mime="text/csv",
        )

st.caption(f"⏱️ 実行時間：{time.time() - start_time:.1f}秒")
