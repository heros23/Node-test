"""
엔벨로프 전략 통합 대시보드 서버
- S&P500 / 코스피200 / 코스닥150
- 전략: 엔벨로프 / TBV-SMC / 볼린저3시그마 / 피봇VA / SSL+RSI
- 스캐너 + 차트 + 백테스트 + 실시간 워치리스트 + 계좌관리
"""

from flask import Flask, jsonify, request, send_from_directory
import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import threading
import os
import json
import gc
import io
import pytz
import requests as _requests

# ── KST 타임존 헬퍼 ──────────────────────────────────────────────────────────
_KST = pytz.timezone('Asia/Seoul')
def _now_kst(fmt='%Y-%m-%d %H:%M:%S') -> str:
    """KST 기준 현재 시각 문자열 반환 (사용자 표시용 타임스탬프 전용)"""
    return datetime.now(_KST).strftime(fmt)
# ─────────────────────────────────────────────────────────────────────────────
try:
    from bs4 import BeautifulSoup as _BS
    _BS_OK = True
except ImportError:
    _BS_OK = False
try:
    import exchange_calendars as xcals
    _XCALS_OK = True
except ImportError:
    _XCALS_OK = False

app = Flask(__name__, static_folder='.', static_url_path='')
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0

@app.after_request
def no_cache(resp):
    resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    resp.headers['Pragma'] = 'no-cache'
    return resp

# ─── 종목 DB ──────────────────────────────────────────────────────────────

MARKETS = {
    "US": {
        "name": "S&P500",
        "currency": "USD",
        "suffix": "",
        "index": "^GSPC",
        "index_name": "S&P 500",
        "sectors": {
            "Technology":    ["AAPL","MSFT","NVDA","META","GOOGL","AVGO","CRM","ORCL","AMD","INTC","QCOM","TXN","NOW","ADBE","INTU","AMAT","MU","LRCX"],
            "Healthcare":    ["LLY","UNH","JNJ","ABBV","MRK","TMO","ABT","DHR","BMY","AMGN","GILD","VRTX","REGN","ISRG","SYK","MDT"],
            "Financials":    ["BRK-B","JPM","V","MA","BAC","WFC","GS","MS","BLK","SCHW","AXP","CB","PGR","MMC","COF"],
            "Consumer Disc": ["AMZN","TSLA","HD","MCD","NKE","LOW","SBUX","TJX","BKNG","CMG","ORLY","AZO","DHI","GM","F"],
            "Industrials":   ["UNP","HON","CAT","GE","RTX","DE","BA","MMM","LMT","FDX","UPS","CSX","WM","ETN","EMR"],
            "Energy":        ["XOM","CVX","COP","SLB","EOG","MPC","VLO","PSX","OXY","BKR","HAL","DVN","HES","APA","MRO"],
            "Comm Svc":      ["NFLX","DIS","CMCSA","VZ","T","TMUS","EA","WBD","OMC"],
            "Cons Staples":  ["PG","KO","PEP","COST","WMT","CL","KMB","MO","GIS","K"],
            "Utilities":     ["NEE","DUK","SO","D","AEP","EXC","XEL","ED","SRE","WEC"],
            "Materials":     ["LIN","APD","SHW","ECL","NEM","FCX","NUE","VMC","DOW"],
            "Real Estate":   ["AMT","PLD","CCI","EQIX","PSA","DLR","O","WELL","SPG"],
        }
    },
    "KOSPI": {
        "name": "코스피200",
        "currency": "KRW",
        "suffix": ".KS",
        "index": "^KS200",
        "index_name": "KOSPI 200",
        "sectors": {
            "반도체":   ["005930","000660","042700","066570","009150","058470","036540"],
            "IT·전기":  ["005380","012330","007070","011200","009540","018260","036460"],
            "금융":     ["105560","055550","086790","316140","138040","175330","024110"],
            "바이오":   ["207940","068270","128940","032640","000100","326030","011070"],
            "소비재":   ["051900","097950","033780","004990","006400","008770","030200"],
            "에너지·화학":["010950","011170","010130","011790","006650","002790","004020"],
            "건설·중공업":["000720","047050","009830","010140","012450","064350","267250"],
            "통신·미디어":["017670","030200","032640","035420","251270","035720","259960"],
            "유통·서비스":["139480","004170","069960","282330","071840","007310","005070"],
        }
    },
    "KOSDAQ": {
        "name": "코스닥150",
        "currency": "KRW",
        "suffix": ".KQ",
        "index": "^KQ150",
        "index_name": "KOSDAQ 150",
        "sectors": {
            "IT·소프트웨어": ["293490","035900","041510","048410","357780","145020","036930"],
            "바이오·헬스":   ["091990","145720","263750","214450","950130","226950","086520"],
            "반도체·장비":   ["058470","036540","054450","036830","095340","240810","039030"],
            "엔터·콘텐츠":   ["041510","035900","093320","035080","112040","950190","122870"],
            "2차전지·소재":  ["247540","357780","096530","006740","298040","298050","064760"],
            "게임":          ["263750","036830","112040","194480","078340","225570","263020"],
            "기타":          ["058970","041830","108790","089030","053300","060150","900110"],
        }
    }
}

# ─── 종목 한국어 이름 DB ────────────────────────────────────────────────────
TICKER_NAMES = {
    # ── 미국 주식 (티커 → 한국어 회사명) ─────────────────────────────────
    # Technology
    "AAPL":  "애플",
    "MSFT":  "마이크로소프트",
    "NVDA":  "엔비디아",
    "META":  "메타",
    "GOOGL": "알파벳",
    "AVGO":  "브로드컴",
    "CRM":   "세일즈포스",
    "ORCL":  "오라클",
    "AMD":   "AMD",
    "INTC":  "인텔",
    "QCOM":  "퀄컴",
    "TXN":   "텍사스인스트루먼트",
    "NOW":   "서비스나우",
    "ADBE":  "어도비",
    "INTU":  "인튜이트",
    "AMAT":  "어플라이드머티리얼즈",
    "MU":    "마이크론",
    "LRCX":  "램리서치",
    # Healthcare
    "LLY":   "일라이릴리",
    "UNH":   "유나이티드헬스",
    "JNJ":   "존슨앤존슨",
    "ABBV":  "애브비",
    "MRK":   "머크",
    "TMO":   "써모피셔",
    "ABT":   "애보트",
    "DHR":   "다나허",
    "BMY":   "브리스톨마이어스스퀴브",
    "AMGN":  "암젠",
    "GILD":  "길리어드",
    "VRTX":  "버텍스파마",
    "REGN":  "리제네론",
    "ISRG":  "인튜이티브서지컬",
    "SYK":   "스트라이커",
    "MDT":   "메드트로닉",
    # Financials
    "BRK-B": "버크셔해서웨이",
    "JPM":   "JP모건",
    "V":     "비자",
    "MA":    "마스터카드",
    "BAC":   "뱅크오브아메리카",
    "WFC":   "웰스파고",
    "GS":    "골드만삭스",
    "MS":    "모건스탠리",
    "BLK":   "블랙록",
    "SCHW":  "찰스슈왑",
    "AXP":   "아메리칸익스프레스",
    "CB":    "처브",
    "PGR":   "프로그레시브",
    "MMC":   "마쉬맥레넌",
    "COF":   "캐피탈원",
    # Consumer Discretionary
    "AMZN":  "아마존",
    "TSLA":  "테슬라",
    "HD":    "홈디포",
    "MCD":   "맥도날드",
    "NKE":   "나이키",
    "LOW":   "로우스",
    "SBUX":  "스타벅스",
    "TJX":   "TJX",
    "BKNG":  "부킹홀딩스",
    "CMG":   "치폴레",
    "ORLY":  "오라일리",
    "AZO":   "오토존",
    "DHI":   "DR호튼",
    "GM":    "제너럴모터스",
    "F":     "포드",
    # Industrials
    "UNP":   "유니온퍼시픽",
    "HON":   "허니웰",
    "CAT":   "캐터필러",
    "GE":    "GE에어로스페이스",
    "RTX":   "RTX",
    "DE":    "존디어",
    "BA":    "보잉",
    "MMM":   "3M",
    "LMT":   "록히드마틴",
    "FDX":   "페덱스",
    "UPS":   "UPS",
    "CSX":   "CSX",
    "WM":    "웨이스트매니지먼트",
    "ETN":   "이튼",
    "EMR":   "에머슨일렉트릭",
    # Energy
    "XOM":   "엑슨모빌",
    "CVX":   "셰브론",
    "COP":   "코노코필립스",
    "SLB":   "슐럼버거",
    "EOG":   "EOG리소스",
    "MPC":   "마라톤페트롤리엄",
    "VLO":   "발레로에너지",
    "PSX":   "필립스66",
    "OXY":   "옥시덴탈",
    "BKR":   "베이커휴즈",
    "HAL":   "할리버튼",
    "DVN":   "데본에너지",
    "HES":   "헤스",
    "APA":   "APA",
    "MRO":   "마라톤오일",
    # Comm Services
    "NFLX":  "넷플릭스",
    "DIS":   "디즈니",
    "CMCSA": "컴캐스트",
    "VZ":    "버라이즌",
    "T":     "AT&T",
    "TMUS":  "T모바일",
    "EA":    "일렉트로닉아츠",
    "WBD":   "워너브라더스디스커버리",
    "OMC":   "옴니콤",
    # Consumer Staples
    "PG":    "프록터앤갬블",
    "KO":    "코카콜라",
    "PEP":   "펩시코",
    "COST":  "코스트코",
    "WMT":   "월마트",
    "CL":    "콜게이트",
    "KMB":   "킴벌리클라크",
    "MO":    "알트리아",
    "GIS":   "제너럴밀스",
    "K":     "켈라노바",
    # Utilities
    "NEE":   "넥스트에라에너지",
    "DUK":   "듀크에너지",
    "SO":    "서던컴퍼니",
    "D":     "도미니언에너지",
    "AEP":   "아메리칸일렉트릭파워",
    "EXC":   "엑셀론",
    "XEL":   "엑셀에너지",
    "ED":    "컨솔리데이티드에디슨",
    "SRE":   "셈프라에너지",
    "WEC":   "WEC에너지",
    # Materials
    "LIN":   "린데",
    "APD":   "에어프로덕츠",
    "SHW":   "셔윈윌리엄스",
    "ECL":   "에코랩",
    "NEM":   "뉴몬트",
    "FCX":   "프리포트맥모란",
    "NUE":   "뉴코어",
    "VMC":   "불칸머티리얼즈",
    "DOW":   "다우",
    # Real Estate
    "AMT":   "아메리칸타워",
    "PLD":   "프로로지스",
    "CCI":   "크라운캐슬",
    "EQIX":  "에퀴닉스",
    "PSA":   "퍼블릭스토리지",
    "DLR":   "디지털리얼티",
    "O":     "리얼티인컴",
    "WELL":  "웰타워",
    "SPG":   "사이먼프로퍼티",

    # ── 코스피 종목 (코드 → 종목명) ──────────────────────────────────────
    # 반도체
    "005930": "삼성전자",
    "000660": "SK하이닉스",
    "042700": "한미반도체",
    "066570": "LG전자",
    "009150": "삼성전기",
    "058470": "리노공업",
    "036540": "SFA반도체",
    # IT·전기
    "005380": "현대차",
    "012330": "현대모비스",
    "007070": "GS리테일",
    "011200": "HMM",
    "009540": "HD한국조선해양",
    "018260": "삼성에스디에스",
    "036460": "한국가스공사",
    # 금융
    "105560": "KB금융",
    "055550": "신한지주",
    "086790": "하나금융지주",
    "316140": "우리금융지주",
    "138040": "메리츠금융지주",
    "175330": "JB금융지주",
    "024110": "기업은행",
    # 바이오
    "207940": "삼성바이오로직스",
    "068270": "셀트리온",
    "128940": "한미약품",
    "032640": "LG유플러스",
    "000100": "유한양행",
    "326030": "SK바이오팜",
    "011070": "LG이노텍",
    # 소비재
    "051900": "LG생활건강",
    "097950": "CJ제일제당",
    "033780": "KT&G",
    "004990": "롯데지주",
    "006400": "삼성SDI",
    "008770": "호텔신라",
    "030200": "KT",
    # 에너지·화학
    "010950": "S-Oil",
    "011170": "롯데케미칼",
    "010130": "고려아연",
    "011790": "SKC",
    "006650": "대한유화",
    "002790": "아모레퍼시픽그룹",
    "004020": "현대제철",
    # 건설·중공업
    "000720": "현대건설",
    "047050": "포스코인터내셔널",
    "009830": "한화솔루션",
    "010140": "삼성중공업",
    "012450": "한화에어로스페이스",
    "064350": "현대로템",
    "267250": "HD현대",
    # 통신·미디어
    "017670": "SK텔레콤",
    "035420": "NAVER",
    "251270": "넷마블",
    "035720": "카카오",
    "259960": "크래프톤",
    # 유통·서비스
    "139480": "이마트",
    "004170": "신세계",
    "069960": "현대백화점",
    "282330": "BGF리테일",
    "071840": "롯데하이마트",
    "007310": "오뚜기",
    "005070": "코스모신소재",

    # ── 코스닥 종목 (코드 → 종목명) ──────────────────────────────────────
    # IT·소프트웨어
    "293490": "카카오게임즈",
    "035900": "JYP엔터테인먼트",
    "041510": "에스엠",
    "048410": "현대바이오",
    "357780": "솔브레인",
    "145020": "휴젤",
    "036930": "주성엔지니어링",
    # 바이오·헬스
    "091990": "셀트리온헬스케어",
    "145720": "덴티움",
    "263750": "펄어비스",
    "214450": "파마리서치",
    "950130": "엑세스바이오",
    "226950": "알테오젠",
    "086520": "에코프로",
    # 반도체·장비
    "054450": "텔레칩스",
    "036830": "솔브레인홀딩스",
    "095340": "ISC",
    "240810": "원익IPS",
    "039030": "이오테크닉스",
    # 엔터·콘텐츠
    "093320": "와이지엔터테인먼트",
    "035080": "인터파크홀딩스",
    "112040": "위메이드",
    "950190": "하이브",
    "122870": "와이지-원",
    # 2차전지·소재
    "247540": "에코프로비엠",
    "096530": "씨젠",
    "006740": "SK아이이테크놀로지",
    "298040": "효성첨단소재",
    "298050": "효성화학",
    "064760": "티씨케이",
    # 게임
    "194480": "데브시스터즈",
    "078340": "컴투스",
    "225570": "넥슨게임즈",
    "263020": "카카오VX",
    # 기타
    "058970": "엠씨넥스",
    "041830": "인바디",
    "108790": "하나투어",
    "089030": "테크윙",
    "053300": "한국콜마",
    "060150": "인선이엔티",
    "900110": "이스타코",
}

def get_display_name(ticker: str, market_key: str = "") -> str:
    """티커/종목코드와 한국어 이름을 조합한 표시명 반환
    - 미국주식: 'NVDA (엔비디아)'
    - 한국주식: '005930 (삼성전자)'
    - 이름 없으면: 'TICKER' 그대로
    """
    suffix = MARKETS.get(market_key, {}).get("suffix", "") if market_key else ""
    base = ticker.replace(suffix, "") if suffix else ticker
    name = TICKER_NAMES.get(base, "")
    if name:
        return f"{base} ({name})"
    return base

# ─── 실시간 지수 구성종목 로더 (캐시 TTL = 1시간) ──────────────────────────

_INDEX_CACHE: dict = {}          # {'US': ([tickers], fetched_at), 'KOSPI': (...), 'KOSDAQ': (...)}
_INDEX_LOCK  = threading.Lock()
_INDEX_TTL   = 3600              # 1시간

_SP500_URL   = ('https://raw.githubusercontent.com/datasets/'
                's-and-p-500-companies/main/data/constituents.csv')
_NAVER_URL   = 'https://finance.naver.com/sise/entryJongmok.naver'
_NAVER_HDRS  = {'User-Agent': 'Mozilla/5.0', 'Referer': 'https://finance.naver.com/'}


