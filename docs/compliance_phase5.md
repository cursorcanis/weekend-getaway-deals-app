# Phase 5 compliance review: direct terme sources and transit timetables

Checked 2026-10-13 by the `scraping-compliance-reviewer` agent (read-only, robots.txt fetched live).
Re-check before implementing anything marked NOT VERIFIED, and re-check any source yearly.

**Summary.** None of the terme sites offers an API, feed or affiliate programme, and most show either
"from" prices for 2 adults or no prices at all. The real 2+2 family price for terme hotels comes from the
existing SerpApi / Google Hotels adapter. For transit, use open GTFS feeds; never automate Trenitalia,
Viaggiatreno or Italo.

## (a) Terme / spa sources

Conditions for every row marked APPROVED WITH CONDITIONS:

- Fetch the static offers listing page only, never a booking engine.
- At most 1 request every 2 s per host; poll every 12 h; 12 h cache; conditional GET (ETag / If-Modified-Since).
- Identifiable User-Agent, e.g. `WeekendGetawayDeals/0.x (personal, non-commercial)`, with no personal email.
- Stop on 403 / 429; never work around blocking.
- Store parsed facts (property, offer title, price, dates, URL) and the link, not copied text or images.
  No GDPR exposure: the pages contain no personal data.

| # | Source | Verdict | Notes |
|---|---|---|---|
| 1 | Bormio Terme (bormioterme.it) | Approved with conditions, low value | robots.txt `Allow: /`, `Disallow: /booking/`. `/offerte` is a 404; `/magazine/promozioni/` has day tickets (family ticket 2 adults + 3 children €122), no hotel packages. Use as hand-maintained reference price. Unconfirmed whether a 15-year-old counts as a child. |
| 2 | Terme di Sirmione (termedisirmione.com) | **Not verified, on hold** | All fetches failed (possible bot protection). Packages under `/pacchetto-esperienza/<slug>/`; "Terme in treno" gives a weekend rail discount. Check robots.txt and terms by hand; cover hotels via SerpApi meanwhile. |
| 3 | Terme di Saturnia (termedisaturnia.it) | Approved with conditions (offer list only) | robots.txt `Disallow: /wp-admin/`. Offers at `/resort/offerte/` (11 offers, no prices). Prices only in Synxis engine (be.synxis.com) – do not automate. |
| 4 | Terme Merano (termemerano.it) | Approved with conditions | robots.txt blocks `Go-http-client`; for `*` disallows `/*offer=*`, `/*offerId=*`, `/*arrival=*`, `/*date-start=*`, `/*room=*`, `/*roomId=*`. Poll only `/de/services/urlaubspakete/`. Packages are couple/per-person, low family value. |
| 5 | Terme Antica Querciolaia (termeaq.it) | Approved with conditions | robots.txt allows everything. No offers section; day tariffs at `it/menu/3/tariffe`. Weekly at most. bookingtermeaq.it and residenzeaq.it not checked. |
| 6 | Grotta Giusti (grottagiustispa.com) | Approved with conditions (offer pages); avoid booking | robots.txt allows all. Offers at `/offerte-pacchetti/`, "from" prices per person in a double. Booking is Marriott – do not automate. Use SerpApi for the 2+2 price. |
| 7 | Calidario (calidario.it) | Approved with conditions, low value | WooCommerce-default robots.txt. No offers URL. Footer forbids copying content: store price facts and link only. Spa engine (zucchettiwellness.it) – avoid. |
| 8 | Terme dei Papi (termedeipapi.it) | **Not verified** | Fetches failed. Only day packages found; hotel (Niccolò V) is on Google Hotels – use SerpApi. |
| 9 | QC Terme (qcterme.com) | **Avoid (policy)** | 2026 rules: "Non è consentito l'accesso al centro termale ai minori di 14 anni". The 7-year-old is barred; no adapter. |
| 10 | Firecrawl | No compliance effect | Its ToS puts compliance on the user; target-site rules still apply. Unnecessary for these static pages. |

