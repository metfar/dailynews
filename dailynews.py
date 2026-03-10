#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#pylint:disable=W0301
#
#  Copyright 2018- William Martinez Bas <metfar@gmail.com>
#
#  This program is free software; you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation; either version 2 of the License, or
#  (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program; if not, write to the Free Software
#  Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston,
#  MA 02110-1301, USA.
#
#
#import warnings;
#warnings.filterwarnings("ignore", category=UserWarning);

"""
dailynews.py;

Daily news digest in Markdown, with morning/evening profiles,
local alerts and automatic fallback if OpenAI fails.

Main features:
- "morning" and "evening" profiles;
- "--alerts-only" mode;
- alert targets by name or coordinates;
- "--location", "--geolocation" and "--locations" mixed;
- source filters by allowlist / denylist;
- output to file and/or stdout;
- fallback to raw Markdown when OpenAI fails;

Dependencies:
    python3 -m pip install --upgrade openai requests feedparser yfinance;

Examples:
    python3 dailynews.py --config ./config.json --profile morning;
    python3 dailynews.py --config ./config.json --profile evening;
    python3 dailynews.py --config ./config.json --alerts-only --print;
    python3 dailynews.py --config ./config.json --alerts-only --location "Montevideo, Uruguay";
    python3 dailynews.py --config ./config.json --alerts-only --geolocation "(-34.48759, -55.62793)";
    python3 dailynews.py --config ./config.json --alerts-only --locations "(Montevideo, Uruguay; Indiana, USA; (-34.48759, -55.62793))";
""";

from __future__ import annotations;

import argparse;
import datetime as dt;
import html;
import json;
import logging;
import os;
import re;
import sys;
from dataclasses import dataclass;
from dataclasses import field;
from typing import Dict;
from typing import List;
from typing import Optional;
from typing import Tuple;
from urllib.parse import quote_plus;
from urllib.parse import urlparse;

import feedparser;
import requests;
import yfinance as yf;
from openai import OpenAI;

DEFAULT_MODEL = "gpt-5-mini";
DEFAULT_OUTPUT_DIR = ".";
DEFAULT_HTTP_TIMEOUT = 20;
USER_AGENT = "dailynews/2.0 (+https://openai.com)";

EXIT_OK = 0;
EXIT_GENERAL_ERROR = 1;
EXIT_NETWORK_ERROR = 2;
EXIT_CONFIG_ERROR = 3;
EXIT_INTERRUPTED = 130;

TOPIC_FEEDS = {
    "space_missions": [
        ("NASA Breaking News", "https://www.nasa.gov/news-release/feed/"),
        ("NASA Image of the Day", "https://www.nasa.gov/image-of-the-day/feed/"),
        ("Google News: upcoming space missions", "https://news.google.com/rss/search?q=" + quote_plus("upcoming space missions OR Artemis OR SpaceX OR ESA OR launch") + "&hl=en-US&gl=US&ceid=US:en"),
    ],
    "markets": [
        ("Google News: global markets", "https://news.google.com/rss/search?q=" + quote_plus("stock market OR bond market OR oil OR inflation OR fed OR nasdaq OR dow") + "&hl=en-US&gl=US&ceid=US:en"),
    ],
    "general": [
        ("Google News: headlines", "https://news.google.com/rss?hl=en-US&gl=US&ceid=US:en"),
    ],
    "geopolitics": [
        ("Google News: geopolitics", "https://news.google.com/rss/search?q=" + quote_plus("international crisis OR diplomacy OR military OR conflict OR ceasefire OR sanctions") + "&hl=en-US&gl=US&ceid=US:en"),
    ],
};

MARKET_TICKERS = {
    "S&P 500": "^GSPC",
    "NASDAQ": "^IXIC",
    "Dow Jones": "^DJI",
    "Russell 2000": "^RUT",
    "VIX": "^VIX",
    "Brent Crude": "BZ=F",
    "Gold": "GC=F",
    "Bitcoin": "BTC-USD",
    "EUR/USD": "EURUSD=X",
};

DEFAULT_SOURCE_POLICY = {
    "mode": "mixed",
    "allow_domains": [],
    "deny_domains": [],
    "deny_if_source_matches": [],
};

SYSTEM_PROMPTS = {
    "morning": """
You are a concise daily briefing editor.
Return Markdown.

Goal:
- Create a quick morning brief for a human reading with breakfast.
- Keep it short and practical.
- Focus on orientation, not deep analysis.

Requirements:
- Use headings and short bullets.
- Include only the most relevant items.
- Prefer facts, timing, and why it matters today.
- If alerts exist, include them near the top.
- Avoid rhetorical flourish.
- Do not invent facts.
""".strip(),
    "evening": """
You are a concise daily digest editor.
Return Markdown.

Goal:
- Create an evening digest for a human reading after work.
- Add more context than the morning brief.
- Highlight what mattered, what stayed uncertain, and what deserves follow-up reading.

Requirements:
- Use headings and short bullets.
- Summarize patterns across items.
- Prefer facts, context, and what changed during the day.
- If alerts exist, include them near the top.
- Avoid rhetorical flourish.
- Do not invent facts.
""".strip(),
};


@dataclass
class NewsItem:
    topic: str;
    source: str;
    title: str;
    link: str;
    published: str;
    summary: str;
    domain: str = "";


@dataclass
class MarketPoint:
    name: str;
    ticker: str;
    price: Optional[float];
    previous_close: Optional[float];
    change: Optional[float];
    change_pct: Optional[float];
    currency: str;


