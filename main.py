"""
제주 지정면세점 수요 대시보드 (FastAPI 서버 하나가 API와 화면을 함께 제공)

데이터 출처
- 네이버 데이터랩 검색어 트렌드 (NAVER API HUB 또는 네이버 개발자센터 키)
- 구글 트렌드 (SerpApi google_trends 엔진, 선택)
- 한국관광공사 빅데이터 지역별 방문자수 (공공데이터포털, 제주 외지인/외국인 일별 방문자)
- 기상청 초단기실황 (공공데이터포털, 현재 날씨) + Open-Meteo (10일 예보·지난 31일, 키 불필요)
- 관리자 입력: 제주관광협회 내국인 입도객, 우도·중문관광단지 방문객, 지정면세점 매출

키는 모두 환경변수로 받는다. 키가 없는 자동 출처는 '예시 데이터'로 표시된다.
"""
import asyncio
import csv
import datetime as dt
import hmac
import io
import json
import math
import os
import random
import sqlite3
import time
from urllib.parse import unquote

import httpx
from fastapi import FastAPI, File, Header, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

# ---------------------------------------------------------------------------
# 기본 설정
# ---------------------------------------------------------------------------
KST = dt.timezone(dt.timedelta(hours=9))
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
DATA_DIR = os.environ.get("DATA_DIR") or os.path.join(BASE_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)
DB_PATH = os.path.join(DATA_DIR, "dashboard.db")

HISTORY_DAYS = 100  # 화면에서 쓰는 과거 데이터 범위(일)


def env(name: str) -> str:
    return (os.environ.get(name) or "").strip()


# 검색 키워드 묶음 (한 번 호출에 최대 5묶음, 묶음당 최대 20개 검색어)
NAVER_GROUPS_MAIN = [
    {"groupName": "제주항공권", "keywords": ["제주항공권", "제주도항공권", "제주 항공권", "제주도 비행기표", "김포 제주 항공권"]},
    {"groupName": "제주렌트카", "keywords": ["제주렌트카", "제주 렌트카", "제주도렌트카", "제주렌터카", "제주도 렌터카"]},
    {"groupName": "제주면세점", "keywords": ["제주면세점", "제주 면세점", "제주공항면세점", "제주 지정면세점", "제주관광공사면세점"]},
    {"groupName": "우도", "keywords": ["우도", "제주 우도", "우도 배편", "우도 도항선"]},
    {"groupName": "중문관광단지", "keywords": ["중문관광단지", "중문 관광단지", "중문해수욕장", "제주 중문"]},
]
NAVER_GROUPS_DFS = [
    {"groupName": "JTO 지정면세점", "keywords": ["제주관광공사면세점", "제주관광공사 면세점", "JTO면세점", "중문면세점", "성산면세점"]},
    {"groupName": "JDC 지정면세점", "keywords": ["JDC면세점", "jdc면세점", "JDC 면세점", "제주공항 jdc면세점"]},
    {"groupName": "제주 시내면세점", "keywords": ["롯데면세점 제주", "신라면세점 제주", "제주 시내면세점"]},
]
GOOGLE_QUERIES = ["제주항공권", "제주렌트카", "제주면세점", "우도", "중문관광단지"]

WEATHER_SPOTS = [
    {"id": "jeju", "name": "제주시(공항)", "lat": 33.5066, "lon": 126.4929},
    {"id": "jungmun", "name": "중문관광단지", "lat": 33.2486, "lon": 126.4123},
    {"id": "seongsan", "name": "성산", "lat": 33.4612, "lon": 126.9300},
    {"id": "udo", "name": "우도", "lat": 33.5060, "lon": 126.9530},
]

