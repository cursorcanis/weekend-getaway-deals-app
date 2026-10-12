# Data Source Research & Evaluation Specification: Weekend Getaway Deals (Italy)

**Target Scenario:** Continuous discovery of weekend hotel and thermal-bath (*terme*) deals in Italy for a family of 4 (2 adults + 2 children aged 15 and 7), departing Friday and returning Sunday.

---

## 1. Executive Summary & Source Strategy

Finding weekend getaways in Italy for this specific party requires combining standard hospitality booking channels with thermal spa access intelligence. Off-the-shelf booking tools do not check thermal bath child admission restrictions or clearly distinguish when a 15-year-old triggers adult room and tax rates.

### 1.1 Multi-Tier Source Architecture

We adopt a three-tier data sourcing strategy:

```
┌────────────────────────────────────────────────────────────────────────┐
│                        Tier 1: Primary MVP Source                      │
│                      SerpApi (Google Hotels Engine)                    │
│   • Multi-OTA & Direct Hotel aggregator                                │
│   • Exact occupancy parameters (adults=2, children=2, ages=15,7)       │
│   • Filter by amenities (spa, pool, breakfast) & hotel class           │
└──────────────────────────────────┬─────────────────────────────────────┘
                                   │
                                   ▼
┌────────────────────────────────────────────────────────────────────────┐
│                   Tier 2: Direct Terme / Spa Adapters                  │
│       Targeted Scraping & Package Parsers (HTTPX / Firecrawl)          │
│   • Family-friendly thermal centers (Saturnia, Bormio, Sirmione, etc.) │
│   • Spa admission packages & weekend stay bundles                      │
│   • Validation of child admission restrictions (7yo eligibility)       │
└──────────────────────────────────┬─────────────────────────────────────┘
                                   │
                                   ▼
┌────────────────────────────────────────────────────────────────────────┐
│                 Tier 3: Long-Term Official Partner APIs                │
│              Expedia Rapid API v3 & Booking.com Demand API             │
│   • High-volume commercial feeds, licensed room-level availability     │
│   • Requires affiliate partner accreditation                           │
└────────────────────────────────────────────────────────────────────────┘
```

### 1.2 Core Finding: Thermal Spa Child Admission Policies

A key architectural insight from this evaluation is that **thermal bath access rules in Italy vary dramatically by operator**:

| Thermal Destination / Operator | Minimum Age Policy | Family Eligibility (15yo & 7yo) | Key Facilities & Restrictions |
|---|---|---|---|
| **QC Terme**<br>*(Pré-Saint-Didier, San Pellegrino, Bormio Bagni Vecchi & Nuovi, Roma, Dolomiti)* | **Strictly 14+ years** | ❌ **Ineligible for family** (7yo barred) | Adults and teens 14+ only. The entire wellness circuit excludes children under 14. Cannot be recommended for the full family of 4. |
| **Terme di Saturnia (Parco Termale)** | All ages permitted in dedicated pools; **14+ or >1.50m** for main deep pools & waterfalls | ✅ **Eligible** (with zone restrictions) | 2 dedicated children's pools (0.7m deep). 7yo cannot enter deep falls/rapids. Cascate del Mulino (free public pools) open to all. |
| **Bormio Terme**<br>*(Civic / Family Thermal Spa)* | **All ages permitted** (0+) | ✅ **Fully Eligible** (High recommendation) | Dedicated children's pools, mushroom water features, 60m thermal waterslide (10+). Distinct from QC Terme Bagni Vecchi/Nuovi. |
| **Terme di Sirmione (Aquaria Thermal SPA)** | **2.5 years (30 months)** | ✅ **Fully Eligible** | Children aged 2.5 to 16 admitted when accompanied by adults. Junior rates available. Quiet relaxation rooms restricted. |
| **Terme Merano** | **All ages permitted** in pools; **14+** for saunas | ✅ **Fully Eligible** (High recommendation) | Dedicated indoor/outdoor family pools, family ticket packages (2 adults + kids <14). Saunas are strictly 14+. |
| **Terme Antica Querciolaia (Rapolano Terme)** | **All ages permitted** | ✅ **Fully Eligible** | Free for <2yo, reduced rate for 2–9yo. Pediatric thermal treatments available. |
| **La Posta Hotel & Thermal Spa**<br>*(formerly Posta Marcucci, Bagno Vignoni)* | **Strictly 14+ years (Adults Only)** | ❌ **Ineligible for family** (7yo barred) | Historic thermal pool hotel converted to adults/teens 14+ only. Alternative for Val d'Orcia: Adler Spa Resort Thermae (has Aki Kids Club 4+). |
| **Abano Terme & Montegrotto Terme**<br>*(Thermal Hotel Spas)* | Hotel-dependent; many dedicated **Family Thermal Hotels** | ✅ **Highly Eligible** | Top family hotels: *Hotel Antoniano*, *Hotel Terme Bologna*, *Hotel Terme Millepini*, *Hotel Terme Venezia*. Indoor/outdoor thermal pools open to children. |