@dataclass
class AlertItem:
    level: str;
    category: str;
    title: str;
    details: str;
    source: str = "";
    link: str = "";


@dataclass
class AlertTarget:
    kind: str;
    value: str = "";
    lat: Optional[float] = None;
    lon: Optional[float] = None;
    label: str = "";


@dataclass
class ProfileConfig:
    name: str;
    topics: List[str];
    max_items: int;
    topic_limits: Dict[str, int];
    global_max_items: Optional[int];
    max_lines: Optional[int];
    use_openai: bool;
    include_markets: bool;
    include_alerts: bool;
    watchlist: List[str] = field(default_factory=list);


@dataclass
class AlertsConfig:
    enabled: bool;
    location_name: str;
    weather_temp_drop_c: float;
    weather_temp_rise_c: float;
    wind_gust_kmh: float;
    air_aqi_us: int;
    alert_keywords: List[str];
    alert_query_location: str;
    max_keyword_items: int;
    targets: List[AlertTarget] = field(default_factory=list);


@dataclass
class SourcePolicy:
    mode: str;
    allow_domains: List[str];
    deny_domains: List[str];
    deny_if_source_matches: List[str];


@dataclass
class AppConfig:
    output_dir: str;
    model: str;
    dry_run: bool;
    do_print: bool;
    stdout_only: bool;
    log_file: str;
    verbose: bool;
    http_timeout: int;
    profiles: Dict[str, ProfileConfig];
    alerts: AlertsConfig;
    source_policy: SourcePolicy;
    feed_urls: Dict[str, List[Tuple[str, str]]] = field(default_factory=dict);


def utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc);


def local_now() -> dt.datetime:
    return dt.datetime.now();


def setup_logging(log_file: str, verbose: bool) -> logging.Logger:
    logger = logging.getLogger("dailynews");
    logger.setLevel(logging.DEBUG if verbose else logging.INFO);
    logger.handlers.clear();

    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s");

    if log_file:
        handler = logging.FileHandler(log_file, encoding="utf-8");
    else:
        handler = logging.StreamHandler(sys.stderr);

    handler.setFormatter(formatter);
    handler.setLevel(logging.DEBUG if verbose else logging.INFO);
    logger.addHandler(handler);
    logger.propagate = False;
    return logger;


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Daily news digest with morning/evening profiles");
    parser.add_argument("--config", default="", help="Path to config.json");
    parser.add_argument("--profile", default="morning", help="Profile: morning or evening");
    parser.add_argument("--alerts-only", action="store_true", help="Generate alerts only");
    parser.add_argument("--dry-run", action="store_true", help="Does not call OpenAI");
    parser.add_argument("--print", dest="do_print", action="store_true", help="Print result to stdout");
    parser.add_argument("--stdout-only", action="store_true", help="Stdout only; does not save file");
    parser.add_argument("--output-dir", default="", help="Output directory");
    parser.add_argument("--log-file", default="", help="Log file");
    parser.add_argument("--verbose", action="store_true", help="Detailed logging");
    parser.add_argument("--http-timeout", type=int, default=None, help="HTTP Timeout in seconds");
    parser.add_argument("--location", action="append", default=[], help="Nominal location for alerts. Can be repeated");
    parser.add_argument("--geolocation", action="append", default=[], help="Coordinates for alerts. Ex: '(-34.48, -55.62)'");
    parser.add_argument("--locations", default="", help="Mixed list. Ex: '(Montevideo, Uruguay; Indiana, USA; (-34.48, -55.62))'");
    return parser.parse_args();


def load_json_config(path: str) -> Dict[str, object]:
    if not path:
        return {};
    with open(path, "r", encoding="utf-8") as handle:
        data = json.load(handle);
    if not isinstance(data, dict):
        raise ValueError("The JSON config must be an object");
    return data;


def clean_html(text: str) -> str:
    text = html.unescape(text or "");
    text = re.sub(r"<[^>]+>", " ", text);
    text = re.sub(r"\s+", " ", text).strip();
    return text;


def safe_int(value: object, default: Optional[int] = None) -> Optional[int]:
    try:
        if value is None:
            return default;
        return int(value);
    except (TypeError, ValueError):
        return default;


def safe_float(value: object, default: Optional[float] = None) -> Optional[float]:
    try:
        if value is None:
            return default;
        return float(value);
    except (TypeError, ValueError):
        return default;


def normalize_domain(url: str) -> str:
    if not url:
        return "";
    try:
        parsed = urlparse(url);
        host = (parsed.netloc or "").lower().strip();
        if host.startswith("www."):
            host = host[4:];
        return host;
    except Exception:
        return "";


def parse_feed_urls(raw_value: object) -> Dict[str, List[Tuple[str, str]]]:
    if raw_value is None:
        return {};
    if not isinstance(raw_value, dict):
        raise ValueError("'feed_urls' must be an object");

    result: Dict[str, List[Tuple[str, str]]] = {};

    for topic, entries in raw_value.items():
        if topic not in TOPIC_FEEDS:
            continue;
        if not isinstance(entries, list):
            continue;

        parsed_entries: List[Tuple[str, str]] = [];
        for entry in entries:
            if isinstance(entry, dict):
                name = str(entry.get("name", "")).strip();
                url = str(entry.get("url", "")).strip();
                if name and url:
                    parsed_entries.append((name, url));
            elif isinstance(entry, list) and len(entry) == 2:
                name = str(entry[0]).strip();
                url = str(entry[1]).strip();
                if name and url:
                    parsed_entries.append((name, url));

        if parsed_entries:
            result[topic] = parsed_entries;

    return result;


