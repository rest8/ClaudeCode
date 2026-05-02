"""CLI サブコマンド: 店舗一覧取得・配信先管理。"""
from __future__ import annotations

import argparse
import logging
import sys

from .config import AppConfig
from .restaurants import RestaurantDirectory
from .subscribers import Subscriber, SubscriberStore

LOGGER = logging.getLogger(__name__)


def cmd_discover(config: AppConfig, args: argparse.Namespace) -> int:
    directory = RestaurantDirectory(config.restaurants_file)
    urls = args.url or config.discover_index_urls
    print(f"店舗一覧を取得します: {urls}")
    added = directory.discover(urls, cookies=config.cookies, user_agent=config.user_agent)
    print(f"取得完了: 全{len(directory.all())}件 (新規 {added}件)")
    print(f"キャッシュ: {config.restaurants_file}")
    if directory.is_empty():
        print(
            "店舗が抽出できませんでした。ログイン Cookie が必要な場合は config.yaml の "
            "cookies を設定するか、--url で別のインデックスURLを指定してください。"
        )
        return 1
    return 0


def cmd_restaurants(config: AppConfig, args: argparse.Namespace) -> int:
    directory = RestaurantDirectory(config.restaurants_file)
    items = directory.search(args.search) if args.search else directory.all()
    if not items:
        print(
            "店舗キャッシュが空です。先に `discover` を実行してください: "
            "python -m omakase_notifier discover"
        )
        return 1
    width = max(len(r.id) for r in items)
    for r in items[: args.limit] if args.limit else items:
        area = f"  [{r.area}]" if r.area else ""
        print(f"  {r.id:<{width}}  {r.name}{area}")
    print(f"\n計 {len(items)} 件 (全 {len(directory.all())} 件中)")
    return 0


def cmd_subscribers(config: AppConfig, _args: argparse.Namespace) -> int:
    store = SubscriberStore(config.subscribers_file)
    directory = RestaurantDirectory(config.restaurants_file)
    subs = store.all()
    if not subs:
        print("配信先がまだ登録されていません。`add-subscriber` で追加してください。")
        return 0
    for s in subs:
        label = f" ({s.label})" if s.label else ""
        print(f"[{s.id}]{label}  {s.channel} -> {s.destination}")
        if not s.subscriptions:
            print("    監視店舗: (なし)")
            continue
        print("    監視店舗:")
        for sub in s.subscriptions:
            r = directory.get(sub.restaurant_id)
            name = r.name if r else "(店舗情報なし)"
            cond_parts = []
            if sub.dates:
                cond_parts.append("日付=" + ",".join(sub.dates))
            if sub.times:
                cond_parts.append("時間=" + ",".join(sub.times))
            if sub.party_size:
                cond_parts.append(f"人数>={sub.party_size}")
            cond = "  [" + ", ".join(cond_parts) + "]" if cond_parts else ""
            print(f"      - {sub.restaurant_id}  {name}{cond}")
    return 0


def cmd_add_subscriber(config: AppConfig, args: argparse.Namespace) -> int:
    store = SubscriberStore(config.subscribers_file)
    try:
        sub = Subscriber(
            id=args.id,
            channel=args.channel,
            destination=args.to,
            label=args.label or "",
        )
        store.add(sub)
    except ValueError as e:
        print(f"エラー: {e}", file=sys.stderr)
        return 2
    print(f"追加しました: {sub.id} ({sub.channel} -> {sub.destination})")
    print(f"次は店舗を購読してください: subscribe {sub.id} <restaurant_id>")
    return 0


def cmd_remove_subscriber(config: AppConfig, args: argparse.Namespace) -> int:
    store = SubscriberStore(config.subscribers_file)
    if store.remove(args.id):
        print(f"削除しました: {args.id}")
        return 0
    print(f"見つかりません: {args.id}", file=sys.stderr)
    return 1


