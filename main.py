# ============================================================
# 어제의 박스오피스 (KOBIS 일별 박스오피스 API)
# ------------------------------------------------------------
# - 초보자를 위해 코드 곳곳에 한국어 주석을 달아두었습니다.
# - 인증키는 절대 코드에 직접 적지 않고, Streamlit의 secrets(비밀 금고)에서
#   불러옵니다. (Streamlit Cloud > App settings > Secrets 에 아래처럼 넣으세요)
#
#   KOBIS_KEY = "여기에_발급받은_인증키"
# ============================================================

import streamlit as st
import pandas as pd
import requests
from datetime import datetime, timedelta, timezone

# ------------------------------------------------------------
# 0. 기본 설정
# ------------------------------------------------------------
st.set_page_config(
    page_title="어제의 박스오피스",
    page_icon="🎬",
    layout="wide",
)

KOBIS_URL = "https://www.kobis.or.kr/kobisopenapi/webservice/rest/boxoffice/searchDailyBoxOfficeList.json"

# 한국 표준시(KST)는 UTC+9이고, 서머타임이 없어서 항상 고정 offset입니다.
# 배포 서버의 시계가 어느 시간대로 맞춰져 있든, 이렇게 계산하면
# 항상 "한국 시간 기준 어제"가 정확히 나옵니다.
KST = timezone(timedelta(hours=9))


def get_yesterday_kst_str() -> str:
    """한국 시간 기준 '어제' 날짜를 yyyymmdd 형식 문자열로 돌려줍니다."""
    now_kst = datetime.now(KST)
    yesterday_kst = now_kst - timedelta(days=1)
    return yesterday_kst.strftime("%Y%m%d")


def get_yesterday_kst_display() -> str:
    """화면에 보여줄 때 쓸 예쁜 날짜 문자열 (예: 2026년 09월 17일)"""
    now_kst = datetime.now(KST)
    yesterday_kst = now_kst - timedelta(days=1)
    return yesterday_kst.strftime("%Y년 %m월 %d일")


# ------------------------------------------------------------
# 1. KOBIS API 호출 함수
# ------------------------------------------------------------
# st.cache_data(ttl=3600) : 같은 날짜(target_dt)로 다시 요청하면
# 실제 API를 또 부르지 않고, 1시간(3600초) 동안은 저장해둔 결과를 그대로 씁니다.
#
# 이 함수는 "성공 여부"와 "결과 또는 에러 메시지"를 함께 돌려줍니다.
#   반환값: (성공했는지 True/False, 영화 리스트 또는 에러 안내 문자열)
@st.cache_data(ttl=3600, show_spinner="박스오피스 정보를 불러오는 중이에요...")
def fetch_box_office(target_dt: str, api_key: str):
    # 1) 인증키가 아예 없는 경우
    if not api_key:
        return False, (
            "🔑 인증키(KOBIS_KEY)를 찾을 수 없어요.\n\n"
            "Streamlit Cloud의 'Settings > Secrets'에 아래처럼 넣어주셨는지 확인해주세요.\n\n"
            'KOBIS_KEY = "발급받은_인증키"'
        )

    params = {
        "key": api_key,
        "targetDt": target_dt,
    }

    # 2) 네트워크 요청 자체가 실패하는 경우 (타임아웃, 연결 끊김 등)
    try:
        response = requests.get(KOBIS_URL, params=params, timeout=10)
    except requests.exceptions.RequestException:
        return False, (
            "🌐 KOBIS 서버에 연결하지 못했어요.\n\n"
            "인터넷 연결 상태나 KOBIS 서버 상태를 확인한 뒤 잠시 후 다시 시도해주세요."
        )

    # 3) 응답이 왔지만 상태코드가 200이 아닌 경우 (서버 오류 등)
    if response.status_code != 200:
        return False, (
            f"⚠️ KOBIS 서버가 오류를 돌려줬어요. (상태코드: {response.status_code})\n\n"
            "잠시 후 다시 시도해주세요."
        )

    # 4) 응답이 JSON 형식이 아닌 경우 (드물지만 방어적으로 처리)
    try:
        data = response.json()
    except ValueError:
        return False, (
            "🧩 KOBIS 서버 응답을 이해할 수 없는 형식이에요.\n\n"
            "잠시 후 다시 시도해보시고, 계속 이러면 KOBIS 서비스 상태를 확인해주세요."
        )

    # 5) 문서에 나온대로, 인증키가 틀려도 상태코드는 200이고
    #    대신 faultInfo 상자가 옵니다. 이 경우를 따로 잡아줍니다.
    if "faultInfo" in data:
        fault = data["faultInfo"]
        message = fault.get("message", "알 수 없는 오류")
        return False, (
            f"🔑 인증키 또는 요청에 문제가 있어요: {message}\n\n"
            "Secrets에 등록한 KOBIS_KEY 값이 정확한지 확인해주세요."
        )

    # 6) boxOfficeResult 자체가 없는 경우 (예상치 못한 응답 구조)
    if "boxOfficeResult" not in data:
        return False, (
            "🧩 예상한 형식의 응답이 아니에요.\n\n"
            "KOBIS 공식 API 문서에 변경 사항이 있는지 확인해주세요."
        )

    movie_list = data["boxOfficeResult"].get("dailyBoxOfficeList", [])

    # 7) 영화 목록이 비어서 오는 경우 (예: 너무 이른 날짜, 아직 집계 전 등)
    if not movie_list:
        return False, (
            "📭 해당 날짜의 박스오피스 데이터가 비어 있어요.\n\n"
            "날짜가 너무 최근이거나(아직 집계 전), KOBIS 쪽 데이터 집계가 늦어졌을 수 있어요.\n"
            "잠시 후 다시 시도해주세요."
        )

    return True, movie_list


