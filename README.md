# Therapist Lead Intelligence & Data Enrichment Pipeline

A PostgreSQL-backed, multi-stage data enrichment pipeline that turns therapist-directory listings into **structured, enriched lead data** using concurrent workers, proxy leasing, resumable processing, and bandwidth-aware HTTP crawling.

**Python 3.12 · PostgreSQL · SQLAlchemy · asyncio · Curl CFFI · BeautifulSoup · Pydantic · Docker**

## Overview 

The pipeline starts with a therapist-directory listing, such as a Psychology Today search URL, and progressively converts directory profiles into structured therapist and practice data that can be used for lead generation.

Given:

- a directory URL
- a maximum number of profiles
- a maximum number of listing pages
- a configured proxy pool

the application processes each therapist through four independent stages:
1. **Directory Discovery** - collect therapist profile URLs.
2. **Profile Enrichment** - extract structured data from each directory profile.
3. **Website Resolution** - resolve external therapist website URLs from the directories without browser automation.
4. **Website Enrichment** - Crawl therapist-owned websites, extract additional information like emails, and categorize them into either private or group practices.


Each stage persists its output to PostgreSQL and only queues the next stage after successful completion. This allows stages to run independently without requiring the entire pipeline to run in one process.


# Architecture

```mermaid
---
config:
  flowchart:
    useMaxWidth: false
    diagramPadding: 5
    rankSpacing: 25
    nodeSpacing: 25
---
flowchart TD 
 
    INPUT["Therapist Directory URL"] 
 
    S1["Stage 1<br/>Collect Directory Listings"] 
 
    DB1["Database<br/>Insert Unique Profiles<br/>profile_scrape_status = pending"] 
 
    READY2["Pending Profiles<br/>Ready for Enrichment"] 
 
    S2["Stage 2<br/>Scrape + Enrich PT Profile"] 
 
    DB2["Database<br/>profile_scrape_status = completed<br/>website_resolution_status = pending"] 
 
    READY3["Pending Website<br/>Resolution"] 
 
    S3["Stage 3<br/>Resolve External Website<br/>via PT Outbound Endpoint"] 
 
    DEST{"Destination Type?"} 
 
    DIRECTORY["Database<br/>Store Resolved URL<br/>website_resolution_status = completed<br/>website_scrape_eligible = false"] 
 
    OWNED["Database<br/>Store Resolved URL<br/>website_resolution_status = completed<br/>website_scrape_eligible = true<br/>website_scrape_status = pending"] 
 
    READY4["Pending Website<br/>Ready for Enrichment"] 
 
    S4["Stage 4<br/>Crawl Therapist Website<br/>+ Enrich Lead Data"] 
 
    DB4["Database<br/>website_scrape_status = completed<br/>Persist Website Enrichment"] 
 
    DONE["Structured<br/>Enriched Lead Record"] 
 
 
    INPUT --> S1 
 
    S1 --> DB1 
 
    DB1 --> READY2 
 
    READY2 --> S2 
 
    S2 --> DB2 
 
    DB2 --> READY3 
 
    READY3 --> S3 
 
    S3 --> DEST 
 
    DEST -->|Known Directory| DIRECTORY 
 
    DEST -->|Owned Website| OWNED 
 
    OWNED --> READY4 
 
    READY4 --> S4 
 
    S4 --> DB4 
 
    DB4 --> DONE
```