def cmd_subscribe(config: AppConfig, args: argparse.Namespace) -> int:
    store = SubscriberStore(config.subscribers_file)
    directory = RestaurantDirectory(config.restaurants_file)
    if directory.get(args.restaurant_id) is None:
        print(
            f"警告: 店舗ID '{args.restaurant_id}' は店舗キャッシュに存在しません。"
            " `discover` または `restaurants --search` で確認してください。",
            file=sys.stderr,
        )
    try:
        sub = store.subscribe(
            args.subscriber,
            args.restaurant_id,
            dates=args.date or [],
            times=args.time or [],
            party_size=args.party_size,
        )
    except (KeyError, ValueError) as e:
        print(f"エラー: {e}", file=sys.stderr)
        return 2
    print(
        f"購読登録: {args.subscriber} -> {sub.restaurant_id} "
        f"(dates={sub.dates}, times={sub.times}, party_size={sub.party_size})"
    )
    return 0


def cmd_unsubscribe(config: AppConfig, args: argparse.Namespace) -> int:
    store = SubscriberStore(config.subscribers_file)
    try:
        ok = store.unsubscribe(args.subscriber, args.restaurant_id)
    except KeyError as e:
        print(f"エラー: {e}", file=sys.stderr)
        return 2
    if ok:
        print(f"購読解除: {args.subscriber} -> {args.restaurant_id}")
        return 0
    print(f"該当する購読が見つかりません: {args.subscriber} / {args.restaurant_id}")
    return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="omakase_notifier", description="Omakase 空席通知")
    parser.add_argument("--config", default="config.yaml", help="設定ファイル (YAML)")

    sub = parser.add_subparsers(dest="command")

    p_run = sub.add_parser("run", help="監視を開始 (既定動作)")
    p_run.add_argument("--once", action="store_true", help="1回だけチェックして終了")
    p_run.add_argument("--no-tray", action="store_true", help="トレイを無効化")

    # 後方互換: --once / --no-tray をトップレベルでも受け付ける
    parser.add_argument("--once", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--no-tray", action="store_true", help=argparse.SUPPRESS)

    p_disc = sub.add_parser("discover", help="店舗一覧をクロールしてキャッシュ")
    p_disc.add_argument("--url", action="append", help="インデックスURL (複数指定可)")

    p_rest = sub.add_parser("restaurants", help="キャッシュ済み店舗の一覧/検索")
    p_rest.add_argument("--search", help="部分一致検索 (店名/エリア/ID)")
    p_rest.add_argument("--limit", type=int, default=0, help="最大表示件数 (0=制限なし)")

    sub.add_parser("subscribers", help="配信先一覧を表示")

    p_add = sub.add_parser("add-subscriber", help="配信先を追加")
    p_add.add_argument("--id", required=True, help="識別子 (英数字/_/-)")
    p_add.add_argument(
        "--channel", required=True, choices=("email", "line", "webhook"), help="通知方式"
    )
    p_add.add_argument("--to", required=True, help="宛先 (メールアドレス/LINE userId/Webhook URL)")
    p_add.add_argument("--label", help="表示名")

    p_rm = sub.add_parser("remove-subscriber", help="配信先を削除")
    p_rm.add_argument("--id", required=True)

    p_sub = sub.add_parser("subscribe", help="店舗を購読")
    p_sub.add_argument("subscriber", help="配信先ID")
    p_sub.add_argument("restaurant_id", help="店舗ID")
    p_sub.add_argument("--date", action="append", help="監視日 YYYY-MM-DD (複数指定可)")
    p_sub.add_argument("--time", action="append", help="監視時刻 HH:MM (複数指定可)")
    p_sub.add_argument("--party-size", type=int, help="必要な人数")

    p_unsub = sub.add_parser("unsubscribe", help="店舗購読を解除")
    p_unsub.add_argument("subscriber")
    p_unsub.add_argument("restaurant_id")

    return parser


COMMANDS = {
    "discover": cmd_discover,
    "restaurants": cmd_restaurants,
    "subscribers": cmd_subscribers,
    "add-subscriber": cmd_add_subscriber,
    "remove-subscriber": cmd_remove_subscriber,
    "subscribe": cmd_subscribe,
    "unsubscribe": cmd_unsubscribe,
}