MANUAL_METRICS = {
    "inbound_domestic": {"label": "내국인 입도객", "unit": "명", "agg": "sum",
                         "source": "제주특별자치도관광협회 입도관광객 통계"},
    "udo": {"label": "우도 방문객", "unit": "명", "agg": "sum", "source": "우도 도항선 입도객 등 현장 집계"},
    "jungmun": {"label": "중문관광단지 방문객", "unit": "명", "agg": "sum", "source": "중문관광단지 집계"},
    "sales": {"label": "지정면세점 매출", "unit": "원", "agg": "sum", "source": "공사 매출 시스템(내부 입력)"},
}
# CSV 머리글에서 받아들이는 한글 이름
MANUAL_ALIASES = {
    "내국인입도객": "inbound_domestic", "내국인 입도객": "inbound_domestic", "입도객": "inbound_domestic",
    "우도": "udo", "우도방문객": "udo", "우도 방문객": "udo",
    "중문": "jungmun", "중문관광단지": "jungmun", "중문관광단지 방문객": "jungmun", "중문방문객": "jungmun",
    "매출": "sales", "면세점매출": "sales", "지정면세점 매출": "sales", "지정면세점매출": "sales",
}

TTL = {  # 초 단위 캐시 유지 시간 (호출 한도 보호)
    "naver_main": 6 * 3600,
    "naver_dfs": 6 * 3600,
    "google": 12 * 3600,
    "kto": 12 * 3600,
    "kma_now": 10 * 60,
    "openmeteo": 30 * 60,
}
MIN_FORCE_INTERVAL = 5 * 60  # '지금 갱신'도 같은 출처는 5분에 한 번만 다시 호출


# ---------------------------------------------------------------------------
# SQLite (DATA_DIR 안에만 저장)
# ---------------------------------------------------------------------------
def db():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with db() as c:
        c.execute("CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, fetched_at REAL, ok INTEGER, payload TEXT, message TEXT)")
        c.execute("CREATE TABLE IF NOT EXISTS manual (metric TEXT, date TEXT, value REAL, updated_at REAL, PRIMARY KEY (metric, date))")


def cache_get(key):
    with db() as c:
        row = c.execute("SELECT * FROM cache WHERE key=?", (key,)).fetchone()
    return dict(row) if row else None


def cache_put(key, ok, payload, message=""):
    with db() as c:
        c.execute("INSERT OR REPLACE INTO cache (key, fetched_at, ok, payload, message) VALUES (?,?,?,?,?)",
                  (key, time.time(), 1 if ok else 0, json.dumps(payload, ensure_ascii=False), message))


# ---------------------------------------------------------------------------
# 날짜 도우미
# ---------------------------------------------------------------------------
def today_kst() -> dt.date:
    return dt.datetime.now(KST).date()


def iso(d: dt.date) -> str:
    return d.isoformat()


def date_range(start: dt.date, end: dt.date):
    d = start
    while d <= end:
        yield d
        d += dt.timedelta(days=1)


# ---------------------------------------------------------------------------
# 1) 네이버 데이터랩 검색어 트렌드
# ---------------------------------------------------------------------------
NAVER_HUB_URL = "https://naverapihub.apigw.ntruss.com/search-trend/v1/search"
NAVER_DEV_URL = "https://openapi.naver.com/v1/datalab/search"


async def fetch_naver(client: httpx.AsyncClient, groups):
    cid, secret = env("NAVER_CLIENT_ID"), env("NAVER_CLIENT_SECRET")
    if not cid or not secret:
        return None, "키 미설정 (NAVER_CLIENT_ID, NAVER_CLIENT_SECRET)"
    end = today_kst() - dt.timedelta(days=1)
    start = end - dt.timedelta(days=HISTORY_DAYS - 1)
    body = {"startDate": iso(start), "endDate": iso(end), "timeUnit": "date", "keywordGroups": groups}
    attempts = [
        (NAVER_HUB_URL, {"X-NCP-APIGW-API-KEY-ID": cid, "X-NCP-APIGW-API-KEY": secret}),
        (NAVER_DEV_URL, {"X-Naver-Client-Id": cid, "X-Naver-Client-Secret": secret}),
    ]
    if env("NAVER_API_TYPE").lower() in ("dev", "developers", "legacy"):
        attempts.reverse()
    last_err = ""
    for url, headers in attempts:
        try:
            r = await client.post(url, json=body, headers={**headers, "Content-Type": "application/json"})
            if r.status_code == 200:
                data = r.json()
                out = {}
                for res in data.get("results", []):
                    pts = {p["period"]: float(p["ratio"]) for p in res.get("data", [])}
                    # 검색이 거의 없던 날은 응답에서 빠지므로 0으로 채운다
                    out[res["title"]] = {iso(d): round(pts.get(iso(d), 0.0), 2) for d in date_range(start, end)}
                return out, ""
            last_err = f"{url.split('/')[2]} 응답 {r.status_code}: {r.text[:160]}"
        except Exception as e:  # noqa: BLE001
            last_err = f"{url.split('/')[2]} 연결 오류: {e}"
    return None, last_err