def parse_source_policy(raw_value: object) -> SourcePolicy:
    policy = DEFAULT_SOURCE_POLICY.copy();

    if isinstance(raw_value, dict):
        policy["mode"] = str(raw_value.get("mode", policy["mode"]) or policy["mode"]).strip().lower();
        policy["allow_domains"] = [str(x).strip().lower() for x in raw_value.get("allow_domains", []) if str(x).strip()];
        policy["deny_domains"] = [str(x).strip().lower() for x in raw_value.get("deny_domains", []) if str(x).strip()];
        policy["deny_if_source_matches"] = [str(x).strip().lower() for x in raw_value.get("deny_if_source_matches", []) if str(x).strip()];

    if policy["mode"] not in ("off", "mixed", "allowlist"):
        policy["mode"] = "mixed";

    return SourcePolicy(
        mode=policy["mode"],
        allow_domains=policy["allow_domains"],
        deny_domains=policy["deny_domains"],
        deny_if_source_matches=policy["deny_if_source_matches"],
    );


def parse_profile(name: str, raw: object) -> ProfileConfig:
    if not isinstance(raw, dict):
        raise ValueError(f"Invalid profile: {name}");

    topics = [str(x).strip() for x in raw.get("topics", []) if str(x).strip() in TOPIC_FEEDS];
    if not topics:
        raise ValueError(f"'{name}' profile has not valid topics");

    topic_limits: Dict[str, int] = {};
    raw_topic_limits = raw.get("topic_limits", {});
    if isinstance(raw_topic_limits, dict):
        for key, value in raw_topic_limits.items():
            if key in TOPIC_FEEDS:
                parsed = safe_int(value, None);
                if parsed is not None and parsed >= 0:
                    topic_limits[key] = parsed;

    watchlist = [str(x).strip() for x in raw.get("watchlist", []) if str(x).strip()];

    return ProfileConfig(
        name=name,
        topics=topics,
        max_items=safe_int(raw.get("max_items", 3), 3) or 3,
        topic_limits=topic_limits,
        global_max_items=safe_int(raw.get("global_max_items", None), None),
        max_lines=safe_int(raw.get("max_lines", None), None),
        use_openai=bool(raw.get("use_openai", True)),
        include_markets=bool(raw.get("include_markets", True)),
        include_alerts=bool(raw.get("include_alerts", True)),
        watchlist=watchlist,
    );


def parse_geo_text(text: str) -> Optional[Tuple[float, float]]:
    raw = text.strip();
    match = re.match(r"^\(\s*([-+]?\d+(?:\.\d+)?)\s*,\s*([-+]?\d+(?:\.\d+)?)\s*\)$", raw);
    if not match:
        return None;

    lat = safe_float(match.group(1), None);
    lon = safe_float(match.group(2), None);

    if lat is None or lon is None:
        return None;

    if lat < -90.0 or lat > 90.0 or lon < -180.0 or lon > 180.0:
        return None;

    return (lat, lon);


def split_locations_text(text: str) -> List[str]:
    raw = text.strip();
    if not raw:
        return [];

    if raw.startswith("(") and raw.endswith(")"):
        raw = raw[1:-1].strip();

    parts: List[str] = [];
    current: List[str] = [];
    depth = 0;

    for char in raw:
        if char == "(":
            depth += 1;
            current.append(char);
            continue;
        if char == ")":
            depth = max(0, depth - 1);
            current.append(char);
            continue;
        if char == ";" and depth == 0:
            chunk = "".join(current).strip();
            if chunk:
                parts.append(chunk);
            current = [];
            continue;
        current.append(char);

    chunk = "".join(current).strip();
    if chunk:
        parts.append(chunk);

    return parts;


def parse_alert_target_text(text: str) -> AlertTarget:
    raw = text.strip();
    geo = parse_geo_text(raw);

    if geo is not None:
        lat, lon = geo;
        return AlertTarget(
            kind="geo",
            lat=lat,
            lon=lon,
            label=f"{lat:.5f}, {lon:.5f}",
        );

    return AlertTarget(
        kind="name",
        value=raw,
        label=raw,
    );


def parse_targets_list(raw_items: List[str], mixed_text: str) -> List[AlertTarget]:
    targets: List[AlertTarget] = [];

    for item in raw_items:
        item = item.strip();
        if item:
            targets.append(parse_alert_target_text(item));

    for item in split_locations_text(mixed_text):
        item = item.strip();
        if item:
            targets.append(parse_alert_target_text(item));

    deduped: List[AlertTarget] = [];
    seen = set();

    for target in targets:
        if target.kind == "geo":
            key = ("geo", round(target.lat or 0.0, 6), round(target.lon or 0.0, 6));
        else:
            key = ("name", target.value.lower().strip());

        if key in seen:
            continue;

        seen.add(key);
        deduped.append(target);

    return deduped;


