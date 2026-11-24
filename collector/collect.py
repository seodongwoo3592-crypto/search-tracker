#!/usr/bin/env python3
"""네이버 검색량 수집기 (표준 라이브러리만 사용)

1) 검색어 트렌드(데이터랩) 일별 지수  : 브랜드마다 따로 호출 → 그 브랜드 최댓값 = 100
2) 검색광고 키워드도구 최근 30일 검색 수 : PC + 모바일
3) 배율 = 30일 검색 수 ÷ 최근 30일 지수 합,  일별 추정 검색 수 = 지수 × 배율

결과: docs/data/daily.json, docs/data/searchad_snapshots.json
하나라도 실패하면 저장할 수 있는 건 저장하고 종료 코드 1을 돌려준다.
"""
import base64
import hashlib
import hmac
import http.client as httplib
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(ROOT, "config", "brands.json")
DATA_DIR = os.path.join(ROOT, "docs", "data")
DAILY_PATH = os.path.join(DATA_DIR, "daily.json")
SNAP_PATH = os.path.join(DATA_DIR, "searchad_snapshots.json")

KST = timezone(timedelta(hours=9))
DEFAULT_DATALAB_URL = "https://naverapihub.apigw.ntruss.com/search-trend/v1/search"
SEARCHAD_BASE = (os.environ.get("SEARCHAD_BASE_URL") or "https://api.searchad.naver.com").strip().rstrip("/")
SEARCHAD_URI = "/keywordstool"

errors = []
warnings = []


def log(msg):
    print(msg, flush=True)


def fail(msg):
    errors.append(msg)
    print("::error::" + msg.replace("\n", " "), flush=True)


def warn(msg):
    warnings.append(msg)
    print("::warning::" + msg.replace("\n", " "), flush=True)


def env(name):
    return (os.environ.get(name) or "").strip()


def load_json(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def save_json(path, obj, compact=False):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        if compact:
            json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))
        else:
            json.dump(obj, f, ensure_ascii=False, indent=1)
        f.write("\n")
    os.replace(tmp, path)