# ---------------------------------------------------------------------------
# 2) 구글 트렌드 (SerpApi)
# ---------------------------------------------------------------------------
async def fetch_google(client: httpx.AsyncClient):
    key = env("SERPAPI_KEY")
    if not key:
        return None, "키 미설정 (SERPAPI_KEY)"
    params = {
        "engine": "google_trends", "q": ",".join(GOOGLE_QUERIES), "geo": "KR",
        "date": "today 3-m", "data_type": "TIMESERIES", "tz": "-540", "hl": "ko", "api_key": key,
    }
    try:
        r = await client.get("https://serpapi.com/search.json", params=params)
        if r.status_code != 200:
            return None, f"SerpApi 응답 {r.status_code}: {r.text[:160]}"
        data = r.json()
        if data.get("error"):
            return None, f"SerpApi 오류: {data['error']}"
        timeline = (data.get("interest_over_time") or {}).get("timeline_data") or []
        out = {q: {} for q in GOOGLE_QUERIES}
        for row in timeline:
            ts = int(row.get("timestamp", 0))
            d = iso(dt.datetime.fromtimestamp(ts, KST).date()) if ts else None
            if not d:
                continue
            for v in row.get("values", []):
                q = v.get("query")
                val = v.get("extracted_value")
                if val is None:
                    try:
                        val = float(str(v.get("value", "0")).replace("<1", "0.5"))
                    except ValueError:
                        val = 0
                if q in out:
                    out[q][d] = float(val)
        if not any(out.values()):
            return None, "구글 트렌드 결과가 비어 있음"
        return out, ""
    except Exception as e:  # noqa: BLE001
        return None, f"SerpApi 연결 오류: {e}"


# ---------------------------------------------------------------------------
# 3) 한국관광공사 빅데이터 지역별 방문자수 (광역 일별)
# ---------------------------------------------------------------------------
KTO_URL = "https://apis.data.go.kr/B551011/DataLabService/metcoRegnVisitrDDList"


def data_go_key():
    k = env("DATA_GO_KR_KEY")
    return unquote(k) if "%" in k else k


def _items(data):
    body = (data.get("response") or {}).get("body") or {}
    items = body.get("items") or {}
    if isinstance(items, dict):
        items = items.get("item") or []
    if isinstance(items, dict):
        items = [items]
    return items, int(body.get("totalCount") or 0)


async def fetch_kto(client: httpx.AsyncClient):
    key = data_go_key()
    if not key:
        return None, "키 미설정 (DATA_GO_KR_KEY)"
    end = today_kst() - dt.timedelta(days=1)
    start = end - dt.timedelta(days=HISTORY_DAYS - 1)
    out = {"외지인": {}, "외국인": {}, "현지인": {}}
    page, rows = 1, 1000
    try:
        while page <= 10:
            params = {"serviceKey": key, "numOfRows": rows, "pageNo": page, "MobileOS": "ETC",
                      "MobileApp": "JejuDFSDashboard", "startYmd": start.strftime("%Y%m%d"),
                      "endYmd": end.strftime("%Y%m%d"), "_type": "json"}
            r = await client.get(KTO_URL, params=params)
            if r.status_code != 200:
                return None, f"관광공사 API 응답 {r.status_code}: {r.text[:160]}"
            try:
                data = r.json()
            except ValueError:
                return None, f"관광공사 API가 JSON이 아닌 응답을 보냄: {r.text[:160]}"
            header = (data.get("response") or {}).get("header") or {}
            if str(header.get("resultCode", "0000")) not in ("0000", "00"):
                return None, f"관광공사 API 오류 {header.get('resultCode')}: {header.get('resultMsg')}"
            items, total = _items(data)
            for it in items:
                name = str(it.get("areaNm", ""))
                code = str(it.get("areaCode", ""))
                if "제주" not in name and code != "50":
                    continue
                kind = str(it.get("touDivNm", ""))
                cd = str(it.get("touDivCd", ""))
                label = "외지인" if ("외지" in kind or cd == "2") else "외국인" if ("외국" in kind or cd == "3") else "현지인"
                ymd = str(it.get("baseYmd", ""))
                if len(ymd) != 8:
                    continue
                d = f"{ymd[:4]}-{ymd[4:6]}-{ymd[6:]}"
                try:
                    out[label][d] = round(float(it.get("touNum", 0)))
                except (TypeError, ValueError):
                    pass
            if page * rows >= total or not items:
                break
            page += 1
        if not out["외지인"]:
            return None, "응답에 제주 데이터가 없음 (활용신청 승인·기간 확인)"
        return out, ""
    except Exception as e:  # noqa: BLE001
        return None, f"관광공사 API 연결 오류: {e}"


