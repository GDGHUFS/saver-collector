# 단기예보 수집기

`weather/`는 기상청 단기예보 조회서비스(`VilageFcstInfoService_2.0`)의
`getVilageFcst`를 호출해 전국 행정구역 격자의 단기예보를 PostgreSQL에
저장한다.

사용자는 다음 두 방식으로 날씨 위치를 찾는 것을 전제로 한다.

* 한국 지역 이름은 `weather_locations`의 1·2·3단계 행정구역명을 검색해
  `nx`, `ny`를 찾는다.
* 위도와 경도는 기상청 Lambert Conformal Conic 변환식으로 `nx`, `ny`를
  계산한다.

전국 선수집은 별첨 XLSX의 3,838개 행정구역이 사용하는 1,632개 고유
격자를 대상으로 한다. 임의의 위경도가 이 집합에 없는 격자로 변환되면
`--coordinate`를 사용한 단건 수집으로 보완할 수 있다.

## 구성

* `main.py`: 위치 동기화, TTL 정리, 전국 또는 선택 격자 수집 진입점.
* `config.py`: 환경 변수와 전국 수집 주기 설정.
* `grid.py`: 위경도와 기상청 격자 간 양방향 변환.
* `locations.py`: 격자·위경도 XLSX 검증과 내부 모델 변환.
* `api.py`: 요청 속도 제한, 재시도, 페이지 순회와 서비스키 처리.
* `parser.py`: JSON 응답 필드, category, 결측값 검증.
* `repository.py`: 위치 동기화, 발표본 저장, 일일 호출량과 TTL 관리.
* `models.py`: 위치, 격자, 예보값 내부 모델.
* `schedule.py`: KST 발표시각 선택.
* `table.sql`: PostgreSQL 스키마와 인덱스.
* `tests/`: 좌표, 주기, 파서, 페이지 호출, 제공 XLSX 검증 테스트.

## API 요청

기본 서비스 URL은 다음과 같다.

```text
http://apis.data.go.kr/1360000/VilageFcstInfoService_2.0
```

단기예보 오퍼레이션은 `getVilageFcst`이며 다음 파라미터를 사용한다.

| 파라미터 | 설명 |
| --- | --- |
| `serviceKey` | 공공데이터포털 인증키. `WEATHER_API_KEY`로만 주입한다. |
| `pageNo` | 페이지 번호. 1부터 `totalCount`를 충족할 때까지 반복한다. |
| `numOfRows` | 페이지당 요청 수. 기본 1,000건이다. |
| `dataType` | `JSON`으로 고정한다. |
| `base_date` | KST 발표일 `YYYYMMDD`. |
| `base_time` | KST 발표시각 `HHMM`. |
| `nx`, `ny` | 기상청 5km 단기예보 격자. |

이미 URL 인코딩된 인증키가 `%252B`처럼 다시 인코딩되지 않도록 다른
파라미터만 `urlencode`하고 서비스키는 마지막에 그대로 붙인다. 요청 URL과
서비스키는 로그에 남기지 않는다.

`resultCode`는 `00`을 정상으로 사용하되 가이드 XML 예제의 `0`도 정상으로
수용한다. `totalCount`까지 모든 페이지를 받은 뒤에만 발표본을 저장한다.

## 전국 수집 주기와 API 한도

기상청 단기예보는 KST 기준 하루 8회 `02·05·08·11·14·17·20·23시`에
발표되며 약 10분 뒤 API에서 제공된다. 이 수집기의 기본 주기는 한 번씩
건너뛴 `02·08·14·20시`다.

응답이 격자당 한 페이지이면 기본 호출량은 다음과 같다.

```text
1,632격자 × 4회 = 하루 6,528 요청
```

개발계정 10,000회 한도에 재시도와 추가 페이지 여유를 남기기 위해 실제
HTTP 요청은 `weather_api_daily_usage`에서 KST 날짜별로 원자적으로
계수하며 기본 9,500회에서 차단한다. 재시도와 모든 페이지 호출도 한도에
포함된다. 동일 키를 다른 애플리케이션에서도 사용한다면 그 호출량만큼
`WEATHER_DAILY_REQUEST_LIMIT`을 더 낮춰야 한다.

`WEATHER_REQUESTS_PER_SECOND` 기본값은 20이며 API 문서의 초당 최대
30트랜잭션을 넘지 못하도록 설정 단계에서 검증한다. 동시에 실행된 수집기는
PostgreSQL advisory lock으로 하나만 동작한다.

최신 선택 발표본을 이미 저장한 격자는 다시 호출하지 않는다. 일부 격자만
실패하면 다음 실행에서 실패한 격자만 다시 시도한다. `--force`를 지정한
경우에만 저장된 격자도 다시 호출한다.