def parse_alerts(raw: object) -> AlertsConfig:
    if not isinstance(raw, dict):
        raw = {};

    targets: List[AlertTarget] = [];

    raw_targets = raw.get("targets", []);
    if isinstance(raw_targets, list):
        for entry in raw_targets:
            if isinstance(entry, dict):
                kind = str(entry.get("kind", "") or "").strip().lower();
                if kind == "geo":
                    lat = safe_float(entry.get("lat"), None);
                    lon = safe_float(entry.get("lon"), None);
                    label = str(entry.get("label", "") or "").strip();
                    if lat is not None and lon is not None:
                        targets.append(
                            AlertTarget(
                                kind="geo",
                                lat=lat,
                                lon=lon,
                                label=label or f"{lat:.5f}, {lon:.5f}",
                            )
                        );
                elif kind == "name":
                    value = str(entry.get("value", "") or "").strip();
                    if value:
                        targets.append(
                            AlertTarget(
                                kind="name",
                                value=value,
                                label=value,
                            )
                        );

    location_name = str(raw.get("location_name", "") or "").strip();
    if location_name and not targets:
        targets.append(AlertTarget(kind="name", value=location_name, label=location_name));

    alert_query_location = str(raw.get("alert_query_location", "") or "").strip();

    return AlertsConfig(
        enabled=bool(raw.get("enabled", True)),
        location_name=location_name,
        weather_temp_drop_c=safe_float(raw.get("weather_temp_drop_c", 8.0), 8.0) or 8.0,
        weather_temp_rise_c=safe_float(raw.get("weather_temp_rise_c", 8.0), 8.0) or 8.0,
        wind_gust_kmh=safe_float(raw.get("wind_gust_kmh", 70.0), 70.0) or 70.0,
        air_aqi_us=safe_int(raw.get("air_aqi_us", 100), 100) or 100,
        alert_keywords=[str(x).strip() for x in raw.get("alert_keywords", []) if str(x).strip()],
        alert_query_location=alert_query_location,
        max_keyword_items=safe_int(raw.get("max_keyword_items", 6), 6) or 6,
        targets=targets,
    );


def merge_config(args: argparse.Namespace, cfg: Dict[str, object]) -> AppConfig:
    output_dir = str(cfg.get("output_dir", DEFAULT_OUTPUT_DIR) or DEFAULT_OUTPUT_DIR);
    if args.output_dir:
        output_dir = args.output_dir;

    model = str(cfg.get("model", DEFAULT_MODEL) or DEFAULT_MODEL);
    dry_run = bool(cfg.get("dry_run", False)) or bool(args.dry_run);
    do_print = bool(cfg.get("print", False)) or bool(args.do_print);
    stdout_only = bool(cfg.get("stdout_only", False)) or bool(args.stdout_only);

    log_file = str(cfg.get("log_file", "") or "");
    if args.log_file:
        log_file = args.log_file;

    verbose = bool(cfg.get("verbose", False)) or bool(args.verbose);

    http_timeout = safe_int(cfg.get("http_timeout", DEFAULT_HTTP_TIMEOUT), DEFAULT_HTTP_TIMEOUT);
    if args.http_timeout is not None:
        http_timeout = args.http_timeout;
    if http_timeout is None or http_timeout <= 0:
        http_timeout = DEFAULT_HTTP_TIMEOUT;

    raw_profiles = cfg.get("profiles", {});
    if not isinstance(raw_profiles, dict) or not raw_profiles:
        raise ValueError("The 'profiles' section is not present at the config");

    profiles: Dict[str, ProfileConfig] = {};
    for name, raw_profile in raw_profiles.items():
        profiles[str(name).strip()] = parse_profile(str(name).strip(), raw_profile);

    alerts = parse_alerts(cfg.get("alerts", {}));

    cli_items: List[str] = [];
    cli_items.extend(args.location);
    cli_items.extend(args.geolocation);

    cli_targets = parse_targets_list(cli_items, args.locations);
    if cli_targets:
        alerts.targets = cli_targets;

    if not alerts.targets and alerts.location_name:
        alerts.targets = [AlertTarget(kind="name", value=alerts.location_name, label=alerts.location_name)];

    source_policy = parse_source_policy(cfg.get("source_policy", {}));
    feed_urls = parse_feed_urls(cfg.get("feed_urls", {}));

    return AppConfig(
        output_dir=output_dir,
        model=model,
        dry_run=dry_run,
        do_print=do_print,
        stdout_only=stdout_only,
        log_file=log_file,
        verbose=verbose,
        http_timeout=http_timeout,
        profiles=profiles,
        alerts=alerts,
        source_policy=source_policy,
        feed_urls=feed_urls,
    );


def get_topic_feeds(config: AppConfig, topic: str) -> List[Tuple[str, str]]:
    if topic in config.feed_urls and config.feed_urls[topic]:
        return config.feed_urls[topic];
    return TOPIC_FEEDS.get(topic, []);


def new_session() -> requests.Session:
    session = requests.Session();
    session.headers.update({"User-Agent": USER_AGENT});
    return session;


def source_allowed(item: NewsItem, policy: SourcePolicy) -> bool:
    source_lc = item.source.lower().strip();
    domain_lc = item.domain.lower().strip();

    for blocked_source in policy.deny_if_source_matches:
        if blocked_source and blocked_source in source_lc:
            return False;

    if domain_lc and domain_lc in policy.deny_domains:
        return False;

    if policy.mode == "off":
        return True;

    if policy.mode == "mixed":
        return True;

    if policy.mode == "allowlist":
        return domain_lc in policy.allow_domains;

    return True;


def fetch_feed(session: requests.Session, url: str, timeout: int, logger: logging.Logger) -> feedparser.FeedParserDict:
    logger.debug("Fetching feed: %s", url);
    response = session.get(url, timeout=timeout);
    response.raise_for_status();
    return feedparser.parse(response.content);


