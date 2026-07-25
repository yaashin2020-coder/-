#!/usr/bin/env python3
"""noteの記事シェア用のX投稿スクリプト。

標準ライブラリだけで動く（pip install 不要）。OAuth 1.0a のユーザーコンテキストで
X API v2 の POST /2/tweets を叩く。

使い方:
    python3 scripts/post_to_x.py --count  --text "本文"      # 文字数を測るだけ
    python3 scripts/post_to_x.py --intent --text "本文"      # 投稿リンクを出すだけ
    python3 scripts/post_to_x.py          --text "本文"      # 実際に投稿
    python3 scripts/post_to_x.py --text "1投目" --text "2投目"  # スレッド

必要な環境変数（投稿するときだけ。--count / --intent には不要）:
    X_API_KEY, X_API_SECRET, X_ACCESS_TOKEN, X_ACCESS_TOKEN_SECRET
"""

import argparse
import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

TWEET_ENDPOINT = "https://api.x.com/2/tweets"
INTENT_ENDPOINT = "https://x.com/intent/post"
WEIGHTED_LIMIT = 280
URL_WEIGHT = 23  # t.co短縮後の固定長。URLの実際の長さは関係ない
URL_RE = re.compile(r"https?://\S+")

# twitter-text v3 の重み設定。ここに入る文字は重み1、それ以外（CJK・絵文字など）は重み2。
_LIGHT_RANGES = (
    (0x0000, 0x10FF),
    (0x2000, 0x200A),
    (0x2028, 0x202F),
    (0x2060, 0x206F),
)


def weighted_length(text: str) -> int:
    """Xの数え方で本文の長さを返す。URLは実長に関わらず23としてカウントする。"""
    without_urls = URL_RE.sub("", text)
    total = URL_WEIGHT * len(URL_RE.findall(text))
    for char in without_urls:
        code = ord(char)
        total += 1 if any(lo <= code <= hi for lo, hi in _LIGHT_RANGES) else 2
    return total


def _quote(value: str) -> str:
    return urllib.parse.quote(str(value), safe="~")


def _oauth1_header(method: str, url: str, creds: dict) -> str:
    """JSONボディのリクエスト用に OAuth 1.0a の Authorization ヘッダを組み立てる。

    Content-Type が application/json のときボディは署名ベースに含めない（仕様通り）。
    """
    params = {
        "oauth_consumer_key": creds["api_key"],
        "oauth_nonce": secrets.token_hex(16),
        "oauth_signature_method": "HMAC-SHA1",
        "oauth_timestamp": str(int(time.time())),
        "oauth_token": creds["access_token"],
        "oauth_version": "1.0",
    }
    normalized = "&".join(
        f"{_quote(k)}={_quote(v)}" for k, v in sorted(params.items())
    )
    base = "&".join([method.upper(), _quote(url), _quote(normalized)])
    key = f"{_quote(creds['api_secret'])}&{_quote(creds['access_token_secret'])}"
    digest = hmac.new(key.encode(), base.encode(), hashlib.sha1).digest()
    params["oauth_signature"] = base64.b64encode(digest).decode()

    joined = ", ".join(
        f'{_quote(k)}="{_quote(v)}"' for k, v in sorted(params.items())
    )
    return f"OAuth {joined}"


def load_credentials() -> dict | None:
    """4つの環境変数が揃っていれば返す。1つでも欠けていれば None。"""
    names = {
        "api_key": "X_API_KEY",
        "api_secret": "X_API_SECRET",
        "access_token": "X_ACCESS_TOKEN",
        "access_token_secret": "X_ACCESS_TOKEN_SECRET",
    }
    found = {key: os.environ.get(env, "").strip() for key, env in names.items()}
    missing = [names[k] for k, v in found.items() if not v]
    if missing:
        print(f"未設定の環境変数: {', '.join(missing)}", file=sys.stderr)
        return None
    return found


def intent_url(text: str) -> str:
    """開くと本文入りのX投稿画面になるURL。認証情報もAPIも不要。"""
    return f"{INTENT_ENDPOINT}?{urllib.parse.urlencode({'text': text})}"


def post_tweet(text: str, creds: dict, reply_to: str | None = None) -> dict:
    payload: dict = {"text": text}
    if reply_to:
        payload["reply"] = {"in_reply_to_tweet_id": reply_to}
    body = json.dumps(payload).encode()

    request = urllib.request.Request(
        TWEET_ENDPOINT,
        data=body,
        method="POST",
        headers={
            "Authorization": _oauth1_header("POST", TWEET_ENDPOINT, creds),
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        raise SystemExit(f"X APIがエラーを返した ({exc.code}): {detail}") from exc
    except urllib.error.URLError as exc:
        raise SystemExit(
            f"api.x.com に接続できない: {exc.reason}\n"
            "environmentのネットワーク許可リストに api.x.com が入っているか確認する。"
        ) from exc


def main() -> int:
    parser = argparse.ArgumentParser(description="noteの記事をXへ投稿する")
    parser.add_argument(
        "--text",
        action="append",
        required=True,
        metavar="本文",
        help="投稿本文。複数回渡すとスレッドとして連投する",
    )
    parser.add_argument("--count", action="store_true", help="文字数を測るだけで投稿しない")
    parser.add_argument("--intent", action="store_true", help="投稿リンクを出すだけで投稿しない")
    args = parser.parse_args()

    # 長さは何をするにせよ先に検証する。超過していたら投稿もリンク生成もしない。
    over = False
    for index, text in enumerate(args.text, start=1):
        length = weighted_length(text)
        label = f"{index}投目" if len(args.text) > 1 else "本文"
        status = "OK" if length <= WEIGHTED_LIMIT else "超過"
        print(f"{label}: {length}/{WEIGHTED_LIMIT} ({status})")
        over = over or length > WEIGHTED_LIMIT

    if over:
        print("\n上限を超えているので短くする。", file=sys.stderr)
        return 1
    if args.count:
        return 0

    if args.intent:
        print()
        for index, text in enumerate(args.text, start=1):
            if len(args.text) > 1:
                print(f"[{index}投目] ", end="")
            print(intent_url(text))
        return 0

    creds = load_credentials()
    if creds is None:
        print(
            "\n認証情報が揃っていないので投稿できない。"
            "代わりに --intent でワンタップ投稿リンクを出せる。"
            "\nセットアップ手順: .claude/skills/note-to-x/references/setup.md",
            file=sys.stderr,
        )
        return 1

    previous_id = None
    for index, text in enumerate(args.text, start=1):
        result = post_tweet(text, creds, reply_to=previous_id)
        previous_id = result.get("data", {}).get("id")
        print(f"\n{index}投目を投稿した: https://x.com/i/status/{previous_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