---

## 2. Occupancy & Italian Hospitality Rules (2A + 15yo + 7yo)

### 2.1 The "15-Year-Old Adult" Rule
In the Italian hospitality industry and European travel standards:
1. **Hotel Rooms:** Children aged 12, 14, or 15 are almost uniformly treated as adult guests for bedding, extra bed supplements (*terzo/quarto letto*), and meal plans. An inquiry for 2 adults and 2 children aged 15 and 7 must be priced as **3 adults + 1 child** in engines that cut off childhood at 12 or 14.
2. **SerpApi / Google Hotels Automation:** Passing `adults=2`, `children=2`, `children_ages=15,7` allows Google Hotels to query underlying inventory providers (Booking.com, Expedia, Agoda, direct brand engines) with the child's exact age. Google's engine automatically applies the partner's age classification matrix.

### 2.2 Family Room vs. Multiple Rooms
* **Single Family Room / Suite:** Accommodates 4 guests (e.g., King/Double bed + 2 twin beds or double sofa bed). Typically 25%–40% cheaper than 2 separate rooms.
* **Two Connecting/Adjacent Rooms:** Required when boutique or historic hotels lack 4-person family rooms.
* **Aggregator Representation:** Google Hotels calculates the total stay price based on the occupancy requested. If the hotel cannot accommodate 4 in one room, Google/Booking either displays no availability or automatically quotes the combined rate for 2 double rooms. The adapter must parse the room description to verify room allocation.

---

## 3. Pricing Breakdown & Taxes

### 3.1 Total Price vs. Nightly Rate
* **VAT (IVA):** In Italy, consumer hotel rates must by law include standard VAT (10% on accommodation and restaurant services). All rates quoted in EUR by SerpApi Google Hotels include Italian VAT.
* **Total Stay Price:** For a standard weekend, check-in is Friday (from 14:00–15:00) and check-out is Sunday (by 10:00–11:00), totaling **2 nights**. Google Hotels API returns both `rate_per_night` and `total_rate`.

### 3.2 Tassa di Soggiorno (Tourist Tax)
* **Legal Framework:** Italian tourist tax (*imposta di soggiorno*) is levied by individual municipalities (*Comuni*).
* **Payment Obligation:** Tourist tax is **never included in OTA pre-payments** or upfront aggregator price totals. It is legally mandated to be paid directly to the hotel upon check-in or check-out.
* **Tariffs & Child Exemptions:**
  * Typical range: **€1.50 to €5.00** per person per night depending on hotel category (3-star: €1.50–€2.50; 4-star: €2.50–€4.00; 5-star: €4.00–€7.00).
  * **Exemptions for 7-year-old:** Almost all Italian municipalities exempt children under 10, 12, or 14 years of age. The 7-year-old is almost universally **exempt (€0)**.
  * **Liability for 15-year-old:** In the vast majority of municipalities (e.g., Rome, Florence, Abano Terme, Sirmione, Merano), the exemption ends at age 12 or 14. Therefore, the **15-year-old pays the full adult tourist tax**.
  * **Estimated Tax Formula for 2-night weekend:**
    $$\text{Tax}_{\text{total}} = 2 \text{ nights} \times 3 \text{ taxable persons (2 adults + 15yo)} \times \text{Tariff}_{\text{star\_rating}}$$
    *(e.g., 4-star hotel in Veneto at €3.00/person/night = $2 \times 3 \times 3.00 = €18.00$)*