# ---------------------------------------------------------------------------
# 4) 기상청 초단기실황 (현재 날씨)
# ---------------------------------------------------------------------------
KMA_URL = "https://apis.data.go.kr/1360000/VilageFcstInfoService_2.0/getUltraSrtNcst"


def latlon_to_grid(lat, lon):
    """기상청 격자(Lambert Conformal Conic) 변환 - 기상청 단기예보 활용가이드 공식."""
    RE, GRID, SLAT1, SLAT2, OLON, OLAT, XO, YO = 6371.00877, 5.0, 30.0, 60.0, 126.0, 38.0, 43, 136
    DEG = math.pi / 180.0
    re = RE / GRID
    slat1, slat2, olon, olat = SLAT1 * DEG, SLAT2 * DEG, OLON * DEG, OLAT * DEG
    sn = math.tan(math.pi * 0.25 + slat2 * 0.5) / math.tan(math.pi * 0.25 + slat1 * 0.5)
    sn = math.log(math.cos(slat1) / math.cos(slat2)) / math.log(sn)
    sf = math.pow(math.tan(math.pi * 0.25 + slat1 * 0.5), sn) * math.cos(slat1) / sn
    ro = re * sf / math.pow(math.tan(math.pi * 0.25 + olat * 0.5), sn)
    ra = re * sf / math.pow(math.tan(math.pi * 0.25 + lat * DEG * 0.5), sn)
    theta = lon * DEG - olon
    if theta > math.pi:
        theta -= 2.0 * math.pi
    if theta < -math.pi:
        theta += 2.0 * math.pi
    theta *= sn
    return int(math.floor(ra * math.sin(theta) + XO + 0.5)), int(math.floor(ro - ra * math.cos(theta) + YO + 0.5))


PTY = {"0": "없음", "1": "비", "2": "비/눈", "3": "눈", "5": "빗방울", "6": "빗방울·눈날림", "7": "눈날림"}


async def fetch_kma_now(client: httpx.AsyncClient):
    key = data_go_key()
    if not key:
        return None, "키 미설정 (DATA_GO_KR_KEY)"
    now = dt.datetime.now(KST)
    base = now - dt.timedelta(hours=1) if now.minute < 45 else now
    base_date, base_time = base.strftime("%Y%m%d"), base.strftime("%H00")

    async def one(spot):
        nx, ny = latlon_to_grid(spot["lat"], spot["lon"])
        params = {"serviceKey": key, "pageNo": 1, "numOfRows": 100, "dataType": "JSON",
                  "base_date": base_date, "base_time": base_time, "nx": nx, "ny": ny}
        r = await client.get(KMA_URL, params=params)
        data = r.json()
        header = (data.get("response") or {}).get("header") or {}
        if str(header.get("resultCode")) != "00":
            raise RuntimeError(f"기상청 오류 {header.get('resultCode')}: {header.get('resultMsg')}")
        items, _ = _items(data)
        v = {it["category"]: it["obsrValue"] for it in items}
        return {
            "id": spot["id"], "name": spot["name"], "grid": [nx, ny],
            "temp": _f(v.get("T1H")), "humidity": _f(v.get("REH")), "rain1h": _f(v.get("RN1")),
            "wind": _f(v.get("WSD")), "wind_dir": _f(v.get("VEC")),
            "pty": PTY.get(str(v.get("PTY", "0")), "없음"),
            "observed": f"{base_date[:4]}-{base_date[4:6]}-{base_date[6:]} {base_time[:2]}:00",
        }

    try:
        res = await asyncio.gather(*[one(s) for s in WEATHER_SPOTS])
        return res, ""
    except Exception as e:  # noqa: BLE001
        return None, f"기상청 API: {e}"


