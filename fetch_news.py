#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A股资讯聚合站点 - 抓取脚本

只依赖 Python 标准库，可直接在本地或 GitHub Actions 中运行。
抓取结果写入 data/archive.json（历史库），并生成站点使用的
data/news.json 与 data/news.js（后者用于 file:// 直接打开）。

说明：所有内容源均为免费公开接口，无需 API Key。
东财系接口有频率限制，脚本内做了串行限流（>=1.2s）与单次重试。
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import time
import uuid
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
CONFIG_PATH = ROOT / "config.json"
ARCHIVE_PATH = DATA_DIR / "archive.json"
NEWS_JSON = DATA_DIR / "news.json"
NEWS_JS = DATA_DIR / "news.js"

BJ = timezone(timedelta(hours=8))
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

DEFAULT_CONFIG = {
    "watchlist": [
        {"code": "600519", "name": "贵州茅台"},
        {"code": "300750", "name": "宁德时代"},
        {"code": "002594", "name": "比亚迪"},
        {"code": "688981", "name": "中芯国际"},
        {"code": "300059", "name": "东方财富"},
    ],
    "keep_days": 7,
    "max_output_items": 1500,
    "flash_page_size": 60,
    "market_page_size": 40,
    "announcement_page_size": 60,
    "report_page_size": 60,
    "stock_news_page_size": 12,
}

CATEGORIES = {
    "flash": "快讯",
    "market": "市场",
    "stock": "个股",
    "ann": "公告",
    "report": "研报",
}


# ---------------------------------------------------------------- 基础工具

def now_bj() -> datetime:
    return datetime.now(BJ)


def load_config() -> dict:
    cfg = dict(DEFAULT_CONFIG)
    if CONFIG_PATH.exists():
        try:
            raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                cfg.update(raw)
        except Exception as exc:  # 配置损坏时使用默认值
            log(f"[WARN] config.json 解析失败，使用默认配置: {exc}")
    return cfg


def log(msg: str) -> None:
    print(f"{now_bj().strftime('%H:%M:%S')} {msg}", flush=True)


_last_em_call = [0.0]


