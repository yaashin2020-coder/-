# セットアップ手順

やりたいことによって必要な準備が違う。**Bだけ済ませれば「投稿した」の一言で
済むようになる**（AはXへの送信まで自動化したい場合のみ）。

| やりたいこと | 必要な準備 |
|---|---|
| 投稿文を作る＋ワンタップリンク | **なし。今すぐ使える**（毎回URLと要点を貼る） |
| 「投稿した」の一言だけで投稿文を作る | **B**（note.com の許可） |
| Xへの送信まで自動 | **A + B** |

**おすすめはBまで。** 手間はほぼ消えて、Xへ送信するかどうかは自分の指で決められる。

## A. Xの認証情報を取る

1. https://developer.x.com/ にログインし、Developer Portal でアプリを作る。
2. アプリの **User authentication settings** を開き、
   **App permissions を「Read and write」に変更**する。
   （デフォルトはRead only。ここを変えずにトークンを発行すると、投稿時に
   403 `oauth1-permissions` エラーになる。**権限を変えたらトークンを作り直す**こと。）
3. **Keys and tokens** タブで4つを控える：
   - API Key → `X_API_KEY`
   - API Key Secret → `X_API_SECRET`
   - Access Token → `X_ACCESS_TOKEN`
   - Access Token Secret → `X_ACCESS_TOKEN_SECRET`

**この4つはリポジトリにコミットしない。** environmentの環境変数（シークレット）
として設定する。Claude Code on the web なら environment 設定の Environment
variables から登録する。

料金：投稿だけなら無料枠（Free）で足りる。書き込みは**月500件**まで。

## B. ネットワークを通す

このenvironmentは既定で外部通信が閉じている（`note.com` も `api.x.com` も
CONNECT に 403 が返る）。environment のネットワークポリシーで、以下の
ホストを許可リストに追加する：

- **`note.com`** … 記事の取得に必要（RSS `https://note.com/<user>/rss` を含む）。
  **これを許可すると「投稿した」の一言だけで済むようになる。**
  URLも要点も貼らなくてよくなるので、効果が一番大きいのはここ。
- `api.x.com` … Xへの送信まで自動化する場合のみ
- `assets.st-note.com` … 記事内の画像を扱う場合のみ

設定場所と各ポリシーの説明：
https://code.claude.com/docs/en/claude-code-on-the-web

許可が入ったか確かめる：

```bash
python3 scripts/fetch_note_latest.py --user long_whale5827
```

最新記事のJSONが出れば通っている。`Tunnel connection failed: 403` と出るなら
まだ塞がっている。

## C. 動作確認

```bash
# 1. 文字数カウント（ネットワーク不要）
python3 scripts/post_to_x.py --count --text "テスト投稿 https://note.com/example/n/xxxx"

# 2. 認証情報が読めているか（投稿はしない）
python3 -c "import scripts.post_to_x as m; print(bool(m.load_credentials()))"

# 3. 本番投稿
python3 scripts/post_to_x.py --text "テスト投稿 https://note.com/example/n/xxxx"
```

## 定期実行にする場合

「noteを投稿したよ」と毎回言う代わりに、RSSを定期チェックして新着だけ投稿する
運用もできる。その場合は Routine（スケジュール実行）を作り、前回処理した記事の
URLを `.claude/skills/note-to-x/references/state.json` などに記録して重複投稿を防ぐ。
ただし**無人で投稿することになる**ので、始める前にユーザーの明示的な合意を取る。
