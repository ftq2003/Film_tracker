# 120 Film Tracker

A Python script that tracks **stock availability and prices for 120mm medium-format film** across major US camera retailers. It runs weekly auto-discovery to find new products, scrapes current prices, builds a sortable HTML report, and plots price history over time.
<img width="1850" height="1455" alt="image" src="https://github.com/user-attachments/assets/8fff60fd-23c3-49d5-aa56-37727b6d0830" />
Figure 1: Result page, you can check manually if the auto fetch is not successful.
The HTML report opens automatically and includes:
- Summary tiles (total checked, in stock, errors, eBay listings)
- "URLs to check manually" — bot-blocked or parser-failed listings with copy-to-clipboard buttons
- "Best Deals" — cheapest in-stock per film
- Full sortable comparison table
- eBay cheapest active listings per film
- Price history plot (after a few runs accumulate data)
<img width="1867" height="1338" alt="image" src="https://github.com/user-attachments/assets/a93709eb-81fc-4697-a578-4cb62c2603e8" />
Figure 2: visualize historic price, let you know if a film has dropped price recently.
<img width="1844" height="1360" alt="image" src="https://github.com/user-attachments/assets/17bc5c72-b8ce-4a75-8b39-68f50e3e51a0" />
Figure 3: in stock or out of stock status, click on y0 labels to sort by name, price/roll, total price.
## What it does

