# ============================================================
# 날짜별 박스오피스 (KOBIS 일별 박스오피스 API)
# ------------------------------------------------------------
# - 초보자를 위해 코드 곳곳에 한국어 주석을 달아두었습니다.
# - 인증키는 절대 코드에 직접 적지 않고, Streamlit의 secrets(비밀 금고)에서
#   불러옵니다. (Streamlit Cloud > App settings > Secrets 에 아래처럼 넣으세요)
#
#   KOBIS_KEY = "여기에_발급받은_인증키"
# ============================================================

import html
import streamlit as st
import pandas as pd
import requests
from datetime import datetime, timedelta, timezone, date

# ------------------------------------------------------------
# 0. 기본 설정
# ------------------------------------------------------------
st.set_page_config(
    page_title="날짜별 박스오피스",
    page_icon="🎬",
    layout="wide",
)

KOBIS_URL = "https://www.kobis.or.kr/kobisopenapi/webservice/rest/boxoffice/searchDailyBoxOfficeList.json"

# 한국 표준시(KST)는 UTC+9이고, 서머타임이 없어서 항상 고정 offset입니다.
# 배포 서버의 시계가 어느 시간대로 맞춰져 있든, 이렇게 계산하면
# 항상 "한국 시간 기준"으로 정확한 날짜가 나옵니다.
KST = timezone(timedelta(hours=9))

# 누적관객이 이 숫자 이상이면 영화명 옆에 트로피를 붙입니다.
MILLION = 1_000_000


def get_yesterday_kst_date() -> date:
    """한국 시간 기준 '어제' 날짜(date 객체)를 돌려줍니다.
    오늘 데이터는 아직 KOBIS에 집계되지 않았기 때문에,
    달력에서 고를 수 있는 가장 늦은 날짜로 이 값을 사용합니다."""
    now_kst = datetime.now(KST)
    return (now_kst - timedelta(days=1)).date()


