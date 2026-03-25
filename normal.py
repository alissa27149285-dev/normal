import streamlit as st
import pandas as pd
import os
import datetime
import re
import uuid
import gspread
from google.oauth2.service_account import Credentials

# --- 設定頁面 ---
st.set_page_config(page_title="旅遊推薦系統", layout="centered")

# --- 定義標準縣市清單 ---
VALID_CITIES = [
    "台北市", "新北市", "桃園市", "台中市", "台南市", "高雄市",
    "基隆市", "宜蘭縣", "新竹縣", "苗栗縣", "彰化縣", "南投縣", "雲林縣", "嘉義縣", "屏東縣",
    "花蓮縣", "台東縣"
]

# --- 1. 資料讀取與清洗 ---
@st.cache_data
def load_data():
    try:
        csv_file = 'TAIWAN_FILTERED.csv'
        if not os.path.exists(csv_file):
            return None

        df = pd.read_csv(csv_file, encoding='utf-8-sig')
        df.columns = [c.strip() for c in df.columns]

        # 1. 欄位改名
        if '城市' in df.columns:
            df.rename(columns={'城市': '縣市'}, inplace=True)
        elif '縣市' not in df.columns and '地址' in df.columns:
            def get_city(addr):
                if pd.isna(addr): return None
                txt = str(addr).replace('臺', '台')
                for c in VALID_CITIES:
                    if c in txt: return c
                return None
            df['縣市'] = df['地址'].apply(get_city)

        # 2. 內容標準化
        if '縣市' in df.columns:
            df['縣市'] = df['縣市'].astype(str).str.strip().str.replace('臺', '台')
            df = df[df['縣市'].isin(VALID_CITIES)]

        if '類別編號' in df.columns:
            df['類別編號'] = df['類別編號'].astype(str).str.strip()

        # 3. 清理數字
        def clean_num(x):
            if pd.notnull(x):
                return int(re.sub(r'\D', '', str(x)) or 0)
            return 0
        df['評論數'] = df['評論數'].apply(clean_num)

        star_col = 'Google 評分' if 'Google 評分' in df.columns else 'Google 星級'
        df['Star'] = pd.to_numeric(df[star_col], errors='coerce')

        return df
    except Exception as e:
        st.error(f"資料讀取錯誤: {e}")
        return None

# --- 2. 主程式 ---
def main():
    st.title("🗺️ 旅遊推薦系統")
    st.caption("依照地區與主題，快速找出熱門景點")

    df = load_data()
    if df is None:
        st.error("❌ 找不到資料檔 `TAIWAN_FULL_REFINED.csv` (請確認檔案是否與 app.py 在同一個資料夾)")
        return

    # 初始化
    if 'step' not in st.session_state: st.session_state.step = 1
    if 'recs' not in st.session_state: st.session_state.recs = []
    if 'user_id' not in st.session_state:
        st.session_state.user_id = f"User_{str(uuid.uuid4())[:8]}"

    # ==========================================
    # 步驟 1: 設定條件
    # ==========================================
    if st.session_state.step == 1:
        st.info(f"🆔 使用者編號：**{st.session_state.user_id}**")

        # 1. 縣市選擇
        st.subheader("1. 選擇旅遊地區")
        available = sorted(list(set(df['縣市'].unique()) & set(VALID_CITIES)))
        final_options = [c for c in VALID_CITIES if c in available]
        
        selected_city = st.selectbox("您想去哪個縣市？", final_options)

        # 2. 主題選擇
        st.subheader("2. 選擇感興趣的主題")
        cat_options = {
            "F1": "F1 - 腎上腺素活動", "F2": "F2 - 荒野自然活動",
            "F3": "F3 - 派對、音樂與夜生活", "F4": "F4 - 陽光、水與沙灘",
            "F5": "F5 - 博物館、船遊與觀景點", "F6": "F6 - 主題與動物公園",
            "F7": "F7 - 文化遺產", "F8": "F8 - 運動與競賽",
            "F9": "F9 - 美食活動", "F10": "F10 - 健康與福祉",
            "F11": "F11 - 自然現象"
        }
        manual_cat = st.selectbox("請選擇類型：", list(cat_options.keys()), format_func=lambda x: cat_options[x])

        # 即時檢查
        match_count = len(df[(df['縣市'] == selected_city) & (df['類別編號'] == manual_cat)])
        if match_count == 0:
            st.error(f"❌ **{selected_city}** 沒有 **{manual_cat}** 類別的資料。")
        else:
            st.success(f"✅ **{selected_city}** 共有 **{match_count}** 筆相關資料。")

        st.markdown("<br>", unsafe_allow_html=True)

        if st.button("🔍 搜尋推薦景點", type="primary", use_container_width=True):
            process_filter(df, st.session_state.user_id, manual_cat, selected_city)
            st.session_state.step = 2
            st.rerun()

    # ==========================================
    # 步驟 2: 顯示結果
    # ==========================================
    elif st.session_state.step == 2:
        user = st.session_state.user_data
        st.header("推薦結果")

        st.markdown(f"""
        > **📍 地區：** {user['selected_city']}  
        > **🎯 主題：** {user['manual_cat_label']}
        """)

        if not st.session_state.recs:
            st.warning("⚠️ 該條件下無景點資料。")
        else:
            rec_df = pd.DataFrame(st.session_state.recs)
            st.subheader(f"🏆 推薦景點清單 (共 {len(rec_df)} 筆)")
            
            st.dataframe(
                rec_df[['rank', 'name', 'city', 'star', 'reviews']],
                hide_index=True, use_container_width=True,
                column_config={
                    "star": st.column_config.NumberColumn("評分", format="⭐ %.1f"),
                    "reviews": st.column_config.NumberColumn("評論數", format="%d 則"),
                    "name": "景點名稱",
                    "city": "縣市"
                }
            )

        st.divider()

        # 滿意度問卷
        st.subheader("4. 系統使用回饋")
        with st.form("academic_feedback"):
            st.markdown("### 🔹 知覺有用性 (PU)")
            pu1 = st.slider("PU1. 系統能幫助我更精準地推薦景點", 1, 5, 3)
            pu2 = st.slider("PU2. 系統能節省我過濾資訊的時間", 1, 5, 3)
            pu3 = st.slider("PU3. 系統能提升我規劃旅遊的效率", 1, 5, 3)
            
            st.markdown("---")
            
            st.markdown("### 🔹 使用者滿意度 (US)")
            us1 = st.slider("US1. 我滿意系統推薦的景點準確度", 1, 5, 3)
            us2 = st.slider("US2. 我滿意系統的介面設計與操作流程", 1, 5, 3)
            us3 = st.slider("US3. 整體而言我對此系統感到滿意", 1, 5, 3)
            
            st.markdown("---")
            other_text = st.text_area("其他建議 (選填)：")

            if st.form_submit_button("送出回饋並結束", type="primary", use_container_width=True):
                # 收集分數並轉換為字典，因之前邏輯使用字典存檔
                scores = {"PU1": pu1, "PU2": pu2, "PU3": pu3, "US1": us1, "US2": us2, "US3": us3}
                save_feedback(scores, other_text)
                st.session_state.step = 3
                st.rerun()

    # ==========================================
    # 步驟 3: 感謝
    # ==========================================
    elif st.session_state.step == 3:
        st.balloons()
        st.success("✅ 回饋已存檔！(可在專案資料夾查看 recommendation_log_simple.csv)")
        if st.button("🔄 重新搜尋"):
            for key in list(st.session_state.keys()): del st.session_state[key]
            st.rerun()

