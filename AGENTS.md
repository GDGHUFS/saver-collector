# SAVER Collector 작업 지침

이 저장소는 SAVER 포털 Backend와 분리되어 외부 API 호출, 데이터 정제, 저장을 담당하는 수집기 모음이다. 각 최상위 작업 디렉토리는 독립 실행 단위로 관리하며, 디렉토리 안의 `main.py`가 해당 작업의 진입점이다. 작업은 Backend 요청 또는 외부 스케줄러에 의해 반복 실행될 수 있다는 전제로 작성한다.

## 현재 구조

```text
.
├── AGENTS.md
├── LICENSE
├── requirements.txt
├── anniversary/
│   ├── README.md
│   ├── config.py
│   ├── main.py
│   ├── parser.py
│   ├── repository.py
│   ├── table.sql
│   └── OpenAPI활용가이드_한국천문연구원_천문우주정보__특일_정보제공_서비스_v1.4.pdf
└── rss/
    ├── README.md
    ├── config.py
    ├── main.py
    ├── parser.py
    ├── repository.py
    ├── table.sql
    ├── hackernews.rss
    ├── 교수신문.xml
    └── 전자신문.xml
```

## 공통 개발 원칙

* 작업 단위는 디렉토리로 분리하고, 새 수집기를 추가할 때도 `<task>/main.py` 구조를 유지한다.
* 수집기는 한 번 실행해도, 주기적으로 반복 실행해도 데이터가 중복되거나 손상되지 않도록 멱등성을 고려한다.
* 외부 API 응답은 신뢰하지 말고 필수 필드 누락, 형식 차이, 인코딩, 날짜 파싱 실패, 네트워크 오류를 명시적으로 처리한다.
* DB 스키마와 데이터 계약은 코드보다 우선한다. 저장 필드나 제약 조건을 바꿀 때는 관련 SQL과 코드 변경을 함께 점검한다.
* 저장 모델은 원천 API의 모든 필드를 복제하지 않고 실제 서비스 화면과 조회 요구사항을 기준으로 설계한다. 수집 제어용 메타데이터와 원문 응답은 운영 또는 감사 요구가 명확할 때만 저장한다.
* 각 수집기의 `README.md`에는 API 요청 방법, 저장 필드와 제외 필드의 근거, 실행 방법, 검증 방법을 기록한다.
* 비밀 정보는 `.env` 또는 실행 환경 변수로만 주입한다. API 키, DB 비밀번호, 토큰을 커밋하지 않는다.
* 생성물, 가상 환경, dependency directory, cache, editor 임시 파일, 로그는 Git에 추가하지 않는다.

## 외부 API 연동

외부 API를 사용하는 수집기는 다음을 공통으로 확인한다.

* 문서의 필드명과 실제 응답이 다를 수 있으므로 정상 응답 예시를 직접 확인하고, 확인된 차이는 파서와 `README.md`에 기록한다.
* 단일 항목과 복수 항목의 응답 구조가 달라질 수 있으면 내부 모델에서는 항상 동일한 컬렉션 형태로 정규화한다.
* `totalCount`, `pageNo`, `numOfRows`를 제공하는 API는 한 페이지의 크기만 늘려 전체 수집을 가정하지 말고 마지막 페이지까지 반복 호출한다.
* API 키가 이미 URL 인코딩되어 제공될 수 있으므로 HTTP 클라이언트가 키를 다시 인코딩하지 않는지 확인한다. 로그에는 API 키가 포함된 전체 URL을 남기지 않는다.
* 응답 성공 코드를 확인한 뒤에만 저장하고, 실패는 호출 단위로 기록한다. 독립된 공급자, 오퍼레이션 또는 조회 기간의 나머지 작업은 계속 수행한다.
* HTTP timeout을 설정하고, 빈 응답, 잘못된 JSON/XML, 필수 필드 누락, 허용되지 않은 열거값을 저장 전에 거른다.

## Python 환경

현재 의존성은 `requirements.txt`에서 관리한다.

```bash
pip install -r requirements.txt
```

작업별 실행은 해당 디렉토리에서 `main.py`를 실행하는 방식을 기본으로 한다. 예를 들어 RSS 수집기는 다음처럼 실행한다.

```bash
cd rss
python main.py
```

루트 기준 상대 경로에 의존하는 코드를 작성할 때는 실행 위치가 달라져도 깨지지 않도록 `pathlib.Path(__file__)` 기준 경로를 우선 사용한다.

## 환경 변수

공통 환경 변수는 루트의 `.env` 또는 실행 환경에서 제공한다.

* `POSTGRES_HOST`: PostgreSQL 호스트. 기본값은 `localhost`.
* `POSTGRES_PORT`: PostgreSQL 포트. 기본값은 `5432`.
* `POSTGRES_USER`: PostgreSQL 사용자. 기본값은 `saver`.
* `POSTGRES_PASSWORD`: PostgreSQL 비밀번호. 기본값은 `saver`.
* `POSTGRES_DB`: PostgreSQL DB 이름. 기본값은 `saverdb`.

`.env`는 Git에 포함하지 않는다.

## RSS 수집기

`rss/`는 RSS 2.0 피드를 읽어 정제한 뒤 PostgreSQL에 저장하는 작업 단위다.