### 3.3 Mandatory Spa / Club Fees
Certain thermal hotels (particularly in Abano, Montegrotto, and Tuscany) separate the room rate from thermal facility access:
* **Included:** Many 4-star and 5-star spa hotels include unlimited access to thermal swimming pools in the nightly rate.
* **Excluded / Extra:** Some properties charge a mandatory resort card (*tessera club* / *ingresso parco termale*) ranging from €15 to €40 per person per day, or charge extra for the sauna/Turkish bath area.
* The adapter normalizer must check amenities and rate inclusions for `terme_included: true/false`.

---

## 4. Evaluation of Candidate Data Sources

### 4.1 Primary MVP: SerpApi Google Hotels API

#### 4.1.1 Overview & Query Structure
SerpApi provides a battle-tested scraping and extraction API for Google Hotels (`engine=google_hotels`). It acts as a meta-search engine aggregating Booking.com, Expedia, Agoda, Hotels.com, and direct hotel booking engines.

```http
GET https://serpapi.com/search HTTP/1.1
Host: serpapi.com
Query Parameters:
  engine=google_hotels
  q=Abano+Terme+Hotels
  check_in_date=2026-11-06
  check_out_date=2026-11-08
  adults=2
  children=2
  children_ages=15,7
  gl=it
  hl=it
  currency=EUR
  hotel_class=3,4,5
  amenities=10,6
  api_key={{SERPAPI_API_KEY}}
```

#### 4.1.2 Parameter Mapping Reference
| Parameter | Value | Rationale |
|---|---|---|
| `engine` | `google_hotels` | Invokes Google Hotels meta-search parser |
| `q` | `{Destination Name} Hotels` | Destination name (e.g. `"Abano Terme Hotels"`, `"Sirmione Hotels"`) |
| `check_in_date` | `YYYY-MM-DD` | Target Friday check-in date |
| `check_out_date` | `YYYY-MM-DD` | Target Sunday check-out date (or Monday for holiday ponti) |
| `adults` | `2` | Exact adult count |
| `children` | `2` | Exact child count |
| `children_ages` | `15,7` | Exact comma-separated child ages (triggers adult pricing for 15yo where required) |
| `gl` | `it` | Geolocation set to Italy for local pricing and Italian availability |
| `hl` | `it` | Italian language interface for parsing amenities and descriptions |
| `currency` | `EUR` | Currency standardized to Euros (€) |
| `hotel_class` | `3,4,5` | Excludes 1-2 star hostels/budget pensions lacking wellness facilities |
| `amenities` | `10,6` | `10` = Spa, `6` = Pool (General). Optional: `9` = Free Breakfast, `4` = Indoor Pool |

#### 4.1.3 Quota, Pricing & Latency Considerations
* **Pricing Plans:**
  * Free Trial: 100 searches total.
  * Developer Plan: $50 / month for 5,000 searches (~$0.01 per search).
  * Production Plan: $130 / month for 15,000 searches (~$0.0087 per search).
* **Latency:**
  * Average latency is **3.5s to 7.0s** per query due to live scraping of dynamic Google Hotels rendering.
  * Must be invoked asynchronously with an HTTP client timeout of $\ge 20\text{s}$.
* **Quota Budgeting Strategy:**
  * Searching 50 reachable destinations across 4 upcoming weekends = $50 \times 4 = 200$ requests per full run.
  * Running a full scan twice daily (morning & evening) = 400 requests/day $\approx$ 12,000 searches/month.
  * **Optimization:** Implement intelligent caching (TTL = 12 hours) and search high-priority weekend departures (next 2-4 weeks) more frequently than distant horizons (8-10 weeks).

#### 4.1.4 Response Schema & Extraction Mapping
SerpApi returns a JSON document with a `properties` array. Key fields mapped to our domain model:

