# dailynews.py

`dailynews.py` is a **Markdown** news reader intended to be used from terminal, `cron` or automation scripts.

`dailynews.py` is not intended to replace human judgment or become a living geopolitical oracle. It is a practical tool to read better: first orient yourself, then go deeper, and in the meantime not miss relevant alerts.



The idea of the project is to imitate the classic use of the paper diary:

- **morning**: a short reading to get your bearings;
- **afternoon**: a broader reading to go deeper;
- **every hour**: a check for local or urgent alerts.

The program combines:

- RSS feeds for news;
- snapshot of markets with `yfinance`;
- weather and air quality alerts with Open-Meteo;
- keyword alerts;
- optional summary with OpenAI;
- automatic fallback to raw Markdown if OpenAI crashes.

## Features

- `morning` and `evening` profiles;
- `--alerts-only` mode;
- output in **Markdown**;
- configuration by `config.json`;
- command line overrides;
- alert targets by name or coordinates;
- multiple locations in a single run;
- source filters by simple policy (`off`, `mixed`, `allowlist`);
- output to file and/or `stdout`;
- logging to `stderr` or file;
- automatic fallback if OpenAI does not respond or has no quota;
- limits by topic, global and by number of lines.

##Use philosophy

This script does not attempt to "think for the user". Try:

- deliver a quick information base in the morning;
- allow for more reflective reading in the afternoon;
- point out useful alerts during the day;
- reduce noise without feigning absolute objectivity.

## Requirements

- Python 3.10 or higher;
- Internet access;
- Optional OpenAI API key, only for assisted summary.

## Dependencies

Recommended installation:

```bash
python3 -m pip install --upgrade openai requests feedparser yfinance;
````

## Main files

* `dailynews.py`
* `config.json`

## Profiles

### `morning`

Designed for breakfast or quick reading:

* fewer items;
* fewer lines;
* focus on orientation;
*includes alerts if enabled.

### `evening`

Designed for the afternoon or end of the day:

* more context;
* more items;
* more space for tracking and watchlist.

## Alerts mode

`--alerts-only` generates a quick alert check without producing the full digest.

It is used for hourly runs with `cron`, for example to detect:

* sudden temperature changes;
* intense gusts;
* poor air quality;
* urgent news associated with configured keywords.

## Installation

1. Save `dailynews.py`.
2. Save `config.json`.
3. Install dependencies.
4. If you want summary with OpenAI, export the key:

```bash
export OPENAI_API_KEY="your_api_key";
```

5. Give execution permissions if necessary:

```bash
chmod +x dailynews.py;
```

## Basic use

### Morning brief

```bash
python3 dailynews.py --config ./config.json --profile morning;
```

### Evening digest

```bash
python3 dailynews.py --config ./config.json --profile evening;
```

### Alerts only

```bash
python3 dailynews.py --config ./config.json --alerts-only --print;
```

### Mode without OpenAI

```bash
python3 dailynews.py --config ./config.json --profile morning --dry-run --print;
```

## Alert targets

Alerts accept locations by name and coordinates.

### A nominal location

```bash
python3 dailynews.py --config ./config.json --alerts-only --location "Montevideo, Uruguay";
```

### Exact coordinates

```bash
python3 dailynews.py --config ./config.json --alerts-only --geolocation "(-34.48759, -55.62793)";
```

### Multiple mixed locations

```bash
python3 dailynews.py --config ./config.json --alerts-only --locations "(Montevideo, Uruguay; Indiana, USA; (-34.48759, -55.62793))";
```

### Multiple locations repeating flags

```bash
python3 dailynews.py --config ./config.json --alerts-only \
  --location "Montevideo, Uruguay" \
  --location "Indiana, USA" \
  --geolocation "(-34.48759, -55.62793)";