인증키 오류, 접근 거부, 요청 한도 초과처럼 모든 격자에 동일하게 적용되는
비재시도 오류가 한 번 확인되면 남은 격자는 HTTP 요청 전에 중단한다. 잘못된
설정으로 수천 건의 실패 요청을 반복해 일일 한도를 소진하지 않기 위해서다.

## 저장 구조

### `weather_grid_points`

고유 `(nx, ny)`와 공식 변환식으로 계산한 격자 중심 위경도를 저장한다.
여러 행정구역이 같은 격자를 공유하고, 예보도 격자 기준으로 한 번만 저장한다.

### `weather_locations`

별첨 XLSX의 행정구역 코드, 1·2·3단계 이름, 대표 위경도와 격자를 저장한다.
행정구역 코드를 기본키로 사용한다. XLSX의 이어도 2개 행은 위경도가
`0, 0`이므로 알 수 없는 좌표로 보고 `NULL`로 정규화한다.

### `weather_forecast_issues`

한 격자의 기상청 발표본이다. `(nx, ny, issued_at)`을 고유 키로 사용한다.
같은 발표본을 다시 수집하면 새 행을 만들지 않고 `updated_at`을 갱신한다.

### `weather_forecasts`

`(forecast_issue_id, forecast_at)`을 기본키로 사용하며 API의 장형 category
응답을 예보시각별 한 행으로 묶는다. 실제 응답은 한 격자에서 871개 category
행이지만 약 72개 예보시각이므로 전국 저장 행 수와 화면 조회 비용을 크게
줄인다. 한 발표본을 재수집할 때 기존 값을 삭제한 뒤 검증이 끝난 전체
스냅샷으로 교체한다.

`fcstValue`는 다음 이유로 `TEXT`에 저장한다.

* `TMP`, `POP`, `REH`처럼 수치인 항목이 있다.
* `SKY`, `PTY`는 코드값이다.
* `PCP`, `SNO`는 수치, `강수없음`, `1mm 미만`, 범위 문자열을 제공할 수 있다.
* 연장 예보기간의 `PCP`, `SNO`, `WSD`는 정량값 대신 정성 코드가 될 수 있다.

저장 category와 컬럼 매핑은 다음과 같다.

| category | 저장 컬럼 |
| --- | --- |
| `POP` | `precipitation_probability` |
| `PTY` | `precipitation_type` |
| `PCP` | `precipitation_amount` |
| `REH` | `humidity` |
| `SNO` | `snowfall_amount` |
| `SKY` | `sky_status` |
| `TMP` | `temperature` |
| `TMN` | `minimum_temperature` |
| `TMX` | `maximum_temperature` |
| `UUU`, `VVV` | `wind_u_component`, `wind_v_component` |
| `WAV` | `wave_height` |
| `VEC`, `WSD` | `wind_direction`, `wind_speed` |

## 저장하지 않는 필드

| 원천 값 | 제외 이유 |
| --- | --- |
| `baseDate`, `baseTime` 원문 | KST `issued_at TIMESTAMPTZ`로 합쳐 저장한다. |
| `fcstDate`, `fcstTime` 원문 | KST `forecast_at TIMESTAMPTZ`로 합쳐 저장한다. |
| item의 `nx`, `ny` 반복값 | 부모 발표본의 격자로 정규화한다. 응답 일치 여부는 저장 전에 확인한다. |
| `pageNo`, `numOfRows`, `totalCount` | 페이지 완결성 검증과 실행 로그에만 사용한다. |
| `resultCode`, `resultMsg` | 호출 성공 판단과 오류 로그에만 사용한다. |
| 원문 응답, 요청 URL | 현재 서비스 조회에 필요 없고 인증키 노출 위험이 있다. |
| XLSX의 도·분·초 좌표 | 십진 위경도와 중복된다. |
| XLSX의 `구분` | 현재 파일의 모든 값이 `kor`이며 가져오기 검증에만 사용한다. |

숫자로 해석되는 `+900` 이상 또는 `-900` 이하 값은 결측으로 제외한다.
`SKY`, `PTY`, `POP`, `REH`, 풍향과 기온·바람 수치는 허용 코드와 범위를
검사한다. 해상 마스킹이나 필수 필드 누락으로 저장하지 못한 item은 격자별
수집 집계에 `skipped_items`로 기록한다.

## TTL 정리

PostgreSQL에는 기본 TTL 기능이 없으므로 수집기 실행 시 애플리케이션이
`issued_at` 기준으로 만료 발표본을 삭제한다. 기본 보관기간은 1일이다.
새 발표본 저장이 성공한 격자는 같은 트랜잭션에서 이전 발표본을 즉시
삭제한다. 새 수집에 실패한 격자는 이전 발표본이 fallback으로 남으며 1일이
지나면 TTL 정리 대상이 된다. `weather_forecast_issues`를 삭제하면 관련
`weather_forecasts`는 `ON DELETE CASCADE`로 함께 삭제된다.