```json
{
  "search_metadata": { "status": "Success", "total_time_taken": 4.82 },
  "properties": [
    {
      "name": "Hotel Terme Bologna",
      "type": "hotel",
      "description": "Family-friendly thermal hotel with indoor and outdoor thermal pools...",
      "link": "https://www.google.com/travel/hotels/entity/...",
      "gps_coordinates": { "latitude": 45.3582, "longitude": 11.7912 },
      "overall_rating": 4.4,
      "reviews": 845,
      "hotel_class": "3-star hotel",
      "amenities": ["Spa", "Indoor pool", "Outdoor pool", "Free breakfast", "Free Wi-Fi"],
      "rate_per_night": {
        "lowest": "€165",
        "extracted_lowest": 165,
        "before_taxes_fees": "€150",
        "extracted_before_taxes_fees": 150
      },
      "total_rate": {
        "lowest": "€330",
        "extracted_lowest": 330,
        "before_taxes_fees": "€300",
        "extracted_before_taxes_fees": 300
      },
      "deal_type": "LESS_THAN_USUAL",
      "deal_description": "18% less than usual",
      "prices": [
        {
          "source": "Booking.com",
          "rate_per_night": { "extracted_lowest": 165 },
          "link": "https://www.booking.com/hotel/it/terme-bologna.html..."
        }
      ]
    }
  ]
}
```

*Mapping to Domain Model (`Deal`)*:
* `property_name` $\leftarrow$ `property["name"]`
* `price.total_eur` $\leftarrow$ `property["total_rate"]["extracted_lowest"]`
* `price.price_per_night_eur` $\leftarrow$ `property["rate_per_night"]["extracted_lowest"]`
* `star_rating` $\leftarrow$ Parsed integer from `property["hotel_class"]`
* `user_review_score` $\leftarrow$ `property["overall_rating"] * 2.0` (normalized to 0–10 scale)
* `room_offer.terme_included` $\leftarrow$ `True` if `"Spa"` in amenities or `"thermal"` in description.

---

### 4.2 Direct Terme / Spa Websites & Aggregators

While SerpApi captures hotels in thermal towns, specific thermal bath complexes offer stay-and-spa packages directly on their websites:

#### 4.2.1 QC Terme (Pré-Saint-Didier, San Pellegrino, Bormio, Roma)
* **Evaluation:** **Rejected for direct family packages.**
* **Reason:** As documented in Section 1.2, QC Terme strictly forbids children under 14 from entering the thermal path (*"L'accesso al percorso benessere è vietato ai minori di 14 anni"*). While the 15-year-old is eligible, the 7-year-old cannot participate.
* **Handling:** If a package explicitly includes QC Terme passes, it must be flagged with `terme_child_policy_compliant: False` and rejected by the family filter.

#### 4.2.2 Bormio Terme
* **Evaluation:** **Primary Recommendation for Alpine Thermal Baths.**
* **Profile:** A family-focused public thermal center with thermal waters at 37°C–40°C, a 60-meter waterslide for older kids, and dedicated 60cm splash pools for younger kids.
* **Data Ingestion:** Partner hotels in Bormio offer the "Bormio Terme Family Package". Can be monitored via SerpApi (filtering for Bormio hotels with pool/spa) and direct scraper on `bormioterme.it/offerte`.

#### 4.2.3 Terme di Sirmione (Aquaria Thermal SPA & Terme Hotels)
* **Evaluation:** **High Recommendation for Lake Garda.**
* **Profile:** Historical thermal resort operating 4 partner hotels (*Grand Hotel Terme*, *Hotel Sirmione*, *Hotel Fonte Boiola*) and the Aquaria Thermal SPA.
* **Admission:** Children aged $\ge 2.5$ years old are welcomed in thermal pools. Junior admission rates apply up to age 11.
* **Data Ingestion:** Direct package monitor for `termedisirmione.com/offerte-soggiorno`.