```

## Command line parameters

| Parameter | Description |                      |
| ---------------------------- | -------------------------------------------- | -------------------- |
| `--config PATH` | Path to `config.json` file |                      |
| `--profile morning | evening` | Select the profile |
| `--alerts-only` | Generate only alerts |                      |
| `--dry-run` | Does not use OpenAI |                      |
| `--print` | Print output by `stdout` |                      |
| `--stdout-only` | Only writes to `stdout`, does not save file |                      |
| `--output-dir DIR` | Directory where the `.md` are saved |                      |
| `--log-file PATH` | Log file |                      |
| `--verbose` | Detailed logging | |
| `--http-timeout N` | HTTP Timeout in seconds |                      |
| `--location TEXT` | Nominal location for alerts; can be repeated |                      |
| `--geolocation "(lat, lon)"` | Coordinates for alerts; can be repeated |                      |
| `--locations "(a; b; c)"` | Mixed list of locations and/or coordinates |                      |

## Example of `config.json`

```json
{
  "output_dir": "./out",
  "model": "gpt-5-mini",
  "dry_run": false,
  "print": true,
  "stdout_only": false,
  "log_file": "./dailynews.log",
  "verbose": false,
  "http_timeout": 20,

  "source_policy": {
    "mode": "mixed",
    "allow_domains": [
      "nasa.gov",
      "reuters.com",
      "apnews.com",
      "bbc.com"
    ],
    "deny_domains": [],
    "deny_if_source_matches": []
  },

  "profiles": {
    "morning": {
      "topics": ["space_missions", "markets", "general"],
      "max_items": 2,
      "topic_limits": {
        "space_missions": 3,
        "markets": 2,
        "general": 3
      },
      "global_max_items": 8,
      "max_lines": 45,
      "use_openai": true,
      "include_markets": true,
      "include_alerts": true,
      "watchlist": [
        "Review space events with confirmed dates",
        "Look at oil volatility and VIX",
        "Check if any local alerts escalate during the day"
      ]
    },
    "evening": {
      "topics": ["space_missions", "markets", "general", "geopolitics"],
      "max_items": 4,
      "topic_limits": {
        "space_missions": 5,
        "markets": 3,
        "general": 4,
        "geopolitics": 3
      },
      "global_max_items": 14,
      "max_lines": 120,
      "use_openai": true,
      "include_markets": true,
      "include_alerts": true,
      "watchlist": [
        "Distinguish what was confirmed and what remained uncertain,"
        "Separating structural signals from daytime noise",
        "Choose 1 or 2 readings to deepen"
      ]
    }
  },

  "alerts": {
    "enabled": true,
    "targets": [
      { "kind": "name", "value": "Montevideo, Uruguay" },
      { "kind": "name", "value": "Indiana, USA" },
      { "kind": "geo", "lat": -34.48759, "lon": -55.62793, "label": "Migues exact" }
    ],
    "weather_temp_drop_c": 8.0,
    "weather_temp_rise_c": 8.0,
    "wind_gust_kmh": 70.0,
    "air_aqi_us": 100,
    "alert_keywords": [
      "wildfire",
      "smoke",
      "chemical spill",
      "power outage",
      "road closed",
      "evacuation",
      "zoo escaped animal",
      "public health alert"
    ],
    "max_keyword_items": 4
  }
}
```

## Font Policy

The `source_policy` section allows simple filters to be applied.

### Modes

* `off`: does not filter;
* `mixed`: allows everything except what is explicitly blocked;
* `allowlist`: Only allow domains listed in `allow_domains`.

### Example

```json
"source_policy": {
  "mode": "allowlist",
  "allow_domains": [
    "nasa.gov",
    "reuters.com",
    "apnews.com",
    "bbc.com"
  ],
  "deny_domains": [],
  "deny_if_source_matches": []
}
```

## Configuration precedence

The order of precedence is:

1. script defaults;
2. `config.json`;
3. command line parameters.

In other words: the CLI steps on the JSON.

## Output

The program generates Markdown files with names like:

* `morning_brief_YYYYMMDD_HHMMSS.md`
* `evening_digest_YYYYMMDD_HHMMSS.md`
* `alerts_YYYYMMDD_HHMMSS.md`

If `--stdout-only` is used, no file is written.

##Logging

Without `--log-file`, the log is output via `stderr`.

With file:

```bash
python3 dailynews.py --config ./config.json --log-file ./dailynews.log;
```

In more detail:

```bash
python3 dailynews.py --config ./config.json --verbose;
```

## OpenAI and fallback

If OpenAI is enabled and the call works, the program attempts to produce a summary that is more compact and pleasant to read.

If OpenAI fails due to:

* lack of quota;
* service error;
* timeout;
* authentication issue;
* any other exceptions;

the program does not abort: it also generates a raw Markdown from the collected data.

This is intended so that `cron` remains useful even if the summary layer fails.

## Examples for cron

### Daily morning brief

```cron
10 7 * * * export OPENAI_API_KEY="your_api_key"; /usr/bin/python3 /path/dailynews.py --config /path/config.json --profile morning >> /path/dailynews_morning.log 2>&1
```

### Daily evening digest

```cron
30 18 * * * export OPENAI_API_KEY="your_api_key"; /usr/bin/python3 /path/dailynews.py --config /path/config.json --profile evening >> /path/dailynews_evening.log 2>&1
```

### Alerts every hour

```cron
0 * * * * /usr/bin/python3 /path/dailynews.py --config /path/config.json --alerts-only >> /path/dailynews_alerts.log 2>&1
```

### Hourly alerts for a specific location

```cron
0 * * * * /usr/bin/python3 /ruta/dailynews.py --config /ruta/config.json --alerts-only --location "Montevideo, Uruguay" >> /path/alerts_montevideo.log 2>&1
```

## Exit codes

| Code | Meaning |
| ------ | ------------------------ |
| `0` | correct execution |
| `1` | general error |
| `2` | network error |
| `3` | configuration error |
| `130` | interrupted by user |

## Known limitations

* RSS feeds may change or downgrade without notice;
* Keyword searches depend on how the media publishes and titles;
* An “escaped zoo animal” alert depends on it appearing in detectable headlines;
* Google News RSS works in practice, but it should not be assumed as an eternal contract;
* `global_max_items` trims by topic order, not relevance;
* source filtering is simple: domain and source name, not deep semantic analysis;
* still no local geocoding or feed cache.

## Possible improvements

* support for separate `--lat` and `--lon`;
* local cache for geocoding and feeds;
* retries with backoff;
* stance rating by article (`neutral`, `favorable`, `critical`, `unclear`);
* balanced grouping of perspectives in the evening digest;
* additional output in JSON;
* integration with mail, Telegram or `ntfy`.

##License

```
  Copyright 2018- William Martinez Bas <metfar@gmail.com>

  This program is free software; you can redistribute it and/or modify
  it under the terms of the GNU General Public License as published by
  the Free Software Foundation; either version 2 of the License, or
  (at your option) any later version.

  This program is distributed in the hope that it will be useful,
  but WITHOUT ANY WARRANTY; without even the implied warranty of
  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
  GNU General Public License for more details.

  You should have received a copy of the GNU General Public License
  along with this program; if not, write to the Free Software
  Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston,
  MA 02110-1301, USA.
```


<p align=center><b>- oOo -</b></p>
