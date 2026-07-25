#!/usr/bin/env python3
"""noteのRSSから最新記事を取ってくる。

標準ライブラリだけで動く。RSSには記事のタイトル・URL・公開日時・本文が
すべて入っているので、これが取れればユーザーは何も貼らなくてよくなる。

使い方:
    python3 scripts/fetch_note_latest.py --user long_whale5827
    python3 scripts/fetch_note_latest.py --user long_whale5827 --count 3
    python3 scripts/fetch_note_latest.py --file tests/fixtures/note_rss.xml  # 検証用

出力はJSON。title / url / published / body を含む。
"""

import argparse
import datetime
import email.utils
import html
import html.parser
import json
import re
import sys
import urllib.error
import urllib.request

CONTENT_NS = "{http://purl.org/rss/1.0/modules/content/}encoded"
# 公開直後はRSSの生成が追いつかないことがある。これより古い記事しか無い場合は警告する。
STALE_AFTER = datetime.timedelta(hours=6)


class _TextExtractor(html.parser.HTMLParser):
    """本文HTMLから読めるテキストだけを取り出す。"""

    _SKIP = {"script", "style"}
    _BREAK = {"p", "br", "div", "h1", "h2", "h3", "h4", "li", "blockquote"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._skipping = 0

    def handle_starttag(self, tag, attrs):
        if tag in self._SKIP:
            self._skipping += 1
        elif tag in self._BREAK:
            self._parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self._SKIP and self._skipping:
            self._skipping -= 1
        elif tag in self._BREAK:
            self._parts.append("\n")

    def handle_data(self, data):
        if not self._skipping:
            self._parts.append(data)

    def text(self) -> str:
        joined = "".join(self._parts)
        # &nbsp; 由来のU+00A0は見た目が空白なのに別文字。投稿文に紛れ込むと
        # 文字数計算がずれ、コピペ先で表示が崩れるので普通の空白にする。
        joined = joined.replace(" ", " ")
        # 半角の空白・タブの連続だけ潰す。全角スペースは原文の表現なので残す。
        joined = re.sub(r"[ \t]+", " ", joined)
        joined = re.sub(r"\n[ \t]*", "\n", joined)
        joined = re.sub(r"\n{3,}", "\n\n", joined)
        return joined.strip()


def html_to_text(markup: str) -> str:
    parser = _TextExtractor()
    parser.feed(markup or "")
    parser.close()
    return parser.text()


def fetch_rss(username: str) -> str:
    url = f"https://note.com/{username}/rss"
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "note-to-x/1.0 (+personal article sharing)"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        raise SystemExit(f"RSSの取得に失敗した ({exc.code}): {url}") from exc
    except urllib.error.URLError as exc:
        raise SystemExit(
            f"note.com に接続できない: {exc.reason}\n"
            "environmentのネットワーク許可リストに note.com を追加する必要がある。"
            "手順: .claude/skills/note-to-x/references/setup.md"
        ) from exc


def parse_items(xml_text: str, limit: int) -> list[dict]:
    # ElementTreeはXML宣言前のBOM等で転ぶことがあるので先頭を落としておく
    import xml.etree.ElementTree as ET

    try:
        root = ET.fromstring(xml_text.lstrip("﻿ \n\r\t"))
    except ET.ParseError as exc:
        raise SystemExit(f"RSSをXMLとして解釈できない: {exc}") from exc

    items = []
    for item in root.iterfind(".//item"):
        published_raw = (item.findtext("pubDate") or "").strip()
        published = None
        if published_raw:
            try:
                published = email.utils.parsedate_to_datetime(published_raw)
            except (TypeError, ValueError):
                published = None

        body_html = item.findtext(CONTENT_NS) or item.findtext("description") or ""
        items.append(
            {
                "title": html.unescape((item.findtext("title") or "").strip()),
                "url": (item.findtext("link") or "").strip(),
                "published": published.isoformat() if published else None,
                "published_raw": published_raw,
                "body": html_to_text(body_html),
            }
        )
        if len(items) >= limit:
            break

    if not items:
        raise SystemExit("RSSに記事が1件も入っていない。ユーザー名が正しいか確認する。")
    return items


def staleness_warning(item: dict) -> str | None:
    """最新記事が古すぎる場合の警告。取り違え防止のため呼び出し側で必ず見せる。"""
    if not item.get("published"):
        return "公開日時が読めなかった。記事が本当に最新か確認すること。"
    published = datetime.datetime.fromisoformat(item["published"])
    now = datetime.datetime.now(datetime.timezone.utc)
    age = now - published
    if age > STALE_AFTER:
        hours = int(age.total_seconds() // 3600)
        return (
            f"最新記事の公開が{hours}時間前。RSSの反映が遅れているか、"
            "今回公開した記事がまだ載っていない可能性がある。"
            "タイトルがユーザーの意図した記事か必ず確認すること。"
        )
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="noteの最新記事をRSSから取得する")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--user", help="noteのユーザー名（note.com/<ここ>）")
    source.add_argument("--file", help="ローカルのRSSファイル（ネットワーク不要、検証用）")
    parser.add_argument("--count", type=int, default=1, help="取得する記事数（既定1）")
    args = parser.parse_args()

    if args.file:
        with open(args.file, encoding="utf-8") as handle:
            xml_text = handle.read()
    else:
        xml_text = fetch_rss(args.user)

    items = parse_items(xml_text, args.count)
    warning = staleness_warning(items[0])
    output = {"items": items}
    if warning:
        output["warning"] = warning

    json.dump(output, sys.stdout, ensure_ascii=False, indent=2)
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
