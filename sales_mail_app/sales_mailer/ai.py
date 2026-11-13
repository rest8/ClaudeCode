"""Claude API を使う機能（任意）.

- personalize_email: テンプレート本文を宛先企業に合わせて個別化する
- research_with_claude: Web 検索で地域×業種の企業を調査する（Google API キーが無い場合の代替）
"""

from __future__ import annotations

import json
import re
import threading
from typing import Callable, Iterable

from .regions import extract_city, extract_prefecture
from .research import Prospect

# 安全性フィルタで断られた場合に、サーバー側で別モデルへ自動で切り替える
FALLBACK_BETA = "server-side-fallback-2026-07-01"


class AIError(Exception):
    pass


def _client(api_key: str):
    try:
        import anthropic
    except ImportError as e:  # pragma: no cover - 依存関係は requirements.txt で導入
        raise AIError("anthropic パッケージがありません。`pip install anthropic` を実行してください") from e
    # api_key が空なら環境変数 ANTHROPIC_API_KEY などから解決される
    return anthropic.Anthropic(api_key=api_key or None, timeout=600.0)


def _create(api_key: str, **kwargs):
    import anthropic

    client = _client(api_key)
    try:
        response = client.beta.messages.create(betas=[FALLBACK_BETA], fallbacks="default", **kwargs)
    except anthropic.AuthenticationError as e:
        raise AIError("Anthropic API キーが無効です（設定タブで確認してください）") from e
    except anthropic.PermissionDeniedError as e:
        raise AIError(f"Anthropic API の権限エラー: {e.message}") from e
    except anthropic.NotFoundError as e:
        raise AIError(f"モデルが見つかりません（設定のモデル名を確認してください）: {e.message}") from e
    except anthropic.RateLimitError as e:
        raise AIError("Anthropic API のレート制限に達しました。しばらく待ってから再実行してください") from e
    except anthropic.BadRequestError as e:
        raise AIError(f"Anthropic API リクエストエラー: {e.message}") from e
    except anthropic.APIStatusError as e:
        raise AIError(f"Anthropic API エラー ({e.status_code}): {e.message}") from e
    except anthropic.APIConnectionError as e:
        raise AIError("Anthropic API に接続できません。ネットワークを確認してください") from e
    if response.stop_reason == "refusal":
        raise AIError("AI がこのリクエストへの回答を控えました。内容を見直してください")
    return response


def _text_of(response) -> str:
    return "".join(b.text for b in response.content if b.type == "text")


# ---------------------------------------------------------------- 個別化
PERSONALIZE_SYSTEM = """あなたは日本のBtoB営業メールの編集者です。
与えられたテンプレートの件名と本文を、宛先企業の情報に合わせて自然に個別化してください。

ルール:
- テンプレートの提案内容・お願い事項・宛名・送信者名は維持する
- 宛先企業について、与えられた情報に書かれていない事実（実績・課題・数字・評判など）を作らない
- 情報が少ない場合は無理に言及せず、テンプレートに近い文面のままにする
- 丁寧で簡潔なビジネス日本語にし、本文の長さはテンプレートと同程度にする
- 署名や配信停止の案内は書かない（システムが自動で付与する）
- 件名は40文字以内"""

PERSONALIZE_SCHEMA = {
    "type": "object",
    "properties": {"subject": {"type": "string"}, "body": {"type": "string"}},
    "required": ["subject", "body"],
    "additionalProperties": False,
}


def personalize_email(api_key: str, model: str, subject: str, body: str, company: dict) -> tuple[str, str]:
    """件名・本文（署名を除く）を個別化して返す."""
    info = {
        "会社名": company.get("name", ""),
        "業種": company.get("industry", ""),
        "所在地": f"{company.get('prefecture', '')}{company.get('city', '')}",
        "Webサイト": company.get("website", ""),
        "企業の説明": company.get("description", ""),
        "メモ": company.get("notes", ""),
    }
    info_text = "\n".join(f"- {k}: {v}" for k, v in info.items() if v)
    prompt = (
        f"<company>\n{info_text}\n</company>\n\n"
        f"<template_subject>\n{subject}\n</template_subject>\n\n"
        f"<template_body>\n{body}\n</template_body>\n\n"
        "上の企業向けに件名と本文を個別化してください。"
    )
    response = _create(
        api_key,
        model=model,
        max_tokens=16000,
        system=PERSONALIZE_SYSTEM,
        output_config={"effort": "medium", "format": {"type": "json_schema", "schema": PERSONALIZE_SCHEMA}},
        messages=[{"role": "user", "content": prompt}],
    )
    try:
        data = json.loads(_text_of(response))
    except json.JSONDecodeError as e:
        raise AIError("AI の応答を読み取れませんでした") from e
    new_subject = str(data.get("subject") or subject).strip()
    new_body = str(data.get("body") or body).strip()
    return new_subject, new_body