* `rss/README.md`: RSS 수집기 구조, 환경 변수, 실행 방법 설명.
* `rss/main.py`: RSS 수집기의 진입점.
* `rss/config.py`: 환경 변수, 공급자 목록, 경로 설정.
* `rss/parser.py`: RSS XML을 내부 데이터 모델로 정규화하는 파서.
* `rss/repository.py`: PostgreSQL 스키마 적용과 upsert 저장 로직.
* `rss/table.sql`: `news_feeds`, `news_feed_categories`, `news_items`, `news_item_categories` 테이블과 인덱스 정의.
* `rss/교수신문.xml`: 교수신문 샘플 RSS. 원본 주소는 파일 주석의 `https://www.kyosu.net/rss/allArticle.xml`.
* `rss/전자신문.xml`: 전자신문 샘플 RSS. 원본 주소는 파일 주석의 `http://rss.etnews.com/Section901.xml`.
* `rss/hackernews.rss`: Hacker News 샘플 RSS.

초기 지원 공급자는 교수신문, 전자신문, Hacker News로 제한한다. 새 공급자를 추가할 때는 샘플 RSS를 먼저 확인하고, 기존 테이블 구조에 매핑되지 않는 필드는 `extensions` JSONB에 보존하는 방향을 우선 검토한다.

RSS 구현 시 지켜야 할 사항:

* 채널 메타데이터는 `news_feeds`에 저장하고, 기사 항목은 `news_items`에 저장한다.
* 기사 항목의 `title`과 `link`는 필수다. 누락되거나 빈 값이면 저장하지 않는다.
* 카테고리는 피드와 아이템을 구분해 각각 `news_feed_categories`, `news_item_categories`에 저장한다.
* `guid`가 있으면 `(feed_id, guid)`, `guid`가 없으면 `(feed_id, link)` 기준으로 중복 저장을 방지한다.
* 날짜는 가능한 한 timezone-aware 값으로 파싱해 `TIMESTAMPTZ`에 저장한다.
* CDATA, HTML entity, 빈 태그, 한국어 날짜 형식과 RFC 2822 형식을 모두 고려한다.
* 공급자별 특수 필드는 버리지 말고 필요한 경우 `extensions`에 저장한다.
* 네트워크 호출에는 timeout을 설정하고, 실패한 공급자가 있어도 전체 작업이 불필요하게 중단되지 않게 처리한다.

## 특일 정보 수집기

`anniversary/`는 한국천문연구원 특일 정보제공 API를 호출해 달력 UI에 필요한 특일을 PostgreSQL에 저장하는 작업 단위다.

* API 키는 `ANNIVERSARY_API_KEY`로만 주입한다.
* 저장 필드는 날짜, 분류 코드, 특일명, 공공기관 휴일 여부로 제한한다. 원천 순번, 천문 시각과 황경, 페이지 정보는 현재 서비스 도메인에 저장하지 않는다.
* `locdate`는 `YYYYMMDD` 형식을 검증해 PostgreSQL `DATE`로 변환한다.
* `dateKind`는 `01`, `02`, `03`, `04`만 허용한다.
* 휴일 필드는 실제 응답의 `isHoliday`를 우선하고, 가이드 일부에 표기된 `ishHoliday`는 호환용 fallback으로만 처리한다.
* 중복 방지와 upsert 기준은 `(observed_date, date_kind, date_name)`이며 `anniversary/table.sql`의 고유 인덱스와 일치해야 한다.
* 국경일, 공휴일, 기념일, 24절기, 잡절 오퍼레이션과 조회 월은 각각 독립된 호출 단위로 취급한다.
* 달력 월 조회는 날짜 범위를 반개구간(`[월 시작일, 다음 월 시작일)`)으로 사용한다.

## DB 스키마 작업

각 수집기의 `table.sql`은 해당 작업의 현재 스키마 계약이다. `rss/table.sql`처럼 이미 DB에 적용된 파일을 수정하거나 새 수집기의 스키마를 추가할 때는 다음을 확인한다.

* PostgreSQL에서 실행 가능한 문법인지 확인한다.
* 각 `CREATE TABLE`, `CREATE INDEX` 문은 세미콜론으로 끝낸다.
* 중복 방지 인덱스와 `CHECK` 제약이 수집 코드의 upsert 조건과 일치하는지 확인한다.
* 새 수집기는 스키마를 명시적으로 적용할 수 있는 실행 옵션 또는 별도 적용 절차를 `README.md`에 제공한다.
* 기존 데이터 마이그레이션이 필요한 변경이면 별도 마이그레이션 파일 또는 적용 절차를 함께 제안한다.

## 검증 기준

변경 범위에 맞게 가능한 검증을 수행한다.

* 문법 확인: `python -m py_compile <path/to/file.py>`
* RSS 파싱 로직 변경: 제공된 세 샘플 파일로 파싱 결과를 확인한다.
* DB 저장 로직 변경: 로컬 PostgreSQL 또는 테스트 DB에서 `rss/table.sql` 적용과 upsert 동작을 확인한다.
* 특일 수집기 변경: 파서 문법 확인 후 가능한 경우 단일 연월·단일 오퍼레이션으로 실제 API 호출과 DB upsert 결과를 확인한다.
* 네트워크 연동 변경: timeout, 오류 로그, 공급자별 실패 격리 동작을 확인한다.

검증을 실행하지 못했다면 이유를 작업 결과에 명시한다.

## 작업 절차와 Git 규칙

* 작업 시작과 종료 시 `git status --short`와 `git diff`를 확인하여 변경 범위를 점검한다.
* 사용자의 기존 변경을 보존한다. 관련 없는 파일을 수정하거나 되돌리지 않는다.
* 사용자가 명시적으로 요청하지 않으면 commit, push, merge, rebase 또는 branch 생성/변경을 수행하지 않는다.
* 커밋을 요청받으면 하나의 논리적 변경 단위로 구성한다.
* 커밋 메시지는 한국어로 상세하게 작성한다. 제목에 변경 목적을 명확히 쓰고, 본문에 주요 구현 내용과 필요하면 검증 방법 및 영향 범위를 설명한다.