def _fetch_sp500() -> list:
    """GitHub CSV → S&P500 구성종목 티커 리스트 반환 (약 503개)"""
    try:
        r = _requests.get(_SP500_URL, timeout=15)
        r.raise_for_status()
        df = pd.read_csv(io.StringIO(r.text))
        # BRK.B → BRK-B (yfinance 형식)
        symbols = df['Symbol'].str.replace('.', '-', regex=False).tolist()
        print(f"[IndexLoader] S&P500 {len(symbols)}개 로드 완료")
        return symbols
    except Exception as e:
        print(f"[IndexLoader] S&P500 로드 실패: {e}")
        return []


def _fetch_naver_index(list_type: str, max_pages: int = 22) -> list:
    """네이버 금융 페이지네이션 → 지수 구성종목 코드 리스트 반환
    list_type: 'kospi200' | 'kosdaq150'
    """
    if not _BS_OK:
        print(f"[IndexLoader] BeautifulSoup 미설치 → {list_type} 로드 불가")
        return []
    all_codes = []
    try:
        for page in range(1, max_pages + 1):
            url = f'{_NAVER_URL}?kospiListType={list_type}&page={page}'
            r = _requests.get(url, headers=_NAVER_HDRS, timeout=10)
            r.encoding = 'euc-kr'
            soup = _BS(r.text, 'html.parser')
            found = []
            for a in soup.find_all('a', href=True):
                h = a['href']
                if 'code=' in h:
                    c = h.split('code=')[-1][:6]
                    if c.isdigit() and len(c) == 6:
                        found.append(c)
            if not found:
                break
            all_codes.extend(found)
        unique = list(dict.fromkeys(all_codes))
        print(f"[IndexLoader] {list_type} {len(unique)}개 로드 완료")
        return unique
    except Exception as e:
        print(f"[IndexLoader] {list_type} 로드 실패: {e}")
        return []


def _load_index_tickers(market_key: str) -> list:
    """캐시 확인 → 만료 시 실시간 fetch, 실패 시 MARKETS 하드코딩 폴백"""
    with _INDEX_LOCK:
        cached = _INDEX_CACHE.get(market_key)
        now = datetime.now().timestamp()
        if cached and (now - cached[1]) < _INDEX_TTL:
            return cached[0]

    # 캐시 만료 또는 미존재 → 실시간 fetch
    print(f"[IndexLoader] {market_key} 구성종목 갱신 중...")
    if market_key == 'US':
        tickers = _fetch_sp500()
    elif market_key == 'KOSPI':
        raw = _fetch_naver_index('kospi200')
        suffix = MARKETS['KOSPI']['suffix']     # '.KS'
        tickers = [c + suffix for c in raw]
    elif market_key == 'KOSDAQ':
        raw = _fetch_naver_index('kosdaq150')
        suffix = MARKETS['KOSDAQ']['suffix']    # '.KQ'
        tickers = [c + suffix for c in raw]
    else:
        tickers = []

    if not tickers:
        # 네트워크 실패 시 기존 하드코딩 폴백
        print(f"[IndexLoader] {market_key} 실시간 로드 실패 → 하드코딩 폴백")
        m = MARKETS.get(market_key, {})
        sfx = m.get('suffix', '')
        fallback = []
        for stocks in m.get('sectors', {}).values():
            for s in stocks:
                fallback.append(s + sfx if sfx and not s.endswith(sfx) else s)
        tickers = list(dict.fromkeys(fallback))

    with _INDEX_LOCK:
        _INDEX_CACHE[market_key] = (tickers, datetime.now().timestamp())

    return tickers


def get_all_tickers(market_key: str) -> list:
    """시장별 전체 구성종목 반환 — 실시간 로딩(캐시 TTL 1h) + 하드코딩 폴백"""
    return _load_index_tickers(market_key)


def get_sector(market_key: str, ticker: str) -> str:
    m = MARKETS.get(market_key, {})
    suffix = m.get("suffix", "")
    base = ticker.replace(suffix, "") if suffix else ticker
    for sec, stocks in m.get("sectors", {}).items():
        if base in stocks or ticker in stocks:
            return sec
    return "기타"


# ─── 엔벨로프 계산 ────────────────────────────────────────────────────────

def calc_envelope(df: pd.DataFrame, period: int = 20, pct: float = 5.0) -> pd.DataFrame:
    df = df.copy()
    df['MA']    = df['Close'].rolling(period).mean()
    df['Upper'] = df['MA'] * (1 + pct / 100)
    df['Lower'] = df['MA'] * (1 - pct / 100)
    return df

def get_signal(df: pd.DataFrame, pct: float = 5.0) -> dict:
    if df is None or len(df) < 3:
        return {"signal": "N/A", "strength": 0}
    last = df.iloc[-1]
    close, ma, upper, lower = last['Close'], last['MA'], last['Upper'], last['Lower']
    if pd.isna(ma):
        return {"signal": "N/A", "strength": 0}

    pct_from_lower = (close - lower) / lower * 100
    pct_from_upper = (close - upper) / upper * 100
    pct_from_ma    = (close - ma)    / ma    * 100

    if   close <= lower:           signal, strength = "STRONG_BUY",  min(100, int(abs(pct_from_lower)*20))
    elif close <= lower * 1.01:    signal, strength = "BUY",         80
    elif close >= upper:           signal, strength = "STRONG_SELL", min(100, int(abs(pct_from_upper)*20))
    elif close >= upper * 0.99:    signal, strength = "SELL",        80
    elif pct_from_ma < -pct*0.5:   signal, strength = "WATCH_BUY",  40
    elif pct_from_ma >  pct*0.5:   signal, strength = "WATCH_SELL", 40
    else:                          signal, strength = "NEUTRAL",     0

    return {
        "signal": signal, "strength": strength,
        "close":  round(float(close), 2),
        "ma":     round(float(ma),    2),
        "upper":  round(float(upper), 2),
        "lower":  round(float(lower), 2),
        "pct_from_ma":    round(float(pct_from_ma),    2),
        "pct_from_lower": round(float(pct_from_lower), 2),
        "pct_from_upper": round(float(pct_from_upper), 2),
    }


# ─── 백테스트 ────────────────────────────────────────────────────────────

def backtest_envelope(df, period=20, pct=5.0, stop_loss=3.0, take_profit=5.0):
    df = calc_envelope(df, period, pct).dropna()
    capital = 10_000_000
    cash, shares, position = capital, 0, None
    trades = []

    for i in range(1, len(df)):
        row, prev = df.iloc[i], df.iloc[i-1]
        price = float(row['Close'])

        if position is None:
            if prev['Close'] > prev['Lower'] and row['Close'] <= row['Lower']:
                shares = int(cash * 0.9 / price)
                if shares > 0:
                    cash -= shares * price
                    position = {"entry": price, "shares": shares, "date": str(row.name)[:10]}
        else:
            pnl_pct = (price - position["entry"]) / position["entry"] * 100
            reason = None
            if   price >= row['Upper']:        reason = "상단밴드 도달"
            elif pnl_pct >= take_profit:       reason = "목표수익 달성"
            elif pnl_pct <= -stop_loss:        reason = "손절"
            if reason:
                cash += shares * price
                trades.append({
                    "entry_date": position["date"], "exit_date": str(row.name)[:10],
                    "entry": round(position["entry"],2), "exit": round(price,2),
                    "shares": position["shares"],
                    "pnl": round(shares*price - position["shares"]*position["entry"], 2),
                    "pnl_pct": round(pnl_pct, 2), "reason": reason,
                })
                position, shares = None, 0

    if position:
        price = float(df.iloc[-1]['Close'])
        cash += shares * price
        pnl_pct = (price - position["entry"]) / position["entry"] * 100
        trades.append({
            "entry_date": position["date"], "exit_date": str(df.index[-1])[:10],
            "entry": round(position["entry"],2), "exit": round(price,2),
            "shares": position["shares"],
            "pnl": round(shares*price - position["shares"]*position["entry"], 2),
            "pnl_pct": round(pnl_pct, 2), "reason": "기간 종료(보유중)",
        })

    wins   = [t for t in trades if t['pnl'] > 0]
    losses = [t for t in trades if t['pnl'] <= 0]
    total_return = (cash - capital) / capital * 100
    win_rate     = len(wins)/len(trades)*100 if trades else 0

    # MDD
    pv = []
    c2, pos2, sh2 = capital, None, 0
    for i in range(1, len(df)):
        row, prev = df.iloc[i], df.iloc[i-1]
        p = float(row['Close'])
        if pos2 is None:
            if prev['Close'] > prev['Lower'] and row['Close'] <= row['Lower']:
                sh2 = int(c2*0.9/p)
                if sh2 > 0: c2 -= sh2*p; pos2 = p
        else:
            pp = (p-pos2)/pos2*100
            if p >= row['Upper'] or pp >= take_profit or pp <= -stop_loss:
                c2 += sh2*p; pos2, sh2 = None, 0
        pv.append(c2 + sh2*p)
    ps = pd.Series(pv) if pv else pd.Series([capital])
    mdd = float(((ps - ps.cummax()) / ps.cummax() * 100).min())

    return {
        "total_return": round(total_return, 2),
        "total_pnl":    round(cash - capital, 0),
        "final_value":  round(cash, 0),
        "win_rate":     round(win_rate, 1),
        "trade_count":  len(trades),
        "win_count":    len(wins),
        "loss_count":   len(losses),
        "avg_profit_pct": round(float(np.mean([t['pnl_pct'] for t in wins]))   if wins   else 0, 2),
        "avg_loss_pct":   round(float(np.mean([t['pnl_pct'] for t in losses])) if losses else 0, 2),
        "mdd":            round(mdd, 2),
        "trades":         trades[-20:],
    }


# ─── 워치리스트 (메모리) ─────────────────────────────────────────────────


# ════════════════════════════════════════════════════════════════
#  4가지 추가 전략 엔진
# ════════════════════════════════════════════════════════════════

# ── 공통 지표 헬퍼 ────────────────────────────────────────────

def _calc_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain  = delta.clip(lower=0).rolling(period).mean()
    loss  = (-delta.clip(upper=0)).rolling(period).mean()
    rs    = gain / loss.replace(0, np.nan)
    return 100 - 100 / (1 + rs)

def _calc_bb(series: pd.Series, period: int = 20, std_mult: float = 2.0):
    ma    = series.rolling(period).mean()
    std   = series.rolling(period).std()
    upper = ma + std_mult * std
    lower = ma - std_mult * std
    return ma, upper, lower

def _calc_ssl(df: pd.DataFrame, period: int = 10):
    """SSL Channel: SMA(High) vs SMA(Low) 교차"""
    sma_h = df['High'].rolling(period).mean()
    sma_l = df['Low'].rolling(period).mean()
    # 종가가 sma_h 위 → bull (1), 아래 → bear (-1)
    trend = np.where(df['Close'] >= sma_h, 1, np.where(df['Close'] <= sma_l, -1, np.nan))
    trend = pd.Series(trend, index=df.index).ffill().fillna(0)
    return sma_h, sma_l, trend

def _swing_highs_lows(series: pd.Series, lookback: int = 5):
    """단순 Swing High/Low 탐색"""
    highs, lows = [], []
    for i in range(lookback, len(series) - lookback):
        w = series.iloc[i-lookback:i+lookback+1]
        if series.iloc[i] == w.max():
            highs.append((i, float(series.iloc[i])))
        if series.iloc[i] == w.min():
            lows.append((i, float(series.iloc[i])))
    return highs, lows

def _calc_fvg(df: pd.DataFrame):
    """Fair Value Gap: 3캔들 패턴으로 갭 구간 계산"""
    fvgs = []
    for i in range(2, len(df)):
        c1, c2, c3 = df.iloc[i-2], df.iloc[i-1], df.iloc[i]
        # 강세 FVG: c1.high < c3.low
        if float(c1['High']) < float(c3['Low']):
            fvgs.append({'idx': i, 'type': 'bull',
                         'top': float(c3['Low']), 'bot': float(c1['High'])})
        # 약세 FVG: c1.low > c3.high
        if float(c1['Low']) > float(c3['High']):
            fvgs.append({'idx': i, 'type': 'bear',
                         'top': float(c1['Low']), 'bot': float(c3['High'])})
    return fvgs


# ── 전략 1: TBV / 유동성 스윕 (SMC) ────────────────────────

def signal_tbv_smc(df: pd.DataFrame, lookback: int = 5) -> dict:
    """
    유동성 스윕 + FVG 매매법
    - Swing High/Low 스윕 후 반대방향 전환
    - FVG 구간에서 발생 시 신뢰도↑
    """
    if len(df) < lookback * 2 + 10:
        return {"signal": "N/A", "strength": 0, "strategy": "TBV_SMC"}

    need_cols = {'Open','High','Low','Close'}
    if not need_cols.issubset(df.columns):
        return {"signal": "N/A", "strength": 0, "strategy": "TBV_SMC"}

    highs, lows = _swing_highs_lows(df['Close'], lookback)
    fvgs        = _calc_fvg(df)
    last_idx    = len(df) - 1
    last        = df.iloc[-1]
    prev        = df.iloc[-2]
    close       = float(last['Close'])
    signal      = "NEUTRAL"
    strength    = 0
    note        = ""

    # 매수 스윕: 최근 Swing Low 아래로 잠깐 찍고 양봉으로 마감
    if lows:
        recent_low_idx, recent_low_val = lows[-1]
        if recent_low_idx > last_idx - 10:   # 최근 10봉 이내
            swept_low  = float(prev['Low']) < recent_low_val
            bull_close = float(last['Close']) > float(last['Open'])
            if swept_low and bull_close:
                signal, strength = "STRONG_BUY", 85
                note = f"Swing Low({recent_low_val:.2f}) 스윕 후 양봉 반전"
                # FVG 내에서 발생하면 신뢰도↑
                for fvg in reversed(fvgs[-10:]):
                    if fvg['type'] == 'bull' and fvg['bot'] <= close <= fvg['top']:
                        strength = 95
                        note += " + FVG 구간 확인"
                        break

    # 매도 스윕: 최근 Swing High 위로 잠깐 찍고 음봉으로 마감
    if highs and signal == "NEUTRAL":
        recent_high_idx, recent_high_val = highs[-1]
        if recent_high_idx > last_idx - 10:
            swept_high = float(prev['High']) > recent_high_val
            bear_close = float(last['Close']) < float(last['Open'])
            if swept_high and bear_close:
                signal, strength = "STRONG_SELL", 85
                note = f"Swing High({recent_high_val:.2f}) 스윕 후 음봉 반전"
                for fvg in reversed(fvgs[-10:]):
                    if fvg['type'] == 'bear' and fvg['bot'] <= close <= fvg['top']:
                        strength = 95
                        note += " + FVG 구간 확인"
                        break

    # 약한 관심 신호: 최근 스윕 접근 중
    if signal == "NEUTRAL" and lows:
        recent_low_idx, recent_low_val = lows[-1]
        if recent_low_idx > last_idx - 15:
            dist_pct = (close - recent_low_val) / recent_low_val * 100
            if 0 < dist_pct < 2.0:
                signal, strength = "WATCH_BUY", 45
                note = f"Swing Low({recent_low_val:.2f}) 접근 중 ({dist_pct:.1f}%)"

    rr_stop  = round(close * 0.98, 2)   # 손절: 진입가 -2%
    rr_tp    = round(close * 1.04, 2)   # 익절: 1:2 손익비

    return {
        "signal": signal, "strength": strength, "strategy": "TBV_SMC",
        "close": round(close, 2), "note": note,
        "stop_loss": rr_stop, "take_profit": rr_tp,
        "rr_ratio": "1:2",
    }