# ---------------------------------------------------------------- Web 調査
RESEARCH_SYSTEM = """あなたは日本のBtoB営業リサーチャーです。web_search と web_fetch を使い、
指定された地域・業種に実在する企業を調べます。

ルール:
- 実在が確認できた企業だけを挙げる。推測で企業名・URL・メールアドレスを作らない
- メールアドレスは公式サイト等に公開されている問い合わせ用のものだけを記載し、見つからなければ空文字にする
- 指定地域外の企業、除外リストにある企業は含めない
- 最後に、結果を次の形式のJSON配列だけを ```json コードブロックで出力する:
  [{"name": "会社名", "website": "https://...", "address": "住所", "phone": "電話番号",
    "email": "公開メールアドレスまたは空文字", "industry": "業種", "description": "事業内容の要約（60字以内）"}]"""


def parse_prospects_json(text: str) -> list[dict]:
    """応答テキストから JSON 配列を取り出す."""
    blocks = re.findall(r"```(?:json)?\s*(\[.*?\])\s*```", text, re.S)
    candidates = list(reversed(blocks))
    start, end = text.find("["), text.rfind("]")
    if start != -1 and end > start:
        candidates.append(text[start:end + 1])
    for chunk in candidates:
        try:
            data = json.loads(chunk)
        except json.JSONDecodeError:
            continue
        if isinstance(data, list):
            return [d for d in data if isinstance(d, dict)]
    return []


def research_with_claude(
    api_key: str,
    model: str,
    queries: Iterable[tuple[str, str]],
    count_per_query: int,
    exclude_names: Callable[[str], list[str]],
    progress: Callable[[str], None],
    stop: threading.Event,
) -> list[Prospect]:
    """queries: (「業種 地域」, 想定都道府県) の一覧."""
    found: dict[str, Prospect] = {}
    queries = list(queries)
    for i, (query, pref) in enumerate(queries, 1):
        if stop.is_set():
            break
        progress(f"AI Web調査中 ({i}/{len(queries)}): {query}  ※1件あたり数分かかることがあります")
        keyword, _, area = query.partition(" ")
        excluded = exclude_names(pref)
        excluded_text = "、".join(excluded[:150]) if excluded else "（なし）"
        user = (
            f"地域: {area or pref}\n業種・キーワード: {keyword}\n件数: 最大{count_per_query}社\n"
            f"除外リスト（登録済みの企業）: {excluded_text}"
        )
        messages: list[dict] = [{"role": "user", "content": user}]
        response = None
        for _ in range(5):  # pause_turn の継続は最大5回まで
            response = _create(
                api_key,
                model=model,
                max_tokens=16000,
                system=RESEARCH_SYSTEM,
                output_config={"effort": "medium"},
                tools=[
                    {"type": "web_search_20260209", "name": "web_search", "max_uses": 10,
                     "user_location": {"type": "approximate", "country": "JP", "timezone": "Asia/Tokyo"}},
                    {"type": "web_fetch_20260209", "name": "web_fetch", "max_uses": 15},
                ],
                messages=messages,
            )
            if response.stop_reason != "pause_turn" or stop.is_set():
                break
            messages = [messages[0], {"role": "assistant", "content": response.content}]
        if response is None:
            continue
        for item in parse_prospects_json(_text_of(response)):
            name = str(item.get("name") or "").strip()
            if not name:
                continue
            address = str(item.get("address") or "")
            prefecture = extract_prefecture(address) or pref
            p = Prospect(
                name=name,
                address=address,
                prefecture=prefecture,
                city=extract_city(address, prefecture),
                phone=str(item.get("phone") or ""),
                website=str(item.get("website") or ""),
                email=str(item.get("email") or "").strip(),
                industry=str(item.get("industry") or keyword),
                description=str(item.get("description") or ""),
                source="claude_web",
            )
            found.setdefault(p.website or f"{p.name}|{p.prefecture}", p)
    return list(found.values())
