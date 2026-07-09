from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import Any
from xml.etree import ElementTree
from zoneinfo import ZoneInfo


RSS_CORE_TAGS = {
    "author",
    "category",
    "channel",
    "cloud",
    "comments",
    "copyright",
    "description",
    "docs",
    "enclosure",
    "generator",
    "guid",
    "image",
    "item",
    "language",
    "lastBuildDate",
    "link",
    "managingEditor",
    "pubDate",
    "rating",
    "skipDays",
    "skipHours",
    "source",
    "textInput",
    "title",
    "ttl",
    "url",
    "webMaster",
}

KOREA_TIMEZONE = ZoneInfo("Asia/Seoul")


@dataclass(frozen=True)
class Category:
    """RSS category 태그의 이름과 선택적 domain 속성을 표현한다."""

    name: str
    domain: str | None = None


@dataclass(frozen=True)
class ParsedFeed:
    """DB의 news_feeds 행으로 들어갈 채널 메타데이터다."""

    feed_url: str
    publisher: str
    title: str
    link: str
    description: str
    language: str | None = None
    copyright: str | None = None
    managing_editor: str | None = None
    web_master: str | None = None
    pub_date: datetime | None = None
    last_build_date: datetime | None = None
    generator: str | None = None
    docs: str | None = None
    cloud: dict[str, Any] | None = None
    ttl: int | None = None
    image: dict[str, Any] | None = None
    rating: str | None = None
    text_input: dict[str, Any] | None = None
    skip_hours: list[int] = field(default_factory=list)
    skip_days: list[str] = field(default_factory=list)
    categories: list[Category] = field(default_factory=list)
    extensions: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ParsedItem:
    """DB의 news_items 행으로 들어갈 RSS item 데이터다."""

    title: str
    link: str
    description: str | None = None
    author: str | None = None
    comments: str | None = None
    enclosure_url: str | None = None
    enclosure_length: int | None = None
    enclosure_type: str | None = None
    guid: str | None = None
    guid_is_permalink: bool | None = None
    pub_date: datetime | None = None
    source_name: str | None = None
    source_url: str | None = None
    categories: list[Category] = field(default_factory=list)
    extensions: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ParsedRss:
    """파싱된 하나의 RSS 문서와 그 안의 기사 목록이다."""

    feed: ParsedFeed
    items: list[ParsedItem]
    skipped_items: int = 0


def parse_rss(xml_text: str, *, feed_url: str, publisher: str) -> ParsedRss:
    """RSS XML 문자열을 내부 모델로 변환한다."""

    root = ElementTree.fromstring(xml_text)
    channel = _find_child(root, "channel")
    if channel is None:
        raise ValueError("RSS channel 태그를 찾을 수 없습니다.")

    feed = ParsedFeed(
        feed_url=feed_url,
        publisher=publisher,
        title=_required_text(channel, "title"),
        link=_required_text(channel, "link"),
        description=_required_text(channel, "description"),
        language=_text(channel, "language"),
        copyright=_text(channel, "copyright"),
        managing_editor=_text(channel, "managingEditor"),
        web_master=_text(channel, "webMaster"),
        pub_date=parse_datetime(_text(channel, "pubDate")),
        last_build_date=parse_datetime(_text(channel, "lastBuildDate")),
        generator=_text(channel, "generator"),
        docs=_text(channel, "docs"),
        cloud=_element_payload(_find_child(channel, "cloud")),
        ttl=_parse_int(_text(channel, "ttl")),
        image=_element_payload(_find_child(channel, "image")),
        rating=_text(channel, "rating"),
        text_input=_element_payload(_find_child(channel, "textInput")),
        skip_hours=_parse_skip_hours(channel),
        skip_days=_parse_skip_days(channel),
        categories=_parse_categories(channel),
        extensions=_feed_extensions(root, channel),
    )

    items: list[ParsedItem] = []
    skipped_items = 0
    for item in _find_children(channel, "item"):
        parsed_item = _parse_item(item)
        if parsed_item is None:
            skipped_items += 1
            continue
        items.append(parsed_item)

    return ParsedRss(feed=feed, items=items, skipped_items=skipped_items)


def parse_datetime(value: str | None) -> datetime | None:
    """공급자별 날짜 문자열을 timezone-aware datetime으로 변환한다."""

    if not value:
        return None

    value = value.strip()
    try:
        parsed = parsedate_to_datetime(value)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=KOREA_TIMEZONE)
        return parsed
    except (TypeError, ValueError, IndexError):
        pass

    for pattern in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            parsed = datetime.strptime(value, pattern)
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=KOREA_TIMEZONE)
            return parsed
        except ValueError:
            continue

    return None


def _parse_item(item: ElementTree.Element) -> ParsedItem | None:
    """RSS item 태그 하나를 DB 저장용 데이터로 정규화한다."""

    enclosure = _find_child(item, "enclosure")
    guid_node = _find_child(item, "guid")
    source = _find_child(item, "source")
    title = _text(item, "title")
    link = _text(item, "link")

    if not title or not link:
        return None

    return ParsedItem(
        title=title,
        link=link,
        description=_text(item, "description"),
        author=_text(item, "author") or _text(item, "creator"),
        comments=_text(item, "comments"),
        enclosure_url=_attr(enclosure, "url"),
        enclosure_length=_parse_int(_attr(enclosure, "length")),
        enclosure_type=_attr(enclosure, "type"),
        guid=_text(item, "guid"),
        guid_is_permalink=_parse_bool(_attr(guid_node, "isPermaLink")),
        pub_date=parse_datetime(_text(item, "pubDate")),
        source_name=_clean_text(source.text) if source is not None else None,
        source_url=_attr(source, "url"),
        categories=_parse_categories(item),
        extensions=_extensions(item),
    )