def backtest_tbv_smc(df: pd.DataFrame, lookback: int = 5,
                     stop_pct: float = 2.0, rr: float = 2.0) -> dict:
    """TBV/SMC 백테스트"""
    if len(df) < lookback * 2 + 20:
        return {"error": "데이터 부족"}
    need = {'Open','High','Low','Close'}
    if not need.issubset(df.columns):
        return {"error": "OHLC 데이터 필요"}

    capital = 10_000_000
    cash, position, shares = capital, None, 0
    trades = []
    highs, lows = _swing_highs_lows(df['Close'], lookback)
    low_set  = {idx: val for idx, val in lows}
    high_set = {idx: val for idx, val in highs}

    for i in range(lookback + 2, len(df)):
        row  = df.iloc[i]
        prev = df.iloc[i-1]
        price = float(row['Close'])

        if position is None:
            # 매수 신호: 최근 swing low 스윕 후 양봉
            for j in range(i-10, i-1):
                if j in low_set:
                    if float(prev['Low']) < low_set[j] and float(row['Close']) > float(row['Open']):
                        shares = int(cash * 0.9 / price)
                        if shares > 0:
                            cash -= shares * price
                            sl = price * (1 - stop_pct/100)
                            tp = price * (1 + stop_pct/100 * rr)
                            position = {"entry": price, "shares": shares,
                                        "date": str(row.name)[:10], "sl": sl, "tp": tp,
                                        "side": "BUY"}
                        break
        else:
            pnl_pct = (price - position["entry"]) / position["entry"] * 100
            reason  = None
            if price <= position["sl"]:   reason = "손절"
            elif price >= position["tp"]: reason = "익절(1:2)"
            if reason:
                cash += shares * price
                trades.append({
                    "entry_date": position["date"], "exit_date": str(row.name)[:10],
                    "entry": round(position["entry"],2), "exit": round(price,2),
                    "shares": shares,
                    "pnl": round(shares*price - position["shares"]*position["entry"], 2),
                    "pnl_pct": round(pnl_pct, 2), "reason": reason,
                })
                position, shares = None, 0

    return _summarize_trades(trades, cash, capital)


# ── 전략 2: 볼린저 밴드 3시그마 ─────────────────────────────

def signal_bb3sigma(df: pd.DataFrame, period: int = 20) -> dict:
    """볼린저 밴드 3표준편차 이탈 후 복귀 신호"""
    if len(df) < period + 5:
        return {"signal": "N/A", "strength": 0, "strategy": "BB3SIGMA"}

    ma, upper3, lower3 = _calc_bb(df['Close'], period, 3.0)
    ma2, upper2, lower2 = _calc_bb(df['Close'], period, 2.0)

    last  = df.iloc[-1]
    prev  = df.iloc[-2]
    close = float(last['Close'])
    prev_close = float(prev['Close'])

    u3, l3 = float(upper3.iloc[-1]), float(lower3.iloc[-1])
    u3p, l3p = float(upper3.iloc[-2]), float(lower3.iloc[-2])
    ma_val = float(ma.iloc[-1])

    signal, strength, note = "NEUTRAL", 0, ""

    # 하단 3σ 이탈 후 복귀 → 매수
    if prev_close < l3p and close > l3:
        signal, strength = "STRONG_BUY", 90
        note = f"하단 3σ({l3:.2f}) 이탈 후 복귀 확인"
    elif close < l3:
        signal, strength = "WATCH_BUY", 50
        note = f"하단 3σ({l3:.2f}) 이탈 중 (복귀 봉 대기)"
    # 상단 3σ 이탈 후 복귀 → 매도
    elif prev_close > u3p and close < u3:
        signal, strength = "STRONG_SELL", 90
        note = f"상단 3σ({u3:.2f}) 이탈 후 복귀 확인"
    elif close > u3:
        signal, strength = "WATCH_SELL", 50
        note = f"상단 3σ({u3:.2f}) 이탈 중 (복귀 봉 대기)"

    return {
        "signal": signal, "strength": strength, "strategy": "BB3SIGMA",
        "close": round(close, 2),
        "bb_upper3": round(u3, 2), "bb_lower3": round(l3, 2),
        "bb_ma": round(ma_val, 2), "note": note,
        "stop_loss":   round(close * (0.97 if 'BUY' in signal else 1.03), 2),
        "take_profit": round(ma_val, 2),
    }


def backtest_bb3sigma(df: pd.DataFrame, period: int = 20,
                      stop_pct: float = 3.0) -> dict:
    """볼린저 3σ 백테스트"""
    if len(df) < period + 5:
        return {"error": "데이터 부족"}
    if 'Close' not in df.columns:
        return {"error": "Close 데이터 필요"}

    capital = 10_000_000
    cash, position, shares = capital, None, 0
    trades = []
    ma_s, up3_s, lo3_s = _calc_bb(df['Close'], period, 3.0)

    for i in range(period + 2, len(df)):
        price = float(df['Close'].iloc[i])
        prev_price = float(df['Close'].iloc[i-1])
        u3  = float(up3_s.iloc[i]);  l3  = float(lo3_s.iloc[i])
        u3p = float(up3_s.iloc[i-1]); l3p = float(lo3_s.iloc[i-1])
        ma_v = float(ma_s.iloc[i])

        if position is None:
            # 하단 3σ 이탈 후 복귀 → 매수
            if prev_price < l3p and price > l3:
                shares = int(cash * 0.9 / price)
                if shares > 0:
                    cash -= shares * price
                    sl = price * (1 - stop_pct/100)
                    position = {"entry": price, "shares": shares,
                                "date": str(df.index[i])[:10], "sl": sl, "tp": ma_v}
        else:
            pnl_pct = (price - position["entry"]) / position["entry"] * 100
            reason  = None
            if price <= position["sl"]:   reason = "손절"
            elif price >= position["tp"]: reason = "MA 복귀(익절)"
            # 상단 3σ 이탈 후 복귀도 청산
            elif prev_price > u3p and price < u3: reason = "상단3σ 복귀 청산"
            if reason:
                cash += shares * price
                trades.append({
                    "entry_date": position["date"], "exit_date": str(df.index[i])[:10],
                    "entry": round(position["entry"],2), "exit": round(price,2),
                    "shares": shares,
                    "pnl": round(shares*price - position["shares"]*position["entry"], 2),
                    "pnl_pct": round(pnl_pct, 2), "reason": reason,
                })
                position, shares = None, 0

    return _summarize_trades(trades, cash, capital)


# ── 전략 3: 피봇 VA 80% 법칙 ────────────────────────────────

def _calc_value_area(df_day: pd.DataFrame, va_pct: float = 0.70):
    """
    일봉 데이터로 Value Area(VA) 계산
    POC = 가장 거래량이 많은 가격, VA = 전체 거래량의 70% 구간
    """
    if df_day.empty or 'Volume' not in df_day.columns:
        return None
    last = df_day.iloc[-1]
    high = float(last['High']); low = float(last['Low'])
    vol  = float(last['Volume'])
    # 가격 버킷 50개로 분할
    buckets = 50
    step = (high - low) / buckets if high != low else 1
    prices = np.linspace(low, high, buckets)
    # 균등 분배 (실제 틱데이터 없으므로 근사)
    vols   = np.ones(buckets) * vol / buckets
    poc_idx = int(np.argmax(vols))
    poc     = float(prices[poc_idx])
    # VA: POC에서 양쪽으로 누적 70%
    total_vol = vols.sum()
    target    = total_vol * va_pct
    lo_i = hi_i = poc_idx
    accum = vols[poc_idx]
    while accum < target and (lo_i > 0 or hi_i < buckets-1):
        add_lo = vols[lo_i-1] if lo_i > 0 else 0
        add_hi = vols[hi_i+1] if hi_i < buckets-1 else 0
        if add_lo >= add_hi and lo_i > 0:
            lo_i -= 1; accum += add_lo
        elif hi_i < buckets-1:
            hi_i += 1; accum += add_hi
        else:
            lo_i -= 1; accum += add_lo
    return {
        "poc": round(poc, 2),
        "vah": round(float(prices[hi_i]), 2),  # Value Area High
        "val": round(float(prices[lo_i]), 2),  # Value Area Low
    }


def signal_pivot_va(df: pd.DataFrame) -> dict:
    """피봇 VA 80% 법칙"""
    if len(df) < 3:
        return {"signal": "N/A", "strength": 0, "strategy": "PIVOT_VA"}
    need = {'High','Low','Close','Volume'}
    if not need.issubset(df.columns):
        return {"signal": "N/A", "strength": 0, "strategy": "PIVOT_VA"}

    va_prev = _calc_value_area(df.iloc[:-1])  # 전날 VA
    if not va_prev:
        return {"signal": "N/A", "strength": 0, "strategy": "PIVOT_VA"}

    close  = float(df.iloc[-1]['Close'])
    open_  = float(df.iloc[-1]['Open']) if 'Open' in df.columns else close
    vah    = va_prev['vah']; val = va_prev['val']; poc = va_prev['poc']

    signal, strength, note = "NEUTRAL", 0, ""

    # 당일 시가가 VA 아래서 시작 → VA 안으로 진입 → 매수 (VAH까지 목표)
    if open_ < val and close > val:
        signal, strength = "STRONG_BUY", 88
        note  = f"시가 VA 하단({val:.2f}) 아래 → VA 진입 → VAH({vah:.2f}) 목표 (80%룰)"
    elif open_ > vah and close < vah:
        signal, strength = "STRONG_SELL", 88
        note  = f"시가 VA 상단({vah:.2f}) 위 → VA 진입 → VAL({val:.2f}) 목표 (80%룰)"
    elif close < val * 1.02 and open_ < val:
        signal, strength = "WATCH_BUY", 45
        note  = f"VA 하단({val:.2f}) 접근 중"
    elif close > vah * 0.98 and open_ > vah:
        signal, strength = "WATCH_SELL", 45
        note  = f"VA 상단({vah:.2f}) 접근 중"

    return {
        "signal": signal, "strength": strength, "strategy": "PIVOT_VA",
        "close": round(close, 2),
        "vah": vah, "val": val, "poc": poc, "note": note,
        "stop_loss":   round(val * 0.99, 2) if 'BUY' in signal else round(vah * 1.01, 2),
        "take_profit": round(vah, 2)         if 'BUY' in signal else round(val, 2),
    }


def backtest_pivot_va(df: pd.DataFrame, stop_pct: float = 2.0) -> dict:
    """피봇 VA 백테스트"""
    if len(df) < 5:
        return {"error": "데이터 부족"}
    need = {'High','Low','Close','Volume'}
    if not need.issubset(df.columns):
        return {"error": "OHLCV 데이터 필요"}

    capital = 10_000_000
    cash, position, shares = capital, None, 0
    trades = []

    for i in range(2, len(df)):
        va = _calc_value_area(df.iloc[:i])
        if not va:
            continue
        row   = df.iloc[i]
        price = float(row['Close'])
        open_ = float(row['Open']) if 'Open' in df.columns else price
        vah, val = va['vah'], va['val']

        if position is None:
            if open_ < val and price > val:
                shares = int(cash * 0.9 / price)
                if shares > 0:
                    cash -= shares * price
                    sl = price * (1 - stop_pct/100)
                    position = {"entry": price, "shares": shares,
                                "date": str(row.name)[:10], "sl": sl, "tp": vah}
        else:
            pnl_pct = (price - position["entry"]) / position["entry"] * 100
            reason  = None
            if price <= position["sl"]:   reason = "손절"
            elif price >= position["tp"]: reason = "VAH 달성(익절)"
            if reason:
                cash += shares * price
                trades.append({
                    "entry_date": position["date"], "exit_date": str(row.name)[:10],
                    "entry": round(position["entry"],2), "exit": round(price,2),
                    "shares": shares,
                    "pnl": round(shares*price - position["shares"]*position["entry"], 2),
                    "pnl_pct": round(pnl_pct, 2), "reason": reason,
                })
                position, shares = None, 0

    return _summarize_trades(trades, cash, capital)


# ── 전략 4: SSL 채널 + RSI ───────────────────────────────────

def signal_ssl_rsi(df: pd.DataFrame, ssl_period: int = 10,
                   rsi_period: int = 14, rsi_ob: float = 70.0) -> dict:
    """SSL 채널 추세 + RSI 돌파 스캘핑"""
    need = {'High','Low','Close'}
    if not need.issubset(df.columns) or len(df) < ssl_period + rsi_period + 5:
        return {"signal": "N/A", "strength": 0, "strategy": "SSL_RSI"}

    sma_h, sma_l, trend = _calc_ssl(df, ssl_period)
    rsi = _calc_rsi(df['Close'], rsi_period)

    curr_trend = float(trend.iloc[-1])
    prev_trend = float(trend.iloc[-2])
    curr_rsi   = float(rsi.iloc[-1])
    prev_rsi   = float(rsi.iloc[-2])
    close      = float(df['Close'].iloc[-1])
    rsi_os     = 100 - rsi_ob   # 과매도선

    signal, strength, note = "NEUTRAL", 0, ""

    # 롱: SSL 상승 추세 + RSI 과매도 → 반등 돌파
    if curr_trend == 1:
        if prev_rsi < rsi_os and curr_rsi >= rsi_os:
            signal, strength = "STRONG_BUY", 88
            note = f"SSL 상승추세 + RSI({curr_rsi:.1f}) 과매도 돌파"
        elif curr_rsi < rsi_os + 5:
            signal, strength = "WATCH_BUY", 50
            note = f"SSL 상승추세 + RSI({curr_rsi:.1f}) 과매도 접근"
        elif prev_trend != 1:
            signal, strength = "BUY", 70
            note = f"SSL 채널 상승 전환"

    # 숏: SSL 하락 추세 + RSI 과매수 → 하락 돌파
    elif curr_trend == -1:
        if prev_rsi > rsi_ob and curr_rsi <= rsi_ob:
            signal, strength = "STRONG_SELL", 88
            note = f"SSL 하락추세 + RSI({curr_rsi:.1f}) 과매수 돌파"
        elif curr_rsi > rsi_ob - 5:
            signal, strength = "WATCH_SELL", 50
            note = f"SSL 하락추세 + RSI({curr_rsi:.1f}) 과매수 접근"
        elif prev_trend != -1:
            signal, strength = "SELL", 70
            note = f"SSL 채널 하락 전환"

    sl_pct = 0.01
    return {
        "signal": signal, "strength": strength, "strategy": "SSL_RSI",
        "close": round(close, 2),
        "rsi": round(curr_rsi, 1),
        "ssl_trend": "상승" if curr_trend == 1 else "하락" if curr_trend == -1 else "중립",
        "note": note,
        "stop_loss":   round(close * (1 - sl_pct), 2) if 'BUY'  in signal else round(close * (1 + sl_pct), 2),
        "take_profit": round(close * (1 + sl_pct*2), 2) if 'BUY' in signal else round(close * (1 - sl_pct*2), 2),
        "rr_ratio": "1:2",
    }


def backtest_ssl_rsi(df: pd.DataFrame, ssl_period: int = 10,
                     rsi_period: int = 14, rsi_ob: float = 70.0,
                     stop_pct: float = 1.0) -> dict:
    """SSL+RSI 백테스트"""
    need = {'High','Low','Close'}
    if not need.issubset(df.columns) or len(df) < ssl_period + rsi_period + 5:
        return {"error": "데이터 부족"}

    capital = 10_000_000
    cash, position, shares = capital, None, 0
    trades = []
    sma_h, sma_l, trend = _calc_ssl(df, ssl_period)
    rsi_s = _calc_rsi(df['Close'], rsi_period)
    rsi_os = 100 - rsi_ob

    for i in range(ssl_period + rsi_period + 2, len(df)):
        price      = float(df['Close'].iloc[i])
        curr_trend = float(trend.iloc[i])
        curr_rsi   = float(rsi_s.iloc[i])
        prev_rsi   = float(rsi_s.iloc[i-1])

        if position is None:
            if curr_trend == 1 and prev_rsi < rsi_os and curr_rsi >= rsi_os:
                shares = int(cash * 0.9 / price)
                if shares > 0:
                    cash -= shares * price
                    sl = price * (1 - stop_pct/100)
                    tp = price * (1 + stop_pct/100 * 2)
                    position = {"entry": price, "shares": shares,
                                "date": str(df.index[i])[:10], "sl": sl, "tp": tp}
        else:
            pnl_pct = (price - position["entry"]) / position["entry"] * 100
            reason  = None
            if price <= position["sl"]:   reason = "손절"
            elif price >= position["tp"]: reason = "익절(1:2)"
            if reason:
                cash += shares * price
                trades.append({
                    "entry_date": position["date"], "exit_date": str(df.index[i])[:10],
                    "entry": round(position["entry"],2), "exit": round(price,2),
                    "shares": shares,
                    "pnl": round(shares*price - position["shares"]*position["entry"], 2),
                    "pnl_pct": round(pnl_pct, 2), "reason": reason,
                })
                position, shares = None, 0

    return _summarize_trades(trades, cash, capital)