# ------------------------------------------------------------
# 2. 문자열로 오는 숫자들을 진짜 숫자(int)로 바꾸는 함수
# ------------------------------------------------------------
def to_int(value, default=0):
    """API에서 문자열로 온 숫자를 정수로 바꿔줍니다. 실패하면 default를 씁니다."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


# ------------------------------------------------------------
# 3. 화면 구성 시작
# ------------------------------------------------------------
st.title("🎬 어제의 박스오피스")

target_dt = get_yesterday_kst_str()
display_date = get_yesterday_kst_display()

st.caption(f"기준 날짜(한국시간 기준 어제): {display_date}")

# secrets에서 인증키 꺼내오기 (없으면 빈 문자열)
# secrets.toml 파일 자체가 아직 없는 경우 st.secrets 접근 시 오류가 날 수 있어서
# try/except로 감싸 안전하게 처리합니다.
try:
    api_key = st.secrets.get("KOBIS_KEY", "")
except Exception:
    api_key = ""

ok, result = fetch_box_office(target_dt, api_key)

if not ok:
    # result 자리에 안내 메시지(문자열)가 들어있습니다.
    st.error(result)
    st.stop()

movie_list = result  # 여기부터는 result가 실제 영화 리스트입니다.

# ------------------------------------------------------------
# 4. 문자열 숫자를 정수로 변환해서 표에 쓸 데이터프레임 만들기
# ------------------------------------------------------------
rows = []
for movie in movie_list:
    rows.append({
        "순위": to_int(movie.get("rank")),
        "영화명": movie.get("movieNm", ""),
        "개봉일": movie.get("openDt", ""),
        "관객수": to_int(movie.get("audiCnt")),
        "누적관객": to_int(movie.get("audiAcc")),
        "스크린수": to_int(movie.get("scrnCnt")),
    })

df = pd.DataFrame(rows)
df = df.sort_values("순위", ascending=True).reset_index(drop=True)

# ------------------------------------------------------------
# 5. 1위 영화 - 지표 카드 3장
# ------------------------------------------------------------
top_movie = df.iloc[0]

st.subheader(f"🏆 어제 1위: {top_movie['영화명']}")

card1, card2, card3 = st.columns(3)

with card1:
    st.metric("영화명", top_movie["영화명"], help=f"개봉일: {top_movie['개봉일']}")

with card2:
    st.metric("어제 관객수", f"{top_movie['관객수']:,}명")

with card3:
    st.metric("누적 관객수", f"{top_movie['누적관객']:,}명")

st.divider()

# ------------------------------------------------------------
# 6. 관객수 상위 5편 - 막대그래프
# ------------------------------------------------------------
st.subheader("📊 관객수 상위 5편")

top5 = df.sort_values("관객수", ascending=False).head(5)
chart_data = top5.set_index("영화명")[["관객수"]]

st.bar_chart(chart_data, height=400)

st.divider()

# ------------------------------------------------------------
# 7. 전체 순위표
# ------------------------------------------------------------
st.subheader("📋 전체 박스오피스 순위")

# 숫자 컬럼에 천 단위 콤마를 붙여서 보기 좋게 표시합니다.
st.dataframe(
    df.style.format({
        "관객수": "{:,}",
        "누적관객": "{:,}",
        "스크린수": "{:,}",
    }),
    width="stretch",
    hide_index=True,
)

st.caption("데이터 출처: 영화진흥위원회(KOBIS) 일별 박스오피스 API")