def http(method, url, headers, body=None, tries=4):
    """HTTP 호출. 429/5xx는 잠깐 쉬고 다시 시도. 실패하면 응답 본문을 담아 예외."""
    data = None
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    last = None
    for attempt in range(tries):
        req = urllib.request.Request(url, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=60) as res:
                return json.loads(res.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            text = e.read().decode("utf-8", "replace")[:800]
            last = RuntimeError("HTTP %s: %s" % (e.code, text))
            if e.code in (429, 500, 502, 503, 504) and attempt < tries - 1:
                time.sleep(2 * (attempt + 1))
                continue
            raise last
        except (urllib.error.URLError, TimeoutError, ConnectionError, httplib.HTTPException, OSError) as e:
            # 서버가 응답 없이 연결을 끊는 경우(Remote end closed connection 등)도 잠깐 쉬고 다시 시도
            last = RuntimeError("연결 실패: %s" % e)
            if attempt < tries - 1:
                time.sleep(3 * (attempt + 1))
                continue
            raise last
    raise last


def norm(kw):
    """공백만 다른 검색어는 같은 것으로 본다."""
    return "".join(kw.split()).upper()


def daterange(start, end):
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


# ---------------------------------------------------------------- 데이터랩
def datalab_headers(url):
    cid, secret = env("NAVER_CLIENT_ID"), env("NAVER_CLIENT_SECRET")
    if "openapi.naver.com" in url:
        return {"X-Naver-Client-Id": cid, "X-Naver-Client-Secret": secret,
                "Content-Type": "application/json"}
    return {"X-NCP-APIGW-API-KEY-ID": cid, "X-NCP-APIGW-API-KEY": secret,
            "Content-Type": "application/json"}


def fetch_trend(url, group, start, end):
    body = {
        "startDate": start.isoformat(),
        "endDate": end.isoformat(),
        "timeUnit": "date",
        "keywordGroups": [{"groupName": group["name"][:50] or group["id"],
                           "keywords": group["keywords"][:20]}],
    }
    res = http("POST", url, datalab_headers(url), body)
    results = res.get("results") or []
    got = {}
    if results:
        for row in results[0].get("data") or []:
            got[row["period"]] = float(row.get("ratio") or 0)
    return got


def fill_days(got, start, end):
    """응답에 없는 날은 0으로 채운다(단, end 까지만)."""
    return [(d.isoformat(), round(got.get(d.isoformat(), 0.0), 5)) for d in daterange(start, end)]


# ---------------------------------------------------------------- 검색광고
def to_count(v):
    if isinstance(v, (int, float)):
        return int(v)
    s = str(v).strip()
    if s.startswith("<"):
        return 5  # "< 10" 은 5로 본다
    try:
        return int(float(s.replace(",", "")))
    except ValueError:
        return 0


def searchad_request(keywords, tries=4):
    """검색광고 키워드도구 호출. 다시 시도할 때마다 서명(타임스탬프)을 새로 만든다."""
    api_key, secret, customer = env("SEARCHAD_API_KEY"), env("SEARCHAD_SECRET"), env("SEARCHAD_CUSTOMER_ID")
    qs = urllib.parse.urlencode({"hintKeywords": ",".join(keywords), "showDetail": "1"})
    last = None
    for attempt in range(tries):
        ts = str(int(time.time() * 1000))
        msg = "%s.GET.%s" % (ts, SEARCHAD_URI)
        sig = base64.b64encode(hmac.new(secret.encode("utf-8"), msg.encode("utf-8"), hashlib.sha256).digest()).decode()
        headers = {"X-Timestamp": ts, "X-API-KEY": api_key, "X-Customer": customer, "X-Signature": sig}
        try:
            return http("GET", "%s%s?%s" % (SEARCHAD_BASE, SEARCHAD_URI, qs), headers, tries=1)
        except RuntimeError as e:
            last = e
            text = str(e)
            # 키·서명 오류(401/403)는 다시 해도 같으니 바로 멈춘다
            if text.startswith("HTTP 401") or text.startswith("HTTP 403") or text.startswith("HTTP 400"):
                raise
            if attempt < tries - 1:
                time.sleep(3 * (attempt + 1))
    raise last


def parse_searchad(res, wanted, out):
    for row in res.get("keywordList") or []:
        n = norm(row.get("relKeyword", ""))
        if n in wanted:
            out[n] = {"pc": to_count(row.get("monthlyPcQcCnt")),
                      "mobile": to_count(row.get("monthlyMobileQcCnt"))}
    for n in wanted:
        if n not in out:
            out[n] = {"pc": 0, "mobile": 0}  # 결과에 없으면 검색이 거의 없는 검색어


def fetch_searchad(all_keywords):
    """({정규화 검색어: {pc, mobile}}, {실패한 검색어: 오류}) 반환.
    5개씩 묶어 부르고, 묶음이 실패하면 한 개씩 다시 부른다."""
    uniq = []
    for kw in all_keywords:
        n = norm(kw)
        if n and n not in uniq:
            uniq.append(n)
    out, failed = {}, {}
    for i in range(0, len(uniq), 5):
        chunk = uniq[i:i + 5]
        try:
            parse_searchad(searchad_request(chunk), chunk, out)
        except Exception as e:  # noqa: BLE001
            log("· 검색광고 묶음 조회 실패, 한 개씩 다시 시도 (%s): %s" % (", ".join(chunk), e))
            for n in chunk:
                time.sleep(0.5)
                try:
                    parse_searchad(searchad_request([n]), [n], out)
                except Exception as e2:  # noqa: BLE001
                    failed[n] = str(e2)
        time.sleep(0.5)
    return out, failed


def last_known_searchad():
    """searchad_snapshots.json 에서 검색어별 가장 최근 값을 꺼낸다(오늘 조회가 실패했을 때 대신 쓰기)."""
    snaps = load_json(SNAP_PATH, {})
    known = {}
    for day in sorted(snaps):
        for kwmap in (snaps.get(day) or {}).values():
            for kw, v in (kwmap or {}).items():
                if isinstance(v, dict) and "pc" in v and "mobile" in v:
                    known[norm(kw)] = {"pc": int(v["pc"]), "mobile": int(v["mobile"]), "date": day}
    return known


# ---------------------------------------------------------------- 메인
def main():
    cfg = load_json(CONFIG_PATH, None)
    if not cfg or not isinstance(cfg.get("groups"), list):
        fail("config/brands.json 을 읽지 못했어요.")
        return 1

    today = datetime.now(KST).date()
    end = today - timedelta(days=1)
    try:
        start = date.fromisoformat(cfg.get("start_date") or "2016-01-01")
    except ValueError:
        start = date(2016, 1, 1)
    start = max(start, date(2016, 1, 1))

    url = env("DATALAB_URL") or DEFAULT_DATALAB_URL
    has_trend_key = bool(env("NAVER_CLIENT_ID") and env("NAVER_CLIENT_SECRET"))
    has_ad_key = bool(env("SEARCHAD_API_KEY") and env("SEARCHAD_SECRET") and env("SEARCHAD_CUSTOMER_ID"))
    if not has_trend_key:
        fail("NAVER_CLIENT_ID / NAVER_CLIENT_SECRET 시크릿이 비어 있어요.")
    if not has_ad_key:
        log("검색광고 키가 없어 트렌드 지수만 저장합니다.")

    prev = load_json(DAILY_PATH, {})
    prev_series = prev.get("series") or {}
    prev_groups = {g.get("id"): g for g in prev.get("groups") or []}

    groups = []
    for g in cfg["groups"]:
        kws, seen = [], set()
        for k in g.get("keywords") or []:
            k = str(k).strip()
            if k and k not in seen:
                seen.add(k)
                kws.append(k)
        groups.append({"id": str(g.get("id")), "name": str(g.get("name") or g.get("id")),
                       "is_mine": bool(g.get("is_mine")), "keywords": kws[:20]})

    # 1) 트렌드 지수
    raw = {}
    for g in groups:
        if not g["keywords"]:
            log("· %s: 검색어가 없어 건너뜀" % g["name"])
            continue
        if not has_trend_key:
            continue
        try:
            raw[g["id"]] = fetch_trend(url, g, start, end)
            log("· %s: 트렌드 %d일 받음" % (g["name"], len(raw[g["id"]])))
        except Exception as e:  # noqa: BLE001
            fail("트렌드 조회 실패 (%s): %s" % (g["name"], e))
        time.sleep(0.2)

    # 데이터랩은 어제 값을 오늘 오전(8~10시간 뒤)에 반영한다. 아직 안 나온 날을 0으로 채우지 않도록
    # 모든 브랜드 중 실제로 값이 온 마지막 날짜까지만 저장한다.
    last_days = [max(got) for got in raw.values() if got]
    if last_days:
        data_end = date.fromisoformat(max(last_days))
        if data_end < end:
            log("· 데이터랩에 %s 값이 아직 없어 %s 까지만 저장해요(다음 수집 때 채워져요)." % (end.isoformat(), data_end.isoformat()))
            end = max(data_end, start)
    trend = {gid: fill_days(got, start, end) for gid, got in raw.items()}

    # 2) 검색광고
    ad, ad_failed, known = {}, {}, {}
    if has_ad_key:
        all_kw = [k for g in groups for k in g["keywords"]]
        if all_kw:
            ad, ad_failed = fetch_searchad(all_kw)
            known = last_known_searchad()

    # 3) 합치기
    last30_from = (end - timedelta(days=29)).isoformat()
    out_groups, series, fresh = [], {}, {}
    for g in groups:
        item = dict(g, monthly_searches=None, scale=None, searchad={})
        rows = trend.get(g["id"])
        if rows is None:
            # 이번에 못 받았으면 이전 데이터를 그대로 둔다
            old = prev_series.get(g["id"])
            if old and g["keywords"]:
                series[g["id"]] = old
                pg = prev_groups.get(g["id"]) or {}
                for k in ("monthly_searches", "scale", "searchad"):
                    if pg.get(k) is not None:
                        item[k] = pg[k]
            out_groups.append(item)
            continue

        counted, pc, mobile, have_all = set(), 0, 0, bool(ad or known)
        fresh[g["id"]] = {}
        for kw in g["keywords"]:
            n = norm(kw)
            if n in counted:
                continue
            counted.add(n)
            v = ad.get(n)
            if v is not None:
                fresh[g["id"]][kw] = v
            elif n in ad_failed and n in known:
                k = known[n]
                v = {"pc": k["pc"], "mobile": k["mobile"]}
                warn("검색광고 조회 실패로 '%s'은(는) %s 값을 대신 썼어요 (%s)" % (kw, k["date"], ad_failed[n][:200]))
            elif n in ad_failed:
                fail("검색광고 조회 실패 (%s): %s" % (kw, ad_failed[n][:300]))
            if v is None:
                have_all = False
                continue
            item["searchad"][kw] = v
            pc += v["pc"]
            mobile += v["mobile"]

        scale = None
        if have_all and counted:
            monthly = pc + mobile
            item["monthly_searches"] = monthly
            idx_sum = sum(r for d, r in rows if d >= last30_from)
            if idx_sum > 0:
                scale = monthly / idx_sum
                item["scale"] = round(scale, 6)
        series[g["id"]] = [[d, r, (round(r * scale) if scale is not None else None)] for d, r in rows]
        out_groups.append(item)

    has_absolute = any(g["scale"] is not None for g in out_groups)
    result = {
        "updated_at": datetime.now(KST).replace(microsecond=0).isoformat(),
        "demo": False,
        "has_absolute": has_absolute,
        "range": [start.isoformat(), end.isoformat()],
        "groups": out_groups,
        "series": series,
        "errors": errors[:20],
    }
    save_json(DAILY_PATH, result, compact=True)
    log("daily.json 저장 완료 (브랜드 %d개, 검색 수 %s)" % (len(out_groups), "있음" if has_absolute else "없음"))

    if ad:
        snaps = load_json(SNAP_PATH, {})
        snaps[today.isoformat()] = {gid: m for gid, m in fresh.items() if m}  # 오늘 실제로 받은 값만 쌓는다
        save_json(SNAP_PATH, dict(sorted(snaps.items())))
        log("searchad_snapshots.json 저장 완료")

    if warnings:
        log("\n참고 %d건(수집은 정상 저장):" % len(warnings))
        for w in warnings:
            log(" - " + w)
    if errors:
        log("\n실패 %d건:" % len(errors))
        for e in errors:
            log(" - " + e)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