- **Searches 16+ retailers automatically** (B&H, KEH, Reformed Film Lab, Film Supply Club, CineStill, Moment, Austin Camera, B&C Camera, District Camera, OC Camera, Photocare, Samy's, Blue Moon, Catlabs, Freestyle, Ace Photo)
- **Auto-discovers new products** — searches each retailer for "kodak 120", "fuji 120", "ilford 120", etc., normalizes the results into known films (Portra 400, Tri-X 400, Velvia 50, etc.)
- **Tracks prices over time** — appends to a CSV history file every run so you can see when prices change
- **eBay "lowest active listings" tracker** — separate from the retailer stock tracker, finds the cheapest current Buy-It-Now listings per film
- **Sortable, filterable HTML report** — one click and your browser opens a page with all results, best deals highlighted, price history plotted, and a prominent "URLs to check manually" section for any listings the parser couldn't read automatically
- **User-editable config file** — enable/disable retailers, add new search brands (Lomography, Rollei, etc.) or formats (135 / instax / 4x5) without touching code
- **Add custom retailers** — paste a homepage URL into `config.txt` and the script auto-detects the e-commerce platform (Shopify / CS-Cart / WooCommerce / Volusion / generic) and tries to scrape it

## Screenshots / sample output

Console during a run:
```
Config: 16/17 retailers enabled (0 custom), 7 brands, 1 formats
Using cached discovery (2 days old)
Will check 87 retail listings (3 expired)

  · Kodak Portra 160 (120)         @ Austin Camera … in stock  $13.99  ($13.99/roll)
  · Kodak Portra 160 (120)         @ B&C Camera    … in stock  $14.95  ($14.95/roll)
  · Kodak Portra 160 (120)         @ Reformed Film … in stock  $69.00  ($13.80/roll)
  · Kodak Tri-X 400 (120)          @ B&H Photo     … in stock  $10.99  ($10.99/roll)
  ...

EBAY — searching for cheapest active listings per film
  · Kodak Portra 400 (120)         …  5 listings, cheapest $48.99
  · Kodak Tri-X 400 (120)          …  5 listings, cheapest $9.50
  ...
```

## Requirements

- **Windows** (the launcher is a `.bat` file; the Python script itself is cross-platform but tested on Windows 11)
- **Python 3.10+** — recommended via [miniconda](https://docs.conda.io/en/latest/miniconda.html)
- **Google Chrome** — used in remote-debug mode for sites with bot detection
- **Internet connection** during runs
- ~150 MB free disk for Playwright's bundled Chromium (downloaded on first run)

The script auto-installs all required Python packages on first run (`curl_cffi`, `beautifulsoup4`, `lxml`, `pandas`, `playwright`, `matplotlib`, `nest_asyncio`).

## Quick start

### Option A: Easy setup with the setup script

1. **Clone the repo**:
   ```
   git clone https://github.com/YOURUSERNAME/film-tracker.git
   cd film-tracker
   ```

2. **Run the setup script** (Windows):
   ```
   setup.bat
   ```
   This checks for Chrome, finds your Python install, and installs all required packages. If anything's missing, it tells you exactly what to do.

3. **Run the tracker**:
   ```
   run_tracker.bat
   ```
   It launches a debug Chrome window, waits for you to dismiss any bot-detection challenges (visit B&H, Adorama, eBay once to set cookies), then runs the discovery + check.

### Option B: Manual setup

1. Install [Python 3.10+](https://www.python.org/downloads/) — make sure to check "Add to PATH" during install.
2. Install [Google Chrome](https://www.google.com/chrome/).
3. Download or clone this repo.
4. Open Command Prompt in the folder and run:
   ```
   pip install curl_cffi beautifulsoup4 lxml pandas playwright matplotlib nest_asyncio
   playwright install chromium
   ```
5. Double-click `run_tracker.bat`.

## Commands

The script supports several modes:

```
python film_tracker.py             # normal: discover-if-stale, then check listings
python film_tracker.py discover    # force fresh discovery (ignores cache)
python film_tracker.py check       # skip discovery, check existing cached URLs only
python film_tracker.py status      # diagnose each retailer (homepage + search reachability)
python film_tracker.py plot        # generate price history plot from existing data
python film_tracker.py clear       # delete history & cache (with confirmation)
```

## Customizing — edit `config.txt`

After your first run, the script creates a well-commented `config.txt`. Edit it to:

**Add or remove search brands** under `[brands]`:
```
[brands]
kodak
fuji
fujifilm
cinestill
ilford
lomography
rollei
foma           # added — uncommon but search will pick it up
```

**Track different film formats** under `[formats]`:
```
[formats]
120
135            # to also track 35mm
```

**Disable specific retailers** under `[retailers]`:
```
samys          : no    # don't search Samy's anymore
adorama        : no    # already disabled by default (PerimeterX bot block)
```

**Add a new retailer** under `[custom_retailers]`:
```
[custom_retailers]
mynewshop : yes : My New Film Shop : https://mynewfilmshop.com
```

The script auto-detects the e-commerce platform on first encounter. Save your edits, run again — changes take effect immediately. No code changes needed.

## How it works

The script uses three different fetching strategies and falls back through them automatically:

1. **`curl_cffi`** — fast, mimics a Chrome browser via TLS fingerprinting. Used for sites without heavy JavaScript.
2. **Attach mode** — connects to your real Chrome browser running on debug port 9222. Used for sites with anti-bot measures (B&H, Adorama, etc.) — your visible browser session bypasses detection because it's a real human session.
3. **Headless Playwright** — fallback if the others fail.

For sites with JavaScript-rendered content (Blue Moon, Moment, B&C, etc.), the script scrolls the page to trigger lazy-loaded products before reading the HTML.

Stock and price extraction tries multiple strategies in order:
- JSON-LD structured data (modern e-commerce standard)
- Meta tags (`<meta itemprop="price">`)
- CSS class price elements (`.price`, `.money`, `.amount`)
- Shopify inline JSON
- Last-resort scan for any `<element>$X.XX</element>` on the page

Pack-size detection auto-corrects when product page price contradicts initial classification: a 5-pack listed for under $25 will be reclassified as a single roll.

## Output files

After a run, your folder will contain:

| File | Purpose |
|---|---|
| `tracker_history.csv` | Append-only log of every check across all runs |
| `ebay_history.csv` | Same for eBay listings |
| `discovery_cache.json` | Cached search results (refreshes weekly by default) |
| `platform_cache.json` | Cached e-commerce platform detection per homepage |
| `report.html` | Human-readable report (opens automatically) |
| `price_history.png` | Per-film price-per-roll plot |
| `config.txt` | Your settings (auto-created on first run) |

## Limitations and honest caveats

- **Adorama** is disabled by default. Their PerimeterX bot detection makes scraping unreliable. If you want to compare Adorama prices, visit their site manually.
- **eBay anti-bot measures** can sometimes block searches. If eBay returns "no results" for everything, wait an hour and try again — it's a rate limit.
- **Some retailers may stop working** if they redesign their websites. The script saves debug HTML for any failures so the parser can be updated.
- **Discovery is not exhaustive** — it only finds products whose names contain a configured brand name. Niche brands need to be added to `config.txt`.
- **Price-per-roll for 5-packs** assumes the listing is what its name says. Edge cases (4-roll packs, pro packs of 5, propacks of 10) can produce slightly off math.
- **The script doesn't make purchases.** It only reads publicly-displayed prices and stock status. Always click through to the retailer's site before buying.

## Project structure

```
film-tracker/
├── film_tracker.py        # main script (~2000 lines)
├── run_tracker.bat        # Windows one-click launcher
├── setup.bat              # one-time environment setup
├── README.md              # this file
├── .gitignore             # keeps generated data out of the repo
├── LICENSE                # MIT
└── (after first run:)
    ├── config.txt
    ├── tracker_history.csv
    ├── ebay_history.csv
    ├── discovery_cache.json
    ├── platform_cache.json
    ├── report.html
    └── price_history.png
```

## License

MIT — do whatever you want with this. If you adapt it for your favorite niche product (vinyl records, vintage cameras, watch parts, anything), I'd love to hear about it.

## Contributing

Found a retailer that doesn't work? Open an issue with:
1. The retailer name + homepage URL
2. The search URL when you search "kodak 120" on their site
3. One product URL from those results

That's enough to add a new retailer in most cases.

## Acknowledgments

Built collaboratively with Claude (Anthropic) over several iteration rounds. Original itch: tracking 120mm film stock during the post-2020 film resurgence when popular stocks (Portra, Tri-X, Velvia) routinely went out of stock at major retailers.
