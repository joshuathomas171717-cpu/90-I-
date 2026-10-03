# Being found, and knowing whether you were

**Phase 5, part 5.** Two decisions that are yours, not mine: whether to claim the site in Search
Console, and whether to measure traffic at all. Everything that could be automated already is —
this file is about the two clicks I cannot make for you, plus the reasoning so you can decide once.

---

## 1. What is already done, automatically

Nothing below needs you. It ships in the repo and runs on every build.

| Thing | Where | What it does |
|---|---|---|
| `sitemap.xml` | `site_pages.py` | 63 URLs: the dashboard, the table, the model page, all 38 matchweeks, all 20 clubs, with `<lastmod>` stamped from the data's as-of date. |
| `robots.txt` | `site_pages.py` | Allows everything except `/api/`, `/healthz`, `/readyz`. Points at the sitemap **when the build knows its own host** (see below). |
| Crawlable HTML | `site_pages.py` | Every fixture, probability, table row and club projection exists as text in a real HTML file — not only inside the JavaScript dashboard. This is the part that matters most: a crawler that cannot run JavaScript still sees the whole season. |
| Structured data | both builders | `SportsEvent` per fixture, `SportsTeam` per club, `ItemList` for the table and fixtures, `Dataset` + `WebSite` on the dashboard, breadcrumbs on every generated page. |
| Link previews | `og_image.py` | A 1200×630 PNG per club, per gameweek and for the site itself, referenced by `og:image` and `twitter:image`. |
| Icons, theme colour, `manifest.webmanifest` | `og_image.py`, `build_dashboard.py` | SVG + 32/180/192/512 PNG, `theme-color`, and a manifest so "add to home screen" is not just a bookmark. |

### The one build flag worth setting

Canonical URLs, `og:url` and the `Sitemap:` line are only emitted as absolute URLs when the build is
told its own address:

```bash
NT90_SITE_URL=https://your-user.github.io/your-repo python3 run_all.py
```

Without it the site is still completely correct — canonicals fall back to relative hrefs, which every
crawler resolves against the page it is reading. With it, the sitemap can carry a `Sitemap:` line and
social platforms get an exact `og:url`. For GitHub Pages the value is
`https://<user>.github.io/<repo>` (for this repo: `https://joshuathomas171717-cpu.github.io/90-I-`).

**Worth doing:** add that as a repository variable and wire it into `pages.yml`:

```yaml
env:
  NT90_SITE_URL: ${{ vars.NT90_SITE_URL }}
```

I have not done that yet because it needs the final URL — which depends on whether you rename the
repository.

---

## 2. Decision 1 — Search Console (your click)

Search Console is free and tells you what people typed to find the site. It requires proving you own
the domain, which needs an account I cannot create for you.

**If you deploy to GitHub Pages** (the path already set up):

1. Go to <https://search.google.com/search-console> and sign in with the account that owns the repo.
2. **Add property → URL prefix** → paste the full Pages URL, e.g.
   `https://joshuathomas171717-cpu.github.io/90-I-/`.
3. Verify. The easiest route for Pages is **HTML tag**: it gives you a
   `<meta name="google-site-verification" content="…">` line. Paste it into the built page's `<head>`
   — or, better, tell me the value and I will add it to `build_dashboard.py` so every rebuild keeps it.
4. **Sitemaps → Add a new sitemap** → enter `sitemap.xml` → Submit.
5. Come back in a week. **Pages → Indexing** should show tens of URLs; if it shows one, something is
   wrong and worth telling me about.

**If you do not deploy anywhere public,** skip this entirely. There is nothing to index.

---

## 3. Decision 2 — analytics (pick one, or none)

The honest options, given what this site is:

| Option | What you get | What it costs | Recommendation |
|---|---|---|---|
| **None** | Nothing. | Nothing. | **Fine, and the default.** This is a forecast dashboard, not a funnel. If nobody is paying for the traffic, measuring it is a hobby. |
| **Server logs** | Counts of pages and API calls, no personal data, no cookies, no banner. | Nothing. | **What I would choose.** `server.py` already counts requests per route and publishes them at `/api/stats`. If you deploy the container, that is your analytics — and it is already written. |
| **GoatCounter / Plausible Cloud** | Page views, referrers, countries. Cookieless, so no consent banner in the EU. | Free (GoatCounter, non-commercial) or ~€9/mo (Plausible). | Reasonable if you want a hosted dashboard without thinking about it. GoatCounter's free tier is fine for a personal project. |
| **Self-hosted Plausible / Umami** | The same, on your own box. | A second deployment to maintain. | Only if you already run servers. It is a lot of infrastructure for a football predictor. |
| **Google Analytics** | Everything, plus an audience you do not have. | A consent banner in the EU, a large script on a page whose selling point is zero external requests, and a privacy page that has to be written carefully. | **No.** It contradicts the design of the page. |

**Whatever you pick, one rule:** an analytics script must not be the first external request this page
makes. The dashboard is self-contained by design — fonts inlined, crests drawn, no CDN — and it works
offline and from a zip. A hosted script is fine *as an addition*; it must never become load-bearing,
and it should be the only one.

**If you want analytics, tell me which and I will wire it in** — including the privacy line it
implies in the model page and `README`, which is part 9.3 of the plan and is already waiting on this
decision.

---

## 4. What I would do, if it were mine

1. Deploy to Pages (one setting), set `NT90_SITE_URL`, submit the sitemap to Search Console.
2. No analytics at all for the first month. `/api/stats` on the container if you run one.
3. Revisit if and when you actually want to know something.

Two of those three are already done in the repository. The third is a URL — and a username.
