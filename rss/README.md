# RSS 수집기

`rss/`는 SAVER 서비스에서 사용할 뉴스 RSS 데이터를 PostgreSQL에 저장하는 독립 실행 작업이다. 현재 지원 공급자는 교수신문, 전자신문, Hacker News다.

## 구성

* `main.py`: 명령행 진입점. 원격 RSS 또는 로컬 샘플을 읽어 수집을 실행한다.
* `config.py`: `.env`와 환경 변수에서 DB 접속 정보, 공급자 URL, timeout 값을 읽는다.
* `parser.py`: RSS XML을 feed, item, category 데이터 모델로 정규화한다.
* `repository.py`: `asyncpg`로 PostgreSQL에 스키마를 적용하고 feed/item/category를 upsert한다.
* `table.sql`: RSS 저장 테이블과 인덱스 정의.
* `교수신문.xml`, `전자신문.xml`, `hackernews.rss`: 로컬 검증용 샘플 RSS.

## 환경 변수

루트 `.env` 또는 실행 환경에 다음 값을 설정한다. 값이 없으면 기본값을 사용한다.

```text
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_USER=saver
POSTGRES_PASSWORD=saver
POSTGRES_DB=saverdb
RSS_HTTP_TIMEOUT=10
RSS_USER_AGENT=SAVER-Collector/1.0
```

## 실행

루트에서 의존성을 설치한다.

```bash
pip install -r requirements.txt
```

샘플 RSS로 스키마 적용과 저장을 함께 확인한다.

```bash
python rss/main.py --samples --apply-schema
```

실제 원격 RSS를 수집한다.

```bash
python rss/main.py
```

## 저장 방식

* 채널 메타데이터는 `news_feeds`에 저장한다.
* 기사 항목은 `news_items`에 저장한다.
* 기사 항목의 `title`과 `link`는 필수다. 둘 중 하나라도 비어 있으면 뉴스로 저장하지 않고 제외한다.
* `guid`가 있으면 `(feed_id, guid)`, `guid`가 없으면 `(feed_id, link)` 기준으로 upsert한다.
* 카테고리는 최신 RSS 상태를 기준으로 삭제 후 다시 삽입한다.
* 스키마에 직접 매핑되지 않는 XML 태그와 루트 속성은 `extensions` JSONB에 보존한다.
* 공급자 하나가 실패해도 다음 공급자 수집은 계속 진행한다.

## 검증

```bash
python -m py_compile rss/main.py rss/config.py rss/parser.py rss/repository.py
python rss/main.py --samples
```