def _parse_categories(parent: ElementTree.Element) -> list[Category]:
    """부모 태그 아래의 category 목록을 추출한다."""

    categories: list[Category] = []
    for node in _find_children(parent, "category"):
        name = _clean_text(node.text)
        if name:
            categories.append(Category(name=name, domain=_attr(node, "domain")))
    return categories


def _parse_skip_hours(channel: ElementTree.Element) -> list[int]:
    """skipHours/hour 값을 PostgreSQL SMALLINT 배열에 맞는 정수 목록으로 만든다."""

    skip_hours = _find_child(channel, "skipHours")
    if skip_hours is None:
        return []
    hours: list[int] = []
    for hour in _find_children(skip_hours, "hour"):
        parsed = _parse_int(_clean_text(hour.text))
        if parsed is not None:
            hours.append(parsed)
    return hours


def _parse_skip_days(channel: ElementTree.Element) -> list[str]:
    """skipDays/day 값을 문자열 목록으로 만든다."""

    skip_days = _find_child(channel, "skipDays")
    if skip_days is None:
        return []
    return [day for node in _find_children(skip_days, "day") if (day := _clean_text(node.text))]


def _extensions(parent: ElementTree.Element) -> dict[str, Any]:
    """RSS 기본 필드에 매핑하지 않는 태그와 속성을 extensions로 보존한다."""

    extensions: dict[str, Any] = {}
    for child in parent:
        tag = _local_name(child.tag)
        if tag in RSS_CORE_TAGS:
            continue
        payload = _element_payload(child)
        if payload is not None:
            extensions[tag] = payload
    return extensions


def _feed_extensions(root: ElementTree.Element, channel: ElementTree.Element) -> dict[str, Any]:
    """채널 확장 필드와 RSS 루트 속성을 함께 보존한다."""

    extensions = _extensions(channel)
    if root.attrib:
        extensions["_root_attributes"] = dict(root.attrib)
    return extensions


def _element_payload(node: ElementTree.Element | None) -> dict[str, Any] | None:
    """중첩 태그를 JSONB에 저장 가능한 dict 형태로 변환한다."""

    if node is None:
        return None

    payload: dict[str, Any] = {}
    if node.attrib:
        payload["attributes"] = dict(node.attrib)

    text = _clean_text(node.text)
    if text:
        payload["text"] = text

    children: dict[str, list[Any]] = {}
    for child in node:
        tag = _local_name(child.tag)
        child_payload = _element_payload(child)
        if child_payload is not None:
            children.setdefault(tag, []).append(child_payload)

    if children:
        payload["children"] = children

    return payload or None


def _text(parent: ElementTree.Element, tag: str) -> str | None:
    """자식 태그의 텍스트를 앞뒤 공백 제거 후 반환한다."""

    node = _find_child(parent, tag)
    if node is None:
        return None
    return _clean_text(node.text)


def _find_child(parent: ElementTree.Element, tag: str) -> ElementTree.Element | None:
    """네임스페이스와 무관하게 첫 번째 자식 태그를 찾는다."""

    for child in parent:
        if _local_name(child.tag) == tag:
            return child
    return None


def _find_children(parent: ElementTree.Element, tag: str) -> list[ElementTree.Element]:
    """네임스페이스와 무관하게 같은 이름의 자식 태그 목록을 찾는다."""

    return [child for child in parent if _local_name(child.tag) == tag]


def _required_text(parent: ElementTree.Element, tag: str) -> str:
    """필수 텍스트 필드가 비어 있으면 명확한 예외를 발생시킨다."""

    value = _text(parent, tag)
    if not value:
        raise ValueError(f"RSS channel 필수 태그가 비어 있습니다: {tag}")
    return value


def _clean_text(value: str | None) -> str | None:
    """빈 문자열을 None으로 통일하고 의미 있는 텍스트만 남긴다."""

    if value is None:
        return None
    value = value.strip()
    return value or None


def _attr(node: ElementTree.Element | None, name: str) -> str | None:
    """XML 속성 값을 빈 문자열 정리 후 반환한다."""

    if node is None:
        return None
    return _clean_text(node.attrib.get(name))


def _parse_int(value: str | None) -> int | None:
    """정수 변환에 실패하면 수집 중단 대신 None을 반환한다."""

    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _parse_bool(value: str | None) -> bool | None:
    """RSS guid의 isPermaLink 같은 문자열 boolean 값을 변환한다."""

    if value is None:
        return None
    normalized = value.strip().lower()
    if normalized == "true":
        return True
    if normalized == "false":
        return False
    return None


def _local_name(tag: str) -> str:
    """네임스페이스가 붙은 XML 태그에서 로컬 이름만 분리한다."""

    if "}" in tag:
        return tag.rsplit("}", 1)[1]
    return tag


def as_pretty_json(value: Any) -> str:
    """수동 확인용으로 파싱 결과를 안정적인 JSON 문자열로 직렬화한다."""

    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