#### 4.2.4 Terme di Saturnia Natural Destination
* **Evaluation:** **High Recommendation for Tuscany.**
* **Profile:** World-renowned sulfur springs (37.5°C). The resort features a 4-star/5-star hotel and a 20,000 sqm Parco Termale.
* **Admission:** Parco Termale has dedicated 0.7m shallow pools for children. Deep waterfall zones enforce a 1.50m / 14yo limit. The free natural cascade (*Cascate del Mulino*) is open to all.
* **Data Ingestion:** Monitored via SerpApi for Saturnia/Manciano hotels and targeted parsing of `termedisaturnia.it/offerte`.

---

### 4.3 Web Scraping Tools vs. Official APIs

| Tool / Technology | Pros | Cons | Recommendation |
|---|---|---|---|
| **SerpApi (Google Hotels)** | • Immediate setup with API key<br>• Real multi-vendor pricing<br>• Native support for child ages<br>• No IP blocking or proxy maintenance | • Commercial cost ($50/mo for 5k calls)<br>• 4-6s latency per call<br>• Room sub-types summarized | **Primary Core MVP** |
| **Firecrawl MCP / API** | • Converts messy hotel/spa package HTML to structured Markdown / JSON<br>• LLM-ready extraction<br>• Handles JS rendering | • Per-page extraction cost<br>• Requires custom target URL list | **Recommended for Tier 2 Direct Terme Package Pages** |
| **Apify (Booking / Google Actors)** | • Pre-built open-source scrapers<br>• Deep room-level fidelity | • Third-party actors can break without notice<br>• High proxy consumption costs<br>• Booking.com aggressive anti-bot defenses | **Secondary / Fallback Only** |
| **Expedia Rapid API v3** | • Official partner API<br>• Guaranteed uptime & room inventory<br>• Full room breakdown & tax itemization | • Requires EPS affiliate partnership application<br>• Volume commitments & verification | **Recommended for Long-Term Production** |
| **Booking.com Demand API** | • Official API with live bookable rates | • Partner qualification barrier is high<br>• Strict compliance audits | **Future Expansion** |

---

## 5. Architectural Implementation Design

### 5.1 Abstract Base Adapter (`src/sources/base.py`)

All sources implement the common interface defined in `docs/architecture.md`:

```python
"""Base adapter contract for hotel and thermal bath deal sources."""

from abc import ABC, abstractmethod
from typing import List
from src.core.models import Deal, Destination, StayRequest


class DealSourceException(Exception):
    """Base exception for deal sourcing failures."""
    pass


class BaseDealSource(ABC):
    """Abstract interface for all hotel and terme data sources."""

    def __init__(self, name: str, rate_limit_rps: float = 1.0) -> None:
        self.name = name
        self.rate_limit_rps = rate_limit_rps

    @abstractmethod
    async def search(
        self,
        destination: Destination,
        stay: StayRequest
    ) -> List[Deal]:
        """Search available offers for the destination and stay party."""
        pass

    @abstractmethod
    async def health_check(self) -> bool:
        """Verify API keys, credentials, or remote connectivity."""
        pass
```

### 5.2 SerpApi Google Hotels Adapter (`src/sources/serpapi.py`)

Key architectural features of the SerpApi adapter:
1. **Async HTTPX Client:** Non-blocking network queries with keep-alive and configurable connection pooling.
2. **Exponential Backoff & Jitter:** Automatically handles transient HTTP 429 (Rate Limit) or 503 errors.
3. **Age & Occupancy Parameter Construction:** Passes `adults=2`, `children=2`, and `children_ages="15,7"`.
4. **Resilience & Fault Isolation:** If SerpApi fails for one destination, it logs a warning and yields empty results without aborting the overall pipeline.

---

## 6. Sourcing Roadmap & Next Steps

1. **Step 1:** Implement `src/sources/base.py` defining `BaseDealSource`.
2. **Step 2:** Implement `src/sources/serpapi.py` with mockable HTTPX client and robust error handling.
3. **Step 3:** Record offline test fixtures (`tests/fixtures/serpapi/abano_terme_success.json`, `sirmione_success.json`) for hermetic testing.
4. **Step 4:** Implement `src/sources/terme_direct.py` stub with admission policy verification for family validation.
