# 특일 정보 수집기

`anniversary/`는 한국천문연구원 천문우주정보 특일 정보제공 서비스(`SpcdeInfoService`)를 호출해 SAVER 달력 UI에서 사용할 특일 데이터를 PostgreSQL에 저장하는 작업 단위다.

달력 화면의 기본 사용 흐름은 다음과 같다.

* 사용자가 달을 열면 해당 월의 날짜 칸 안에 특일 이름을 표시한다.
* 사용자가 특일을 클릭하면 날짜, 특일명, 분류, 공공기관 휴일 여부 정도의 기본 정보를 보여준다.

이 요구사항을 기준으로 API 원천 필드 중 화면과 서비스 도메인에 필요 없는 값은 저장하지 않는다.

## 구성

* `main.py`: 현재 API 키 로드와 `getHoliDeInfo` 호출 예시를 포함한 진입점.
* `table.sql`: 달력 UI에 필요한 특일 항목 저장 테이블 정의.
* `OpenAPI활용가이드_한국천문연구원_천문우주정보__특일_정보제공_서비스_v1.4.pdf`: 공공데이터포털 OpenAPI 활용가이드 원본.

## 환경 변수

루트 `.env` 또는 실행 환경에 다음 값을 설정한다.

```text
ANNIVERSARY_API_KEY=공공데이터포털에서 발급받은 서비스키

POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_USER=saver
POSTGRES_PASSWORD=saver
POSTGRES_DB=saverdb
```

공공데이터포털 서비스키가 이미 URL 인코딩된 값이면 HTTP 클라이언트의 자동 인코딩으로 이중 인코딩되지 않도록 호출 방식을 확인한다.

## API 명세

기본 URL은 다음과 같다.

```text
http://apis.data.go.kr/B090041/openapi/service/SpcdeInfoService
```

공통 요청 파라미터는 다음과 같다.

| 이름 | 필수 | 설명 |
| --- | --- | --- |
| `ServiceKey` | 예 | 공공데이터포털에서 발급받은 서비스키. 이 저장소에서는 `ANNIVERSARY_API_KEY`로 주입한다. |
| `solYear` | 예 | 조회 연도. 예: `2026` |
| `solMonth` | 아니오 | 조회 월. 2자리 문자열 권장. 예: `06` |
| `_type` | 아니오 | `json`을 지정하면 JSON 응답을 받는다. 기본값은 XML이다. |
| `numOfRows` | 아니오 | 페이지당 결과 수. 기본값은 10이다. 월 또는 연 단위 전체 수집 시 충분히 큰 값을 지정하거나 `totalCount`를 기준으로 페이지를 반복한다. |

지원 오퍼레이션은 다음과 같다.

| 오퍼레이션 | 설명 | 저장 여부 |
| --- | --- | --- |
| `getHoliDeInfo` | 국경일 정보 조회. 제헌절은 포함되지만 휴일 여부는 `N`으로 내려올 수 있다. | 저장 |
| `getRestDeInfo` | 공휴일 정보 조회. 제헌절은 제공되지 않는다. | 저장 |
| `getAnniversaryInfo` | 기념일 정보 조회. | 저장 |
| `get24DivisionsInfo` | 24절기 정보 조회. | 저장 |
| `getSundryDayInfo` | 잡절 정보 조회. | 저장 |

JSON 요청 예시는 다음과 같다.

```text
GET /B090041/openapi/service/SpcdeInfoService/getRestDeInfo?solYear=2026&solMonth=06&_type=json&numOfRows=100&ServiceKey=...
```

응답의 공통 구조는 다음과 같다.

```json
{
  "response": {
    "header": {
      "resultCode": "00",
      "resultMsg": "NORMAL SERVICE."
    },
    "body": {
      "items": {
        "item": [
          {
            "dateKind": "01",
            "dateName": "현충일",
            "isHoliday": "Y",
            "locdate": 20260606,
            "seq": 2
          }
        ]
      },
      "numOfRows": 10,
      "pageNo": 1,
      "totalCount": 1
    }
  }
}
```

## 저장 필드

달력 UI와 상세 팝업에 필요한 필드만 저장한다.

| API 필드 | 저장 컬럼 | 설명 |
| --- | --- | --- |
| `locdate` | `observed_date` | 날짜. API의 `YYYYMMDD` 값을 PostgreSQL `DATE`로 변환한다. |
| `dateKind` | `date_kind` | 특일 분류 코드. |
| `dateName` | `date_name` | 날짜 칸과 상세 팝업에 표시할 특일명. |
| `isHoliday` | `is_holiday` | 공공기관 휴일 여부. `Y`는 `TRUE`, `N`은 `FALSE`로 저장한다. |

`dateKind` 분류는 다음과 같다.

| 코드 | 이름 | 예시 |
| --- | --- | --- |
| `01` | 국경일 | 어린이 날, 광복절, 개천절 |
| `02` | 기념일 | 의병의 날, 정보보호의 날, 4·19 혁명 기념일 |
| `03` | 24절기 | 청명, 경칩, 하지 |
| `04` | 잡절 | 단오, 한식 |

## 제외한 필드

API 가이드에는 존재하지만 현재 서비스 도메인에는 저장하지 않는다.