# ── 공통 성과 집계 ────────────────────────────────────────────

def _summarize_trades(trades: list, cash: float, capital: float) -> dict:
    wins   = [t for t in trades if t['pnl'] > 0]
    losses = [t for t in trades if t['pnl'] <= 0]
    total_return = (cash - capital) / capital * 100
    win_rate     = len(wins)/len(trades)*100 if trades else 0
    pv = pd.Series([capital] + [capital + sum(t['pnl'] for t in trades[:i+1])
                                for i in range(len(trades))])
    mdd = float(((pv - pv.cummax()) / pv.cummax() * 100).min()) if len(pv) > 1 else 0
    return {
        "total_return":    round(total_return, 2),
        "total_pnl":       round(cash - capital, 0),
        "final_value":     round(cash, 0),
        "win_rate":        round(win_rate, 1),
        "trade_count":     len(trades),
        "win_count":       len(wins),
        "loss_count":      len(losses),
        "avg_profit_pct":  round(float(np.mean([t['pnl_pct'] for t in wins]))   if wins   else 0, 2),
        "avg_loss_pct":    round(float(np.mean([t['pnl_pct'] for t in losses])) if losses else 0, 2),
        "mdd":             round(mdd, 2),
        "trades":          trades[-20:],
    }


# ── 전략 라우터 ──────────────────────────────────────────────

STRATEGY_LIST = {
    "ENVELOPE":  {"name": "엔벨로프 전략",           "desc": "MA±N% 밴드 하단 매수 / 상단 매도"},
    "TBV_SMC":   {"name": "TBV / 유동성 스윕 (SMC)", "desc": "Swing H/L 스윕 + FVG 반전 (손익비 1:2)"},
    "BB3SIGMA":  {"name": "볼린저 밴드 3σ",          "desc": "3표준편차 이탈 후 평균 회귀"},
    "PIVOT_VA":  {"name": "피봇 VA 80% 법칙",        "desc": "Value Area 진입 후 반대 끝 목표"},
    "SSL_RSI":   {"name": "SSL 채널 + RSI",          "desc": "SSL 추세 + RSI 돌파 스캘핑 (손익비 1:2)"},
}

def get_strategy_signal(df: pd.DataFrame, strategy: str, params: dict) -> dict:
    """전략 코드 → 신호 계산"""
    if strategy == "TBV_SMC":
        return signal_tbv_smc(df, lookback=int(params.get('lookback', 5)))
    elif strategy == "BB3SIGMA":
        return signal_bb3sigma(df, period=int(params.get('period', 20)))
    elif strategy == "PIVOT_VA":
        return signal_pivot_va(df)
    elif strategy == "SSL_RSI":
        return signal_ssl_rsi(df,
            ssl_period=int(params.get('ssl_period', 10)),
            rsi_period=int(params.get('rsi_period', 14)),
            rsi_ob=float(params.get('rsi_ob', 70)),
        )
    else:  # ENVELOPE (기본)
        return get_signal(df, pct=float(params.get('pct', 5.0)))

def run_backtest(df: pd.DataFrame, strategy: str, params: dict) -> dict:
    """전략 코드 → 백테스트 실행"""
    if strategy == "TBV_SMC":
        return backtest_tbv_smc(df,
            lookback=int(params.get('lookback', 5)),
            stop_pct=float(params.get('stop_loss', 2.0)),
            rr=float(params.get('rr', 2.0)),
        )
    elif strategy == "BB3SIGMA":
        return backtest_bb3sigma(df,
            period=int(params.get('period', 20)),
            stop_pct=float(params.get('stop_loss', 3.0)),
        )
    elif strategy == "PIVOT_VA":
        return backtest_pivot_va(df, stop_pct=float(params.get('stop_loss', 2.0)))
    elif strategy == "SSL_RSI":
        return backtest_ssl_rsi(df,
            ssl_period=int(params.get('ssl_period', 10)),
            rsi_period=int(params.get('rsi_period', 14)),
            rsi_ob=float(params.get('rsi_ob', 70)),
            stop_pct=float(params.get('stop_loss', 1.0)),
        )
    else:  # ENVELOPE
        return backtest_envelope(df,
            period=int(params.get('period', 20)),
            pct=float(params.get('pct', 5.0)),
            stop_loss=float(params.get('stop_loss', 3.0)),
            take_profit=float(params.get('take_profit', 5.0)),
        )

wl_lock = threading.Lock()
watchlist: dict = {}   # key = "market:ticker"

def fetch_snapshot(ticker: str, period: int, pct: float) -> dict:
    df = None
    try:
        end   = datetime.now()
        start = end - timedelta(days=max(90, period*3))
        df    = yf.Ticker(ticker).history(start=start, end=end, auto_adjust=True)
        if df.empty or len(df) < period+2:
            return None
        df = df[['Close']].copy()
        df = calc_envelope(df, period, pct).dropna()
        if df.empty:
            return None
        sig = get_signal(df, pct)
        change_1d = 0.0
        if len(df) >= 2:
            prev = float(df['Close'].iloc[-2])
            curr = float(df['Close'].iloc[-1])
            change_1d = round((curr-prev)/prev*100, 2)
        sig['change_1d']  = change_1d
        sig['updated_at'] = _now_kst('%H:%M:%S')
        return sig
    except Exception:
        return None
    finally:
        del df
        gc.collect()


# ─── API 라우트 ───────────────────────────────────────────────────────────

@app.route('/')
def index():
    return send_from_directory('.', 'envelope_dashboard.html')

# 전략 목록
@app.route('/api/strategies')
def strategies_list():
    return jsonify(STRATEGY_LIST)

# 시장 목록
@app.route('/api/markets')
def markets():
    return jsonify({k: {"name": v["name"], "currency": v["currency"],
                        "index_name": v["index_name"]} for k, v in MARKETS.items()})

# 지수 현황
@app.route('/api/index/<market>')
def index_summary(market: str):
    m = MARKETS.get(market)
    if not m:
        return jsonify({"error": "unknown market"}), 404
    period = int(request.args.get('period', 20))
    pct    = float(request.args.get('pct', 5.0))
    raw = raw1y = df = None
    try:
        end   = datetime.now()
        start = end - timedelta(days=120)
        raw = yf.download(m['index'], start=start, end=end, auto_adjust=True, progress=False)
        df  = pd.DataFrame({'Close': raw['Close'].squeeze()})
        df  = calc_envelope(df, period, pct)
        sig = get_signal(df, pct)

        raw1y = yf.download(m['index'], start=end-timedelta(days=365), end=end,
                            auto_adjust=True, progress=False)
        ret1y = 0.0
        if not raw1y.empty:
            c = raw1y['Close'].squeeze()
            ret1y = float((c.iloc[-1]-c.iloc[0])/c.iloc[0]*100)

        return jsonify({"market": market, "name": m['index_name'],
                        "signal": sig, "return_1y": round(ret1y,2)})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        del raw, raw1y, df
        gc.collect()

# 스캐너
@app.route('/api/scan/<market>')
def scan(market: str):
    m = MARKETS.get(market)
    if not m:
        return jsonify({"error": "unknown market"}), 404
    period     = int(request.args.get('period', 20))
    pct        = float(request.args.get('pct', 5.0))
    sig_filter = request.args.get('signal', 'BUY_ONLY')   # 기본값: 매수관심 이상만
    strategy   = request.args.get('strategy', 'ENVELOPE').upper()
    limit      = int(request.args.get('limit', 50))

    tickers = get_all_tickers(market)[:60]
    end   = datetime.now()
    start = end - timedelta(days=180)   # 전략별 지표 계산에 충분한 기간

    results = []
    raw = None
    try:
        raw      = yf.download(tickers, start=start, end=end, auto_adjust=True, progress=False)
        close_df = raw['Close'] if isinstance(raw.columns, pd.MultiIndex) else raw

        # OHLCV 전체가 필요한 전략
        need_ohlcv = strategy in ("TBV_SMC", "PIVOT_VA", "SSL_RSI")
        ohlcv_cache = {}
        if need_ohlcv:
            for col in ('Open','High','Low','Volume'):
                try:
                    ohlcv_cache[col] = raw[col] if isinstance(raw.columns, pd.MultiIndex) else raw
                except Exception:
                    pass

        for ticker in tickers:
            df = None
            df_env = None
            try:
                col = ticker if ticker in close_df.columns else None
                if col is None:
                    continue
                s = close_df[col].dropna()
                if len(s) < 30:
                    continue

                # 기본 df 구성
                df = pd.DataFrame({'Close': s})

                # OHLCV 컬럼 추가 (있으면)
                for c in ('Open','High','Low','Volume'):
                    if c in ohlcv_cache and col in ohlcv_cache[c].columns:
                        df[c] = ohlcv_cache[c][col]

                # 엔벨로프는 항상 계산 (신호 강도 보조용)
                df_env = calc_envelope(df, period, pct)

                # 선택된 전략으로 신호 계산
                params = {'period': period, 'pct': pct}
                sig = get_strategy_signal(df, strategy, params)

                if sig.get('signal') in ('N/A', None):
                    continue

                w52_high = float(s.tail(252).max())
                w52_low  = float(s.tail(252).min())
                close_v  = float(s.iloc[-1])
                from_52h = (close_v - w52_high) / w52_high * 100
                chg = 0.0
                if len(s) >= 2:
                    chg = (float(s.iloc[-1]) - float(s.iloc[-2])) / float(s.iloc[-2]) * 100

                # 엔벨로프 보조 수치
                env_sig = get_signal(df_env.dropna(), pct)

                results.append({
                    "ticker": ticker,
                    "display_ticker": get_display_name(ticker, market),
                    "sector": get_sector(market, ticker),
                    "signal":   sig.get('signal', 'N/A'),
                    "strength": sig.get('strength', 0),
                    "strategy": strategy,
                    "note":     sig.get('note', ''),
                    "close":    close_v,
                    "ma":       env_sig.get('ma', 0),
                    "upper":    env_sig.get('upper', 0),
                    "lower":    env_sig.get('lower', 0),
                    "pct_from_ma":    env_sig.get('pct_from_ma', 0),
                    "pct_from_lower": env_sig.get('pct_from_lower', 0),
                    "pct_from_upper": env_sig.get('pct_from_upper', 0),
                    "stop_loss":   sig.get('stop_loss', 0),
                    "take_profit": sig.get('take_profit', 0),
                    "week52_high": round(w52_high, 2),
                    "week52_low":  round(w52_low,  2),
                    "from_52w_high": round(from_52h, 2),
                    "change_1d": round(chg, 2),
                    "currency": m['currency'],
                })
            except Exception:
                continue
            finally:
                del df, df_env
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        del raw
        gc.collect()

    # ── 필터: 기본값 BUY_ONLY (강력매수 + 매수관심만)
    buy_signals = {'STRONG_BUY', 'BUY', 'WATCH_BUY'}
    sell_signals = {'STRONG_SELL', 'SELL', 'WATCH_SELL'}

    if sig_filter == 'BUY_ONLY' or sig_filter == 'BUY':
        results = [r for r in results if r['signal'] in buy_signals]
    elif sig_filter == 'STRONG_BUY':
        results = [r for r in results if r['signal'] in {'STRONG_BUY', 'BUY'}]
    elif sig_filter == 'SELL':
        results = [r for r in results if r['signal'] in sell_signals]
    elif sig_filter == 'ALL':
        results = [r for r in results]   # 전체

    # 강도 순 정렬
    sig_order = {'STRONG_BUY':0,'BUY':1,'WATCH_BUY':2,'NEUTRAL':3,'WATCH_SELL':4,'SELL':5,'STRONG_SELL':6}
    results.sort(key=lambda x: (sig_order.get(x['signal'], 9), -x['strength']))
    return jsonify({"stocks": results[:limit], "total": len(results),
                    "scanned": len(tickers), "market": market, "strategy": strategy})

# 차트 데이터
@app.route('/api/chart/<market>/<ticker>')
def chart_data(market: str, ticker: str):
    m = MARKETS.get(market)
    if not m:
        return jsonify({"error":"unknown market"}), 404
    days   = int(request.args.get('days', 180))
    period = int(request.args.get('period', 20))
    pct    = float(request.args.get('pct', 5.0))

    # market suffix 자동 추가 (예: 042700 → 042700.KS)
    suffix = m.get('suffix', '')
    full_ticker = ticker + suffix if suffix and not ticker.endswith(suffix) else ticker

    end   = datetime.now()
    start = end - timedelta(days=days + period*2)
    df = None
    try:
        df = yf.Ticker(full_ticker).history(start=start, end=end, auto_adjust=True)
        if df.empty:
            return jsonify({"error":"No data"}), 404
        df = df[['Open','High','Low','Close','Volume']].copy()
        df = calc_envelope(df, period, pct).dropna()
        df = df.tail(days)
        sig = get_signal(df, pct)

        ohlc = [{"date": str(dt)[:10],
                 "open":   round(float(r['Open']),  2),
                 "high":   round(float(r['High']),  2),
                 "low":    round(float(r['Low']),   2),
                 "close":  round(float(r['Close']), 2),
                 "volume": int(r['Volume']),
                 "ma":     round(float(r['MA']),    2),
                 "upper":  round(float(r['Upper']), 2),
                 "lower":  round(float(r['Lower']), 2),
                 } for dt, r in df.iterrows()]
        return jsonify({"ticker": ticker, "market": market,
                        "currency": m['currency'], "ohlc": ohlc, "signal": sig})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        del df
        gc.collect()

# 백테스트
@app.route('/api/backtest/<market>/<ticker>')
def backtest_route(market: str, ticker: str):
    m = MARKETS.get(market)
    if not m:
        return jsonify({"error":"unknown market"}), 404

    strategy    = request.args.get('strategy', 'ENVELOPE').upper()
    days        = int(request.args.get('days', 365))
    period      = int(request.args.get('period', 20))
    pct         = float(request.args.get('pct', 5.0))
    stop_loss   = float(request.args.get('stop_loss', 3.0))
    take_profit = float(request.args.get('take_profit', 5.0))
    lookback    = int(request.args.get('lookback', 5))
    rr          = float(request.args.get('rr', 2.0))
    ssl_period  = int(request.args.get('ssl_period', 10))
    rsi_period  = int(request.args.get('rsi_period', 14))
    rsi_ob      = float(request.args.get('rsi_ob', 70.0))

    end   = datetime.now()
    start = end - timedelta(days=days + 60)
    df = None
    try:
        df = yf.Ticker(ticker).history(start=start, end=end, auto_adjust=True)
        if df.empty:
            return jsonify({"error":"No data"}), 404

        # OHLCV 컬럼 정리
        cols = [c for c in ['Open','High','Low','Close','Volume'] if c in df.columns]
        df = df[cols].copy()

        params = {
            'period': period, 'pct': pct,
            'stop_loss': stop_loss, 'take_profit': take_profit,
            'lookback': lookback, 'rr': rr,
            'ssl_period': ssl_period, 'rsi_period': rsi_period, 'rsi_ob': rsi_ob,
        }
        result = run_backtest(df, strategy, params)
        result.update({
            "ticker": ticker, "market": market, "currency": m['currency'],
            "strategy": strategy,
            "strategy_name": STRATEGY_LIST.get(strategy, {}).get('name', strategy),
            "params": params,
        })
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        del df
        gc.collect()


