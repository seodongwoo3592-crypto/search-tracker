#!/usr/bin/env python3
"""예시 페이지(docs/demo/)용 임의 데이터와 화면 복사본을 만든다.
실행: python3 tools/make_demo.py
"""
import json
import math
import os
import random
import shutil
from datetime import date, datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KST = timezone(timedelta(hours=9))
random.seed(42)

end = datetime.now(KST).date() - timedelta(days=1)
start = date(2016, 1, 1)
days = (end - start).days + 1

brands = [
    # id, 이름, 내 브랜드, 검색어, 출시일, 기본량, 성장률, 30일 검색 수, 모바일 비율
    ("mine", "내 브랜드", True, ["내 브랜드", "내브랜드"], date(2023, 3, 1), 60, 1.9, 18400, 0.82),
    ("demo_a", "가상 경쟁사 A", False, ["가상 경쟁사 A", "가상경쟁사A"], date(2016, 1, 1), 300, 0.25, 41200, 0.74),
    ("demo_b", "가상 경쟁사 B", False, ["가상 경쟁사 B", "가상경쟁사B"], date(2019, 6, 1), 120, 0.8, 12600, 0.88),
]

groups, series = [], {}
for bid, name, mine, kws, launch, base, growth, monthly, mo in brands:
    raw = []
    for i in range(days):
        d = start + timedelta(days=i)
        if d < launch:
            raw.append((d, 0.0))
            continue
        t = (d - launch).days / 365.0
        trend = base * (1 + growth * t) / (1 + 0.15 * t * t / (1 + t))
        season = 1 + 0.18 * math.sin((d.timetuple().tm_yday / 365.0) * 2 * math.pi - 1.2)
        weekday = 0.9 if d.weekday() >= 5 else 1.04
        promo = 1.0
        if d.month == 11 and 8 <= d.day <= 14:
            promo = 1.8
        if random.random() < 0.006:
            promo *= 2.4
        noise = random.gauss(1, 0.09)
        raw.append((d, max(0.0, trend * season * weekday * promo * noise)))
    peak = max(v for _, v in raw) or 1
    idx = [(d, round(v / peak * 100, 5)) for d, v in raw]
    last30 = sum(v for d, v in idx if d > end - timedelta(days=30))
    scale = monthly / last30
    series[bid] = [[d.isoformat(), v, round(v * scale)] for d, v in idx]
    pc = round(monthly * (1 - mo))
    groups.append({
        "id": bid, "name": name, "is_mine": mine, "keywords": kws,
        "monthly_searches": monthly, "scale": round(scale, 6),
        "searchad": {kws[0]: {"pc": pc, "mobile": monthly - pc}},
    })

out = {
    "updated_at": datetime.now(KST).replace(hour=9, minute=3, second=0, microsecond=0).isoformat(),
    "demo": True,
    "has_absolute": True,
    "range": [start.isoformat(), end.isoformat()],
    "groups": groups,
    "series": series,
}
os.makedirs(os.path.join(ROOT, "docs", "demo", "data"), exist_ok=True)
with open(os.path.join(ROOT, "docs", "demo", "data", "daily.json"), "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
shutil.copyfile(os.path.join(ROOT, "docs", "index.html"), os.path.join(ROOT, "docs", "demo", "index.html"))
print("예시 데이터 생성:", len(groups), "개 브랜드,", days, "일")