def _f(x):
    try:
        v = float(x)
        return None if v <= -900 else v  # 결측값(-998 등) 제거
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# 5) Open-Meteo (지난 31일 + 앞으로 10일, 키 불필요)
# ---------------------------------------------------------------------------
async def fetch_openmeteo(client: httpx.AsyncClient):
    params = {
        "latitude": ",".join(str(s["lat"]) for s in WEATHER_SPOTS),
        "longitude": ",".join(str(s["lon"]) for s in WEATHER_SPOTS),
        "current": "temperature_2m,relative_humidity_2m,precipitation,weather_code,wind_speed_10m",
        "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_sum,"
                 "precipitation_probability_max,wind_speed_10m_max",
        "timezone": "Asia/Seoul", "past_days": 31, "forecast_days": 10, "wind_speed_unit": "ms",
    }
    try:
        r = await client.get("https://api.open-meteo.com/v1/forecast", params=params)
        if r.status_code != 200:
            return None, f"Open-Meteo 응답 {r.status_code}: {r.text[:160]}"
        data = r.json()
        if isinstance(data, dict):
            data = [data]
        out = {}
        for spot, d in zip(WEATHER_SPOTS, data):
            daily = d.get("daily", {})
            days = []
            for i, day in enumerate(daily.get("time", [])):
                days.append({
                    "date": day,
                    "code": daily["weather_code"][i],
                    "tmax": daily["temperature_2m_max"][i],
                    "tmin": daily["temperature_2m_min"][i],
                    "precip": daily["precipitation_sum"][i],
                    "pop": daily["precipitation_probability_max"][i],
                    "wind": daily["wind_speed_10m_max"][i],
                })
            cur = d.get("current", {})
            out[spot["id"]] = {
                "name": spot["name"], "days": days,
                "current": {
                    "temp": cur.get("temperature_2m"), "humidity": cur.get("relative_humidity_2m"),
                    "precip": cur.get("precipitation"), "code": cur.get("weather_code"),
                    "wind": cur.get("wind_speed_10m"), "time": cur.get("time"),
                },
            }
        return out, ""
    except Exception as e:  # noqa: BLE001
        return None, f"Open-Meteo 연결 오류: {e}"


# ---------------------------------------------------------------------------
# 예시 데이터 (키가 없을 때 화면 구성을 보여주기 위함 - 화면에 '예시'로 표시)
# ---------------------------------------------------------------------------
def demo_series(seed, base, amp, weekly, noise, end_offset=1):
    rnd = random.Random(seed)
    end = today_kst() - dt.timedelta(days=end_offset)
    start = end - dt.timedelta(days=HISTORY_DAYS - 1)
    out = {}
    for i, d in enumerate(date_range(start, end)):
        wk = weekly[d.weekday()]
        trend = 1 + 0.08 * math.sin(i / 14)
        out[iso(d)] = round(max(0, base * wk * trend * (1 + amp * math.sin(i / 9)) + rnd.gauss(0, noise)), 1)
    return out


def demo_naver(groups):
    weekly = [0.95, 0.92, 0.94, 1.0, 1.08, 0.98, 1.05]
    bases = [72, 58, 18, 40, 22, 14, 9, 6]
    return {g["groupName"]: demo_series("n" + g["groupName"], bases[i % len(bases)], 0.12, weekly, 3)
            for i, g in enumerate(groups)}