# --- 核心邏輯：純篩選 ---
def process_filter(df, user_id, manual_cat, selected_city):
    work_df = df[
        (df['縣市'] == selected_city) & 
        (df['類別編號'] == manual_cat)
    ].copy()

    # 排序 (評論數高優先 -> 評分高優先)
    sorted_df = work_df.sort_values(by=['評論數', 'Star'], ascending=[False, False])
    
    # 取前 10 名
    top_10 = sorted_df.head(10)

    recs = []
    rank = 1
    for _, r in top_10.iterrows():
        recs.append({
            "rank": rank,
            "name": r['景點名稱'],
            "city": r['縣市'],
            "star": r['Star'],
            "reviews": r['評論數']
        })
        rank += 1

    st.session_state.user_data = {
        "name": user_id,
        "selected_city": selected_city,
        "manual_cat_label": manual_cat
    }
    st.session_state.recs = recs

def save_feedback(scores_dict, text):
    if 'user_data' not in st.session_state: return
    u = st.session_state.user_data
    
    # 依照你的 Google Sheets 標題順序準備資料列 (A~L欄)
    row_data = [
        datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), # A. 時間
        u['name'],                                            # B. User_ID
        u['selected_city'],                                   # C. 篩選縣市
        u['manual_cat_label'],                                # D. 篩選主題
        scores_dict["PU1"], scores_dict["PU2"], scores_dict["PU3"], # E, F, G
        scores_dict["US1"], scores_dict["US2"], scores_dict["US3"], # H, I, J
        text,                                                 # K. 建議回饋
        "|".join([r['name'] for r in st.session_state.recs])  # L. 推薦清單
    ]

    try:
        # 1. 讀取你之前在 Streamlit Secrets 填好的 JSON 密碼
        credentials_dict = dict(st.secrets["gcp_service_account"])
        scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        creds = Credentials.from_service_account_info(credentials_dict, scopes=scopes)
        client = gspread.authorize(creds)

        # 2. 打開你的「簡易版」專屬表單 (請確保名稱與 Google Sheets 上的完全一致)
        sheet = client.open("旅遊推薦系統實驗數據_簡易版").sheet1
        
        # 3. 寫入資料
        sheet.append_row(row_data)
        st.success("✅ 回饋已成功同步至 Google 雲端！")
        
    except Exception as e:
        st.error(f"雲端寫入失敗: {e}")
        # 如果失敗，依然在本機存一份備份
        pd.DataFrame([row_data]).to_csv('backup_log_simple.csv', mode='a', index=False, header=False)