# ── 시장 전체 일괄 백테스트 ──────────────────────────────────────────────────
@app.route('/api/backtest_all/<market>')
def backtest_all_route(market: str):
    """티커 미지정 시 시장 전체 종목 일괄 백테스트 (상위 결과 반환)"""
    m = MARKETS.get(market)
    if not m:
        return jsonify({"error": "unknown market"}), 404

    strategy    = request.args.get('strategy', 'ENVELOPE').upper()
    days        = int(request.args.get('days', 365))
    period      = int(request.args.get('period', 20))
    pct         = float(request.args.get('pct', 5.0))
    stop_loss   = float(request.args.get('stop_loss', 3.0))
    take_profit = float(request.args.get('take_profit', 5.0))
    lookback    = int(request.args.get('lookback', 5))
    rr          = float(request.args.get('rr', 2.0))
    ssl_period  = int(request.args.get('ssl_period', 10))
    rsi_period  = int(request.args.get('rsi_period', 14))
    rsi_ob      = float(request.args.get('rsi_ob', 70.0))
    top_n       = int(request.args.get('top_n', 20))  # 상위 N개만 반환

    all_tickers = get_all_tickers(market)
    end   = datetime.now()
    start = end - timedelta(days=days + 60)

    params = {
        'period': period, 'pct': pct,
        'stop_loss': stop_loss, 'take_profit': take_profit,
        'lookback': lookback, 'rr': rr,
        'ssl_period': ssl_period, 'rsi_period': rsi_period, 'rsi_ob': rsi_ob,
    }

    results = []
    errors  = []
    for ticker in all_tickers:
        df = None
        try:
            df = yf.Ticker(ticker).history(start=start, end=end, auto_adjust=True)
            if df.empty or len(df) < 30:
                continue
            cols = [c for c in ['Open','High','Low','Close','Volume'] if c in df.columns]
            df = df[cols].copy()
            r = run_backtest(df, strategy, params)
            # ticker 표시용 (접미사 제거 + 한국어명)
            display = get_display_name(ticker, market)
            r.update({
                "ticker": ticker,
                "display_ticker": display,
                "market": market,
                "currency": m['currency'],
                "strategy": strategy,
                "strategy_name": STRATEGY_LIST.get(strategy, {}).get('name', strategy),
            })
            results.append(r)
        except Exception as e:
            errors.append({"ticker": ticker, "error": str(e)})
        finally:
            del df
            gc.collect()

    # 수익률 기준 내림차순 정렬
    results.sort(key=lambda x: x.get('total_return', -9999), reverse=True)

    return jsonify({
        "ok": True,
        "market": market,
        "strategy": strategy,
        "strategy_name": STRATEGY_LIST.get(strategy, {}).get('name', strategy),
        "total_scanned": len(results) + len(errors),
        "success_count": len(results),
        "error_count": len(errors),
        "top_results": results[:top_n],
        "all_results": results,
        "days": days,
        "params": params,
    })



@app.route('/api/watchlist', methods=['GET'])
def wl_get():
    with wl_lock:
        return jsonify(list(watchlist.values()))

@app.route('/api/watchlist/add', methods=['POST'])
def wl_add():
    data    = request.get_json(force=True)
    market  = data.get('market','US')
    ticker  = data.get('ticker','').upper().strip()
    period  = int(data.get('period', 20))
    pct     = float(data.get('pct', 5.0))
    if not ticker:
        return jsonify({'error':'티커 없음'}), 400

    m = MARKETS.get(market, {})
    suffix = m.get('suffix','')
    full_ticker = ticker + suffix if suffix and not ticker.endswith(suffix) else ticker

    snap = fetch_snapshot(full_ticker, period, pct)
    if snap is None:
        return jsonify({'error': f'{ticker} 데이터 없음'}), 404

    key = f"{market}:{ticker}"
    entry = {
        "key": key, "market": market, "ticker": full_ticker,
        "display_ticker": get_display_name(full_ticker, market),
        "market_name": m.get('name', market),
        "currency": m.get('currency','USD'),
        "sector": get_sector(market, full_ticker),
        "period": period, "pct": pct,
        "added_at": _now_kst('%H:%M:%S'),
        "last_signal": snap, "prev_signal": snap['signal'],
        "history": [{"time": snap['updated_at'], "signal": snap['signal'],
                     "close": snap['close'], "pct_from_lower": snap['pct_from_lower']}],
        "alert_count": 0, "active": snap['signal'] != 'NEUTRAL',
        "signal_changed": False,
    }
    with wl_lock:
        watchlist[key] = entry
    return jsonify({'ok': True, 'data': entry})

@app.route('/api/watchlist/remove/<path:key>', methods=['DELETE'])
def wl_remove(key: str):
    with wl_lock:
        watchlist.pop(key, None)
    return jsonify({'ok': True})

@app.route('/api/watchlist/update', methods=['POST'])
def wl_update():
    snap_targets = {}
    with wl_lock:
        for k, v in watchlist.items():
            snap_targets[k] = (v['ticker'], v['period'], v['pct'])

    updated = []
    for key, (ticker, period, pct) in snap_targets.items():
        snap = fetch_snapshot(ticker, period, pct)
        if snap is None:
            continue
        with wl_lock:
            if key not in watchlist:
                continue
            item = watchlist[key]
            prev = item.get('prev_signal', snap['signal'])
            changed = prev != snap['signal']
            if changed:
                item['alert_count'] += 1
                item['history'].append({
                    "time": snap['updated_at'], "signal": snap['signal'],
                    "close": snap['close'], "pct_from_lower": snap['pct_from_lower'],
                })
                item['history'] = item['history'][-30:]
            item['last_signal']    = snap
            item['prev_signal']    = snap['signal']
            item['signal_changed'] = changed
            item['active']         = snap['signal'] != 'NEUTRAL'
            updated.append(dict(item))

    return jsonify({"updated": len(updated), "items": updated})


# ─── 계좌 & 운영 API ──────────────────────────────────────────────────────

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def _read_json(filename: str) -> dict:
    """로컬 JSON 파일을 읽어 dict 반환. 없거나 파싱 실패 시 {} 반환."""
    path = os.path.join(BASE_DIR, filename)
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}

def _resolve_kr_ticker(code6: str) -> str:
    """6자리 한국 종목코드 → yfinance ticker 자동 판별 (KQ 우선, 실패 시 KS)"""
    for suffix in ('.KQ', '.KS'):
        try:
            df = yf.Ticker(code6 + suffix).history(period='2d', auto_adjust=True)
            if not df.empty:
                return code6 + suffix
        except Exception:
            pass
    return code6 + '.KS'   # fallback


# ─── 실시간 USD/KRW 환율 조회 ─────────────────────────────────────────────────
_fx_cache = {'rate': 1400.0, 'ts': 0.0}   # 10분 캐시

def _get_usd_krw() -> float:
    """USD/KRW 실시간 환율 조회.
    1차: yfinance USDKRW=X  2차: open.er-api.com  3차: 캐시값  4차: 1400 기본값"""
    import time
    now = time.time()
    if now - _fx_cache['ts'] < 600 and _fx_cache['rate'] > 0:   # 10분 캐시
        return _fx_cache['rate']
    rate = None
    # 1차: yfinance
    _fx_df = None
    try:
        _fx_df = yf.Ticker('USDKRW=X').history(period='2d', auto_adjust=True)
        if not _fx_df.empty:
            rate = float(_fx_df['Close'].iloc[-1])
    except Exception:
        pass
    finally:
        del _fx_df
        gc.collect()
    # 2차: open.er-api (무료, 키 불필요)
    if not rate or rate < 100:
        try:
            import requests as _req
            r = _req.get('https://open.er-api.com/v6/latest/USD', timeout=5)
            rate = float(r.json()['rates']['KRW'])
        except Exception:
            pass
    if rate and rate > 100:
        _fx_cache['rate'] = round(rate, 2)
        _fx_cache['ts']   = now
        return _fx_cache['rate']
    return _fx_cache['rate']   # 캐시 또는 기본값 1400


# KIS(한국투자증권) / 토스증권 API — 실계좌 보유종목 조회
def _fetch_real_holdings():
    """토스증권 Open API로 실계좌 보유종목 + 계좌 요약 조회.
    - 토큰: POST /oauth2/token
    - 계좌: GET /api/v1/accounts → accountSeq
    - 보유종목+요약: GET /api/v1/holdings
    반환: (kr_holdings, us_holdings, account_summary)
      account_summary = {assets_krw, assets_usd, pnl_krw, pnl_usd,
                         daily_pnl_krw, daily_pnl_usd, return_rate, daily_rate,
                         purchase_krw, purchase_usd}
    실패 시 ([], [], {}) 반환."""
    cfg        = _read_json('config.json')
    base_url   = cfg.get('base_url', 'https://openapi.tossinvest.com').rstrip('/')
    client_id  = cfg.get('api_key', '')
    client_secret = cfg.get('api_secret', '')
    if not (client_id and client_secret):
        return [], [], {}
    try:
        import requests as _req

        # ── 1. OAuth2 토큰 발급 (form-urlencoded) ───────────────────────
        token_res = _req.post(
            f'{base_url}/oauth2/token',
            data={
                'grant_type':    'client_credentials',
                'client_id':     client_id,
                'client_secret': client_secret,
            },
            timeout=10
        )
        token_data = token_res.json()
        access_token = token_data.get('access_token', '')
        if not access_token:
            return [], [], {}

        auth_headers = {'Authorization': f'Bearer {access_token}'}

        # ── 2. 계좌 목록 조회 → accountSeq 추출 ────────────────────────
        # 실제 응답: {"result": [{"accountNo":"...","accountSeq":1,...}]}
        accounts_res = _req.get(
            f'{base_url}/api/v1/accounts',
            headers=auth_headers,
            timeout=10
        )
        accounts_data = accounts_res.json()
        # 토스증권 응답은 result 배열 또는 data.accounts 배열 모두 지원
        accounts = (accounts_data.get('result') or
                    accounts_data.get('data', {}).get('accounts', []))
        if not accounts:
            return [], [], {}
        account_seq = str(accounts[0].get('accountSeq', '1'))

        # ── 3. 보유종목 조회 ─────────────────────────────────────────────
        hold_headers = {**auth_headers, 'X-Tossinvest-Account': account_seq}
        hold_res = _req.get(
            f'{base_url}/api/v1/holdings',
            headers=hold_headers,
            timeout=15
        )
        hold_data = hold_res.json()
        # 실제 응답: {"result": {"items": [...]}}
        result_body = hold_data.get('result', {})
        items = (result_body.get('items') or
                 hold_data.get('data', {}).get('holdings', []))

        kr_holdings, us_holdings = [], []
        for item in items:
            # 실제 필드명: marketCountry, lastPrice, averagePurchasePrice
            market = item.get('marketCountry') or item.get('market', 'KR')
            qty    = float(item.get('quantity', 0))
            if qty <= 0:
                continue
            # 현재가: lastPrice 우선, 없으면 currentPrice
            cur_price = float(item.get('lastPrice') or item.get('currentPrice') or 0)
            # 평균단가: averagePurchasePrice 우선, 없으면 averagePrice
            avg_price = float(item.get('averagePurchasePrice') or item.get('averagePrice') or 0)
            # 평가금액: marketValue.amount.krw 또는 evaluationAmount
            mv_obj = item.get('marketValue', {})
            if isinstance(mv_obj, dict):
                amt_obj = mv_obj.get('amount', {})
                if isinstance(amt_obj, dict):
                    market_val = float(amt_obj.get('usd' if market == 'US' else 'krw', 0))
                else:
                    market_val = float(amt_obj or mv_obj.get('amount', 0) or 0)
            else:
                market_val = float(mv_obj or item.get('evaluationAmount', 0) or 0)
            # 손익: profitLoss.amount.krw 또는 profitLoss
            pl_obj = item.get('profitLoss', {})
            if isinstance(pl_obj, dict):
                amt_obj2 = pl_obj.get('amount', {})
                if isinstance(amt_obj2, dict):
                    pnl_val = float(amt_obj2.get('usd' if market == 'US' else 'krw', 0))
                else:
                    pnl_val = float(amt_obj2 or 0)
            else:
                pnl_val = float(pl_obj or 0)

            entry = {
                'symbol':        item.get('symbol', ''),
                'name':          item.get('name', ''),
                'quantity':      qty,
                'average_price': avg_price,
                'current_price': cur_price,
                'market_value':  market_val if market_val else cur_price * qty,
                'pnl':           pnl_val,
                'currency':      'USD' if market == 'US' else 'KRW',
                'market':        market,
                'side':          '보유',
                'source':        'TOSS_API',
            }
            if market == 'US':
                us_holdings.append(entry)
            else:
                kr_holdings.append(entry)

        # ── 4. holdings 상위 요약 필드 파싱 ──────────────────────────
        # result.totalPurchaseAmount / marketValue / profitLoss / dailyProfitLoss
        def _f(obj, *keys):
            """중첩 dict 안전 float 추출"""
            for k in keys:
                if isinstance(obj, dict):
                    obj = obj.get(k, {})
                else:
                    return 0.0
            try:
                return float(obj or 0)
            except (TypeError, ValueError):
                return 0.0

        mv_krw  = _f(result_body, 'marketValue', 'amount', 'krw')
        mv_usd  = _f(result_body, 'marketValue', 'amount', 'usd')
        pl_krw  = _f(result_body, 'profitLoss',  'amount', 'krw')
        pl_usd  = _f(result_body, 'profitLoss',  'amount', 'usd')
        dpl_krw = _f(result_body, 'dailyProfitLoss', 'amount', 'krw')
        dpl_usd = _f(result_body, 'dailyProfitLoss', 'amount', 'usd')
        pur_krw = _f(result_body, 'totalPurchaseAmount', 'krw')
        pur_usd = _f(result_body, 'totalPurchaseAmount', 'usd')
        try:
            ret_rate  = float(result_body.get('profitLoss',  {}).get('rate',  0) or 0)
            day_rate  = float(result_body.get('dailyProfitLoss', {}).get('rate', 0) or 0)
        except (TypeError, ValueError):
            ret_rate = day_rate = 0.0

        account_summary = {
            'assets_krw':    mv_krw,
            'assets_usd':    mv_usd,
            'pnl_krw':       pl_krw,
            'pnl_usd':       pl_usd,
            'daily_pnl_krw': dpl_krw,
            'daily_pnl_usd': dpl_usd,
            'purchase_krw':  pur_krw,
            'purchase_usd':  pur_usd,
            'return_rate':   ret_rate,
            'daily_rate':    day_rate,
        }

        return kr_holdings, us_holdings, account_summary

    except Exception:
        return [], [], {}


def _enrich_holdings_with_live_price(holdings: list) -> list:
    """보유 종목 리스트의 current_price / market_value / pnl 을 yfinance 실시간으로 갱신.
    KIS API로 이미 현재가가 채워진 종목(source=KIS_API)은 yfinance 조회 생략."""
    if not holdings:
        return holdings

    def normalize_ticker(raw_code: str) -> str:
        """A005930 → 005930, 6자리 숫자 → KQ/KS 자동 판별"""
        code = raw_code.lstrip('A')
        if code.isdigit() and len(code) == 6:
            return _resolve_kr_ticker(code)
        return raw_code   # US 종목 등 그대로

    # KIS API 데이터는 current_price가 이미 있으므로 yfinance 불필요
    need_yf = [h for h in holdings if not (h.get('source') == 'KIS_API' and h.get('current_price', 0) > 0)]

    ticker_map = {}
    for h in need_yf:
        raw = h.get('symbol') or h.get('stock_code') or h.get('code', '')
        if raw and raw not in ticker_map:
            ticker_map[raw] = normalize_ticker(raw)

    prices = {}
    if ticker_map:
        yf_tickers = list(set(ticker_map.values()))
        try:
            for t in yf_tickers:
                try:
                    df = yf.Ticker(t).history(period='2d', auto_adjust=True)
                    if not df.empty:
                        prices[t] = float(df['Close'].iloc[-1])
                except Exception:
                    pass
        except Exception:
            pass

    enriched = []
    for h in holdings:
        h = dict(h)
        # KIS API 데이터는 그대로
        if h.get('source') == 'KIS_API' and h.get('current_price', 0) > 0:
            enriched.append(h)
            continue
        raw = h.get('symbol') or h.get('stock_code') or h.get('code', '')
        yf_t = ticker_map.get(raw)
        live = prices.get(yf_t) if yf_t else None
        if live and live > 0:
            qty = int(h.get('quantity', 0))
            avg = float(h.get('average_price', h.get('avg_price', 0)))
            h['current_price'] = round(live, 2)
            h['market_value']  = round(live * qty, 0)
            h['pnl']           = round((live - avg) * qty, 0)
        enriched.append(h)
    return enriched