def demo_kto():
    weekly = [0.92, 0.9, 0.92, 0.97, 1.08, 1.12, 1.05]
    return {
        "외지인": {k: round(v) for k, v in demo_series("kto-ext", 150000, 0.06, weekly, 4000, 5).items()},
        "외국인": {k: round(v) for k, v in demo_series("kto-for", 9000, 0.1, weekly, 600, 5).items()},
        "현지인": {k: round(v) for k, v in demo_series("kto-loc", 260000, 0.02, [1] * 7, 3000, 5).items()},
    }


# ---------------------------------------------------------------------------
# 출처별 가져오기 + 캐시
# ---------------------------------------------------------------------------
SOURCES = {
    "naver_main": {"name": "네이버 검색어 트렌드 (관광 키워드)", "provider": "네이버 데이터랩",
                   "cadence": "일 단위 · 전일까지", "url": "https://datalab.naver.com/keyword/trendSearch.naver"},
    "naver_dfs": {"name": "네이버 검색어 트렌드 (면세점 비교)", "provider": "네이버 데이터랩",
                  "cadence": "일 단위 · 전일까지", "url": "https://datalab.naver.com/keyword/trendSearch.naver"},
    "google": {"name": "구글 트렌드 (대한민국)", "provider": "Google Trends · SerpApi 경유",
               "cadence": "일 단위 · 최근 3개월", "url": "https://trends.google.co.kr/trends/"},
    "kto": {"name": "제주 방문자수 (외지인·외국인)", "provider": "한국관광공사 한국관광 데이터랩 (KT·SKT 통신 데이터)",
            "cadence": "일 단위 · 수일 지연 공개", "url": "https://datalab.visitkorea.or.kr"},
    "kma_now": {"name": "현재 날씨 (초단기실황)", "provider": "기상청 · 공공데이터포털",
                "cadence": "매시간", "url": "https://www.data.go.kr/data/15084084/openapi.do"},
    "openmeteo": {"name": "지난 31일·향후 10일 날씨", "provider": "Open-Meteo (기상 모델 기반)",
                  "cadence": "1시간 단위 갱신", "url": "https://open-meteo.com"},
}

FETCHERS = {
    "naver_main": lambda c: fetch_naver(c, NAVER_GROUPS_MAIN),
    "naver_dfs": lambda c: fetch_naver(c, NAVER_GROUPS_DFS),
    "google": fetch_google,
    "kto": fetch_kto,
    "kma_now": fetch_kma_now,
    "openmeteo": fetch_openmeteo,
}

_locks = {k: asyncio.Lock() for k in FETCHERS}


async def get_source(client, key, force=False):
    """캐시가 유효하면 캐시, 아니면 새로 호출. 실패하면 마지막 성공값을 유지."""
    async with _locks[key]:
        cached = cache_get(key)
        age = time.time() - cached["fetched_at"] if cached else None
        # 실패 기록(키 미설정 등)은 2분만 유지 → 키를 넣고 재배포하면 바로 실제 값으로 바뀜
        ttl = TTL[key] if (cached and cached["ok"]) else 120
        fresh = cached and age < ttl
        if cached and (fresh and not force or (force and age < MIN_FORCE_INTERVAL)):
            return cached
        data, msg = await FETCHERS[key](client)
        if data is not None:
            cache_put(key, True, data, "")
            return cache_get(key)
        # 실패: 이전 성공 데이터가 있으면 그대로 두고 메시지만 남긴다
        if cached and cached["ok"]:
            with db() as c:
                c.execute("UPDATE cache SET message=? WHERE key=?", (f"최근 갱신 실패 – 이전 값 표시 중 ({msg})", key))
            return cache_get(key)
        cache_put(key, False, None, msg)
        return cache_get(key)


def manual_series():
    with db() as c:
        rows = c.execute("SELECT metric, date, value FROM manual ORDER BY date").fetchall()
    out = {k: {} for k in MANUAL_METRICS}
    for r in rows:
        if r["metric"] in out:
            out[r["metric"]][r["date"]] = r["value"]
    return out


# ---------------------------------------------------------------------------
# FastAPI 앱
# ---------------------------------------------------------------------------
app = FastAPI(title="제주 지정면세점 수요 대시보드")
init_db()