Aggregators: Booking.com Demand API requires a contracted Managed Affiliate Partner (not viable for a private tool);
Secret Escapes / Voyage Privé affiliate programmes need a publishing website (not viable).

**Recommendation (a)**

1. First add the terme resort hotels as named SerpApi targets (Saturnia resort, Grotta Giusti, Grand Hotel Terme Sirmione,
   Niccolò V, Calidario, Bormio partner hotels).
2. Then an offer-change detector for Saturnia `/resort/offerte/`, Grotta Giusti `/offerte-pacchetti/` and
   Merano `/de/services/urlaubspakete/`: alert on new or changed offer titles and validity periods, with the link.
   Don't extract a family price from these pages.
3. Bormio, Querciolaia and Terme dei Papi day-ticket prices: hand-maintained reference data, not polled.
4. Sirmione and Terme dei Papi: on hold until a human checks robots.txt and terms.

## (b) Transit timetables

| # | Source | Verdict | Notes |
|---|---|---|---|
| 1 | Trenitalia / lefrecce.it | **Avoid automation** | No public API. Site terms allow personal, non-commercial use and forbid "ogni utilizzo dei contenuti del Sito in un altro Sito, server o ambiente informatico". The app JSON endpoints are unauthorised. Use only as a deep link in alerts. |
| 2 | Viaggiatreno | **Avoid** | 403 to fetchers; undocumented endpoints; real-time status, not planning. |
| 3 | Italo | **Avoid** | Note legali §7 same prohibition as Trenitalia; doesn't serve Santa Margherita Ligure. |
| 4a | Trenitalia national GTFS (Mobility Database mdb-1052, `sardegnamobilita.it/opendata/dati_trenitalia.zip`) | Approved with conditions, licence unverified | No licence stated; service 6 Jun – 12 Dec 2026. Liguria regional coverage unconfirmed. Weekly download at most, attribute, don't redistribute. |
| 4b | Italian NAP / RAP Liguria | Not verified | NeTEx, licence unknown, may need login. Contact labtpl@regione.liguria.it. |
| 4c | AMT Genova GTFS (`amt.genova.it/amt/GTFS/GTFS_AMT_GENOVA.zip`) | Approved with conditions | CC BY 4.0 (attribute "AMT Genova"). Check whether ex-ATP Tigullio lines (Santa Margherita) are included. |
| 4d | ATP Esercizio GTFS | Not found | Probably merged into AMT (2021). |
| 5a | Transitous API | Conditional on open-sourcing the repo | Policy requires open-source, non-commercial, identifying User-Agent, attribution. Private repo does not qualify. |
| 5b | Google Routes API (transit) | Approved with conditions | Free monthly tier covers our volume. Cache ≤ 30 days (from secondary sources; current terms not opened), Google attribution, no permanent timetable DB. |
| 5c | Navitia | Avoid | No current Italian coverage found. |

**Recommendation (b)**

1. Primary: keep the static reachability catalogue, verified by a weekly offline job doing self-hosted routing
   (GTFS connection scan, or MOTIS / OpenTripPlanner) over Trenitalia GTFS + AMT Genova GTFS.
2. Secondary, live check before an alert: Google Routes API transit mode, free tier, cache ≤ 30 days, attribution.
3. Never call lefrecce, Viaggiatreno or Italo automatically; put a lefrecce.it link in alerts for manual checking.
4. Before relying on GTFS: confirm the Trenitalia GTFS licence (Trenitalia / BusOne) and ask RAP Liguria about a Liguria feed.

## Open questions

- Sirmione and Terme dei Papi robots.txt and terms (sites unreachable to fetchers).
- Trenitalia GTFS licence; RAP Liguria licence; whether AMT GTFS includes the Tigullio lines.
- Google Routes caching clause and which SKU transit mode bills as.
- Bormio Terme's age limit for "bambini".
