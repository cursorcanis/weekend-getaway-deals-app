# Weekend Getaway Deals

A long-running service that continuously searches for weekend deals on **hotels** and **thermal baths (terme / spa hotels)** in Italy and sends alerts when good options appear.

## Hard requirements

- **Party:** family of 4 — 2 adults + 2 children aged **15** and **7**. Every price must be for this exact occupancy (one family room, or two connecting rooms if no family room exists). Note: many Italian hotels and terme price a 15-year-old as an adult — never assume child pricing for them.
- **Dates:** weekend stays only — check-in **Friday**, check-out **Sunday** (2 nights: Friday + Saturday). Optionally check-out Monday to cover Sunday night on long weekends / Italian public holidays (configurable).
- **Origin:** Santa Margherita Ligure (GE), Liguria. Nearest stations: Santa Margherita Ligure–Portofino (train), plus local buses (AMT/ATP).
- **Reachability:** the destination must be reachable **by train and/or bus** from Santa Margherita Ligure in **≤ 7–8 hours door-to-door** (configurable; default 7h, soft limit 8h). No car, no flights.
- **Scope:** Italy only.
- **Runs continuously:** scheduled polling, deduplication, and alerts only for new or meaningfully cheaper deals.

## Agents

Project-specific subagents live in `.claude/agents/`:

| Agent | Responsibility |
|---|---|
| `architect` | Overall design, tech stack, data model, module boundaries, roadmap |
| `deal-sourcing` | Hotel & terme data sources (APIs, feeds, scrapers), normalization into a common `Deal` model |
| `transit-reachability` | Train/bus travel times from Santa Margherita Ligure; reachable-destination list |
| `deal-filter-ranker` | Family occupancy, Fri–Sun date rules, price normalization, scoring, dedup |
| `scheduler-notifier` | Continuous run loop/scheduler, persistence, alert delivery (email/Telegram), deployment |
| `qa-reviewer` | Tests, fixtures, and review of changes against the hard requirements above |

## Conventions

- Configuration (party, origin, max travel hours, budget, alert channels) lives in one config file — never hard-code it.
- Secrets (API keys, SMTP/Telegram tokens) come from environment variables / `.env`, never committed.
- Respect each source's Terms of Service and robots.txt; prefer official/affiliate APIs over scraping; rate-limit all network calls.