@app.get("/api/health")
async def health():
    return {"ok": True, "time": dt.datetime.now(KST).isoformat(), "data_dir": DATA_DIR}


@app.get("/api/data")
async def api_data(refresh: int = 0):
    async with httpx.AsyncClient(timeout=httpx.Timeout(20.0), follow_redirects=True) as client:
        keys = list(FETCHERS)
        results = await asyncio.gather(*[get_source(client, k, force=bool(refresh)) for k in keys])
    res = dict(zip(keys, results))

    status = []
    payload = {}
    for k in keys:
        row = res[k] or {}
        ok = bool(row.get("ok")) and row.get("payload") not in (None, "null")
        data = json.loads(row["payload"]) if ok else None
        mode = "live" if ok else "demo"
        if not ok:
            if k == "naver_main":
                data = demo_naver(NAVER_GROUPS_MAIN)
            elif k == "naver_dfs":
                data = demo_naver(NAVER_GROUPS_DFS)
            elif k == "google":
                data = {g: v for g, v in demo_naver([{"groupName": q} for q in GOOGLE_QUERIES]).items()}
            elif k == "kto":
                data = demo_kto()
            else:
                mode = "off"
        payload[k] = data
        info = SOURCES[k]
        status.append({
            "id": k, **info, "mode": mode,
            "message": row.get("message") or "",
            "updated_at": dt.datetime.fromtimestamp(row["fetched_at"], KST).strftime("%Y-%m-%d %H:%M") if row.get("fetched_at") else None,
        })

    manual = manual_series()
    for mk, meta in MANUAL_METRICS.items():
        n = len(manual[mk])
        last = max(manual[mk]) if n else None
        status.append({"id": "manual_" + mk, "name": meta["label"], "provider": meta["source"],
                       "cadence": "관리자 입력", "url": "", "mode": "manual" if n else "empty",
                       "message": f"{n}일치 입력됨 · 최근 {last}" if n else "아직 입력된 값 없음", "updated_at": last})

    return JSONResponse({
        "generated_at": dt.datetime.now(KST).strftime("%Y-%m-%d %H:%M"),
        "today": iso(today_kst()),
        "sources": status,
        "naver_main": payload["naver_main"],
        "naver_dfs": payload["naver_dfs"],
        "google": payload["google"],
        "kto": payload["kto"],
        "kma_now": payload["kma_now"],
        "openmeteo": payload["openmeteo"],
        "manual": manual,
        "manual_meta": MANUAL_METRICS,
        "admin_enabled": bool(env("ADMIN_PASSWORD")),
    })


# ---------------- 관리자 입력 ----------------
def check_admin(pw):
    real = env("ADMIN_PASSWORD")
    if not real:
        raise HTTPException(403, "관리자 기능이 꺼져 있습니다. 배포 화면 환경변수에 ADMIN_PASSWORD를 넣어 주세요.")
    if not pw or not hmac.compare_digest(pw.encode(), real.encode()):
        raise HTTPException(401, "관리자 비밀번호가 맞지 않습니다.")


def parse_date(s):
    s = str(s).strip().replace(".", "-").replace("/", "-")
    if len(s) == 8 and s.isdigit():
        s = f"{s[:4]}-{s[4:6]}-{s[6:]}"
    parts = s.split("-")
    if len(parts) != 3:
        raise ValueError(f"날짜 형식 오류: {s}")
    return dt.date(int(parts[0]), int(parts[1]), int(parts[2])).isoformat()


def parse_num(s):
    s = str(s).strip().replace(",", "").replace("명", "").replace("원", "")
    if s == "":
        return None
    return float(s)


@app.post("/api/admin/check")
async def admin_check(x_admin_password: str = Header(default="")):
    check_admin(x_admin_password)
    return {"ok": True}