def collect_topic_news(topic: str, profile: ProfileConfig, config: AppConfig, session: requests.Session, logger: logging.Logger) -> List[NewsItem]:
    items: List[NewsItem] = [];
    seen = set();
    per_topic_limit = profile.topic_limits.get(topic, profile.max_items);

    for source_name, feed_url in get_topic_feeds(config, topic):
        try:
            parsed = fetch_feed(session, feed_url, config.http_timeout, logger);
            entries = parsed.entries[:per_topic_limit];
        except Exception as exc:
            logger.warning("Feed failed topic=%s source=%s error=%s", topic, source_name, exc);
            continue;

        for entry in entries:
            title = clean_html(getattr(entry, "title", ""));
            link = getattr(entry, "link", "").strip();
            published = getattr(entry, "published", "") or getattr(entry, "updated", "");
            summary = clean_html(getattr(entry, "summary", "") or getattr(entry, "description", ""));
            domain = normalize_domain(link);
            key = (title.lower(), link);

            if not title or key in seen:
                continue;

            item = NewsItem(
                topic=topic,
                source=source_name,
                title=title,
                link=link,
                published=published,
                summary=summary,
                domain=domain,
            );

            if not source_allowed(item, config.source_policy):
                logger.debug("Source filtered topic=%s source=%s domain=%s", topic, item.source, item.domain);
                continue;

            seen.add(key);
            items.append(item);

    logger.info("Collected topic=%s count=%d", topic, len(items));
    return items;


def apply_global_limit(topic_map: Dict[str, List[NewsItem]], topics: List[str], global_max_items: Optional[int]) -> Dict[str, List[NewsItem]]:
    if global_max_items is None:
        return topic_map;

    remaining = global_max_items;
    limited: Dict[str, List[NewsItem]] = {};

    for topic in topics:
        if remaining <= 0:
            limited[topic] = [];
            continue;
        original = topic_map.get(topic, []);
        sliced = original[:remaining];
        limited[topic] = sliced;
        remaining -= len(sliced);

    return limited;


def fetch_market_snapshot(logger: logging.Logger) -> List[MarketPoint]:
    snapshot: List[MarketPoint] = [];

    for name, ticker in MARKET_TICKERS.items():
        price = None;
        previous_close = None;
        currency = "";

        try:
            data = yf.Ticker(ticker);
            info = data.fast_info;
            price = safe_float(getattr(info, "last_price", None), None);
            previous_close = safe_float(getattr(info, "previous_close", None), None);

            if price is None or previous_close is None:
                hist = data.history(period="2d", interval="1d", auto_adjust=False, prepost=False);
                if not hist.empty:
                    closes = hist["Close"].dropna().tolist();
                    if closes:
                        price = safe_float(closes[-1], None);
                    if len(closes) >= 2:
                        previous_close = safe_float(closes[-2], None);
                info_dict = getattr(data, "info", {}) or {};
                currency = str(info_dict.get("currency", "") or "");
            else:
                currency = str(getattr(info, "currency", "") or "");
        except Exception as exc:
            logger.warning("Market fetch failed name=%s ticker=%s error=%s", name, ticker, exc);

        change = None;
        change_pct = None;
        if price is not None and previous_close not in (None, 0.0):
            change = price - previous_close;
            change_pct = (change / previous_close) * 100.0;

        snapshot.append(
            MarketPoint(
                name=name,
                ticker=ticker,
                price=price,
                previous_close=previous_close,
                change=change,
                change_pct=change_pct,
                currency=currency,
            )
        );

    logger.info("Collected market snapshot count=%d", len(snapshot));
    return snapshot;


def geocode_location(session: requests.Session, location_name: str, timeout: int, logger: logging.Logger) -> Optional[Tuple[float, float, str]]:
    if not location_name:
        return None;

    url = "https://geocoding-api.open-meteo.com/v1/search";
    params = {
        "name": location_name,
        "count": 1,
        "language": "en",
        "format": "json",
    };

    try:
        response = session.get(url, params=params, timeout=timeout);
        response.raise_for_status();
        data = response.json();
        results = data.get("results", []);
        if not results:
            logger.warning("Geocoding returned no results for location=%s", location_name);
            return None;

        first = results[0];
        lat = safe_float(first.get("latitude"), None);
        lon = safe_float(first.get("longitude"), None);
        name = str(first.get("name", location_name) or location_name);
        country = str(first.get("country", "") or "");
        label = f"{name}, {country}".strip(", ");

        if lat is None or lon is None:
            return None;

        logger.info("Geocoded location=%s lat=%s lon=%s", label, lat, lon);
        return (lat, lon, label);
    except Exception as exc:
        logger.warning("Geocoding failed location=%s error=%s", location_name, exc);
        return None;


def resolve_alert_target(session: requests.Session, target: AlertTarget, timeout: int, logger: logging.Logger) -> Optional[Tuple[float, float, str, str]]:
    if target.kind == "geo":
        if target.lat is None or target.lon is None:
            return None;
        label = target.label or f"{target.lat:.5f}, {target.lon:.5f}";
        return (target.lat, target.lon, label, label);

    if target.kind == "name":
        if not target.value:
            return None;
        geocoded = geocode_location(session, target.value, timeout, logger);
        if not geocoded:
            return None;
        lat, lon, label = geocoded;
        query_text = target.value.strip() or label;
        return (lat, lon, label, query_text);

    return None;