# ------------------------------------------------------------
# 1. KOBIS API 호출 함수
# ------------------------------------------------------------
# st.cache_data(ttl=3600) : 같은 날짜(target_dt)로 다시 요청하면
# 실제 API를 또 부르지 않고, 1시간(3600초) 동안은 저장해둔 결과를 그대로 씁니다.
#
# 이 함수는 (상태, 결과)를 함께 돌려줍니다.
#   상태가 "ok"이면 결과 자리에 영화 리스트가 들어있고,
#   그 외의 상태면 결과 자리에 화면에 보여줄 안내 문구가 들어있습니다.
@st.cache_data(ttl=3600, show_spinner="박스오피스 정보를 불러오는 중이에요...")
def fetch_box_office(target_dt: str, api_key: str):
    # 1) 인증키가 아예 없는 경우
    if not api_key:
        return "no_key", (
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
        return "network_error", (
            "🌐 KOBIS 서버에 연결하지 못했어요.\n\n"
            "인터넷 연결 상태나 KOBIS 서버 상태를 확인한 뒤 잠시 후 다시 시도해주세요."
        )

    # 3) 응답이 왔지만 상태코드가 200이 아닌 경우 (서버 오류 등)
    if response.status_code != 200:
        return "http_error", (
            f"⚠️ KOBIS 서버가 오류를 돌려줬어요. (상태코드: {response.status_code})\n\n"
            "잠시 후 다시 시도해주세요."
        )

    # 4) 응답이 JSON 형식이 아닌 경우 (드물지만 방어적으로 처리)
    try:
        data = response.json()
    except ValueError:
        return "json_error", (
            "🧩 KOBIS 서버 응답을 이해할 수 없는 형식이에요.\n\n"
            "잠시 후 다시 시도해보시고, 계속 이러면 KOBIS 서비스 상태를 확인해주세요."
        )

    # 5) 문서에 나온대로, 인증키가 틀려도 상태코드는 200이고
    #    대신 faultInfo 상자가 옵니다. 이 경우를 따로 잡아줍니다.
    if "faultInfo" in data:
        fault = data["faultInfo"]
        message = fault.get("message", "알 수 없는 오류")
        return "fault_info", (
            f"🔑 인증키 또는 요청에 문제가 있어요: {message}\n\n"
            "Secrets에 등록한 KOBIS_KEY 값이 정확한지 확인해주세요."
        )

    # 6) boxOfficeResult 자체가 없는 경우 (예상치 못한 응답 구조)
    if "boxOfficeResult" not in data:
        return "bad_shape", (
            "🧩 예상한 형식의 응답이 아니에요.\n\n"
            "KOBIS 공식 API 문서에 변경 사항이 있는지 확인해주세요."
        )

    movie_list = data["boxOfficeResult"].get("dailyBoxOfficeList", [])

    # 7) 영화 목록이 비어서 오는 경우 -> 아직 집계가 안 된 날짜라는 뜻입니다.
    if not movie_list:
        return "empty", "📭 그날은 아직 집계 전입니다."

    return "ok", movie_list


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
# 3. 순위 변동을 화살표 배지로 바꿔주는 함수
# ------------------------------------------------------------
def rank_badge_html(rank: int, rank_inten: int) -> str:
    """순위 숫자 옆에 전날 대비 변동 화살표를 붙인 HTML 문자열을 만듭니다.
    rank_inten이 양수면(순위가 오름) 빨간 위쪽 화살표,
    음수면(순위가 내림) 파란 아래쪽 화살표를 붙입니다."""
    if rank_inten > 0:
        arrow = f'<span style="color:#e63946; font-weight:bold;">▲{rank_inten}</span>'
    elif rank_inten < 0:
        arrow = f'<span style="color:#1d7fd6; font-weight:bold;">▼{abs(rank_inten)}</span>'
    else:
        arrow = '<span style="color:#999;">-</span>'
    return f"{rank} {arrow}"


def movie_name_html(name: str, audi_acc: int) -> str:
    """누적관객이 100만 명을 넘으면 영화명 옆에 트로피 이모지를 붙입니다."""
    safe_name = html.escape(name)
    if audi_acc >= MILLION:
        return f"{safe_name} 🏆"
    return safe_name


def build_table_html(df: pd.DataFrame) -> str:
    """데이터프레임을 화살표·트로피가 들어간 HTML 표로 변환합니다."""
    header_cells = "".join(
        f'<th style="padding:8px 12px; text-align:left; border-bottom:2px solid #ddd;">{col}</th>'
        for col in ["순위", "영화명", "개봉일", "관객수", "누적관객", "스크린수"]
    )

    body_rows = []
    for _, row in df.iterrows():
        rank_cell = rank_badge_html(row["순위"], row["순위변동"])
        name_cell = movie_name_html(row["영화명"], row["누적관객"])
        body_rows.append(
            "<tr>"
            f'<td style="padding:8px 12px; border-bottom:1px solid #eee;">{rank_cell}</td>'
            f'<td style="padding:8px 12px; border-bottom:1px solid #eee;">{name_cell}</td>'
            f'<td style="padding:8px 12px; border-bottom:1px solid #eee;">{row["개봉일"]}</td>'
            f'<td style="padding:8px 12px; border-bottom:1px solid #eee; text-align:right;">{row["관객수"]:,}</td>'
            f'<td style="padding:8px 12px; border-bottom:1px solid #eee; text-align:right;">{row["누적관객"]:,}</td>'
            f'<td style="padding:8px 12px; border-bottom:1px solid #eee; text-align:right;">{row["스크린수"]:,}</td>'
            "</tr>"
        )

    return (
        '<table style="width:100%; border-collapse:collapse; font-size:1rem;">'
        f"<thead><tr>{header_cells}</tr></thead>"
        f"<tbody>{''.join(body_rows)}</tbody>"
        "</table>"
    )


# ------------------------------------------------------------
# 4. 화면 구성 시작
# ------------------------------------------------------------
st.title("🎬 날짜별 박스오피스")

yesterday_kst = get_yesterday_kst_date()

# 달력에서 날짜를 고를 수 있게 합니다.
# max_value를 어제로 막아서, 아직 집계되지 않은 오늘/미래 날짜는 고를 수 없습니다.
selected_date = st.date_input(
    "조회할 날짜를 선택하세요 (오늘 데이터는 아직 집계 전이라 어제까지만 고를 수 있어요)",
    value=yesterday_kst,
    max_value=yesterday_kst,
)

target_dt = selected_date.strftime("%Y%m%d")
display_date = selected_date.strftime("%Y년 %m월 %d일")

st.caption(f"선택한 날짜: {display_date}")

# secrets에서 인증키 꺼내오기 (없으면 빈 문자열)
# secrets.toml 파일 자체가 아직 없는 경우 st.secrets 접근 시 오류가 날 수 있어서
# try/except로 감싸 안전하게 처리합니다.
try:
    api_key = st.secrets.get("KOBIS_KEY", "")
except Exception:
    api_key = ""

status, result = fetch_box_office(target_dt, api_key)

if status == "empty":
    # 진짜 오류는 아니고, 아직 집계가 안 된 것뿐이라 부드러운 안내(info)로 보여줍니다.
    st.info(result)
    st.stop()
elif status != "ok":
    # 그 외의 경우는 실제 문제 상황이므로 error로 보여줍니다.
    st.error(result)
    st.stop()

movie_list = result  # 여기부터는 result가 실제 영화 리스트입니다.

# ------------------------------------------------------------
# 5. 문자열 숫자를 정수로 변환해서 표에 쓸 데이터프레임 만들기
# ------------------------------------------------------------
rows = []
for movie in movie_list:
    rows.append({
        "순위": to_int(movie.get("rank")),
        "순위변동": to_int(movie.get("rankInten")),
        "영화명": movie.get("movieNm", ""),
        "개봉일": movie.get("openDt", ""),
        "관객수": to_int(movie.get("audiCnt")),
        "누적관객": to_int(movie.get("audiAcc")),
        "스크린수": to_int(movie.get("scrnCnt")),
    })

df = pd.DataFrame(rows)
df = df.sort_values("순위", ascending=True).reset_index(drop=True)

# ------------------------------------------------------------
# 6. 1위 영화 - 지표 카드 3장
# ------------------------------------------------------------
top_movie = df.iloc[0]
top_name_display = movie_name_html(top_movie["영화명"], top_movie["누적관객"])

st.subheader(f"🏆 {display_date} 1위: {top_movie['영화명']}" + (" 🏆" if top_movie["누적관객"] >= MILLION else ""))

card1, card2, card3 = st.columns(3)

with card1:
    st.metric("영화명", top_movie["영화명"], help=f"개봉일: {top_movie['개봉일']}")

with card2:
    st.metric("그날 관객수", f"{top_movie['관객수']:,}명")

with card3:
    st.metric("누적 관객수", f"{top_movie['누적관객']:,}명")

st.divider()

# ------------------------------------------------------------
# 7. 관객수 상위 5편 - 막대그래프
# ------------------------------------------------------------
st.subheader("📊 관객수 상위 5편")

top5 = df.sort_values("관객수", ascending=False).head(5)
chart_data = top5.set_index("영화명")[["관객수"]]

# horizontal=True로 가로 막대그래프를 그리면 영화 제목이 왼쪽에
# 가로 방향 그대로 표시되어 글자가 세로로 눕지 않습니다.
st.bar_chart(chart_data, horizontal=True, height=400)

st.divider()

# ------------------------------------------------------------
# 8. 전체 순위표 (순위 변동 화살표 + 트로피 포함)
# ------------------------------------------------------------
st.subheader("📋 전체 박스오피스 순위")
st.caption("▲ 빨간 화살표: 전날보다 순위 상승 · ▼ 파란 화살표: 전날보다 순위 하락 · 🏆 누적관객 100만 명 이상")

st.markdown(build_table_html(df), unsafe_allow_html=True)

st.caption("데이터 출처: 영화진흥위원회(KOBIS) 일별 박스오피스 API")