@app.post("/api/manual")
async def manual_add(request: Request, x_admin_password: str = Header(default="")):
    check_admin(x_admin_password)
    body = await request.json()
    rows = body if isinstance(body, list) else [body]
    saved = 0
    with db() as c:
        for r in rows:
            metric = r.get("metric")
            if metric not in MANUAL_METRICS:
                raise HTTPException(400, f"알 수 없는 지표: {metric}")
            try:
                d, v = parse_date(r.get("date")), parse_num(r.get("value"))
            except (ValueError, TypeError) as e:
                raise HTTPException(400, f"입력 오류: {e}")
            if v is None:
                continue
            c.execute("INSERT OR REPLACE INTO manual VALUES (?,?,?,?)", (metric, d, v, time.time()))
            saved += 1
    return {"ok": True, "saved": saved}


@app.delete("/api/manual")
async def manual_delete(metric: str, date: str, x_admin_password: str = Header(default="")):
    check_admin(x_admin_password)
    with db() as c:
        n = c.execute("DELETE FROM manual WHERE metric=? AND date=?", (metric, parse_date(date))).rowcount
    return {"ok": True, "deleted": n}


@app.post("/api/manual/upload")
async def manual_upload(file: UploadFile = File(...), x_admin_password: str = Header(default="")):
    check_admin(x_admin_password)
    raw = await file.read()
    if len(raw) > 2_000_000:
        raise HTTPException(400, "파일이 너무 큽니다 (2MB 이하).")
    text = None
    for enc in ("utf-8-sig", "cp949", "euc-kr"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        raise HTTPException(400, "CSV 글자 인코딩을 읽을 수 없습니다 (UTF-8 또는 CP949로 저장해 주세요).")
    reader = list(csv.reader(io.StringIO(text)))
    if len(reader) < 2:
        raise HTTPException(400, "데이터 행이 없습니다.")
    header = [h.strip() for h in reader[0]]
    cols = {}
    for i, h in enumerate(header[1:], start=1):
        key = h if h in MANUAL_METRICS else MANUAL_ALIASES.get(h) or MANUAL_ALIASES.get(h.replace(" ", ""))
        if key:
            cols[i] = key
    if not cols:
        raise HTTPException(400, "머리글에서 지표를 찾지 못했습니다. 예: 날짜,내국인입도객,우도,중문,매출")
    saved, errors = 0, []
    with db() as c:
        for ln, row in enumerate(reader[1:], start=2):
            if not row or not row[0].strip():
                continue
            try:
                d = parse_date(row[0])
            except (ValueError, TypeError) as e:
                errors.append(f"{ln}행: {e}")
                continue
            for i, metric in cols.items():
                if i >= len(row):
                    continue
                try:
                    v = parse_num(row[i])
                except ValueError:
                    errors.append(f"{ln}행 {header[i]}: 숫자가 아님")
                    continue
                if v is None:
                    continue
                c.execute("INSERT OR REPLACE INTO manual VALUES (?,?,?,?)", (metric, d, v, time.time()))
                saved += 1
    return {"ok": True, "saved": saved, "columns": [MANUAL_METRICS[m]["label"] for m in cols.values()],
            "errors": errors[:20]}


@app.get("/api/manual/template.csv")
async def manual_template():
    t = today_kst()
    lines = ["날짜,내국인입도객,우도,중문,매출"]
    for i in range(3, 0, -1):
        lines.append(f"{iso(t - dt.timedelta(days=i))},,,,")
    return PlainTextResponse("﻿" + "\n".join(lines) + "\n", media_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition": "attachment; filename=jeju_manual_template.csv"})


@app.get("/api/manual/export.csv")
async def manual_export():
    m = manual_series()
    dates = sorted({d for s in m.values() for d in s})
    lines = ["날짜,내국인입도객,우도,중문,매출"]
    for d in dates:
        vals = [m[k].get(d, "") for k in ("inbound_domestic", "udo", "jungmun", "sales")]
        lines.append(",".join([d] + [("" if v == "" else str(int(v) if float(v).is_integer() else v)) for v in vals]))
    return PlainTextResponse("﻿" + "\n".join(lines) + "\n", media_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition": "attachment; filename=jeju_manual_data.csv"})


# ---------------- 화면 ----------------
@app.get("/")
async def index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


@app.get("/admin")
async def admin_page():
    return FileResponse(os.path.join(STATIC_DIR, "admin.html"))


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))