@app.route('/api/account')
def account_api():
    """실계좌 보유종목 KIS API 자동 조회 + yfinance 현재가 보완
    우선순위: KIS API 실계좌 → runtime_payload.json 수동 데이터
    """
    dashboard = _read_json('dashboard_data.json')
    runtime   = _read_json('runtime_payload.json')
    cfg       = _read_json('config.json')

    # ── KIS API 실계좌 조회 시도 ──────────────────────────────────────────
    kis_ok = False
    acct_summary = {}
    if cfg.get('base_url') and cfg.get('api_key') and cfg.get('api_secret'):
        try:
            kr_live, us_live, acct_summary = _fetch_real_holdings()
            if kr_live or us_live or acct_summary:
                runtime['holdings']    = kr_live
                runtime['us_holdings'] = us_live
                runtime['_data_source'] = 'KIS_API'
                kis_ok = True
        except Exception:
            pass

    # ── KIS 실패 시 수동 데이터 + yfinance 현재가 갱신 ──────────────────
    if not kis_ok:
        runtime['_data_source'] = 'manual+yfinance'
        for key in ('holdings', 'us_holdings', 'mock_holdings'):
            if runtime.get(key):
                runtime[key] = _enrich_holdings_with_live_price(runtime[key])

    # us_holdings 없으면 빈 배열 보장
    if 'us_holdings' not in runtime:
        runtime['us_holdings'] = []

    # ── 실시간 환율 조회 ─────────────────────────────────────────────────────
    usd_krw = _get_usd_krw()
    runtime['_usd_krw'] = usd_krw   # 프론트엔드에 전달

    # ── 미국 주식 각 항목에 KRW 환산 필드 추가 ───────────────────────────────
    for h in runtime.get('us_holdings', []):
        mv_usd  = float(h.get('market_value', 0) or 0)
        pnl_usd = float(h.get('pnl', 0) or 0)
        avg_usd = float(h.get('average_price', 0) or 0)
        cur_usd = float(h.get('current_price', 0) or 0)
        h['market_value_krw']  = round(mv_usd  * usd_krw, 0)
        h['pnl_krw']           = round(pnl_usd * usd_krw, 0)
        h['average_price_krw'] = round(avg_usd * usd_krw, 0)
        h['current_price_krw'] = round(cur_usd * usd_krw, 0)

    # ── 토스증권 API 계좌 요약 → account 실시간 업데이트 ────────────────────
    if kis_ok and acct_summary:
        # 미국 주식 평가액(USD)을 KRW로 환산해 한국 주식과 합산
        mv_kr  = float(acct_summary.get('assets_krw', 0))   # 한국 주식 KRW 평가액
        mv_us_usd = float(acct_summary.get('assets_usd', 0)) # 미국 주식 USD 평가액
        mv_us_krw = round(mv_us_usd * usd_krw, 0)
        total_stock_krw = mv_kr + mv_us_krw                  # 전체 주식 합산 KRW

        pl_kr  = float(acct_summary.get('pnl_krw', 0))
        pl_us_usd = float(acct_summary.get('pnl_usd', 0))
        pl_us_krw  = round(pl_us_usd * usd_krw, 0)
        total_pnl_krw = pl_kr + pl_us_krw

        dpl_kr = float(acct_summary.get('daily_pnl_krw', 0))
        dpl_us_usd = float(acct_summary.get('daily_pnl_usd', 0))
        dpl_us_krw = round(dpl_us_usd * usd_krw, 0)
        total_daily_pnl_krw = dpl_kr + dpl_us_krw

        pur_kr  = float(acct_summary.get('purchase_krw', 0))
        pur_us_krw = round(float(acct_summary.get('purchase_usd', 0)) * usd_krw, 0)
        total_purchase_krw = pur_kr + pur_us_krw
        ret_rate = (total_pnl_krw / total_purchase_krw) if total_purchase_krw else 0

        runtime['account'] = {
            'account_id':  runtime.get('account', {}).get('account_id', '토스증권'),
            'mode':        'live',
            'assets':      round(total_stock_krw, 0),   # 주식 평가액(KRW 합산)
            'assets_kr':   round(mv_kr, 0),
            'assets_us_usd': round(mv_us_usd, 2),
            'assets_us_krw': round(mv_us_krw, 0),
            'purchase_krw':  round(total_purchase_krw, 0),
            'pnl':           round(total_pnl_krw, 0),
            'daily_pnl':     round(total_daily_pnl_krw, 0),
            'return_rate':   round(ret_rate, 6),
            'daily_rate':    float(acct_summary.get('daily_rate', 0)),
            'cash':          runtime.get('account', {}).get('cash', 0),  # 예수금은 별도 API 없음
            'error':         None,
            'status_text':   '토스증권 실시간',
        }

    # ── 한국+미국 합산 총 자산 (KRW 기준) ───────────────────────────────────
    kr_stock_value = sum(float(h.get('market_value', 0) or 0)
                         for h in (runtime.get('holdings') or []))
    us_stock_value_krw = sum(float(h.get('market_value_krw', 0) or 0)
                              for h in (runtime.get('us_holdings') or []))
    total_stock_value  = kr_stock_value + us_stock_value_krw
    runtime['_total_assets_live']    = round(total_stock_value, 0)
    runtime['_kr_stock_value']       = round(kr_stock_value, 0)
    runtime['_us_stock_value_krw']   = round(us_stock_value_krw, 0)
    runtime['_kis_connected']        = kis_ok

    return jsonify({
        "dashboard": dashboard,
        "runtime":   runtime,
        "config": {
            "base_url":   cfg.get('base_url', ''),
            "api_key":    cfg.get('api_key', ''),
            "api_secret": cfg.get('api_secret', ''),
            "mock_mode":  cfg.get('mock_mode', False),
        }
    })


@app.route('/api/holdings/update', methods=['POST'])
def holdings_update_api():
    """보유 종목(한국/미국) 수동 추가·삭제·전체교체 — runtime_payload.json 영구 저장
    body: { "market": "KR"|"US", "action": "add"|"remove"|"replace", "item": {...} | "symbol": "..." | "items": [...] }
    """
    data    = request.get_json(force=True)
    market  = data.get('market', 'KR').upper()   # 'KR' 또는 'US'
    action  = data.get('action', 'add')           # 'add' | 'remove' | 'replace'
    key     = 'us_holdings' if market == 'US' else 'holdings'
    path    = os.path.join(BASE_DIR, 'runtime_payload.json')

    try:
        runtime = _read_json('runtime_payload.json')
        if key not in runtime:
            runtime[key] = []

        if action == 'replace':
            runtime[key] = data.get('items', [])

        elif action == 'add':
            item = data.get('item', {})
            if not item.get('symbol'):
                return jsonify({"ok": False, "message": "symbol 필드가 필요합니다."}), 400
            # 이미 있으면 수량/가격 업데이트, 없으면 추가
            sym = item['symbol'].upper()
            item['symbol'] = sym
            existing = next((h for h in runtime[key] if h.get('symbol','').upper() == sym), None)
            if existing:
                existing.update(item)
            else:
                runtime[key].append(item)

        elif action == 'remove':
            sym = (data.get('symbol') or data.get('item', {}).get('symbol', '')).upper()
            runtime[key] = [h for h in runtime[key] if h.get('symbol','').upper() != sym]

        with open(path, 'w', encoding='utf-8') as f:
            json.dump(runtime, f, ensure_ascii=False, indent=2)

        return jsonify({"ok": True, "key": key, "count": len(runtime[key])})
    except Exception as e:
        return jsonify({"ok": False, "message": str(e)}), 500

@app.route('/api/save_config', methods=['POST'])
def save_config_api():
    """API 설정 저장 (config.json 갱신)"""
    data = request.get_json(force=True)
    path = os.path.join(BASE_DIR, 'config.json')
    try:
        existing = _read_json('config.json')
        allowed = ('base_url','api_key','api_secret','mock_mode',
                   'account_no','account_product_code',
                   'auto_strategy','auto_strategies','auto_market','auto_markets','auto_ticker',
                   'auto_enabled','auto_interval_sec')
        existing.update({k: data[k] for k in allowed if k in data})
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(existing, f, ensure_ascii=False, indent=2)
        return jsonify({"ok": True, "message": "설정이 저장되었습니다."})
    except Exception as e:
        return jsonify({"ok": False, "message": str(e)}), 500


@app.route('/api/auto_signal')
def auto_signal_api():
    """자동매매 신호 반환 (복수 전략 × 복수 시장 지원).
    쿼리 파라미터 strategy/market/ticker가 있으면 단일 조회(프론트 병렬용),
    없으면 config.json 기반 전체 조회.
    """
    cfg     = _read_json('config.json')
    enabled = cfg.get('auto_enabled', False)

    # ── 쿼리 파라미터 우선(프론트가 전략×시장 각각 직접 호출) ──
    q_strategy = request.args.get('strategy')
    q_market   = request.args.get('market')
    q_ticker   = request.args.get('ticker')

    if q_strategy and q_market and q_ticker:
        # 단일 (strategy, market, ticker) 조회 모드
        strategies_list = [q_strategy]
        markets_list    = [q_market]
        ticker          = q_ticker.upper()
    else:
        # config 기반 전체 조회 모드
        cfg_strats   = cfg.get('auto_strategies') or [cfg.get('auto_strategy', 'ENVELOPE')]
        strategies_list = cfg_strats if isinstance(cfg_strats, list) else [cfg_strats]
        markets_list    = cfg.get('auto_markets') or [cfg.get('auto_market', 'US')]
        ticker          = cfg.get('auto_ticker', 'AAPL')

    sig_order = {'STRONG_BUY':0,'BUY':1,'WATCH_BUY':2,'NEUTRAL':3,
                 'WATCH_SELL':4,'SELL':5,'STRONG_SELL':6}

    signals = []
    # 전략 × 시장 카테시안 곱
    for strategy in strategies_list:
        for market in markets_list:
            mkt_cfg   = MARKETS.get(market, MARKETS['US'])
            suffix    = mkt_cfg['suffix']
            yf_ticker = ticker + suffix if ticker and not ticker.endswith(suffix) else ticker

            try:
                df = yf.download(yf_ticker, period='60d', interval='1d',
                                 auto_adjust=True, progress=False)
                if df.empty or len(df) < 20:
                    signals.append({"ok": False, "error": "데이터 부족",
                                    "strategy": strategy, "market": market, "ticker": ticker})
                    continue

                df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
                df = df.rename(columns=str.title)
                df.index = pd.to_datetime(df.index)

                params = {}
                if strategy == 'ENVELOPE':
                    period_v = int(cfg.get('auto_period', 20))
                    pct_v    = float(cfg.get('auto_pct', 5.0))
                    df_env   = calc_envelope(df.copy(), period_v, pct_v).dropna()
                    result   = get_signal(df_env, pct=pct_v)
                else:
                    result = get_strategy_signal(df, strategy, params)

                _close_s      = df['Close'].dropna()
                current_price = float(_close_s.iloc[-1]) if not _close_s.empty else 0.0
                strat_info    = STRATEGY_LIST.get(strategy, {})
                signals.append({
                    "ok":            True,
                    "strategy":      strategy,
                    "strategy_name": strat_info.get('name', strategy),
                    "market":        market,
                    "ticker":        ticker,
                    "signal":        result.get('signal', 'NEUTRAL'),
                    "strength":      result.get('strength', 0),
                    "note":          result.get('note', ''),
                    "current_price": current_price,
                    "currency":      mkt_cfg['currency'],
                })
            except Exception as e:
                signals.append({"ok": False, "error": str(e),
                                "strategy": strategy, "market": market, "ticker": ticker})

    # 대표 신호: 가장 강한 것
    ok_signals = [s for s in signals if s.get('ok')]
    best = min(ok_signals, key=lambda s: sig_order.get(s['signal'], 9)) if ok_signals else {}

    return jsonify({
        "ok":            bool(ok_signals),
        "strategy":      best.get('strategy', strategies_list[0]),
        "strategy_name": best.get('strategy_name', strategies_list[0]),
        "ticker":        ticker,
        "markets":       markets_list,
        "market":        best.get('market', markets_list[0]),
        "enabled":       enabled,
        "signal":        best.get('signal', 'NEUTRAL'),
        "strength":      best.get('strength', 0),
        "note":          best.get('note', ''),
        "current_price": best.get('current_price', 0),
        "currency":      best.get('currency', 'USD'),
        "all_signals":   signals,
        "updated":       _now_kst(),
    })


# ══════════════════════════════════════════════════════════════════════════════
#  모의 자동매매 엔진 (Paper Trading Engine)
# ══════════════════════════════════════════════════════════════════════════════

PAPER_FILE    = os.path.join(BASE_DIR, 'paper_account.json')
paper_lock    = threading.Lock()
paper_timer   = None          # 백그라운드 타이머

# ── 토스증권 수수료율 ─────────────────────────────────────────────────
# 국내주식: 0.015% (매수/매도 각각)
# 해외주식: 0.10%  (매수/매도 각각, 2026년 이벤트 수수료 기준)
TOSS_FEE_RATE = {
    'KRW': 0.00015,   # 국내주식 0.015%
    'USD': 0.00100,   # 해외주식 0.10%
}

# ── 시장별 엔벨로프 전략 파라미터 (실제 지수 구성종목 백테스트 최적값) ──────
# US  (S&P500)           : MA20, 밴드±10% / 익절 15.0% / 손절 6.5%
#                           → 30종목 샘플: 수익률 +7.43% / 승률 35.1% / 거래 3.6회
# KR  (KOSPI200+KOSDAQ150): MA20, 밴드± 5% / 익절  8.0% / 손절 7.0%
#                           → 20종목 샘플: 수익률 +39.52% / 승률 62.4% / 거래 14.6회
#                           ※ ±20%는 신호 발생 너무 드물어 실전 부적합 (거래 0.4회/종목)
MARKET_ENVELOPE_PARAMS = {
    'US':     {'period': 20, 'pct': 10.0, 'tp': 15.0, 'sl': 6.5},
    'KOSPI':  {'period': 20, 'pct':  5.0, 'tp':  8.0, 'sl': 7.0},
    'KOSDAQ': {'period': 20, 'pct':  5.0, 'tp':  8.0, 'sl': 7.0},
}

PAPER_INIT = {
    "enabled":       True,              # 항상 켜진 상태
    "strategies":    ["ENVELOPE"],
    "markets":       ["US", "KOSPI"],
    "cash":          10_000_000,        # 초기 자본 1천만원
    "initial_cash":  10_000_000,
    "positions":     {},                # {ticker: {qty, avg_price, market, strategy, currency}}
    "trade_log":     [],                # 최근 200건
    "closed_trades": [],                # 체결 완료 거래 이력 (최근 500건)
    "equity_curve":  [],                # 총자산 시계열 [{ts, value, pnl_pct}] 최근 200건
    "cycle_count":   0,
    "last_run":      "",
    "interval_sec":  300,              # 기본 5분 주기
    "per_stock_pct": 0.05,             # 종목당 최대 5% 비중
    "stop_loss_pct": 3.0,
    "take_profit_pct": 6.0,
    "max_positions": 10,               # 최대 동시 보유 종목 수
    "signal_threshold": ["BUY", "STRONG_BUY"],  # 진입 허용 신호
    "total_fee":     0.0,              # 누적 수수료 합계 (원화)
}