def http_get(url: str, headers: dict | None = None, timeout: int = 20, retries: int = 1,
             eastmoney: bool = False) -> bytes:
    """带 UA、可选东财限流与一次重试的 GET。"""
    if eastmoney:
        wait = 1.2 - (time.time() - _last_em_call[0])
        if wait > 0:
            time.sleep(wait + 0.15)
        _last_em_call[0] = time.time()

    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": UA, "Accept": "*/*", **(headers or {})},
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if attempt < retries:
                time.sleep(1.5)
    raise last_error  # type: ignore[misc]


def get_json(url: str, headers: dict | None = None, timeout: int = 20,
             eastmoney: bool = False) -> dict:
    return json.loads(http_get(url, headers, timeout, eastmoney=eastmoney).decode("utf-8"))


def get_jsonp(url: str, headers: dict | None = None, timeout: int = 20) -> dict:
    text = http_get(url, headers, timeout, eastmoney=True).decode("utf-8", "replace")
    start, end = text.find("("), text.rfind(")")
    if start < 0 or end <= start:
        raise ValueError("无效的 JSONP 响应")
    return json.loads(text[start + 1:end])


def parse_cn_time(text: str) -> datetime | None:
    """解析 '2026-11-26 15:37:34' / '2026-11-26 15:38:56:274' / 秒或毫秒时间戳。"""
    if text is None:
        return None
    if isinstance(text, (int, float)):
        stamp = float(text)
        return datetime.fromtimestamp(stamp / 1000 if stamp > 1e11 else stamp, BJ)
    value = str(text).strip()
    if not value:
        return None
    if re.fullmatch(r"\d{10}|\d{13}", value):
        stamp = int(value)
        return datetime.fromtimestamp(stamp / 1000 if len(value) == 13 else stamp, BJ)
    value = value[:19]
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=BJ)
        except ValueError:
            continue
    return None


def iso(dt: datetime | None) -> str:
    if dt is None:
        return ""
    return dt.astimezone(BJ).isoformat(timespec="seconds")


def clean_text(text: str, limit: int = 0) -> str:
    value = re.sub(r"<[^>]+>", "", str(text or ""))
    value = value.replace("\u3000", " ").replace("\xa0", " ")
    value = re.sub(r"\s+", " ", value).strip()
    if limit and len(value) > limit:
        value = value[:limit].rstrip() + "…"
    return value


def make_item(cat: str, title: str, url: str, dt: datetime | None, source: str,
              summary: str = "", stock: dict | None = None, tag: str = "") -> dict | None:
    title = clean_text(title, 160)
    if not title or not url:
        return None
    summary = clean_text(summary, 260)
    if summary.startswith(title):
        summary = summary[len(title):].lstrip(" ：:，,。;；-—")
    summary = clean_text(summary, 220)
    norm = re.sub(r"[\s\u3000【】\[\]（）()：:，,。.!！?？\"'“”‘’·|—-]+", "", title)
    digest = hashlib.sha1(f"{cat}|{norm}".encode("utf-8")).hexdigest()[:16]
    return {
        "id": digest,
        "cat": cat,
        "title": title,
        "summary": summary,
        "time": iso(dt),
        "source": source,
        "url": url,
        "stock": stock or None,
        "tag": clean_text(tag, 20),
    }


# ---------------------------------------------------------------- 各内容源

def fetch_eastmoney_flash(page_size: int) -> list[dict]:
    """东财 7×24 全球财经快讯。"""
    params = {
        "client": "web", "biz": "web_724", "fastColumn": "102",
        "sortEnd": "", "pageSize": str(page_size), "req_trace": str(uuid.uuid4()),
    }
    url = "https://np-weblist.eastmoney.com/comm/web/getFastNewsList?" + urllib.parse.urlencode(params)
    data = get_json(url, {"Referer": "https://kuaixun.eastmoney.com/"}, eastmoney=True)
    items = []
    for row in data.get("data", {}).get("fastNewsList", []) or []:
        title = row.get("title") or ""
        summary = row.get("summary") or ""
        prefix = f"【{title}】"
        if summary.startswith(prefix):
            summary = summary[len(prefix):].strip()
        code = row.get("code", "")
        item = make_item(
            "flash", title,
            f"https://finance.eastmoney.com/a/{code}.html" if code else "https://kuaixun.eastmoney.com/",
            parse_cn_time(row.get("showTime")), "东方财富", summary,
        )
        if item:
            items.append(item)
    return items


def fetch_sina_flash(page_size: int) -> list[dict]:
    """新浪财经 7×24 快讯。"""
    url = ("https://zhibo.sina.com.cn/api/zhibo/feed?"
           f"page=1&page_size={page_size}&zhibo_id=152&tag_id=0&dire=f&dpc=1")
    data = get_json(url, {"Referer": "https://finance.sina.com.cn/7x24/"})
    rows = data.get("result", {}).get("data", {}).get("feed", {}).get("list", []) or []
    items = []
    for row in rows:
        text = clean_text(row.get("rich_text", ""))
        if not text:
            continue
        match = re.match(r"^【([^】]{2,80})】\s*(.*)$", text, re.S)
        if match:
            title, summary = match.group(1), match.group(2)
        else:
            title, summary = text[:56], text
        try:
            docurl = json.loads(row.get("ext") or "{}").get("docurl", "")
        except Exception:
            docurl = ""
        item = make_item(
            "flash", title,
            docurl or "https://finance.sina.com.cn/7x24/",
            parse_cn_time(row.get("create_time")), "新浪财经", summary,
        )
        if item:
            items.append(item)
    return items


def fetch_sina_market(page_size: int) -> list[dict]:
    """新浪财经滚动新闻（2516 财经 + 2517 股市）。"""
    items: list[dict] = []
    seen_urls: set[str] = set()
    for lid in ("2517", "2516"):
        url = ("https://feed.mix.sina.com.cn/api/roll/get?"
               f"pageid=153&lid={lid}&k=&num={page_size}&page=1")
        data = get_json(url, {"Referer": "https://finance.sina.com.cn/"})
        rows = data.get("result", {}).get("data", []) or []
        for row in rows:
            link = row.get("url") or ""
            if not link or link in seen_urls:
                continue
            seen_urls.add(link)
            item = make_item(
                "market", row.get("title", ""), link,
                parse_cn_time(row.get("ctime")), row.get("media_name") or "新浪财经",
                row.get("intro") or row.get("summary") or "",
            )
            if item:
                items.append(item)
    return items


def fetch_stock_news(watchlist: list[dict], page_size: int) -> list[dict]:
    """东财个股新闻（按自选股列表）。"""
    items: list[dict] = []
    for stock in watchlist[:10]:
        code = str(stock.get("code", "")).strip()
        name = str(stock.get("name", "")).strip()
        if not re.fullmatch(r"\d{6}", code):
            continue
        inner = json.dumps({
            "uid": "", "keyword": code, "type": ["cmsArticleWebOld"],
            "client": "web", "clientType": "web", "clientVersion": "curr",
            "param": {"cmsArticleWebOld": {
                "searchScope": "default", "sort": "default", "pageIndex": 1,
                "pageSize": page_size, "preTag": "", "postTag": "",
            }},
        }, separators=(",", ":"))
        url = ("https://search-api-web.eastmoney.com/search/jsonp?cb=jQuery_news&param="
               + urllib.parse.quote(inner))
        data = get_jsonp(url, {"Referer": "https://so.eastmoney.com/"})
        rows = data.get("result", {}).get("cmsArticleWebOld", []) or []
        for row in rows:
            link = (row.get("url") or "").replace("http://", "https://")
            item = make_item(
                "stock", row.get("title", ""), link,
                parse_cn_time(row.get("date")), row.get("mediaName") or "东方财富",
                row.get("content") or "", {"code": code, "name": name},
            )
            if item:
                items.append(item)
    return items


def fetch_announcements(page_size: int) -> list[dict]:
    """东财全市场沪深公告（A 股）。"""
    url = ("https://np-anotice-stock.eastmoney.com/api/security/ann?"
           f"sr=-1&page_size={page_size}&page_index=1&ann_type=A&client_source=web&f_node=0&s_node=0")
    data = get_json(url, {"Referer": "https://data.eastmoney.com/"}, eastmoney=True)
    rows = data.get("data", {}).get("list", []) or []
    items = []
    for row in rows:
        codes = row.get("codes") or []
        stock = None
        if codes:
            stock = {
                "code": codes[0].get("stock_code", ""),
                "name": codes[0].get("short_name", ""),
            }
        columns = row.get("columns") or []
        tag = columns[0].get("column_name", "") if columns else ""
        stock_code = (stock or {}).get("code", "")
        art_code = row.get("art_code", "")
        link = (f"https://data.eastmoney.com/notices/detail/{stock_code}/{art_code}.html"
                if stock_code and art_code else "https://data.eastmoney.com/notices/")
        item = make_item(
            "ann", row.get("title") or row.get("title_ch", ""), link,
            parse_cn_time(row.get("display_time") or row.get("notice_date")),
            "东方财富·公告", "", stock, tag,
        )
        if item:
            items.append(item)
    return items


def fetch_reports(page_size: int) -> list[dict]:
    """东财研报列表（全市场最新研报）。"""
    today = now_bj()
    params = {
        "industryCode": "*", "pageSize": str(page_size), "industry": "*",
        "rating": "*", "ratingChange": "*",
        "beginTime": (today - timedelta(days=4)).strftime("%Y-%m-%d"),
        "endTime": (today + timedelta(days=1)).strftime("%Y-%m-%d"),
        "pageNo": "1", "fields": "", "qType": "0", "orgCode": "", "code": "",
        "rcode": "", "p": "1", "pageNum": "1", "pageNumber": "1",
    }
    url = "https://reportapi.eastmoney.com/report/list?" + urllib.parse.urlencode(params)
    data = get_json(url, {"Referer": "https://data.eastmoney.com/"}, eastmoney=True)
    rows = data.get("data") or []
    items = []
    for row in rows:
        info_code = row.get("infoCode", "")
        if not info_code:
            continue
        stock = None
        if row.get("stockCode"):
            stock = {"code": str(row.get("stockCode")), "name": row.get("stockName") or ""}
        parts = [row.get("orgSName") or row.get("orgName") or "", row.get("emRatingName") or "",
                 row.get("indvInduName") or ""]
        summary = " · ".join(p for p in parts if p)
        item = make_item(
            "report", row.get("title", ""),
            f"https://data.eastmoney.com/report/info/{info_code}.html",
            parse_cn_time(row.get("publishDate")), "东方财富·研报",
            summary, stock, row.get("emRatingName") or "",
        )
        if item:
            items.append(item)
    return items


# ---------------------------------------------------------------- 汇总与输出

def merge_archive(existing: list[dict], incoming: list[dict], keep_days: int,
                  max_items: int) -> tuple[list[dict], int]:
    merged = {item["id"]: item for item in existing if item.get("id")}
    new_count = 0
    for item in incoming:
        if item["id"] not in merged:
            new_count += 1
        merged[item["id"]] = item
    cutoff = now_bj() - timedelta(days=keep_days)
    kept = []
    for item in merged.values():
        dt = parse_cn_time(item.get("time", ""))
        if dt is None or dt >= cutoff:
            kept.append(item)
    kept.sort(key=lambda x: x.get("time", ""), reverse=True)
    if max_items and len(kept) > max_items:
        kept = kept[:max_items]
    return kept, new_count


def write_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)


def main() -> int:
    cfg = load_config()
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    started = now_bj()

    sources = [
        ("东方财富 7×24", "flash", lambda: fetch_eastmoney_flash(int(cfg["flash_page_size"]))),
        ("新浪财经 7×24", "flash", lambda: fetch_sina_flash(int(cfg["flash_page_size"]))),
        ("新浪财经滚动", "market", lambda: fetch_sina_market(int(cfg["market_page_size"]))),
        ("东方财富个股新闻", "stock",
         lambda: fetch_stock_news(cfg.get("watchlist") or [], int(cfg["stock_news_page_size"]))),
        ("东方财富公告", "ann", lambda: fetch_announcements(int(cfg["announcement_page_size"]))),
        ("东方财富研报", "report", lambda: fetch_reports(int(cfg["report_page_size"]))),
    ]

    incoming: list[dict] = []
    status: list[dict] = []
    for name, cat, fn in sources:
        try:
            items = fn()
            incoming.extend(items)
            status.append({"name": name, "cat": cat, "status": "ok",
                           "fetched": len(items), "error": ""})
            log(f"[OK] {name}: {len(items)} 条")
        except Exception as exc:  # noqa: BLE001
            status.append({"name": name, "cat": cat, "status": "error",
                           "fetched": 0, "error": str(exc)[:160]})
            log(f"[ERR] {name}: {exc}")

    existing: list[dict] = []
    if ARCHIVE_PATH.exists():
        try:
            payload = json.loads(ARCHIVE_PATH.read_text(encoding="utf-8"))
            existing = payload if isinstance(payload, list) else payload.get("items", [])
        except Exception as exc:  # noqa: BLE001
            log(f"[WARN] archive.json 读取失败，将重建: {exc}")

    keep_days = int(cfg.get("keep_days", 7))
    max_output = int(cfg.get("max_output_items", 1500))
    merged, new_count = merge_archive(existing, incoming, keep_days, max(keep_days * 1200, max_output))
    write_atomic(ARCHIVE_PATH, json.dumps(merged, ensure_ascii=False, separators=(",", ":")))

    output_items = merged[:max_output]
    generated = now_bj()
    counts = {"all": len(output_items)}
    for cat in CATEGORIES:
        counts[cat] = sum(1 for item in output_items if item["cat"] == cat)

    ok_sources = sum(1 for s in status if s["status"] == "ok")
    payload = {
        "generated_at": iso(generated),
        "started_at": iso(started),
        "elapsed_sec": round((generated - started).total_seconds(), 1),
        "new_count": new_count,
        "counts": counts,
        "sources": status,
        "source_ok": ok_sources,
        "source_total": len(status),
        "watchlist": cfg.get("watchlist") or [],
        "items": output_items,
    }

    write_atomic(NEWS_JSON, json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    write_atomic(NEWS_JS, "window.NEWS_DATA = " + json.dumps(payload, ensure_ascii=False,
                                                             separators=(",", ":")) + ";\n")

    log(f"完成：{ok_sources}/{len(status)} 个源成功，新增 {new_count} 条，"
        f"输出 {len(output_items)} 条 -> data/news.json")
    if not output_items:
        log("[FATAL] 没有任何可用资讯，请检查网络或内容源状态")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