TTL 삭제는 새 발표본 수집 뒤에 실행한다. 전국 수집이 진행되는 동안 기존
fallback을 먼저 지워 화면 데이터에 공백이 생기는 것을 피하기 위해서다.

일일 API 사용량 행은 운영 확인을 위해 30일간 보관한다. TTL 정리는 동일
실행이 반복되어도 안전하다.

## 환경 변수

```text
WEATHER_API_KEY=공공데이터포털에서 발급받은 서비스키
WEATHER_BASE_URL=http://apis.data.go.kr/1360000/VilageFcstInfoService_2.0
WEATHER_LOCATIONS_PATH=weather/기상청41_단기예보 조회서비스_오픈API활용가이드_격자_위경도(2607).xlsx

WEATHER_COLLECTION_HOURS=2,8,14,20
WEATHER_AVAILABILITY_DELAY_MINUTES=10
WEATHER_RETENTION_DAYS=1
WEATHER_DAILY_REQUEST_LIMIT=9500
WEATHER_REQUESTS_PER_SECOND=20
WEATHER_CONCURRENCY=10
WEATHER_NUM_OF_ROWS=1000
WEATHER_HTTP_TIMEOUT=15
WEATHER_MAX_ATTEMPTS=3
WEATHER_RETRY_BASE_DELAY=1
WEATHER_USER_AGENT=SAVER-Collector/1.0
WEATHER_DB_POOL_SIZE=4

POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_USER=saver
POSTGRES_PASSWORD=saver
POSTGRES_DB=saverdb
POSTGRES_CONNECT_TIMEOUT=10
```

`WEATHER_COLLECTION_HOURS`는 공식 발표시각 중 일부만 쉼표로 지정한다.
기본 네 시각을 변경하면 일일 예상 호출량도 함께 계산해야 한다.

## 실행

의존성을 설치한다.

```bash
pip install -r requirements.txt
```

처음에는 스키마와 위치 기준정보만 적용한다. 이 모드는 API 키가 없어도 된다.

```bash
python weather/main.py --apply-schema --locations-only
```

현재 시각에 이용 가능한 최신 선택 발표본을 전국 수집한다.

```bash
python weather/main.py
```

위치 XLSX가 갱신되었으면 동기화 후 같은 실행에서 수집할 수 있다.

```bash
python weather/main.py --sync-locations
```

단일 격자, 위경도 또는 지역명으로 제한해 검증한다.

```bash
python weather/main.py --grid 60 127
python weather/main.py --coordinate 37.5704 126.9816
python weather/main.py --region "서울 종로구"
python weather/main.py --region "충북 청주시"
```

과거 발표본을 재현할 때는 공식 발표시각을 KST로 지정한다.

```bash
python weather/main.py --issue 202607160800 --grid 60 127 --force
```

외부 스케줄러는 발표 지연 여유를 두어 KST `02:15`, `08:15`, `14:15`,
`20:15` 실행을 권장한다. 한 번 실패한 격자를 같은 발표 주기 안에서 다시
시도하려면 각 시각 30~60분 뒤 한 번 더 실행할 수 있지만, 모든 재시도는
일일 DB 요청 예산에 포함된다.

## 서비스 조회 예시

지역명 검색은 행정구역 전체 이름에 공백 단위 토큰을 모두 적용한다.
CLI에서는 `충북`, `충남`, `전북`, `전남`, `경북`, `경남` 약칭을 공식
시도명으로 변환하며 `강원도`, `전라북도`, `제주도`, `세종시`의 이전 또는
축약 명칭도 현재 공식 명칭으로 변환한다.

격자의 최신 발표본 조회 예시는 다음과 같다.

```sql
SELECT issue.issued_at,
       forecast.forecast_at,
       forecast.temperature,
       forecast.sky_status,
       forecast.precipitation_probability,
       forecast.precipitation_type,
       forecast.precipitation_amount,
       forecast.humidity,
       forecast.wind_direction,
       forecast.wind_speed
FROM weather_forecast_issues AS issue
JOIN weather_forecasts AS forecast
  ON forecast.forecast_issue_id = issue.id
WHERE issue.nx = 60
  AND issue.ny = 127
  AND issue.issued_at = (
      SELECT MAX(latest.issued_at)
      FROM weather_forecast_issues AS latest
      WHERE latest.nx = issue.nx
        AND latest.ny = issue.ny
  )
ORDER BY forecast.forecast_at;
```

## 검증

```bash
python -m py_compile weather/*.py
PYTHONPATH=weather python -m unittest discover -s weather/tests -v
psql "$DATABASE_URL" -f weather/table.sql
python weather/main.py --apply-schema --locations-only
python weather/main.py --grid 60 127
```

실제 API 검증은 전국 실행 전에 단일 격자로 수행한다. 네트워크 timeout,
비정상 JSON, 실패 resultCode, 빈 페이지, 다른 격자·발표시각 응답은 해당
격자만 실패 처리하며 다른 격자 작업은 계속한다.