def get_weather_alerts(session: requests.Session, alerts_cfg: AlertsConfig, timeout: int, logger: logging.Logger) -> List[AlertItem]:
    items: List[AlertItem] = [];

    for target in alerts_cfg.targets:
        resolved = resolve_alert_target(session, target, timeout, logger);
        if not resolved:
            continue;

        lat, lon, label, _query_text = resolved;

        url = "https://api.open-meteo.com/v1/forecast";
        params = {
            "latitude": lat,
            "longitude": lon,
            "current": "temperature_2m,wind_gusts_10m",
            "hourly": "temperature_2m,wind_gusts_10m",
            "forecast_days": 2,
            "timezone": "auto",
        };

        try:
            response = session.get(url, params=params, timeout=timeout);
            response.raise_for_status();
            data = response.json();

            current = data.get("current", {}) or {};
            hourly = data.get("hourly", {}) or {};
            temps = hourly.get("temperature_2m", []) or [];
            gusts = hourly.get("wind_gusts_10m", []) or [];

            current_temp = safe_float(current.get("temperature_2m"), None);
            current_gust = safe_float(current.get("wind_gusts_10m"), None);

            if current_temp is not None and temps:
                window = [safe_float(x, None) for x in temps[:8]];
                window = [x for x in window if x is not None];

                if window:
                    min_future = min(window);
                    max_future = max(window);

                    if current_temp - min_future >= alerts_cfg.weather_temp_drop_c:
                        items.append(
                            AlertItem(
                                level="warning",
                                category="weather",
                                title=f"Sudden drop in temperature at {label}",
                                details=f"Actual temperature {current_temp:.1f}°C; Potencial fall of {current_temp - min_future:.1f}°C in the next hours.",
                                source="Open-Meteo",
                            )
                        );

                    if max_future - current_temp >= alerts_cfg.weather_temp_rise_c:
                        items.append(
                            AlertItem(
                                level="warning",
                                category="weather",
                                title=f"Sudden rise in temperatura at {label}",
                                details=f"Temperatura actual {current_temp:.1f}°C; Potential rise of {max_future - current_temp:.1f}°C in the next hours.",
                                source="Open-Meteo",
                            )
                        );

            gust_window = [safe_float(x, None) for x in gusts[:8]];
            gust_window = [x for x in gust_window if x is not None];
            max_gust = max(gust_window) if gust_window else current_gust;

            if max_gust is not None and max_gust >= alerts_cfg.wind_gust_kmh:
                items.append(
                    AlertItem(
                        level="warning",
                        category="weather",
                        title=f"Intense gusts expected in {label}",
                        details=f"Maximum estimated gust: {max_gust:.1f} km/h.",
                        source="Open-Meteo",
                    )
                );
        except Exception as exc:
            logger.warning("Weather alerts fetch failed target=%s error=%s", label, exc);

    return items;


def get_air_alerts(session: requests.Session, alerts_cfg: AlertsConfig, timeout: int, logger: logging.Logger) -> List[AlertItem]:
    items: List[AlertItem] = [];

    for target in alerts_cfg.targets:
        resolved = resolve_alert_target(session, target, timeout, logger);
        if not resolved:
            continue;

        lat, lon, label, _query_text = resolved;

        url = "https://air-quality-api.open-meteo.com/v1/air-quality";
        params = {
            "latitude": lat,
            "longitude": lon,
            "current": "us_aqi,pm2_5,pm10,ozone",
            "timezone": "auto",
        };

        try:
            response = session.get(url, params=params, timeout=timeout);
            response.raise_for_status();
            data = response.json();
            current = data.get("current", {}) or {};

            us_aqi = safe_int(current.get("us_aqi"), None);
            pm25 = safe_float(current.get("pm2_5"), None);
            pm10 = safe_float(current.get("pm10"), None);
            ozone = safe_float(current.get("ozone"), None);

            if us_aqi is not None and us_aqi >= alerts_cfg.air_aqi_us:
                parts: List[str] = [f"AQI US actual: {us_aqi}"];
                if pm25 is not None:
                    parts.append(f"PM2.5: {pm25:.1f}");
                if pm10 is not None:
                    parts.append(f"PM10: {pm10:.1f}");
                if ozone is not None:
                    parts.append(f"O₃: {ozone:.1f}");

                items.append(
                    AlertItem(
                        level="warning",
                        category="air",
                        title=f"Air quality compromised in {label}",
                        details="; ".join(parts) + ".",
                        source="Open-Meteo",
                    )
                );
        except Exception as exc:
            logger.warning("Air alerts fetch failed target=%s error=%s", label, exc);

    return items;


def get_keyword_alerts(session: requests.Session, alerts_cfg: AlertsConfig, timeout: int, logger: logging.Logger) -> List[AlertItem]:
    items: List[AlertItem] = [];

    if not alerts_cfg.alert_keywords:
        return items;

    seen = set();

    query_targets: List[str] = [];
    for target in alerts_cfg.targets:
        if target.kind == "name" and target.value.strip():
            query_targets.append(target.value.strip());
        elif target.kind == "geo" and target.label.strip():
            query_targets.append(target.label.strip());

    if not query_targets and alerts_cfg.alert_query_location.strip():
        query_targets.append(alerts_cfg.alert_query_location.strip());

    if not query_targets:
        query_targets.append("");

    for query_target in query_targets:
        for keyword in alerts_cfg.alert_keywords:
            query = keyword;
            if query_target:
                query = f"{keyword} {query_target}";

            feed_url = "https://news.google.com/rss/search?q=" + quote_plus(query) + "&hl=en-US&gl=US&ceid=US:en";

            try:
                parsed = fetch_feed(session, feed_url, timeout, logger);
                entries = parsed.entries[:alerts_cfg.max_keyword_items];
            except Exception as exc:
                logger.warning("Keyword alert feed failed keyword=%s target=%s error=%s", keyword, query_target, exc);
                continue;

            for entry in entries:
                title = clean_html(getattr(entry, "title", ""));
                link = getattr(entry, "link", "").strip();
                source = "Google News alerts";
                summary = clean_html(getattr(entry, "summary", "") or getattr(entry, "description", ""));
                sig = (keyword.lower(), query_target.lower(), title.lower(), link);

                if not title or sig in seen:
                    continue;

                seen.add(sig);
                details = f"Keyword: {keyword}.";
                if query_target:
                    details += f" Lugar: {query_target}.";
                if summary:
                    details += f" {summary}";

                items.append(
                    AlertItem(
                        level="urgent",
                        category="keyword",
                        title=title,
                        details=details.strip(),
                        source=source,
                        link=link,
                    )
                );

    logger.info("Collected keyword alerts count=%d", len(items));
    return items;


