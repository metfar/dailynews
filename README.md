# dailynews.py

`dailynews.py` is a **Markdown** news reader intended to be used from the terminal, `cron`, or automation scripts.  
The project can also be used with `dailynews_gui.py`, a `tkinter` desktop frontend that reads the generated Markdown files and presents them in a more visual way.

`dailynews.py` is not intended to replace human judgment or become a living geopolitical oracle. It is a practical tool to read better: first orient yourself, then go deeper, and meanwhile avoid missing relevant alerts.

The idea of the project is to imitate the classic rhythm of reading a daily newspaper:

- **morning**: a short reading to get your bearings;
- **evening**: a broader reading to go deeper;
- **every hour**: a check for local or urgent alerts.

The program combines:

- RSS feeds for news;
- market snapshots with `yfinance`;
- weather and air quality alerts with Open-Meteo;
- keyword alerts;
- optional summaries with OpenAI;
- automatic fallback to raw Markdown if OpenAI fails.

## Index

- [Use philosophy](#use-philosophy)
- [Requirements](#requirements)
- [Dependencies](#dependencies)
- [Main files](#main-files)
- [Profiles](#profiles)
  - [morning](#morning)
  - [evening](#evening)
- [Alerts mode](#alerts-mode)
- [Installation](#installation)
- [Basic use](#basic-use)
  - [Morning brief](#morning-brief)
  - [Evening digest](#evening-digest)
  - [Alerts only](#alerts-only)
  - [Mode without OpenAI](#mode-without-openai)
- [Graphical frontend](#graphical-frontend)
  - [Start the GUI](#start-the-gui)
- [Alert targets](#alert-targets)
  - [A named location](#a-named-location)
  - [Exact coordinates](#exact-coordinates)
  - [Multiple mixed locations](#multiple-mixed-locations)
  - [Multiple locations by repeating flags](#multiple-locations-by-repeating-flags)
- [Command-line parameters](#command-line-parameters)
- [Example `config.json`](#example-configjson)
- [Source policy](#source-policy)
  - [Modes](#modes)
  - [Example](#example)
- [Configuration precedence](#configuration-precedence)
- [Output](#output)
- [GUI workflow](#gui-workflow)
- [Logging](#logging)
- [OpenAI and fallback](#openai-and-fallback)
- [Examples for cron](#examples-for-cron)
  - [Daily morning brief](#daily-morning-brief)
  - [Daily evening digest](#daily-evening-digest)
  - [Alerts every hour](#alerts-every-hour)
  - [Hourly alerts for a specific location](#hourly-alerts-for-a-specific-location)
- [Exit codes](#exit-codes)
- [Known limitations](#known-limitations)
- [Possible improvements](#possible-improvements)
- [License](#license)

## Features

- `morning` and `evening` profiles;
- `--alerts-only` mode;
- output in **Markdown**;
- optional `tkinter` GUI frontend with visual navigation;
- configuration through `config.json`;
- command-line overrides;
- alert targets by name or coordinates;
- multiple locations in a single run;
- source filters through a simple policy (`off`, `mixed`, `allowlist`);
- navigation by date, run time, profile, and article inside the GUI;
- dark card-style rendering for articles and alerts inside the GUI;
- output to file and/or `stdout`;
- logging to `stderr` or to a file;
- automatic fallback if OpenAI does not respond or has no quota;
- limits by topic, global item count, and maximum number of lines.

## Use philosophy

This script does not attempt to "think for the user". It tries to:

- deliver a quick information base in the morning;
- allow more reflective reading in the evening;
- point out useful alerts during the day;
- reduce noise without pretending to offer absolute objectivity.

## Requirements

- Python 3.10 or higher;
- Internet access;
- optional OpenAI API key, only for assisted summaries.

## Dependencies

Recommended installation:

```bash
python3 -m pip install --upgrade openai requests feedparser yfinance;
```

`tkinter` is part of the standard Python installation in most desktop distributions. If your system packages it separately, install the corresponding Tk package for your platform.

## Main files

- `dailynews.py`
- `dailynews_gui.py`
- `config.json`

## Profiles

### `morning`

Designed for breakfast or quick reading:

- fewer items;
- fewer lines;
- focus on orientation;
- includes alerts if enabled.

### `evening`

Designed for the afternoon or end of the day:

- more context;
- more items;
- more space for tracking and watchlist;
- includes alerts if enabled.

## Alerts mode

`--alerts-only` generates a quick alert check without producing the full digest.

It is intended for hourly runs with `cron`, for example to detect:

- sudden temperature changes;
- intense gusts;
- poor air quality;
- urgent news associated with configured keywords.

## Installation

1. Save `dailynews.py`.
2. Save `dailynews_gui.py` if you want the desktop frontend.
3. Save `config.json`.
4. Install dependencies.
5. If you want summaries with OpenAI, export the key:

```bash
export OPENAI_API_KEY="your_api_key";
```

6. Give execution permissions if necessary:

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

## Graphical frontend

`dailynews_gui.py` is a `tkinter` frontend intended to run in the same directory as `dailynews.py` and `config.json`.

The GUI does not replace the collector. It sits on top of the existing Markdown output and provides a friendlier reading workflow.

Main ideas of the GUI:

- read generated `.md` files from `output_dir`;
- organize the history by **date -> time -> profile -> article**;
- keep alerts in their own tab so they do not pollute the normal reading flow;
- render articles and alerts as dark cards with title, source, date, summary, and link;
- open the article URL in the default browser;
- allow manual execution of `morning`, `evening`, and `alerts` runs;
- keep a run log visible inside the application.

### Start the GUI

```bash
python3 dailynews_gui.py;
```

The GUI expects `dailynews.py` and `config.json` to be available in the same working directory.

## Alert targets

Alerts accept locations by name and by coordinates.

### A named location

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

### Multiple locations by repeating flags

```bash
python3 dailynews.py --config ./config.json --alerts-only \
  --location "Montevideo, Uruguay" \
  --location "Indiana, USA" \
  --geolocation "(-34.48759, -55.62793)";
```

## Command-line parameters

| Parameter | Description |
| ---------------------------- | -------------------------------------------- |
| `--config PATH` | Path to the `config.json` file |
| `--profile morning/evening` | Select the profile |
| `--alerts-only` | Generate only alerts |
| `--dry-run` | Do not use OpenAI |
| `--print` | Print output to `stdout` |
| `--stdout-only` | Only write to `stdout`; do not save a file |
| `--output-dir DIR` | Directory where `.md` files are saved |
| `--log-file PATH` | Log file path |
| `--verbose` | Detailed logging |
| `--http-timeout N` | HTTP timeout in seconds |
| `--location TEXT` | Named location for alerts; can be repeated |
| `--geolocation "(lat, lon)"` | Coordinates for alerts; can be repeated |
| `--locations "(a; b; c)"` | Mixed list of locations and/or coordinates |

## Example `config.json`

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
        "Check whether any local alerts escalate during the day"
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
        "Distinguish what was confirmed and what remained uncertain",
        "Separate structural signals from daytime noise",
        "Choose 1 or 2 readings to explore more deeply"
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

## Source policy

The `source_policy` section allows simple filters to be applied.

### Modes

- `off`: do not filter;
- `mixed`: allow everything except what is explicitly blocked;
- `allowlist`: only allow domains listed in `allow_domains`.

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
3. command-line parameters.

In other words: the CLI overrides the JSON.

## Output

The program generates Markdown files with names such as:

- `morning_brief_YYYYMMDD_HHMMSS.md`
- `evening_digest_YYYYMMDD_HHMMSS.md`
- `alerts_YYYYMMDD_HHMMSS.md`

If `--stdout-only` is used, no file is written.

The GUI reads those generated Markdown files directly and uses their timestamps to build the navigation tree.

## GUI workflow

A typical workflow can be:

1. let `cron` generate morning, evening, and alerts runs;
2. open `dailynews_gui.py` later;
3. browse runs by date and time;
4. enter a profile and then a specific article;
5. switch to the **Alerts** tab when reviewing urgent items;
6. open the original article in the default browser when deeper reading is needed.

## Logging

Without `--log-file`, the log is written to `stderr`.

With a file:

```bash
python3 dailynews.py --config ./config.json --log-file ./dailynews.log;
```

With more detail:

```bash
python3 dailynews.py --config ./config.json --verbose;
```

## OpenAI and fallback

If OpenAI is enabled and the call works, the program attempts to produce a summary that is more compact and pleasant to read.

If OpenAI fails because of:

- lack of quota;
- service error;
- timeout;
- authentication issue;
- any other exception;

the program does not abort: it still generates raw Markdown from the collected data.

This is intended to keep `cron` useful even if the summary layer fails.

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
0 * * * * /usr/bin/python3 /path/dailynews.py --config /path/config.json --alerts-only --location "Montevideo, Uruguay" >> /path/alerts_montevideo.log 2>&1
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

- RSS feeds may change or degrade without notice;
- keyword searches depend on how media outlets publish and title their stories;
- an “escaped zoo animal” alert depends on it appearing in detectable headlines;
- Google News RSS works in practice, but it should not be treated as an eternal contract;
- `global_max_items` trims by topic order, not by relevance;
- source filtering is simple: domain and source name, not deep semantic analysis;
- there is still no local geocoding or feed cache;
- the GUI currently renders from generated Markdown, so its parser depends on the output structure remaining reasonably stable;
- the GUI is intentionally conservative and still does not implement full `config.json` editing.

## Possible improvements

- support for separate `--lat` and `--lon`;
- local cache for geocoding and feeds;
- retries with backoff;
- stance rating by article (`neutral`, `favorable`, `critical`, `unclear`);
- balanced grouping of perspectives in the evening digest;
- additional output in JSON;
- integration with mail, Telegram, or `ntfy`;
- a settings editor for `config.json` inside the GUI;
- optional migration from Markdown parsing to native JSON rendering in the GUI.

## License

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