def _read_paper() -> dict:
    try:
        with open(PAPER_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        # 필수 키 보정
        for k, v in PAPER_INIT.items():
            if k not in data:
                data[k] = v
        return data
    except Exception:
        d = dict(PAPER_INIT)
        _write_paper(d)
        return d

def _write_paper(data: dict):
    with open(PAPER_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def _paper_log(data: dict, msg: str, log_type: str = 'info'):
    entry = {
        "ts":   _now_kst(),
        "type": log_type,
        "msg":  msg,
    }
    data['trade_log'].insert(0, entry)
    data['trade_log'] = data['trade_log'][:200]  # 최근 200건만 보관

def _paper_get_price(ticker: str) -> float | None:
    """종목 현재가 조회 — 당일 미완성 봉(NaN) 제외 후 마지막 종가 반환"""
    df = None
    try:
        df = yf.download(ticker, period='5d', interval='1d',
                         auto_adjust=True, progress=False)
        if df.empty:
            return None
        df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
        close = df['Close'].dropna()   # 당일 미종료 봉(NaN) 제거
        if close.empty:
            return None
        price = float(close.iloc[-1])  # 유효한 가장 최근 종가
        return price if price > 0 else None
    except Exception:
        return None
    finally:
        del df
        gc.collect()

def _is_market_open(market: str) -> tuple[bool, str]:
    """
    시장 개장 여부 판단.
    반환: (개장중 여부, 사유 메시지)
    - 주말·공휴일(휴장일) → False
    - 장 시간 외 → False
    - 개장 중 → True
    """
    try:
        if market == 'US':
            tz   = pytz.timezone('America/New_York')
            now  = datetime.now(tz)
            open_h, open_m   = 9, 30
            close_h, close_m = 16, 0
            cal_id = 'XNYS'
        else:  # KOSPI / KOSDAQ 모두 KRX
            tz   = pytz.timezone('Asia/Seoul')
            now  = datetime.now(tz)
            open_h, open_m   = 9, 0
            close_h, close_m = 15, 30
            cal_id = 'XKRX'

        today_str = now.strftime('%Y-%m-%d')

        # ── 휴장일 체크 (exchange_calendars) ──────────────────
        if _XCALS_OK:
            cal = xcals.get_calendar(cal_id)
            if not cal.is_session(today_str):
                weekday = now.strftime('%A')
                return False, f"휴장일 ({today_str} {weekday})"
        else:
            # fallback: 주말만 체크
            if now.weekday() >= 5:
                return False, f"주말 ({now.strftime('%A')})"

        # ── 장 시간 체크 ────────────────────────────────────
        cur_min  = now.hour * 60 + now.minute
        open_min = open_h  * 60 + open_m
        close_min = close_h * 60 + close_m
        if cur_min < open_min:
            return False, f"장 시작 전 ({now.strftime('%H:%M')}, 개장 {open_h:02d}:{open_m:02d})"
        if cur_min >= close_min:
            return False, f"장 종료 후 ({now.strftime('%H:%M')}, 마감 {close_h:02d}:{close_m:02d})"

        return True, f"장 중 ({now.strftime('%H:%M')})"

    except Exception as e:
        # 판단 실패 시 안전하게 허용 (매매 차단보다 허용이 덜 위험)
        return True, f"개장 판단 오류({e}) → 허용"


def _paper_cycle():
    """모의 자동매매 1사이클 실행"""
    global paper_timer
    with paper_lock:
        data = _read_paper()
        if not data.get('enabled'):
            return

        strategies  = data.get('strategies', ['ENVELOPE'])
        markets     = data.get('markets',    ['US'])
        cash        = float(data.get('cash', 0))
        positions   = data.get('positions',  {})
        per_pct     = float(data.get('per_stock_pct', 0.05))
        sl_pct      = float(data.get('stop_loss_pct', 3.0))
        tp_pct      = float(data.get('take_profit_pct', 6.0))
        max_pos     = int(data.get('max_positions', 10))
        thresholds  = set(data.get('signal_threshold', ['BUY','STRONG_BUY']))
        initial     = float(data.get('initial_cash', 10_000_000))

        data['cycle_count'] = data.get('cycle_count', 0) + 1
        data['last_run']    = _now_kst()

        _paper_log(data, f"▶ 사이클 #{data['cycle_count']} 시작 "
                         f"| 현금: {cash:,.0f}원 | 보유: {len(positions)}종목", 'info')

        # ── 환율 조회 (USD 종목 원화 환산용) ─────────────────────────────
        fx = _get_usd_krw()   # 현재 USD/KRW 환율 (예: 1380)

        # ── 1. 보유 종목 청산 검사 (손절/익절) ──────────────────────────
        sold_tickers = []
        closed_trades = data.setdefault('closed_trades', [])
        total_fee = float(data.get('total_fee', 0.0))   # 누적 수수료
        for ticker, pos in list(positions.items()):
            # 휴장일·장 시간 외엔 가격 조회 자체가 의미 없으므로 스킵
            pos_market = pos.get('market', 'US')
            sell_open, sell_reason = _is_market_open(pos_market)
            if not sell_open:
                continue
            price = _paper_get_price(ticker)
            if price is None:
                continue
            avg   = float(pos['avg_price'])
            qty   = int(pos['qty'])
            pnl_pct = (price - avg) / avg * 100
            mkt   = pos.get('market', 'US')
            cur   = MARKETS.get(mkt, {}).get('currency', 'USD')
            cur_sym = '$' if cur == 'USD' else '₩'
            # 원화 환산 (USD면 fx 곱, KRW면 그대로)
            rate  = fx if cur == 'USD' else 1.0
            # 매도 수수료 계산 (토스증권 기준, 원화)
            fee_rate = TOSS_FEE_RATE.get(cur, 0.00015)
            sell_fee_krw = price * qty * rate * fee_rate

            # 전략·시장별 익절/손절 기준 결정
            # ENVELOPE 전략: MARKET_ENVELOPE_PARAMS 최적값 우선 적용
            # 그 외 전략 또는 파라미터 미정의 시장: PAPER_INIT 기본값(UI 설정값) 사용
            pos_strategy = pos.get('strategy', '')
            if pos_strategy == 'ENVELOPE' and mkt in MARKET_ENVELOPE_PARAMS:
                eff_tp = MARKET_ENVELOPE_PARAMS[mkt]['tp']
                eff_sl = MARKET_ENVELOPE_PARAMS[mkt]['sl']
            else:
                eff_tp = tp_pct
                eff_sl = sl_pct

            if pnl_pct >= eff_tp:
                # 익절 — proceeds를 원화로 현금에 복귀 (수수료 차감)
                proceeds_krw = price * qty * rate - sell_fee_krw
                cash += proceeds_krw
                total_fee += sell_fee_krw
                sold_tickers.append(ticker)
                pnl_amt = (price - avg) * qty   # 외화 기준 손익
                pnl_amt_krw = pnl_amt * rate - sell_fee_krw  # 수수료 반영
                closed_trades.insert(0, {
                    "ts":       _now_kst(),
                    "ticker":   pos.get('display', ticker),
                    "market":   mkt,
                    "strategy": pos.get('strategy', ''),
                    "signal":   pos.get('entry_signal', ''),
                    "entry_time": pos.get('entry_time', ''),
                    "exit_time":  _now_kst(),
                    "qty":      qty,
                    "avg_price": round(avg, 4),
                    "exit_price": round(price, 4),
                    "pnl_amt":  round(pnl_amt_krw, 0),
                    "pnl_pct":  round(pnl_pct, 2),
                    "exit_type": "take_profit",
                    "currency": cur,
                    "fx_rate":  round(rate, 2),
                    "fee":      round(sell_fee_krw, 0),
                })
                _paper_log(data,
                    f"💰 익절 [{pos.get('display',ticker)}@{mkt}] {qty}주 × {cur_sym}{price:,.2f} "
                    f"| 수익: +{pnl_pct:.1f}% (+₩{pnl_amt_krw:,.0f}) | 수수료: ₩{sell_fee_krw:,.0f}"
                    f" [기준 tp={eff_tp}%]", 'ok')
            elif pnl_pct <= -eff_sl:
                # 손절 — proceeds를 원화로 현금에 복귀 (수수료 차감)
                proceeds_krw = price * qty * rate - sell_fee_krw
                cash += proceeds_krw
                total_fee += sell_fee_krw
                sold_tickers.append(ticker)
                pnl_amt = (price - avg) * qty
                pnl_amt_krw = pnl_amt * rate - sell_fee_krw  # 수수료 반영
                closed_trades.insert(0, {
                    "ts":       _now_kst(),
                    "ticker":   pos.get('display', ticker),
                    "market":   mkt,
                    "strategy": pos.get('strategy', ''),
                    "signal":   pos.get('entry_signal', ''),
                    "entry_time": pos.get('entry_time', ''),
                    "exit_time":  _now_kst(),
                    "qty":      qty,
                    "avg_price": round(avg, 4),
                    "exit_price": round(price, 4),
                    "pnl_amt":  round(pnl_amt_krw, 0),
                    "pnl_pct":  round(pnl_pct, 2),
                    "exit_type": "stop_loss",
                    "currency": cur,
                    "fx_rate":  round(rate, 2),
                    "fee":      round(sell_fee_krw, 0),
                })
                _paper_log(data,
                    f"🛑 손절 [{pos.get('display',ticker)}@{mkt}] {qty}주 × {cur_sym}{price:,.2f} "
                    f"| 손실: {pnl_pct:.1f}% (₩{pnl_amt_krw:,.0f}) | 수수료: ₩{sell_fee_krw:,.0f}"
                    f" [기준 sl={eff_sl}%]", 'err')

        # closed_trades 최근 500건 유지
        data['closed_trades'] = closed_trades[:500]

        for t in sold_tickers:
            del positions[t]

        # ── 2. 신규 매수 신호 스캔 ──────────────────────────────────────
        if len(positions) < max_pos:
            # ── 총 포트폴리오 가치(원화) 기준 종목당 예산 계산
            # avg_price(매수가) 기준 빠른 추산 (네트워크 조회 없이)
            port_val_krw = cash
            for t, pv in positions.items():
                avg_p = float(pv.get('avg_price', 0))
                qty_v = int(pv.get('qty', 0))
                cur_v = MARKETS.get(pv.get('market','US'), {}).get('currency','USD')
                port_val_krw += avg_p * qty_v * (fx if cur_v == 'USD' else 1.0)
            per_budget = port_val_krw * per_pct   # 원화 기준 종목당 예산

            # ── 전략 우선순위: 백테스트 매매빈도 높은 순으로 정렬 ─────────
            # 순위: PIVOT_VA(22.4회) > TBV_SMC(17.8회) > ENVELOPE(13.6회)
            #       > SSL_RSI(2.6회) > BB3SIGMA(0.9회)
            STRATEGY_PRIORITY = ["PIVOT_VA", "TBV_SMC", "ENVELOPE", "SSL_RSI", "BB3SIGMA"]
            strategies_sorted = sorted(
                strategies,
                key=lambda s: STRATEGY_PRIORITY.index(s) if s in STRATEGY_PRIORITY else 99
            )

            # ── 루프 구조: market → ticker → strategy (전략 우선순위 적용)
            # 종목 하나를 내려받아 우선순위 순으로 전략 검사 → 신호 있으면 즉시 매수
            # 슬롯 제한 없음: max_pos 총량만 관리 (시장별·전략별 인위적 상한 없음)
            for market in markets:
                if len(positions) >= max_pos:
                    break

                # ── 휴장일·장 시간 외 매수 차단 ──────────────────────────
                mkt_open, mkt_reason = _is_market_open(market)
                if not mkt_open:
                    _paper_log(data,
                        f"⏸ [{market}] 매수 스킵 — {mkt_reason}", 'info')
                    continue

                tickers_list = get_all_tickers(market)
                mkt_cfg  = MARKETS.get(market, MARKETS['US'])
                suffix   = mkt_cfg['suffix']
                currency = mkt_cfg['currency']
                cur_sym  = '$' if currency == 'USD' else '₩'
                rate     = fx if currency == 'USD' else 1.0

                for ticker in tickers_list:
                    if len(positions) >= max_pos:
                        break
                    if ticker in positions:
                        continue

                    # ── 종목 데이터 1회만 다운로드 후 모든 전략 검사
                    df = None
                    try:
                        df = yf.download(ticker, period='60d', interval='1d',
                                         auto_adjust=True, progress=False)
                        if df.empty or len(df) < 20:
                            continue
                        df.columns = [c[0] if isinstance(c, tuple) else c
                                      for c in df.columns]
                        df = df.rename(columns=str.title)
                        df.index = pd.to_datetime(df.index)
                        close_s = df['Close'].dropna()
                        if close_s.empty:
                            continue
                        price = float(close_s.iloc[-1])  # 미완성 봉 NaN 제거
                        if price <= 0:
                            continue

                        # ── 전략별 신호 검사 (우선순위 순, 슬롯 제한 없음)
                        for strategy in strategies_sorted:
                            if len(positions) >= max_pos:
                                break
                            # 이미 이 종목을 보유 중이면 스킵 (중복 보유 방지)
                            if ticker in positions:
                                break
                            # 선택된 전략 목록에 없으면 스킵
                            if strategy not in strategies:
                                continue

                            try:
                                if strategy == 'ENVELOPE':
                                    # 시장별 최적 파라미터 적용 (백테스트 확정값)
                                    _ep = MARKET_ENVELOPE_PARAMS.get(
                                        market,
                                        MARKET_ENVELOPE_PARAMS['US']  # 미정의 시장 → US 기본값
                                    )
                                    _env_period = _ep['period']
                                    _env_pct    = _ep['pct']
                                    df_env = calc_envelope(df.copy(), _env_period, _env_pct).dropna()
                                    result = get_signal(df_env, pct=_env_pct)
                                    del df_env
                                else:
                                    result = get_strategy_signal(df, strategy, {})
                            except Exception:
                                continue

                            signal = result.get('signal', 'NEUTRAL')
                            if signal not in thresholds:
                                continue

                            price_krw = price * rate

                            # 종목당 예산 계산
                            budget_krw = min(per_budget, cash * 0.95)
                            qty = max(1, int(budget_krw / price_krw))
                            cost_krw = price_krw * qty

                            if cost_krw > cash:
                                qty = max(1, int(cash * 0.95 / price_krw))
                                cost_krw = price_krw * qty

                            if qty < 1 or cost_krw > cash:
                                continue

                            # 매수 수수료 계산
                            fee_rate = TOSS_FEE_RATE.get(currency, 0.00015)
                            buy_fee_krw = cost_krw * fee_rate
                            total_cost_krw = cost_krw + buy_fee_krw

                            if total_cost_krw > cash:
                                qty = max(1, int(cash * 0.95 / (price_krw * (1 + fee_rate))))
                                cost_krw = price_krw * qty
                                buy_fee_krw = cost_krw * fee_rate
                                total_cost_krw = cost_krw + buy_fee_krw
                            if qty < 1 or total_cost_krw > cash:
                                continue

                            # 매수 체결
                            cash -= total_cost_krw
                            total_fee += buy_fee_krw
                            display = get_display_name(ticker, market)
                            positions[ticker] = {
                                "qty":          qty,
                                "avg_price":    round(price, 4),
                                "market":       market,
                                "strategy":     strategy,
                                "currency":     currency,
                                "display":      display,
                                "entry_signal": signal,
                                "entry_time":   _now_kst(),
                                "fx_rate":      round(rate, 2),
                                "buy_fee":      round(buy_fee_krw, 0),
                            }
                            strat_name = STRATEGY_LIST.get(strategy, {}).get('name', strategy)
                            _paper_log(data,
                                f"🟢 매수 [{display}@{market}] {qty}주 × {cur_sym}{price:,.2f}"
                                f"{f' (₩{price_krw:,.0f})' if currency=='USD' else ''}"
                                f" = ₩{cost_krw:,.0f} | 수수료 ₩{buy_fee_krw:,.0f} | {strat_name} / {signal}", 'ok')
                            break  # 종목 1개에 전략 1개만 진입 (중복 방지)

                    except Exception:
                        pass
                    finally:
                        if df is not None:
                            del df
                        gc.collect()

        # ── 3. 총 자산 계산 (원화 기준) ─────────────────────────────────
        total_value = cash
        for ticker, pos in positions.items():
            p = _paper_get_price(ticker)
            if p:
                cur  = pos.get('currency', MARKETS.get(pos.get('market','US'),{}).get('currency','USD'))
                rate = fx if cur == 'USD' else 1.0
                total_value += p * pos['qty'] * rate
        pnl_total = total_value - initial
        pnl_pct_total = pnl_total / initial * 100

        data['cash']      = round(cash, 2)
        data['positions'] = positions
        data['total_value']    = round(total_value, 2)
        data['total_pnl']      = round(pnl_total, 2)
        data['total_pnl_pct']  = round(pnl_pct_total, 2)
        data['total_fee']      = round(total_fee, 0)   # 누적 수수료 갱신

        # 수익 곡선 업데이트 (사이클마다 1포인트 기록 — NaN 방어)
        import math as _math
        equity_curve = data.setdefault('equity_curve', [])
        _tv_safe  = 0 if _math.isnan(total_value)    else round(total_value, 0)
        _pct_safe = 0 if _math.isnan(pnl_pct_total)  else round(pnl_pct_total, 2)
        if _tv_safe > 0:   # 유효한 값일 때만 기록
            equity_curve.append({
                "ts":      _now_kst('%Y-%m-%d %H:%M'),
                "value":   _tv_safe,
                "pnl_pct": _pct_safe,
            })
        data['equity_curve'] = equity_curve[-200:]  # 최근 200포인트

        _paper_log(data,
            f"✅ 사이클 완료 | 현금: {cash:,.0f} | 총자산: {total_value:,.0f} "
            f"| 손익: {'+' if pnl_total>=0 else ''}{pnl_total:,.0f} ({pnl_pct_total:+.2f}%)"
            f" | 누적수수료: ₩{total_fee:,.0f}", 'info')

        _write_paper(data)

    # 다음 사이클 예약
    with paper_lock:
        d = _read_paper()
        interval = int(d.get('interval_sec', 300))
        if d.get('enabled'):
            paper_timer = threading.Timer(interval, _paper_cycle)
            paper_timer.daemon = True
            paper_timer.start()


def _paper_start():
    global paper_timer
    if paper_timer:
        paper_timer.cancel()
    paper_timer = threading.Timer(1, _paper_cycle)
    paper_timer.daemon = True
    paper_timer.start()

def _paper_stop():
    global paper_timer
    if paper_timer:
        paper_timer.cancel()
        paper_timer = None


# ── Paper Trading API ────────────────────────────────────────────────────────

@app.route('/api/paper/status')
def paper_status():
    """모의 자동매매 현재 상태 조회"""
    with paper_lock:
        data = _read_paper()

    # 보유 종목 현재가 갱신 (원화 기준 평가)
    positions = data.get('positions', {})
    status_fx = _get_usd_krw()
    enriched  = []
    total_mkt_val = 0.0
    for ticker, pos in positions.items():
        price = _paper_get_price(ticker)
        if price is None:
            price = pos['avg_price']
        qty   = pos['qty']
        avg   = pos['avg_price']
        cur   = pos.get('currency', MARKETS.get(pos.get('market','US'),{}).get('currency','USD'))
        rate  = status_fx if cur == 'USD' else 1.0
        mkt_val_krw = price * qty * rate
        pnl_krw     = (price - avg) * qty * rate
        pnl_pct     = (price - avg) / avg * 100 if avg else 0
        total_mkt_val += mkt_val_krw
        enriched.append({
            "ticker":        ticker,
            "display":       pos.get('display', ticker),
            "market":        pos.get('market', 'US'),
            "strategy":      pos.get('strategy', ''),
            "qty":           qty,
            "avg_price":     round(avg, 4),
            "current_price": round(price, 4),
            "market_value":  round(mkt_val_krw, 0),
            "pnl":           round(pnl_krw, 0),
            "pnl_pct":       round(pnl_pct, 2),
            "entry_signal":  pos.get('entry_signal', ''),
            "entry_time":    pos.get('entry_time', ''),
            "currency":      cur,
            "fx_rate":       round(rate, 2),
        })

    cash     = float(data.get('cash', 10_000_000))
    initial  = float(data.get('initial_cash', 10_000_000))
    total_v  = cash + total_mkt_val
    pnl      = total_v - initial

    return jsonify({
        "ok":          True,
        "enabled":     data.get('enabled', False),
        "strategies":  data.get('strategies', ['ENVELOPE']),
        "markets":     data.get('markets',    ['US']),
        "cash":        round(cash, 2),
        "initial_cash": initial,
        "total_value": round(total_v, 2),
        "total_pnl":   round(pnl, 2),
        "total_pnl_pct": round(pnl / initial * 100, 2) if initial else 0,
        "positions":   enriched,
        "trade_log":   data.get('trade_log', [])[:50],
        "cycle_count": data.get('cycle_count', 0),
        "last_run":    data.get('last_run', ''),
        "interval_sec": data.get('interval_sec', 300),
        "per_stock_pct": data.get('per_stock_pct', 0.05),
        "stop_loss_pct": data.get('stop_loss_pct', 3.0),
        "take_profit_pct": data.get('take_profit_pct', 6.0),
        "max_positions": data.get('max_positions', 10),
        "total_fee":    round(float(data.get('total_fee', 0)), 0),
        "closed_trades": data.get('closed_trades', [])[:100],  # 최근 100건
        "equity_curve":  data.get('equity_curve',  []),        # 전체 시계열
        "running":       data.get('running', False),
    })


@app.route('/api/paper/config', methods=['POST'])
def paper_config():
    """모의 자동매매 설정 저장 (enabled 변경 불가 — 항상 ON)"""
    body = request.get_json(force=True)
    with paper_lock:
        data = _read_paper()
        allowed = ('strategies','markets','interval_sec','per_stock_pct',
                   'stop_loss_pct','take_profit_pct','max_positions','signal_threshold')
        for k in allowed:
            if k in body:
                data[k] = body[k]
        data['enabled'] = True   # 항상 활성화 유지
        _write_paper(data)

    # 타이머 재시작 (설정 변경 반영)
    _paper_stop()
    _paper_start()

    return jsonify({"ok": True, "message": "설정이 저장되었습니다."})


@app.route('/api/paper/reset', methods=['POST'])
def paper_reset():
    """모의 계좌 초기화 (자본 1천만원 리셋 후 자동 재시작)"""
    _paper_stop()
    with paper_lock:
        data = dict(PAPER_INIT)
        data['enabled'] = True
        data['trade_log'] = [{
            "ts":   _now_kst(),
            "type": "warn",
            "msg":  "🔄 모의 계좌 초기화 — 자본 10,000,000원으로 리셋",
        }]
        _write_paper(data)
    _paper_start()
    return jsonify({"ok": True, "message": "모의 계좌가 초기화되었습니다."})


@app.route('/api/paper/sell', methods=['POST'])
def paper_sell():
    """보유 종목 수동 매도"""
    body   = request.get_json(force=True)
    ticker = body.get('ticker', '').upper()
    if not ticker:
        return jsonify({"ok": False, "error": "ticker 필요"}), 400
    with paper_lock:
        data = _read_paper()
        pos  = data['positions'].get(ticker)
        if not pos:
            return jsonify({"ok": False, "error": "보유 중이 아닌 종목"}), 404
        price = _paper_get_price(ticker) or pos['avg_price']
        qty   = pos['qty']
        avg   = pos['avg_price']
        mkt   = pos.get('market', 'US')
        cur   = pos.get('currency', 'USD')
        cur_sym = '$' if cur == 'USD' else '₩'
        sell_fx = _get_usd_krw() if cur == 'USD' else 1.0
        # 수수료 계산 (토스증권)
        fee_rate = TOSS_FEE_RATE.get(cur, 0.00015)
        sell_fee_krw = price * qty * sell_fx * fee_rate
        # 원화 기준 정산 (수수료 차감)
        proceeds_krw = price * qty * sell_fx - sell_fee_krw
        pnl_amt      = (price - avg) * qty          # 현지 통화 손익
        pnl_amt_krw  = pnl_amt * sell_fx - sell_fee_krw  # 원화 손익 (수수료 반영)
        pnl_pct      = (price - avg) / avg * 100 if avg else 0
        data['cash'] += proceeds_krw
        data['total_fee'] = round(float(data.get('total_fee', 0)) + sell_fee_krw, 0)
        del data['positions'][ticker]

        # closed_trades 저장
        closed = data.setdefault('closed_trades', [])
        closed.insert(0, {
            "ts":        _now_kst(),
            "ticker":    pos.get('display', ticker),
            "market":    mkt,
            "strategy":  pos.get('strategy', ''),
            "signal":    pos.get('entry_signal', ''),
            "entry_time": pos.get('entry_time', ''),
            "exit_time": _now_kst(),
            "qty":       qty,
            "avg_price": round(avg, 4),
            "exit_price": round(price, 4),
            "pnl_amt":   round(pnl_amt_krw, 0),
            "pnl_pct":   round(pnl_pct, 2),
            "exit_type": "manual",
            "currency":  cur,
            "fx_rate":   round(sell_fx, 2),
            "fee":       round(sell_fee_krw, 0),
        })
        data['closed_trades'] = closed[:500]

        _paper_log(data,
            f"✋ 수동매도 [{pos.get('display',ticker)}] {qty}주 × {cur_sym}{price:,.2f}"
            f"{f' (₩{price*sell_fx:,.0f})' if cur=='USD' else ''}"
            f" | 수익률: {pnl_pct:+.1f}% (₩{pnl_amt_krw:+,.0f}) | 수수료: ₩{sell_fee_krw:,.0f}", 'warn')
        _write_paper(data)
    return jsonify({"ok": True, "message": f"{ticker} 수동 매도 완료"})


@app.route('/api/paper/dashboard')
def paper_dashboard():
    """모의투자 대시보드용 집계 데이터"""
    with paper_lock:
        data = _read_paper()

    positions   = data.get('positions', {})
    closed      = data.get('closed_trades', [])
    # equity_curve에서 NaN 방어 (JSON 직렬화 오류 방지)
    import math as _math
    equity      = [e for e in data.get('equity_curve', [])
                   if not _math.isnan(float(e.get('value', 0) or 0))
                   and not _math.isnan(float(e.get('pnl_pct', 0) or 0))]
    initial     = float(data.get('initial_cash', 10_000_000))
    cash        = float(data.get('cash', initial))

    # ── 환율 조회 (포지션 평가용) ──
    dash_fx = _get_usd_krw()

    # ── 현재 포지션 평가 (원화 기준) ──
    total_mkt = 0.0
    pos_list  = []
    for ticker, pos in positions.items():
        price = _paper_get_price(ticker) or pos['avg_price']
        qty   = pos['qty'];  avg = pos['avg_price']
        cur   = pos.get('currency', MARKETS.get(pos.get('market','US'),{}).get('currency','USD'))
        rate  = dash_fx if cur == 'USD' else 1.0
        mv_krw  = price * qty * rate          # 원화 평가금액
        avg_krw = avg * rate                  # 매수단가 원화 환산
        pnl_krw = (price - avg) * qty * rate  # 원화 손익
        pnl_pct = (price - avg) / avg * 100 if avg else 0
        total_mkt += mv_krw
        pos_list.append({
            "ticker":        ticker,
            "display":       pos.get('display', ticker),
            "market":        pos.get('market', 'US'),
            "strategy":      pos.get('strategy', ''),
            "qty":           qty,
            "avg_price":     round(avg, 4),       # 현지 통화 매수가
            "avg_price_krw": round(avg_krw, 0),  # 원화 환산 매수가
            "current_price": round(price, 4),    # 현지 통화 현재가
            "market_value":  round(mv_krw, 0),   # 원화 평가금액
            "pnl":           round(pnl_krw, 0),  # 원화 손익
            "pnl_pct":       round(pnl_pct, 2),
            "entry_time":    pos.get('entry_time', ''),
            "entry_signal":  pos.get('entry_signal', ''),
            "currency":      cur,
            "fx_rate":       round(rate, 2),
        })

    total_value = cash + total_mkt
    total_pnl   = total_value - initial
    total_pnl_pct = total_pnl / initial * 100 if initial else 0

    # ── 전략별 성과 집계 ──
    strat_stats = {}
    for t in closed:
        s = t.get('strategy', '?')
        if s not in strat_stats:
            strat_stats[s] = {'wins':0,'losses':0,'total_pnl':0.0,'count':0,'win_pnl':0.0,'loss_pnl':0.0}
        ss = strat_stats[s]
        ss['count'] += 1
        ss['total_pnl'] += t.get('pnl_pct', 0)
        if t.get('pnl_pct', 0) >= 0:
            ss['wins'] += 1
            ss['win_pnl'] += t.get('pnl_pct', 0)
        else:
            ss['losses'] += 1
            ss['loss_pnl'] += t.get('pnl_pct', 0)
    strat_list = []
    for s, ss in strat_stats.items():
        cnt = ss['count']
        win_rate = ss['wins'] / cnt * 100 if cnt else 0
        avg_pnl  = ss['total_pnl'] / cnt if cnt else 0
        strat_list.append({
            "strategy": s,
            "count":    cnt,
            "wins":     ss['wins'],
            "losses":   ss['losses'],
            "win_rate": round(win_rate, 1),
            "avg_pnl":  round(avg_pnl, 2),
            "total_pnl": round(ss['total_pnl'], 2),
        })
    strat_list.sort(key=lambda x: x['total_pnl'], reverse=True)

    # ── 현재 보유 전략별 분포 ──
    holding_by_strat = {}
    for p in pos_list:
        s = p['strategy']
        holding_by_strat[s] = holding_by_strat.get(s, 0) + 1

    # ── 요약 통계 ──
    wins      = [t for t in closed if t.get('pnl_pct', 0) >= 0]
    losses    = [t for t in closed if t.get('pnl_pct', 0) < 0]
    total_cnt = len(closed)
    win_rate  = len(wins) / total_cnt * 100 if total_cnt else 0
    avg_win   = sum(t['pnl_pct'] for t in wins)   / len(wins)   if wins   else 0
    avg_loss  = sum(t['pnl_pct'] for t in losses) / len(losses) if losses else 0
    profit_factor = abs(avg_win * len(wins) / (avg_loss * len(losses))) if losses and avg_loss != 0 else None

    return jsonify({
        "ok":            True,
        "summary": {
            "initial_cash":  initial,
            "cash":          round(cash, 2),
            "total_value":   round(total_value, 2),
            "total_pnl":     round(total_pnl, 2),
            "total_pnl_pct": round(total_pnl_pct, 2),
            "total_fee":     round(float(data.get('total_fee', 0)), 0),
            "total_pnl_pct": round(total_pnl_pct, 2),
            "holding_count": len(positions),
            "closed_count":  total_cnt,
            "win_count":     len(wins),
            "loss_count":    len(losses),
            "win_rate":      round(win_rate, 1),
            "avg_win_pct":   round(avg_win, 2),
            "avg_loss_pct":  round(avg_loss, 2),
            "profit_factor": round(profit_factor, 2) if profit_factor else 0,
            "cycle_count":   data.get('cycle_count', 0),
            "last_run":      data.get('last_run', ''),
            "enabled":       data.get('enabled', True),
        },
        "strategy_stats": strat_list,
        "holding_by_strat": holding_by_strat,
        "positions":      pos_list,
        "closed_trades":  closed[:100],   # 최근 100건
        "equity_curve":   equity,         # 전체 시계열
        "strategies":     data.get('strategies', ['ENVELOPE']),
        "markets":        data.get('markets', ['US']),
    })


# ─────────────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    # 서버 시작 시 모의 자동매매 항상 ON (24시간 풀매매)
    try:
        with paper_lock:
            d = _read_paper()
            d['enabled'] = True   # 강제 활성화
            _write_paper(d)
        _paper_start()
        print("✅ 모의 자동매매 24시간 자동 시작")
    except Exception as e:
        print(f"⚠️ 자동매매 시작 오류: {e}")
    print("🚀 엔벨로프 전략 통합 대시보드 시작 (포트 5050)")
    app.run(host='0.0.0.0', port=5050, debug=False)

