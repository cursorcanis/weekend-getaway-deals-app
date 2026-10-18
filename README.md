# Weekend Getaway Deals

An unattended service that searches for weekend hotel and thermal-spa (*terme*) deals in Italy for a family of four. It sends a Telegram or email alert only when a deal is new or meaningfully cheaper. Python, SQLite, SerpApi (Google Hotels), Google Routes API.

## The problem

Booking sites can't search the way this family travels:

- **No car, no flights.** The destination has to be reachable by train or bus from the Ligurian coast in 7 hours (soft limit 8).
- **Real family pricing.** Two adults and two children in one family room, or two rooms if there's no family room. Many Italian hotels and terme charge a teenager the adult rate, so the app never assumes a child discount for them.
- **Weekends only.** Friday to Sunday, extended to three nights on Italian public-holiday weekends (*ponti*), including Easter.

## How it works

```
weekend dates ─┐
               ├─► search (SerpApi) ─► filter ─► rank ─► SQLite price history ─► alert if new / cheaper
100 reachable ─┘                                                                  (Telegram / email)
destinations
```

1. **Dates.** Generates the next N weekends and adds a Monday night when a national holiday falls on it.
2. **Destinations.** A catalogue of 100 destinations (`data/destinations.yaml`) with train/bus times from the origin station. Five terme resorts are also searched by name, and two resort offer pages are watched for new package titles.
3. **Search.** Each (destination, weekend) pair is one SerpApi search. Runs are capped at 20 searches and results are cached for 12 hours. Successive runs rotate through all pairs, so the cap spreads coverage over time instead of repeating the nearest destinations.
4. **Rank.** Over-budget deals are dropped, the cheapest offer per property is kept, and each deal gets a 0–100 score:

   | Factor | Points |
   |---|---|
   | Price per night vs. the cheapest in the run | 50 |
   | Discount vs. usual price (capped at 40%) | 15 |
   | Guest review score | 15 |
   | Shorter travel time | 10 |
   | Breakfast included, spa the whole family can use | 10 |

5. **Store and alert.** Every deal is written to SQLite. A deal triggers an alert when it scores at least 60 and has never been alerted, or when it's at least €30 cheaper than its last alert. Alerts are marked sent only after a channel confirms delivery.
6. **Optional live transit check.** With a Google Maps key, each alert's check-in-day journey is checked through the Routes API, and the deal is dropped if the trip runs over the limit.

## Engineering notes

- **Compliance first.** Every data source passed a terms-of-service, robots.txt and rate-limit review before it was added (`docs/compliance_phase5.md`). Offer pages are read for titles and links only. A page that returns 403 or 429 is paused until manually unblocked. Trenitalia and Italo are never called automatically.
- **Pluggable sources.** Each source implements one adapter interface (`src/sources/base.py`), so adding a source doesn't touch ranking or alerting.
- **Hermetic tests.** 75 tests run against recorded API responses, with no network calls.
- **Runs on a home PC.** On Windows, a Task Scheduler job (`scripts/install_task.ps1`) runs one cycle every 12 hours, so runs survive sleep and reboots. Logs rotate at 1 MB.
- **Read-only dashboard.** `--dashboard` serves stored deals on localhost using only the standard library.
- **Built with Claude Code subagents.** `.claude/agents/` defines the roles used during development: architect, sourcing, transit, ranking, scheduling, QA, plus read-only compliance and security reviewers.

## Run it

```bash
pip install -r requirements.txt
cp .env.example .env                        # add SERPAPI_API_KEY; alert channels are optional

python -m src.cli --demo                    # offline, uses a recorded sample response
python -m src.cli --plan                    # list the searches a live run would make
python -m src.cli --demo --once --dry-run   # offline: full search -> store -> alert cycle
python -m src.cli --once                    # one live cycle
python -m src.cli --daemon                  # repeat every POLL_INTERVAL_HOURS (default 12)
python -m src.cli --dashboard               # http://127.0.0.1:8765/
python -m pytest
```

Party, origin, travel limits, budget and alert thresholds are all set in `.env` (see `.env.example`). None of them are hard-coded.

## Repository

```
src/sources/    SerpApi adapter, terme offer-page watcher
src/engine/     date rules (weekends, holidays, Easter), ranking, alert decisions
src/storage/    SQLite store and price history
src/notify/     Telegram and email channels
transit/        static reachability catalogue, live Google Routes check
data/           destinations, terme resorts, offer pages (YAML)
docs/           architecture, data sources, compliance review
scripts/        Windows Task Scheduler install and run scripts
```

`docs/architecture.md` is the original design spec. Where it differs from the code (it proposed APScheduler, SQLAlchemy and Typer), the code went with simpler choices.