def collect_alerts(config: AppConfig, session: requests.Session, logger: logging.Logger) -> List[AlertItem]:
    if not config.alerts.enabled:
        return [];

    items: List[AlertItem] = [];
    items.extend(get_weather_alerts(session, config.alerts, config.http_timeout, logger));
    items.extend(get_air_alerts(session, config.alerts, config.http_timeout, logger));
    items.extend(get_keyword_alerts(session, config.alerts, config.http_timeout, logger));
    return items;


def build_payload(profile: ProfileConfig, config: AppConfig, session: requests.Session, logger: logging.Logger, alerts_only: bool = False) -> Dict[str, object]:
    payload: Dict[str, object] = {
        "generated_at_utc": utc_now().isoformat(),
        "generated_at_local": local_now().isoformat(),
        "hostname": os.uname().nodename if hasattr(os, "uname") else "",
        "profile": profile.name,
        "topics_order": [],
        "topics": {},
        "markets": [],
        "alerts": [],
        "watchlist": profile.watchlist,
    };

    if profile.include_alerts or alerts_only:
        payload["alerts"] = [item.__dict__ for item in collect_alerts(config, session, logger)];

    if alerts_only:
        return payload;

    topic_map: Dict[str, List[NewsItem]] = {};
    for topic in profile.topics:
        topic_map[topic] = collect_topic_news(topic, profile, config, session, logger);

    topic_map = apply_global_limit(topic_map, profile.topics, profile.global_max_items);

    payload["topics_order"] = profile.topics;
    for topic in profile.topics:
        payload["topics"][topic] = [item.__dict__ for item in topic_map.get(topic, [])];

    if profile.include_markets:
        payload["markets"] = [item.__dict__ for item in fetch_market_snapshot(logger)];

    return payload;


def render_alerts_markdown(payload: Dict[str, object]) -> str:
    lines: List[str] = [];
    lines.append("# Quick alerts");
    lines.append("");
    lines.append(f"Generated at UTC: `{payload.get('generated_at_utc', '')}`");
    lines.append("");

    alerts = payload.get("alerts", []) or [];
    if not alerts:
        lines.append("- No relevant alerts in this check.");
        lines.append("");
        return "\n".join(lines).strip() + "\n";

    urgent = [x for x in alerts if x.get("level") == "urgent"];
    warning = [x for x in alerts if x.get("level") == "warning"];
    other = [x for x in alerts if x.get("level") not in ("urgent", "warning")];

    def emit_group(title: str, group: List[Dict[str, object]]) -> None:
        if not group:
            return;
        lines.append(f"## {title}");
        lines.append("");
        for item in group:
            lines.append(f"- **{item.get('title', '')}**");
            if item.get("details", ""):
                lines.append(f"  - Details: {item.get('details', '')}");
            if item.get("source", ""):
                lines.append(f"  - Source: {item.get('source', '')}");
            if item.get("link", ""):
                lines.append(f"  - Link: {item.get('link', '')}");
            lines.append("");

    emit_group("Urgent", urgent);
    emit_group("Warnings", warning);
    emit_group("Others", other);

    return "\n".join(lines).strip() + "\n";


def render_raw_markdown(payload: Dict[str, object]) -> str:
    profile_name = str(payload.get("profile", "digest") or "digest");
    title = "# Morning Brief" if profile_name == "morning" else "# Evening Digest";

    lines: List[str] = [];
    lines.append(title);
    lines.append("");
    lines.append(f"Generated at UTC: `{payload.get('generated_at_utc', '')}`");
    lines.append(f"Generated at local: `{payload.get('generated_at_local', '')}`");
    if payload.get("hostname", ""):
        lines.append(f"Host: `{payload.get('hostname', '')}`");
    lines.append("");

    alerts = payload.get("alerts", []) or [];
    if alerts:
        lines.append("## Alerts");
        lines.append("");
        for item in alerts[:6]:
            lines.append(f"- **[{item.get('level', '').upper()}]** {item.get('title', '')}");
            if item.get("details", ""):
                lines.append(f"  - {item.get('details', '')}");
            if item.get("source", ""):
                lines.append(f"  - Fuente: {item.get('source', '')}");
            if item.get("link", ""):
                lines.append(f"  - Enlace: {item.get('link', '')}");
            lines.append("");

    topics_order = payload.get("topics_order", []) or [];
    topics = payload.get("topics", {}) or {};

    for topic in topics_order:
        items = topics.get(topic, []) or [];
        lines.append(f"## {topic}");
        lines.append("");

        if not items:
            lines.append("- No items available.");
            lines.append("");
            continue;

        for item in items:
            lines.append(f"- **{item.get('title', '')}**");
            if item.get("source", ""):
                lines.append(f"  - Source: {item.get('source', '')}");
            if item.get("published", ""):
                lines.append(f"  - Date: {item.get('published', '')}");
            if item.get("summary", ""):
                lines.append(f"  - Summary: {item.get('summary', '')}");
            if item.get("link", ""):
                lines.append(f"  - Link: {item.get('link', '')}");
            lines.append("");

    markets = payload.get("markets", []) or [];
    if markets:
        lines.append("## Markets");
        lines.append("");
        for item in markets:
            price = item.get("price", None);
            change = item.get("change", None);
            change_pct = item.get("change_pct", None);
            currency = item.get("currency", "");
            price_txt = "N/D" if price is None else f"{price:.4f}";
            change_txt = "N/D" if change is None else f"{change:+.4f}";
            pct_txt = "N/D" if change_pct is None else f"{change_pct:+.2f}%";
            suffix = f" {currency}" if currency else "";
            lines.append(f"- **{item.get('name', '')}** ({item.get('ticker', '')}): {price_txt}{suffix} | change {change_txt} ({pct_txt})");
        lines.append("");

    watchlist = payload.get("watchlist", []) or [];
    if watchlist:
        lines.append("## Surveillance / What to watch for");
        lines.append("");
        for item in watchlist:
            lines.append(f"- {item}");
        lines.append("");

    return "\n".join(lines).strip() + "\n";


