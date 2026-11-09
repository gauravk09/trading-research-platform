# launchers

Double-click scripts for macOS (or run them from a terminal at the repo root). Each one changes into the
repo root itself, so it works from wherever you start it.

## data/

| Script | What it does |
|---|---|
| `refresh_kite_token.command` | Opens the Zerodha login and saves today's Kite token. Needed every morning (the token expires at 6 AM IST). |
| `update_data.command` | Runs the full nightly update by hand, the same job as the 8 PM cron. Safe during market hours. |

## dashboards/

| Script | What it does |
|---|---|
| `run_dashboard.command` | Starts the web dashboard (API on 8700, page on 5173), the live scanner (8602) and the F&O IV feed, then opens the browser. Closing the window stops them. Restarting also restarts the live scanner so it reloads today's token. |
| `run_fno_dashboard.command` | Same as above, but opens straight on the F&O Board. |
| `run_fund_study.command` | Standalone SBI Contra Fund study on separate ports (8710, 5180), so the trading dashboard can keep running. |

The 8 PM cron does not use these. It runs `src/eod_update_cron.sh`, which stays in `src/` because your crontab points at that path.
