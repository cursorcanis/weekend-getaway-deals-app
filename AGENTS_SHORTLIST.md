# Agent & tool shortlist — Weekend Getaway Deals (Italy)

Goal of the app: find hotel and thermal-bath (terme) deals in Italy for a
**Friday → Sunday-night** stay, **2 adults + children aged 15 and 7**.

Vetted on GitHub on **2026-10-12**. Criteria, in order:

1. **Who publishes it** — vendor-official (Anthropic, Microsoft, the data
   provider itself) beats an individual's repo.
2. **Security posture** — a `SECURITY.md`/disclosure policy, an OSI license,
   CI, and no install script that runs unreviewed code.
3. **Maintenance** — pushed within the last month, not archived.
4. **Adoption** — stars are a weak signal on their own; used only as a
   tie-breaker.

No third-party code was downloaded or installed. Everything below is opt-in.

---

## Tier 1 — install these (vendor-official, actively maintained)

| # | What | Repo | Stars | License | Last push | Why for this app |
|---|---|---|---|---|---|---|
| 1 | **Playwright MCP** | [microsoft/playwright-mcp](https://github.com/microsoft/playwright-mcp) | 38k | Apache-2.0 | 2026-10-08 | Lets Claude drive a real browser to inspect hotel/terme sites, test your own UI, and prototype scrapers. Has `SECURITY.md` (Microsoft MSRC). |
| 2 | **Official Claude Code plugins** | [anthropics/claude-plugins-official](https://github.com/anthropics/claude-plugins-official) | 38k | Apache-2.0 | 2026-10-12 | Use `security-guidance`, `code-review`, `pr-review-toolkit`, `feature-dev`, `frontend-design`, and the LSP plugin for your language (`pyright-lsp` or `typescript-lsp`). |
| 3 | **Claude Code Security Review** | [anthropics/claude-code-security-review](https://github.com/anthropics/claude-code-security-review) | 6.4k | MIT | 2026-02-11 | GitHub Action that security-reviews every PR. Note: not hardened against prompt injection — require approval for outside contributors' PRs. |
| 4 | **Context7 MCP** | [upstash/context7](https://github.com/upstash/context7) | 63k | MIT | 2026-10-12 | Pulls current library docs (FastAPI, Next.js, httpx…) into context so Claude doesn't code against stale APIs. Has `SECURITY.md`. |
| 5 | **GitHub MCP server** | [github/github-mcp-server](https://github.com/github/github-mcp-server) | 34k | MIT | 2026-10-12 | Issues/PRs/Actions from inside Claude Code. Only if you host the project on GitHub. |

## Tier 2 — security-specialist skills (reputable, read before enabling)

| # | What | Repo | Stars | License | Last push | Use |
|---|---|---|---|---|---|---|
| 6 | **Trail of Bits skills** | [trailofbits/skills](https://github.com/trailofbits/skills) | 7.5k | CC-BY-SA-4.0 | 2026-10-09 | From a professional security-audit firm. Pick `insecure-defaults`, `supply-chain-risk-auditor`, `static-analysis`, `differential-review`, `modern-python`. Has `CODEOWNERS` + pre-commit. |

## Tier 3 — deal-data sources (the app's core; choose one or two)

The app's value is the data, and **scraping booking sites directly is usually
against their Terms of Service**. Prefer an official/licensed API.

| # | Source | Repo / access | Fits the brief? | Notes |
|---|---|---|---|---|
| 7 | **SerpApi Google Hotels** | [serpapi/serpapi-mcp](https://github.com/serpapi/serpapi-mcp) (179★, MIT, pushed 2026-10-12) | **Yes** — `adults=2`, `children=2`, `children_ages=15,7`, `check_in_date`/`check_out_date`, `gl=it`, `currency=EUR`, `amenities` (spa), `hotel_class` | Paid API key. Aggregates prices across Booking, Expedia, hotel sites. Easiest path to a working MVP. |
| 8 | **Apify MCP** | [apify/apify-mcp-server](https://github.com/apify/apify-mcp-server) (10.8k★, MIT, has `SECURITY.md`) | Partly | Marketplace of scrapers ("Actors"), incl. Booking.com. Actors are third-party — check each one's ToS exposure. Good for terme sites that have no API. |
| 9 | **Firecrawl MCP** | [firecrawl/firecrawl-mcp-server](https://github.com/firecrawl/firecrawl-mcp-server) (7.6k★, MIT) | Partly | Turns individual websites (e.g. a spa resort's offers page) into clean markdown. Respect `robots.txt`. |
| 10 | **Booking.com Demand API / Expedia Rapid API** | Partner programmes, no MCP | Yes | Official, licensed — requires an affiliate/partner application. The right long-term answer if the app ever goes public. |

## Rejected — and why

| Candidate | Reason |
|---|---|
| Any **Amadeus** hotel MCP (`travel-amadeus-mcp`, `lev-corrupted/travel-mcp-server`, …) | Amadeus **shut down its Self-Service API portal on 2026-07-17**; keys no longer work. `amadeus4dev/amadeus-python` is archived. Enterprise access only. |
| `esakrissa/hotels_mcp_server` | 29 stars, no push since 2025-03, single maintainer, goes through an unofficial RapidAPI wrapper. |
| `lst97/claude-code-sub-agents` | No push since 2025-08. |
| `wshobson/agents` (40k★) and `VoltAgent/awesome-claude-code-subagents` (26k★) | **Not rejected, but not auto-installed.** Popular, MIT, active — but community-written prompts with no independent audit. VoltAgent ships an `install-agents.sh`; don't run it blind. Cherry-pick individual `.md` files (e.g. `python-pro`, `backend-architect`, `security-auditor`) after reading them. |

---

## Project-local agents already added

Written for this project (no third-party content) in `.claude/agents/`.
Claude Code picks them up automatically when working in this folder:

| Agent | Use it for |
|---|---|
| `deal-search-engineer` | Data-source integration, the Fri→Sun date logic, family-occupancy rules, price normalisation. |
| `scraping-compliance-reviewer` | Checking any new data source against ToS, `robots.txt`, rate limits and GDPR before code is written. |
| `security-reviewer` | Secrets, dependency risk, SSRF/injection in anything that fetches URLs. |

## How to install Tier 1 (run from this folder in a terminal)

```bash
claude mcp add --scope project playwright -- npx @playwright/mcp@latest
```

```bash
claude mcp add --scope project context7 -- npx -y @upstash/context7-mcp
```

```bash
claude plugin marketplace add anthropics/claude-plugins-official
```

Then inside Claude Code: `/plugin install security-guidance@claude-plugins-official`
(repeat for `code-review`, `feature-dev`, `frontend-design`, and your LSP).

Pin versions (`@playwright/mcp@<version>`) once the project is stable, so an
upstream release can't change your tools under you. Keep API keys in a `.env`
that is git-ignored, never in `.mcp.json`.

## Open decision

"Friday to Sunday night" can mean **2 nights** (check in Fri, check out Sun)
or **3 nights** (Fri, Sat and Sun nights; check out Mon). `deal-search-engineer`
is told to ask rather than guess.
