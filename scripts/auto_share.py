#!/usr/bin/env python3
"""noteの新着記事を検出してXへ自動投稿する。GitHub Actionsから定期実行される。

人が介在しないので、安全側に倒した作りにしてある。

- 投稿済みの記事は state ファイルで管理し、二重投稿しない
- 初回実行では既存記事を一気に投稿しない（過去記事が全部流れる事故を防ぐ）
- 投稿文はRSSの実データ（タイトル・URL）から組み立てる。文章を creative に
  生成しないので、記事にないことを書く余地がない
- DRY_RUN=1 なら投稿せず内容だけ出力する

使い方:
    python3 scripts/auto_share.py --user long_whale5827 --state .note-to-x-state.json
    DRY_RUN=1 python3 scripts/auto_share.py --user ... --state ...   # 試運転
"""

import argparse
import datetime
import json
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from fetch_note_latest import fetch_rss, parse_items  # noqa: E402
from post_to_x import (  # noqa: E402
    WEIGHTED_LIMIT,
    intent_url,
    load_credentials,
    post_tweet,
    weighted_length,
)

# 1回の実行で投稿する上限。RSSが一時的に壊れて大量の「新着」に見えたときの保険。
MAX_POSTS_PER_RUN = 2
# これより古い記事は、未投稿でも新着とみなさない（初回実行時の過去記事流出を防ぐ）
MAX_AGE = datetime.timedelta(days=2)
DEFAULT_TEMPLATE = "{title}\n\n{url}\n\n#note"


def load_state(path: pathlib.Path) -> dict:
    if not path.exists():
        return {"posted_urls": [], "initialized": False}
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        # 壊れた state で全記事を再投稿するのが最悪なので、ここは落とす
        raise SystemExit(f"stateファイルが壊れている: {path}")
    state.setdefault("posted_urls", [])
    state.setdefault("initialized", False)
    return state


def save_state(path: pathlib.Path, state: dict) -> None:
    path.write_text(
        json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def is_fresh(item: dict) -> bool:
    if not item.get("published"):
        return False
    published = datetime.datetime.fromisoformat(item["published"])
    return datetime.datetime.now(datetime.timezone.utc) - published <= MAX_AGE


def build_text(item: dict, template: str) -> str:
    text = template.format(title=item["title"], url=item["url"])
    if weighted_length(text) <= WEIGHTED_LIMIT:
        return text

    # タイトルが長すぎる場合だけ、末尾を1文字ずつ落として収める。URLは削らない
    # （削ると記事に飛べなくなる）。省略記号自身の幅も数える必要があるので、
    # 引き算で見積もらず、実際に組み立てて測り直す。
    title = item["title"]
    while title:
        title = title[:-1]
        text = template.format(title=title.rstrip() + "…", url=item["url"])
        if weighted_length(text) <= WEIGHTED_LIMIT:
            return text
    raise SystemExit(f"URLだけで上限を超える。テンプレートを見直す: {item['url']}")


def main() -> int:
    parser = argparse.ArgumentParser(description="noteの新着をXへ自動投稿する")
    parser.add_argument("--user", required=True, help="noteのユーザー名")
    parser.add_argument("--state", required=True, help="投稿済みURLを記録するJSONファイル")
    parser.add_argument("--file", help="RSSをファイルから読む（テスト用）")
    parser.add_argument("--template", default=DEFAULT_TEMPLATE, help="投稿文のテンプレート")
    args = parser.parse_args()

    dry_run = os.environ.get("DRY_RUN", "").strip() not in ("", "0", "false")
    state_path = pathlib.Path(args.state)
    state = load_state(state_path)

    xml_text = (
        pathlib.Path(args.file).read_text(encoding="utf-8")
        if args.file
        else fetch_rss(args.user)
    )
    items = parse_items(xml_text, limit=10)

    if not state["initialized"]:
        # 初回は「今ある記事はすべて投稿済み」として記録するだけで終わる。
        # ここで投稿してしまうと過去記事がまとめてXに流れる。
        state["posted_urls"] = [item["url"] for item in items]
        state["initialized"] = True
        save_state(state_path, state)
        print(f"初期化した。既存{len(items)}件を投稿済みとして記録。今回は投稿しない。")
        return 0

    already = set(state["posted_urls"])
    new_items = [i for i in items if i["url"] not in already and is_fresh(i)]
    new_items.reverse()  # 古い順に投稿する

    if not new_items:
        print("新着なし。")
        return 0

    if len(new_items) > MAX_POSTS_PER_RUN:
        print(
            f"新着が{len(new_items)}件あるが、1回の実行では{MAX_POSTS_PER_RUN}件までにする。",
            file=sys.stderr,
        )
        new_items = new_items[:MAX_POSTS_PER_RUN]

    creds = None if dry_run else load_credentials()
    if not dry_run and creds is None:
        raise SystemExit("Xの認証情報が設定されていない。GitHub Secretsを確認する。")

    for item in new_items:
        text = build_text(item, args.template)
        print(f"\n--- {item['title']}\n{text}\n({weighted_length(text)}/{WEIGHTED_LIMIT}文字)")
        if dry_run:
            print(f"[DRY_RUN] 投稿しない。手動投稿リンク: {intent_url(text)}")
            continue
        result = post_tweet(text, creds)
        tweet_id = result.get("data", {}).get("id")
        print(f"投稿した: https://x.com/i/status/{tweet_id}")
        # 1件ごとに保存する。途中で落ちても、投稿済みの記事を再投稿しないため。
        state["posted_urls"].append(item["url"])
        save_state(state_path, state)

    if dry_run:
        print("\n[DRY_RUN] stateは更新していない。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