| 필드 | 제외 이유 |
| --- | --- |
| `seq` | 원천 응답 내부 순번일 뿐 달력 표시나 상세 정보에 쓰이지 않는다. 정렬은 `observed_date`, `date_kind`, `date_name`으로 충분하다. |
| `kst` | 24절기의 정확한 시각 정보지만 현재 팝업 요구사항은 기본 특일 정보 표시다. 향후 절기 상세 정보가 필요할 때 추가한다. |
| `sunLongitude` | 천문 계산 부가 정보로 달력 UI와 기본 팝업에 필요하지 않다. |
| `locdate` 원문 문자열 | `observed_date`로 정규화하면 중복 저장할 필요가 없다. |
| `solYear`, `solMonth` | `observed_date`에서 계산할 수 있다. |
| `source_operation` | 사용자에게 노출되는 도메인 정보가 아니다. 같은 날짜·분류·이름은 하나의 특일로 합친다. |
| `pageNo`, `numOfRows`, `totalCount` | 수집 중 페이지 처리에만 필요하며 서비스 데이터가 아니다. |
| `resultCode`, `resultMsg` | 호출 성공 여부 판단에만 사용한다. 실패 로그가 필요하면 애플리케이션 로그나 별도 운영 로그로 남긴다. |
| `request_url`, `raw_response`, `base_url`, `service_name` | 재현·감사용 원천 보존 필드지만 현재 달력 기능에는 과하다. |
| `extensions` | 현재는 API 필드를 제한적으로 수용한다. 정의되지 않은 필드를 서비스에 노출할 계획이 없으므로 저장하지 않는다. |
| `is_active`, `first_seen_at`, `last_seen_at`, `last_batch_id` | 변경 추적용 메타데이터다. 현재는 연월 재수집 시 해당 범위를 삭제 후 재삽입하거나 upsert하는 방식으로 충분하다. |

가이드 문서의 일부 표에는 `ishHoliday` 또는 `dateKind=00`처럼 실제 예시와 다른 표기가 있다. 구현 시 `isHoliday`를 우선 사용하고 `ishHoliday`는 호환용 fallback으로만 처리한다. `dateKind`는 `01`, `02`, `03`, `04`만 저장한다.

## 저장 구조

`table.sql`은 단일 테이블 `anniversary_special_days`를 만든다.

| 컬럼 | 설명 |
| --- | --- |
| `id` | 내부 식별자. |
| `observed_date` | 달력 칸 매칭에 사용하는 날짜. |
| `date_kind` | 특일 분류 코드. |
| `date_name` | 특일명. |
| `is_holiday` | 공공기관 휴일 여부. |
| `created_at`, `updated_at` | 저장 시각과 마지막 수정 시각. |

중복 방지 기준은 `(observed_date, date_kind, date_name)`이다. 같은 특일이 국경일 조회와 공휴일 조회에서 모두 내려와도 서비스에는 하나의 특일로 저장한다.

월별 달력 조회는 다음 조건으로 충분하다.

```sql
SELECT id, observed_date, date_kind, date_name, is_holiday
FROM anniversary_special_days
WHERE observed_date >= DATE '2026-06-01'
  AND observed_date < DATE '2026-07-01'
ORDER BY observed_date, date_kind, date_name, id;
```

## 수집 방침

* 기본 응답 형식은 JSON으로 요청한다.
* 수집 단위는 오퍼레이션과 연월 조합으로 둔다.
* `resultCode`가 `00`이 아니면 해당 응답의 항목 저장을 건너뛴다.
* `items.item`은 항목이 1개일 때 객체로 내려올 수 있으므로 리스트로 정규화한다.
* `dateName`, `locdate`, `dateKind`, `isHoliday`가 없거나 비어 있으면 저장하지 않는다.
* `locdate`는 `YYYYMMDD`로 검증한 뒤 `DATE`로 변환해 저장한다.
* `isHoliday`는 `Y`를 `TRUE`, `N`을 `FALSE`로 변환한다.
* 같은 연월을 재수집할 때는 해당 날짜 범위의 기존 데이터를 삭제 후 삽입하거나, `(observed_date, date_kind, date_name)` 기준으로 upsert한다.
* 한 오퍼레이션이 실패해도 다른 오퍼레이션과 다른 월 수집은 계속 진행한다.
* HTTP 호출에는 timeout을 설정한다.

## 실행

루트에서 의존성을 설치한다.

```bash
pip install -r requirements.txt
```

현재 예시 진입점은 다음처럼 실행한다.

```bash
python anniversary/main.py
```

DB 저장 구현을 추가한 뒤에는 `anniversary/table.sql`을 먼저 적용하고, 수집 코드의 upsert 조건이 `anniversary_special_days_unique_key`와 일치하는지 확인한다.

## 검증

문서 또는 수집 코드를 변경한 뒤 가능한 검증은 다음과 같다.

```bash
python -m py_compile anniversary/main.py
psql "$DATABASE_URL" -f anniversary/table.sql
python anniversary/main.py
```

로컬 PostgreSQL을 직접 쓰지 않는 환경에서는 최소한 SQL 문법과 Python 문법 확인 결과를 작업 결과에 남긴다.
