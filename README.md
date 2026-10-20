# search-tracker · 브랜드 검색량 대시보드

네이버 검색량으로 내 브랜드와 경쟁사를 일·주·월별로 비교하는 개인용 대시보드입니다. 서버 없이 GitHub만으로 돌아갑니다.

- 대시보드: `https://<아이디>.github.io/search-tracker/`
- 예시 화면: `https://<아이디>.github.io/search-tracker/demo/`

## 구성

| 파일 | 하는 일 |
|---|---|
| `config/brands.json` | 브랜드와 검색어 목록 (대시보드의 ‘+ 브랜드 관리’로 고칠 수 있음) |
| `collector/collect.py` | 네이버 API에서 데이터를 모으는 수집기 (파이썬 표준 라이브러리만 사용) |
| `.github/workflows/collect.yml` | 매일 한국시간 오전 9시 자동 수집 + 수동 실행 |
| `docs/index.html` | 대시보드 화면 (GitHub Pages: main 브랜치 `/docs`) |
| `docs/data/daily.json` | 수집 결과 |
| `docs/data/searchad_snapshots.json` | 날짜별 검색광고 원본 값 |
| `docs/demo/` | 임의 데이터로 만든 예시 화면 |
| `tools/make_demo.py` | 예시 데이터를 다시 만들고 `docs/index.html`을 예시 폴더로 복사 |

## 숫자 계산

- 트렌드 지수: 데이터랩 검색어 트렌드(NAVER API HUB). 브랜드별로 따로 조회해 그 브랜드 최고치 = 100.
- 실제 검색 수: 검색광고 키워드도구 최근 30일 PC+모바일. `< 10`은 5로 계산, 공백만 다른 검색어는 한 번만.
- 배율 = 최근 30일 실제 검색 수 ÷ 최근 30일 지수 합, 일별 추정 검색 수 = 지수 × 배율.

## GitHub Secrets

`NAVER_CLIENT_ID`, `NAVER_CLIENT_SECRET` (NAVER API HUB Client ID/Secret), `SEARCHAD_API_KEY`, `SEARCHAD_SECRET`, `SEARCHAD_CUSTOMER_ID` (검색광고 API). 검색광고 키가 없으면 트렌드 지수만 저장합니다.

데이터랩 주소를 바꾸려면 저장소 **Settings → Secrets and variables → Actions → Variables**에 `DATALAB_URL`을 넣습니다. `openapi.naver.com` 주소면 예전 개발자센터 방식 헤더(X-Naver-Client-Id/Secret)를 씁니다.