def clip_markdown_lines(text: str, max_lines: Optional[int]) -> str:
    if max_lines is None or max_lines <= 0:
        return text;

    lines = text.splitlines();
    if len(lines) <= max_lines:
        return text if text.endswith("\n") else text + "\n";

    clipped = lines[:max_lines];
    clipped.append("");
    clipped.append("_Output cut short due to line limit._");
    return "\n".join(clipped).strip() + "\n";


def summarize_with_openai(payload: Dict[str, object], profile_name: str, model: str, logger: logging.Logger) -> str:
    api_key = os.environ.get("OPENAI_API_KEY", "").strip();
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY must be defined in the environment");

    client = OpenAI(api_key=api_key);
    raw_json = json.dumps(payload, ensure_ascii=False, indent=2);
    system_prompt = SYSTEM_PROMPTS.get(profile_name, SYSTEM_PROMPTS["morning"]);

    logger.info("Calling OpenAI model=%s profile=%s", model, profile_name);

    response = client.responses.create(
        model=model,
        input=[
            {
                "role": "system",
                "content": [
                    {
                        "type": "input_text",
                        "text": system_prompt,
                    }
                ],
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": "Generate a Markdown digest from this JSON.\n\n" + raw_json,
                    }
                ],
            },
        ],
    );

    text = getattr(response, "output_text", "");
    if text:
        return text.strip() + "\n";

    raise RuntimeError("OpenAI output_text is empty");


def save_markdown(output_dir: str, profile_name: str, alerts_only: bool, content: str) -> str:
    os.makedirs(output_dir, exist_ok=True);
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S");

    if alerts_only:
        filename = f"alerts_{stamp}.md";
    elif profile_name == "morning":
        filename = f"morning_brief_{stamp}.md";
    else:
        filename = f"evening_digest_{stamp}.md";

    path = os.path.join(output_dir, filename);
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(content);
    return path;


def emit_output(content: str, config: AppConfig, profile_name: str, alerts_only: bool, logger: logging.Logger) -> Optional[str]:
    if config.do_print or config.stdout_only:
        print(content, end="" if content.endswith("\n") else "\n");

    if config.stdout_only:
        logger.info("stdout-only enabled; file output skipped");
        return None;

    path = save_markdown(config.output_dir, profile_name, alerts_only, content);
    logger.info("Markdown saved path=%s", path);
    return path;


def main() -> int:
    args = parse_args();
    pre_logger = setup_logging(args.log_file, args.verbose);

    try:
        cfg_json = load_json_config(args.config);
        config = merge_config(args, cfg_json);
        logger = setup_logging(config.log_file, config.verbose);

        if args.profile not in config.profiles:
            raise ValueError(f"Profile does not exist: {args.profile}");

        profile = config.profiles[args.profile];
        session = new_session();

        logger.info("Start profile=%s alerts_only=%s dry_run=%s", profile.name, args.alerts_only, config.dry_run);

        payload = build_payload(profile, config, session, logger, alerts_only=args.alerts_only);

        if args.alerts_only:
            content = render_alerts_markdown(payload);
            content = clip_markdown_lines(content, 80);
        else:
            if config.dry_run or not profile.use_openai:
                content = render_raw_markdown(payload);
            else:
                try:
                    content = summarize_with_openai(payload, profile.name, config.model, logger);
                except Exception as exc:
                    logger.warning("OpenAI failed; using raw fallback error=%s", exc);
                    content = render_raw_markdown(payload);
                    content += "\n> Note: output generated without AI summary due to OpenAI failure.\n";
            content = clip_markdown_lines(content, profile.max_lines);

        out_path = emit_output(content, config, profile.name, args.alerts_only, logger);

        if out_path:
            print(f"Markdown saved at: {out_path}");

        logger.info("Completed successfully");
        return EXIT_OK;
    except KeyboardInterrupt:
        pre_logger.warning("Interrupted by user");
        return EXIT_INTERRUPTED;
    except requests.RequestException as exc:
        pre_logger.error("Network error: %s", exc);
        print(f"Error de red: {exc}", file=sys.stderr);
        return EXIT_NETWORK_ERROR;
    except ValueError as exc:
        pre_logger.error("Config error: %s", exc);
        print(f"Error de configuración: {exc}", file=sys.stderr);
        return EXIT_CONFIG_ERROR;
    except Exception as exc:
        pre_logger.error("General error: %s", exc);
        print(f"Error: {exc}", file=sys.stderr);
        return EXIT_GENERAL_ERROR;


if __name__ == "__main__":
    raise SystemExit(main());
