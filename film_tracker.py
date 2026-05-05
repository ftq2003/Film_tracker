"""
120mm Film Stock & Price Tracker — v8

USAGE:
  python film_tracker.py             # normal: discover-if-stale, then check
  python film_tracker.py discover    # force fresh discovery
  python film_tracker.py check       # skip discovery, check existing only
  python film_tracker.py status      # diagnose retailers
  python film_tracker.py plot        # generate plot from history
  python film_tracker.py clear       # delete history & cache

CONFIG (edit `config.txt`):
  - Enable/disable built-in retailers
  - Customize search brands & formats
  - ADD CUSTOM RETAILERS by homepage URL — script auto-detects their platform

OUTPUT FILES:
  config.txt               — user-editable settings
  tracker_history.csv      — append-only log
  ebay_history.csv         — append-only eBay log
  discovery_cache.json     — last discovery (refreshes weekly)
  report.html              — sortable/filterable report
  price_history.png        — price plot
"""

import sys, subprocess

REQUIRED = ['curl_cffi', 'beautifulsoup4', 'lxml', 'pandas', 'playwright',
            'matplotlib', 'nest_asyncio']

def _ensure_packages():
    missing = []
    for pkg in REQUIRED:
        try:
            __import__('bs4' if pkg == 'beautifulsoup4' else pkg.replace('-', '_'))
        except ImportError:
            missing.append(pkg)
    if missing:
        print(f'Installing missing packages: {", ".join(missing)}')
        subprocess.run([sys.executable, '-m', 'pip', 'install', '-q'] + missing,
                       check=False)
        if 'playwright' in missing:
            print('Downloading Chromium for Playwright (one-time, ~150MB)...')
            subprocess.run([sys.executable, '-m', 'playwright', 'install', 'chromium'],
                           check=False)

_ensure_packages()

import asyncio, re, json, os, time, html as html_mod, webbrowser
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict, fields as dc_fields
from typing import Optional
from urllib.parse import urlparse


# ============================================================
# 1. DEFAULTS
# ============================================================

DEFAULT_RETAILERS = {
    'bhphoto':        {'name': 'B&H Photo',          'mode': 'attach',
                       'home': 'https://www.bhphotovideo.com',
                       'platform': 'bh', 'enabled': True, 'js_required': True},
    'adorama':        {'name': 'Adorama',            'mode': 'attach',
                       'home': 'https://www.adorama.com',
                       'platform': 'generic', 'enabled': False,  # PerimeterX bot block — manual only
                       'js_required': True},
    'freestyle':      {'name': 'Freestyle Photo',    'mode': 'attach',
                       'home': 'https://www.freestylephoto.com',
                       'platform': 'freestyle', 'enabled': True, 'js_required': True},
    'keh':            {'name': 'KEH Camera',         'mode': 'attach',
                       'home': 'https://www.keh.com',
                       'platform': 'keh', 'enabled': True, 'js_required': True},
    'bluemoon':       {'name': 'Blue Moon Camera',   'mode': 'attach',
                       'home': 'https://www.bluemooncamera.com',
                       'platform': 'bluemoon', 'enabled': True, 'js_required': True},
    'catlabs':        {'name': 'Catlabs',            'mode': 'attach',
                       'home': 'https://www.catlabs.info',
                       'platform': 'generic', 'enabled': False, 'js_required': False},
    'reformed':       {'name': 'Reformed Film Lab',  'mode': 'attach',
                       'home': 'https://reformedfilmlab.com',
                       'platform': 'shopify', 'enabled': True, 'js_required': False},
    'acephoto':       {'name': 'Ace Photo',          'mode': 'attach',
                       'home': 'https://acephoto.net',
                       'platform': 'cscart', 'enabled': True, 'js_required': False},
    'austincamera':   {'name': 'Austin Camera',      'mode': 'attach',
                       'home': 'https://austincamera.com',
                       'platform': 'shopify', 'enabled': True, 'js_required': False},
    'bccamera':       {'name': 'B&C Camera',         'mode': 'attach',
                       'home': 'https://store.bandccamera.com',
                       'platform': 'shopify', 'enabled': True, 'js_required': True},
    'districtcamera': {'name': 'District Camera',    'mode': 'attach',
                       'home': 'https://www.districtcamera.com',
                       'platform': 'districtcamera', 'enabled': True, 'js_required': False},
    'filmsupplyclub': {'name': 'Film Supply Club',   'mode': 'attach',
                       'home': 'https://filmsupply.club',
                       'platform': 'shopify', 'enabled': True, 'js_required': False},
    'occamera':       {'name': 'OC Camera',          'mode': 'attach',
                       'home': 'https://www.occamera.com',
                       'platform': 'occamera', 'enabled': True, 'js_required': False},
    'photocare':      {'name': 'Photocare',          'mode': 'attach',
                       'home': 'https://www.fotocare.com',
                       'platform': 'photocare', 'enabled': True, 'js_required': False},
    'samys':          {'name': "Samy's Camera",      'mode': 'attach',
                       'home': 'https://www.samys.com',
                       'platform': 'samys', 'enabled': True, 'js_required': True},
    'cinestill':      {'name': 'CineStill',          'mode': 'attach',
                       'home': 'https://cinestillfilm.com',
                       'platform': 'shopify', 'enabled': True, 'js_required': False},
    'moment':         {'name': 'Moment',             'mode': 'attach',
                       'home': 'https://www.shopmoment.com',
                       'platform': 'moment', 'enabled': True, 'js_required': True},
}

DEFAULT_BRANDS = ['kodak', 'fuji', 'fujifilm', 'cinestill', 'ilford',
                  'lomography', 'rollei']
DEFAULT_FORMATS = ['120']
DEFAULT_INCLUDE_EBAY = True

# ============================================================
# State sales tax rates (2024-2026 base rates, no local additions)
# Source: avg state-level rates. Local/county/city tax can add 0.5%-3%
# in some areas — users in those areas should use the manual rate override.
# ============================================================
STATE_TAX_RATES = {
    'AL': 4.00, 'AK': 0.00, 'AZ': 5.60, 'AR': 6.50, 'CA': 7.25,
    'CO': 2.90, 'CT': 6.35, 'DE': 0.00, 'DC': 6.00, 'FL': 6.00,
    'GA': 4.00, 'HI': 4.00, 'ID': 6.00, 'IL': 6.25, 'IN': 7.00,
    'IA': 6.00, 'KS': 6.50, 'KY': 6.00, 'LA': 4.45, 'ME': 5.50,
    'MD': 6.00, 'MA': 6.25, 'MI': 6.00, 'MN': 6.875,'MS': 7.00,
    'MO': 4.225,'MT': 0.00, 'NE': 5.50, 'NV': 6.85, 'NH': 0.00,
    'NJ': 6.625,'NM': 5.125,'NY': 4.00, 'NC': 4.75, 'ND': 5.00,
    'OH': 5.75, 'OK': 4.50, 'OR': 0.00, 'PA': 6.00, 'RI': 7.00,
    'SC': 6.00, 'SD': 4.20, 'TN': 7.00, 'TX': 6.25, 'UT': 6.10,
    'VT': 6.00, 'VA': 5.30, 'WA': 6.50, 'WV': 6.00, 'WI': 5.00,
    'WY': 4.00,
}
DEFAULT_TAX_STATE = ''       # blank = disabled
DEFAULT_TAX_RATE_OVERRIDE = None
DEFAULT_TAX_FREE_RETAILERS = []
DEFAULT_TAX_ON_EBAY = True


# ============================================================
# 2. CONFIG FILE
# ============================================================

CONFIG_FILE = 'config.txt'
PLATFORM_DETECTION_CACHE = 'platform_cache.json'

CONFIG_TEMPLATE = """# ============================================================================
# Film Tracker Configuration
# ============================================================================
# Edit this file to control what gets searched.
# Lines starting with # are comments and are ignored.
# Save the file, then run the tracker again.
#
# To restore defaults: delete this file, the script will recreate it.
# ============================================================================


# ----------------------------------------------------------------------------
# SEARCH BRANDS — searched as "<brand> <format>" on each retailer
# ----------------------------------------------------------------------------
# Common brand names: kodak, fuji, fujifilm, cinestill, ilford, lomography,
# rollei, foma, adox, bergger, agfa, polaroid

[brands]
{brands}


# ----------------------------------------------------------------------------
# SEARCH FORMATS — film formats to search for
# ----------------------------------------------------------------------------
# 120 = medium format (default)
# 135 = 35mm
# instax = Fujifilm Instax peel-apart instant film
# 4x5 / 8x10 = sheet film

[formats]
{formats}


# ----------------------------------------------------------------------------
# BUILT-IN RETAILERS
# ----------------------------------------------------------------------------
# Enable/disable each retailer with "yes" or "no" after the colon.
# Disabled retailers are skipped entirely.

[retailers]
{retailers}


# ----------------------------------------------------------------------------
# CUSTOM RETAILERS — add your own sites here
# ----------------------------------------------------------------------------
# Format:  retailer_key : enabled : Display Name : homepage_url
# Example: freshfilm    : yes     : Fresh Film   : https://freshfilmco.com
#
# The "retailer_key" is your internal identifier — must be one word, no spaces,
# letters/numbers/underscores only. Pick anything, e.g. "myshop" or "freshfilm".
#
# When you add a line, the script will:
#   1. Visit the homepage once
#   2. Auto-detect which e-commerce platform it uses (Shopify, CS-Cart,
#      Volusion, WooCommerce, or generic)
#   3. Try each platform's search until one returns results
#   4. Treat it like any other retailer for searches
#
# Caveat: auto-detection works for ~80% of small shops. If a custom retailer
# returns no results no matter what, the homepage may need a custom parser
# (you'd ask the script's author to add one).
#
# Uncomment the example lines below to add retailers, or copy them as templates.

[custom_retailers]
# myshop      : yes : My New Film Shop : https://mynewfilmshop.com
# anothershop : yes : Another Shop     : https://anotherfilmshop.example.com


# ----------------------------------------------------------------------------
# EBAY TRACKING
# ----------------------------------------------------------------------------
# eBay is a separate "cheapest active listings" tracker.
# Set to "yes" to include, "no" to skip.

[ebay]
include: {ebay}


# ----------------------------------------------------------------------------
# SALES TAX
# ----------------------------------------------------------------------------
# Adds estimated sales tax to prices so you can see the actual cost.
# This is a state-level approximation — your real tax may be 0.5%-3% higher
# in cities with local taxes (NYC, Chicago, Seattle, LA, etc.).
#
# state:  Your 2-letter state code (MA, NY, CA, etc.) — leave blank to skip.
#         Built-in rates: AL 4%, AK 0%, AZ 5.6%, AR 6.5%, CA 7.25%, CO 2.9%,
#         CT 6.35%, DE 0%, FL 6%, GA 4%, IL 6.25%, MA 6.25%, NJ 6.625%,
#         NY 4%, OR 0%, PA 6%, TX 6.25%, WA 6.5%, etc.
#
# rate:   (Optional) override the state rate. Use this if you live in a
#         high-local-tax area. Example: NYC residents pay ~8.875%, so:
#           state: NY
#           rate: 8.875
#
# tax_free_retailers:  Comma-separated list of retailer keys where you don't
#         pay sales tax. The classic case: B&H Photo's Payboo card and
#         Adorama's EDGE card both instantly rebate sales tax as store
#         credit on every purchase. If you have one of those cards, list
#         that retailer here.
#
# tax_on_ebay:  Whether to apply tax to eBay listings (yes/no). Most eBay
#         sellers do collect state tax now, but it varies by seller.

[tax]
state: {tax_state}
# rate: 8.875
tax_free_retailers: {tax_free_retailers}
tax_on_ebay: {tax_on_ebay}
"""


def parse_config(path=CONFIG_FILE):
    """Returns (retailers, brands, formats, include_ebay, tax_cfg).
    tax_cfg is a dict with: state, rate (None or float),
    tax_free_retailers (set of keys), tax_on_ebay (bool), effective_rate (float)"""
    if not os.path.exists(path):
        write_default_config(path)
        print(f'Created default {path} — edit it to customize.')

    section = None
    brands, formats = [], []
    builtin_state = {}
    custom_retailers = {}
    include_ebay = True
    tax_state = ''
    tax_rate_override = None
    tax_free_retailers = set()
    tax_on_ebay = True

    with open(path, 'r', encoding='utf-8') as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith('#'): continue
            if line.startswith('[') and line.endswith(']'):
                section = line[1:-1].strip().lower()
                continue
            if section == 'brands':
                brands.append(line.lower())
            elif section == 'formats':
                formats.append(line.lower())
            elif section == 'retailers':
                if ':' not in line: continue
                key, val = line.split(':', 1)
                val = val.split('#')[0].strip().lower()
                builtin_state[key.strip()] = val in ('yes', 'true', '1', 'on', 'enabled')
            elif section == 'custom_retailers':
                parts = [p.strip() for p in line.split(':', 3)]
                if len(parts) < 4: continue
                key, enabled_str, name, home = parts
                if not key or not home.startswith(('http://', 'https://')):
                    continue
                if key in DEFAULT_RETAILERS:
                    print(f'Warning: custom retailer key "{key}" conflicts with a built-in. Skipping.')
                    continue
                custom_retailers[key] = {
                    'name': name or key,
                    'home': home.rstrip('/'),
                    'mode': 'attach',
                    'platform': None,
                    'enabled': enabled_str.lower() in ('yes', 'true', '1', 'on', 'enabled'),
                    'is_custom': True,
                }
            elif section == 'ebay':
                if line.lower().startswith('include:'):
                    val = line.split(':', 1)[1].split('#')[0].strip().lower()
                    include_ebay = val in ('yes', 'true', '1', 'on')
            elif section == 'tax':
                if ':' not in line: continue
                key, val = line.split(':', 1)
                key = key.strip().lower()
                val = val.split('#')[0].strip()
                if key == 'state':
                    tax_state = val.upper()
                elif key == 'rate':
                    try:
                        tax_rate_override = float(val)
                    except ValueError:
                        pass
                elif key == 'tax_free_retailers':
                    # Comma-separated list of retailer keys
                    tax_free_retailers = set(
                        r.strip().lower() for r in val.split(',') if r.strip())
                elif key == 'tax_on_ebay':
                    tax_on_ebay = val.lower() in ('yes', 'true', '1', 'on')

    # Build retailer config
    retailers = {}
    for key, cfg in DEFAULT_RETAILERS.items():
        retailers[key] = dict(cfg)
        retailers[key]['enabled'] = builtin_state.get(key, cfg.get('enabled', True))
        retailers[key]['is_custom'] = False
    retailers.update(custom_retailers)

    if not brands: brands = DEFAULT_BRANDS[:]
    if not formats: formats = DEFAULT_FORMATS[:]

    # Compute effective tax rate
    effective_rate = 0.0
    if tax_state and tax_state != 'SKIP':
        if tax_rate_override is not None:
            effective_rate = tax_rate_override
        elif tax_state in STATE_TAX_RATES:
            effective_rate = STATE_TAX_RATES[tax_state]
        else:
            print(f'Warning: unknown state code "{tax_state}". Tax disabled.')
            tax_state = ''

    tax_cfg = {
        'state': tax_state,
        'rate_override': tax_rate_override,
        'tax_free_retailers': tax_free_retailers,
        'tax_on_ebay': tax_on_ebay,
        'effective_rate': effective_rate,  # percentage, e.g., 6.25
        'enabled': bool(tax_state) and effective_rate > 0,
    }

    return retailers, brands, formats, include_ebay, tax_cfg


def write_default_config(path=CONFIG_FILE):
    brands_block = '\n'.join(DEFAULT_BRANDS)
    formats_block = '\n'.join(DEFAULT_FORMATS)
    max_key = max(len(k) for k in DEFAULT_RETAILERS)
    retailer_lines = []
    for key, cfg in DEFAULT_RETAILERS.items():
        enabled_str = 'yes' if cfg.get('enabled', True) else 'no '
        note = ''
        if not cfg.get('enabled', True):
            if key == 'adorama':
                note = '  # disabled: PerimeterX bot block makes scraping unreliable'
            elif key == 'catlabs':
                note = '  # disabled: too few results to be useful'
            else:
                note = '  # disabled by default'
        retailer_lines.append(
            f'{key.ljust(max_key)} : {enabled_str}   # {cfg["name"]:18s} ({cfg["home"]}){note}')
    retailers_block = '\n'.join(retailer_lines)
    content = CONFIG_TEMPLATE.format(
        brands=brands_block, formats=formats_block,
        retailers=retailers_block,
        ebay='yes' if DEFAULT_INCLUDE_EBAY else 'no',
        tax_state=DEFAULT_TAX_STATE or '',
        tax_free_retailers=', '.join(DEFAULT_TAX_FREE_RETAILERS) if DEFAULT_TAX_FREE_RETAILERS else '',
        tax_on_ebay='yes' if DEFAULT_TAX_ON_EBAY else 'no')
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)


# ============================================================
# 3. FILM RULES + CONSTANTS
# ============================================================

FILM_RULES = [
    ('Kodak Portra 160 (120)',     ['portra', '160']),
    ('Kodak Portra 400 (120)',     ['portra', '400']),
    ('Kodak Portra 800 (120)',     ['portra', '800']),
    ('Kodak Gold 200 (120)',       ['gold', '200']),
    ('Kodak Ektar 100 (120)',      ['ektar']),
    ('Kodak Ektachrome E100 (120)',['ektachrome']),
    ('Kodak Tri-X 400 (120)',      ['tri-x']),
    ('Kodak T-Max 100 (120)',      ['t-max', '100']),
    ('Kodak T-Max 400 (120)',      ['t-max', '400']),
    ('Kodak ColorPlus 200 (120)',  ['colorplus']),
    ('Kodak BW400CN (120)',        ['bw400cn']),
    ('Fuji Provia 100F (120)',     ['provia']),
    ('Fuji Velvia 50 (120)',       ['velvia', '50']),
    ('Fuji Velvia 100 (120)',      ['velvia', '100']),
    ('Fuji Acros II (120)',        ['acros']),
    ('Fuji Pro 400H (120)',        ['pro 400h']),
    ('Fujicolor 200 (120)',        ['fujicolor', '200']),
    ('CineStill 800T (120)',       ['cinestill', '800t']),
    ('CineStill 400D (120)',       ['cinestill', '400d']),
    ('CineStill 50D (120)',        ['cinestill', '50d']),
    ('CineStill BWxx (120)',       ['cinestill', 'bwxx']),
    ('CineStill BWxx (120)',       ['cinestill', 'bw xx']),
    ('Ilford HP5 Plus 400 (120)',  ['hp5']),
    ('Ilford FP4 Plus 125 (120)',  ['fp4']),
    ('Ilford Delta 100 (120)',     ['delta', '100']),
    ('Ilford Delta 400 (120)',     ['delta', '400']),
    ('Ilford Delta 3200 (120)',    ['delta', '3200']),
    ('Ilford XP2 Super 400 (120)', ['xp2']),
    ('Ilford SFX 200 (120)',       ['sfx', '200']),
    ('Ilford Pan F Plus 50 (120)', ['pan f']),
    ('Ilford Ortho Plus 80 (120)', ['ortho plus']),
    ('Lomography Color 100 (120)', ['lomography', '100']),
    ('Lomography Color 400 (120)', ['lomography', '400']),
    ('Lomography Color 800 (120)', ['lomography', '800']),
    ('Lomography LomoChrome Purple (120)', ['lomochrome', 'purple']),
    ('Lomography LomoChrome Metropolis (120)', ['lomochrome', 'metropolis']),
]

FILM_EXCLUDES = {
    'Fuji Velvia 50 (120)':  ['100'],
    'Fuji Velvia 100 (120)': ['50'],
    'Kodak T-Max 100 (120)': ['400'],
    'Kodak T-Max 400 (120)': ['100'],
    'Kodak Portra 160 (120)':['400', '800'],
    'Kodak Portra 400 (120)':['160', '800'],
    'Kodak Portra 800 (120)':['160', '400'],
    'Ilford Delta 100 (120)':['400', '3200'],
    'Ilford Delta 400 (120)':['100', '3200'],
    'Ilford Delta 3200 (120)':['100', '400'],
    'Lomography Color 100 (120)':['400', '800'],
    'Lomography Color 400 (120)':['100', '800'],
    'Lomography Color 800 (120)':['100', '400'],
}

CHROME_DEBUG_PORT = 9222
HISTORY_FILE = 'tracker_history.csv'
EBAY_HISTORY_FILE = 'ebay_history.csv'
DISCOVERY_CACHE = 'discovery_cache.json'
REPORT_HTML = 'report.html'
PLOT_PNG = 'price_history.png'
DISCOVERY_REFRESH_DAYS = 7
PER_LISTING_TIMEOUT = 35
PER_SEARCH_TIMEOUT = 25

MIN_PRICE_5_PACK = 12.0   # 5-packs of bulk/expired film exist; threshold is for parser miscatches
MIN_PRICE_SINGLE = 2.0    # Single rolls can be $3 (cheap Lomography)

NEGATIVE_FILTERS = [
    '36 exp', '36-exp', '36exp', '24 exp', '24-exp',
    'sheet film', '4x5', '5x4', '8x10', '10x8',
    'disposable', 'single use', 'single-use', 'quicksnap', 'quick snap',
    'camera body', 'lens hood', 'lens cap', 'lens filter', 'macro lens',
    'tripod', 'flash unit', 'enlarger', 'darkroom kit',
    'developer ', 'fixer ', 'film holder', 'film case', 'changing bag',
    'bulk film', 'mm f/', 'mm f1.', 'mm f2.', 'mm f3.', 'mm f4.', 'mm f5.',
    'mm lens', 'gf 120mm', 'm.zuiko', 'aperture', 'telephoto',
    'rangefinder', 'mirrorless', 'dslr',
    ' bag', ' strap', ' battery', ' charger',
    'srp from', 'save $', '$$', ' valor ', ' valo ',
]

PACK_HINTS_5 = ['5-pack', '5 pack', '5pack', 'propack', 'pro pack', 'pro-pack',
                '5 rolls', '5-roll', '5 roll', '(5)', 'box of 5', 'pack of 5']
PACK_HINTS_SINGLE = ['single roll', 'single-roll', '1 roll', '1-roll',
                     'single', '(1)']
EXPIRED_HINTS = ['expired', 'out of date', 'out-of-date', 'expir.']

BLOCK_MARKERS = ['access denied', 'unusual traffic', 'are you human',
                 'just a moment', 'attention required', 'verify you',
                 'press and hold', 'press & hold', 'completing a captcha',
                 'enable javascript and cookies']
BLOCK_PAGE_MAX_TEXT = 2000


# ============================================================
# 4. Boilerplate
# ============================================================

if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

from curl_cffi import requests as cffi_requests
from bs4 import BeautifulSoup
import pandas as pd

BROWSER_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                  '(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.9',
    'Accept-Encoding': 'gzip, deflate, br',
    'Sec-Ch-Ua': '"Chromium";v="131", "Not_A Brand";v="24", "Google Chrome";v="131"',
    'Sec-Ch-Ua-Mobile': '?0',
    'Sec-Ch-Ua-Platform': '"Windows"',
    'Sec-Fetch-Dest': 'document',
    'Sec-Fetch-Mode': 'navigate',
    'Sec-Fetch-Site': 'none',
    'Upgrade-Insecure-Requests': '1',
}


@dataclass
class Listing:
    film: str
    retailer: str
    url: str
    pack_size: int
    in_stock: Optional[bool] = None
    price_total: Optional[float] = None
    price_per_roll: Optional[float] = None
    shipping_info: str = ''
    error: str = ''
    fetcher: str = ''
    expired: bool = False
    source: str = 'discovered'
    product_name: str = ''
    checked_at: str = ''


@dataclass
class EbayListing:
    film: str
    title: str
    price: float
    shipping: str
    url: str
    seller_loc: str
    condition: str
    checked_at: str


# ============================================================
# 5. Block detection
# ============================================================

def page_looks_blocked(soup):
    if soup is None or soup == 'TIMEOUT': return False
    body = soup.find('body') or soup
    text = body.get_text(' ', strip=True).lower()
    if len(text) > BLOCK_PAGE_MAX_TEXT: return False
    return any(m in text for m in BLOCK_MARKERS)


def page_is_empty_or_failed(soup):
    if soup is None or soup == 'TIMEOUT': return True
    body = soup.find('body') or soup
    return len(body.get_text(' ', strip=True)) < 100


# ============================================================
# 6. Fetchers
# ============================================================

def fetch_curl_cffi_sync(url, retries=2):
    for attempt in range(retries + 1):
        try:
            r = cffi_requests.get(url, headers=BROWSER_HEADERS,
                                   impersonate='chrome131', timeout=20)
            if r.status_code == 200:
                return BeautifulSoup(r.text, 'lxml')
            if r.status_code == 404:
                return BeautifulSoup('<html><body>NOT FOUND 404</body></html>', 'lxml')
            if r.status_code in (403, 429, 503):
                time.sleep(3 + attempt * 2)
                continue
        except Exception:
            time.sleep(2)
    return None


async def fetch_attach_async(url):
    from playwright.async_api import async_playwright
    pw = await async_playwright().start()
    try:
        browser = await pw.chromium.connect_over_cdp(f'http://localhost:{CHROME_DEBUG_PORT}')
        ctx = browser.contexts[0] if browser.contexts else await browser.new_context()
        page = await ctx.new_page()
        try:
            response = await page.goto(url, wait_until='domcontentloaded', timeout=30000)
            status = response.status if response else 0
            # Wait for initial JS to settle
            await page.wait_for_timeout(3000)
            # Try waiting for network idle (don't fail if it times out)
            try:
                await page.wait_for_load_state('networkidle', timeout=8000)
            except Exception:
                pass
            # Trigger lazy-loading by scrolling — many sites only render
            # products that are in the viewport. Scroll down twice with pauses.
            try:
                await page.evaluate('window.scrollTo(0, document.body.scrollHeight / 2)')
                await page.wait_for_timeout(1500)
                await page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
                await page.wait_for_timeout(2000)
                await page.evaluate('window.scrollTo(0, 0)')
                await page.wait_for_timeout(500)
            except Exception:
                pass
            # Retry getting content up to 3 times in case of mid-navigation
            html_text = None
            for attempt in range(3):
                try:
                    html_text = await page.content()
                    break
                except Exception as e:
                    if 'navigating' in str(e).lower() and attempt < 2:
                        await page.wait_for_timeout(2000)
                        continue
                    raise
            await page.close()
            if status == 404:
                return BeautifulSoup('<html><body>NOT FOUND 404</body></html>', 'lxml')
            return BeautifulSoup(html_text or '', 'lxml')
        except Exception as e:
            print(f'    [attach goto: {type(e).__name__}: {str(e)[:80]}]')
            try: await page.close()
            except Exception: pass
            return None
    except Exception as e:
        print(f'    [attach connect: {type(e).__name__}: {str(e)[:80]}]')
        return None
    finally:
        try: await pw.stop()
        except Exception: pass


async def fetch_playwright_async(url):
    from playwright.async_api import async_playwright
    pw = await async_playwright().start()
    try:
        browser = await pw.chromium.launch(
            headless=True, args=['--disable-blink-features=AutomationControlled'])
        ctx = await browser.new_context(
            user_agent=BROWSER_HEADERS['User-Agent'],
            viewport={'width': 1366, 'height': 800}, locale='en-US')
        await ctx.add_init_script(
            'Object.defineProperty(navigator, "webdriver", {get: () => undefined})')
        page = await ctx.new_page()
        response = await page.goto(url, wait_until='domcontentloaded', timeout=25000)
        status = response.status if response else 0
        await page.wait_for_timeout(2000)
        html_text = await page.content()
        await browser.close()
        if status == 404:
            return BeautifulSoup('<html><body>NOT FOUND 404</body></html>', 'lxml')
        return BeautifulSoup(html_text, 'lxml')
    except Exception as e:
        print(f'    [playwright: {type(e).__name__}: {str(e)[:80]}]')
        return None
    finally:
        try: await pw.stop()
        except Exception: pass


async def _fetch_one(url, mode, timeout):
    try:
        if mode == 'attach':
            return await asyncio.wait_for(fetch_attach_async(url), timeout=timeout)
        if mode == 'playwright':
            return await asyncio.wait_for(fetch_playwright_async(url), timeout=timeout)
        loop = asyncio.get_event_loop()
        return await asyncio.wait_for(
            loop.run_in_executor(None, fetch_curl_cffi_sync, url), timeout=timeout)
    except asyncio.TimeoutError:
        print(f'    [TIMEOUT after {timeout}s in {mode} mode]')
        return 'TIMEOUT'


async def fetch_smart(url, fallback_mode='attach', timeout=PER_LISTING_TIMEOUT,
                       primary_mode='curl_cffi'):
    """Fetch a URL with auto-fallback. Default tries curl_cffi first, falls back
    to attach if blocked/empty. JS-heavy sites should pass primary_mode='attach'
    to skip curl_cffi (which can't run JavaScript)."""
    soup = await _fetch_one(url, primary_mode, timeout)
    if primary_mode != fallback_mode and (page_is_empty_or_failed(soup) or
                                            page_looks_blocked(soup)):
        reason = 'empty' if page_is_empty_or_failed(soup) else 'blocked'
        print(f'    [fallback: {primary_mode} {reason} -> trying {fallback_mode}]')
        soup = await _fetch_one(url, fallback_mode, timeout)
    return soup


# ============================================================
# 7. PLATFORMS — search URL pattern + result parser per platform
# ============================================================

# Each platform definition has:
#   detect(html, url): returns True if this platform fits the homepage
#   search_url(home, query): builds the search URL
#   parser(soup, base_url): extracts list of {name, url, price} from search results

def parse_price(text):
    """Parse a $-prefixed price from text. Handle the case where the price
    appears as cents only (e.g., '1799' meaning $17.99) by looking at the
    raw number's magnitude. Real film prices are < $1000 for any sane case,
    so any dollar-formatted match >= $1000 is suspect — likely a 4-digit
    cents value being read without a decimal point."""
    if not text: return None
    s = str(text)
    # Try a normal $X.XX or $X,XXX.XX match first
    m = re.search(r'\$\s*([0-9,]+\.[0-9]{2})', s)
    if m:
        return float(m.group(1).replace(',', ''))
    # Then try $X (whole-dollar) match — but be wary of cents-encoded values
    m = re.search(r'\$\s*([0-9,]+)(?!\d)', s)
    if m:
        val = float(m.group(1).replace(',', ''))
        # If the value is huge (>$500) AND appears to have no decimal,
        # it's probably cents: divide by 100
        if val >= 500 and '.' not in m.group(1):
            val = val / 100
        return val
    return None


def _consolidate_by_url(items):
    """Merge multiple entries with the same URL: keep the longest name and
    any non-null price. This fixes the common bug where a product has
    multiple <a> tags (image link, name link, reviews link) — the image
    link has empty text, the reviews link has 'N Reviews', and only the
    name link has the real product name. Without consolidation, only the
    first one (often the empty image link) is kept."""
    by_url = {}
    for item in items:
        url = item['url']
        if url not in by_url:
            by_url[url] = dict(item)
        else:
            existing = by_url[url]
            new_name = item.get('name', '') or ''
            if len(new_name) > len(existing.get('name', '') or ''):
                existing['name'] = new_name
            if existing.get('price') is None and item.get('price') is not None:
                existing['price'] = item['price']
    return list(by_url.values())


def _extract_products_from_links(soup, base_url, link_pattern,
                                   excluded_url_words=None):
    """Generic helper: find all <a> tags whose href matches link_pattern,
    extract name + price, then consolidate duplicates so we keep the
    real product names instead of empty/junk text from image links.

    Returns list of {name, url, price} dicts.
    """
    excluded = set(excluded_url_words or [])
    raw = []
    for a in soup.find_all('a', href=link_pattern):
        href = a.get('href', '')
        if not href: continue
        # Build full URL
        if href.startswith('/'):
            url = base_url.rstrip('/') + href.split('?')[0]
        elif href.startswith('http'):
            url = href.split('?')[0]
        else:
            continue
        if not url: continue
        # Skip excluded paths (cart, checkout, search, account, etc.)
        href_lower = href.lower()
        if any(x in href_lower for x in excluded): continue
        # Get name from any of these sources
        name = (a.get('aria-label') or a.get('title') or
                a.get_text(' ', strip=True))[:200].strip()
        # Find price in nearby DOM
        price = None
        parent = a.parent
        for _ in range(4):
            if parent is None: break
            # Prefer a price-classed element
            for cls_pat in ['price', 'money', 'amount']:
                el = parent.find(class_=re.compile(cls_pat, re.I))
                if el:
                    p = parse_price(el.get_text())
                    if p: price = p; break
            if price: break
            # Fall back to any $-formatted text
            p = parse_price(parent.get_text(' ', strip=True))
            if p: price = p; break
            parent = parent.parent
        raw.append({'name': name, 'url': url, 'price': price})
    return _consolidate_by_url(raw)


def _filter_real_products(items, min_name_len=8, junk_names=None,
                            junk_phrases=None):
    """Apply common name-quality filters AFTER consolidation."""
    junk_names = junk_names or set()
    junk_phrases = junk_phrases or []
    out = []
    for p in items:
        name = (p.get('name') or '').strip()
        if not name or len(name) < min_name_len: continue
        n_low = name.lower()
        if n_low in junk_names: continue
        if any(ph in n_low for ph in junk_phrases): continue
        # Reject if too few letters (catches emoji-heavy junk)
        if len(re.findall(r'[a-z]', n_low)) < 5: continue
        # Reject "N Reviews" / "N reviews" / pure numbers
        if re.match(r'^\d+\s*(reviews?|review|items?|results?)?\s*$', n_low):
            continue
        out.append(p)
    return out


SHOPIFY_JUNK_NAMES = {
    'gift cards', 'gift card', 'shop', 'shop all', 'home', 'about',
    'contact', 'cart', 'login', 'account', 'menu', 'search',
    'newsletter', 'subscribe',
}
SHOPIFY_JUNK_PHRASES = ['shop long', 'view all', 'shop now', 'gift card']


def _parse_shopify_search(soup, base_url):
    """Shopify: products at /products/<slug>"""
    items = _extract_products_from_links(
        soup, base_url, re.compile(r'/products/'),
        excluded_url_words=['/cart', '/checkout', '/account'])
    return _filter_real_products(items, min_name_len=5,
                                   junk_names=SHOPIFY_JUNK_NAMES,
                                   junk_phrases=SHOPIFY_JUNK_PHRASES)


def _parse_cscart_search(soup, base_url):
    """CS-Cart: products at various paths but typically /<slug>/"""
    # Try product-title selectors first (more reliable)
    selectors = ['a.product-title', 'a[class*="product-title"]',
                 '.ut2-gl__name a', '.ty-grid-list__item-name a',
                 '.product-name a']
    raw = []
    for sel in selectors:
        for a in soup.select(sel):
            href = a.get('href', '')
            if not href: continue
            url = (base_url.rstrip('/') + href.split('?')[0]) if href.startswith('/') else \
                  (href.split('?')[0] if href.startswith('http') else None)
            if not url: continue
            name = a.get_text(' ', strip=True)[:200].strip()
            price = None
            parent = a.parent
            for _ in range(4):
                if parent is None: break
                p = parse_price(parent.get_text(' ', strip=True))
                if p: price = p; break
                parent = parent.parent
            raw.append({'name': name, 'url': url, 'price': price})
    items = _consolidate_by_url(raw)
    if items:
        return _filter_real_products(items, min_name_len=8)
    # Fallback to generic if no product-title selectors matched
    return _parse_generic_search(soup, base_url)


def _parse_volusion_search(soup, base_url):
    """Volusion / older asp shops: products at /product-p/<id>.htm"""
    items = _extract_products_from_links(
        soup, base_url, re.compile(r'/(p|product)-p/[^/]+\.htm', re.I))
    return _filter_real_products(items, min_name_len=8)


def _parse_woocommerce_search(soup, base_url):
    """WooCommerce: products at /product/<slug>"""
    items = _extract_products_from_links(
        soup, base_url, re.compile(r'/product/'),
        excluded_url_words=['/cart', '/checkout', '/category', '/tag'])
    return _filter_real_products(items, min_name_len=8)


def _parse_generic_search(soup, base_url):
    """Last-resort fallback: any product-looking link."""
    pattern = re.compile(
        r'/(products?|p|item|shop|film)/|product-p/', re.I)
    raw = []
    for a in soup.find_all('a', href=True):
        href = a['href']
        if not pattern.search(href): continue
        url = (base_url.rstrip('/') + href.split('?')[0]) if href.startswith('/') else \
              (href.split('?')[0] if href.startswith('http') else None)
        if not url: continue
        # Skip if not within base_url's domain
        try:
            if urlparse(url).netloc and urlparse(url).netloc != urlparse(base_url).netloc:
                continue
        except Exception:
            pass
        name = (a.get('aria-label') or a.get('title') or
                a.get_text(' ', strip=True))[:200].strip()
        price = None
        parent = a.parent
        for _ in range(3):
            if parent is None: break
            p = parse_price(parent.get_text(' ', strip=True))
            if p: price = p; break
            parent = parent.parent
        raw.append({'name': name, 'url': url, 'price': price})
    items = _consolidate_by_url(raw)
    return _filter_real_products(items, min_name_len=8)


# Each platform's signature in the homepage HTML
PLATFORM_DETECTORS = {
    'shopify':     [r'cdn\.shopify\.com', r'Shopify\.theme', r'shopify-section'],
    'cscart':      [r'cs-cart', r'tygh-', r'class="ut2-', r'dispatch=products'],
    'volusion':    [r'volusion', r'/product-p/[^/]+\.htm', r'/v/vspfiles/'],
    'woocommerce': [r'woocommerce', r'wp-content/plugins/woocommerce',
                    r'wc-blocks', r'wp-includes/js/wp-emoji'],
}

# Platform -> (search URL builder, parser)
PLATFORM_HANDLERS = {
    'shopify':     {
        'search_url': lambda home, q: f'{home.rstrip("/")}/search?q={q.replace(" ", "+")}',
        'parser': _parse_shopify_search,
    },
    'cscart':      {
        'search_url': lambda home, q: f'{home.rstrip("/")}/?subcats=Y&pcode_from_q=Y&pshort=Y&pfull=Y&pname=Y&pkeywords=Y&search_performed=Y&q={q.replace(" ", "+")}&dispatch=products.search',
        'parser': _parse_cscart_search,
    },
    'volusion':    {
        'search_url': lambda home, q: f'{home.rstrip("/")}/searchresults.asp?Search={q.replace(" ", "+")}',
        'parser': _parse_volusion_search,
    },
    'woocommerce': {
        'search_url': lambda home, q: f'{home.rstrip("/")}/?s={q.replace(" ", "+")}&post_type=product',
        'parser': _parse_woocommerce_search,
    },
    'generic':     {
        # Multiple search URL patterns to try in order
        'search_url': lambda home, q: f'{home.rstrip("/")}/search?q={q.replace(" ", "+")}',
        'parser': _parse_generic_search,
    },
    # Specialized built-in retailers (parsers tuned for them)
    'bh': {
        'search_url': lambda home, q: f'{home.rstrip("/")}/c/search?q={q.replace(" ", "%20")}&sts=ma',
        'parser': lambda s, base_url: _parse_bh_search(s, base_url),
    },
    'bluemoon': {
        'search_url': lambda home, q: f'{home.rstrip("/")}/shop/search?keywords={q.replace(" ", "%20")}',
        'parser': lambda s, base_url: _parse_bluemoon_search(s, base_url),
    },
    'keh': {
        'search_url': lambda home, q: f'{home.rstrip("/")}/shop/search/?q={q.replace(" ", "+")}',
        'parser': lambda s, base_url: _parse_keh_search(s, base_url),
    },
    'samys': {
        # Samy's: /s/<query>  (path-based search)
        # Products at /p/Film/<sku>/<slug>/<id>.html
        'search_url': lambda home, q: f'{home.rstrip("/")}/s/{q.replace(" ", "%20")}',
        'parser': lambda s, base_url: _parse_samys_search(s, base_url),
    },
    'occamera': {
        # OC Camera: /SearchResults.asp?Search=<query>&Submit= (capital S, trailing Submit=)
        # Products at /product-p/<sku>.htm
        'search_url': lambda home, q: f'{home.rstrip("/")}/SearchResults.asp?Search={q.replace(" ", "+")}&Submit=',
        'parser': lambda s, base_url: _parse_occamera_search(s, base_url),
    },
    'photocare': {
        # Photocare: /searchresults.asp?Search=<query> (lowercase)
        # Products at /<slug>_p/<id>.htm
        'search_url': lambda home, q: f'{home.rstrip("/")}/searchresults.asp?Search={q.replace(" ", "+")}',
        'parser': lambda s, base_url: _parse_photocare_search(s, base_url),
    },
    'moment': {
        # Moment uses query= NOT q=
        # Products at /products/<slug>
        'search_url': lambda home, q: f'{home.rstrip("/")}/search?query={q.replace(" ", "%20")}',
        'parser': lambda s, base_url: _parse_shopify_search(s, base_url),
    },
    'districtcamera': {
        # District Camera: /search?type=product&q=<query>
        # Products at /products/<slug>
        'search_url': lambda home, q: f'{home.rstrip("/")}/search?type=product&q={q.replace(" ", "+")}',
        'parser': lambda s, base_url: _parse_shopify_search(s, base_url),
    },
    'freestyle': {
        # Freestyle: /search?q=<query>
        # Products at /<sku>-<slug> (no /products/ prefix — custom path)
        'search_url': lambda home, q: f'{home.rstrip("/")}/search?q={q.replace(" ", "+")}',
        'parser': lambda s, base_url: _parse_freestyle_search(s, base_url),
    },
}


def _parse_bh_search(soup, base_url):
    """B&H Photo: products at /c/product/<id>-REG/<slug>.html"""
    items = _extract_products_from_links(
        soup, base_url, re.compile(r'/c/product/'),
        excluded_url_words=['/cart', '/account'])
    return _filter_real_products(items, min_name_len=8)


def _parse_bluemoon_search(soup, base_url):
    """Blue Moon Camera: products at /shop/product/<sku>/<slug>"""
    items = _extract_products_from_links(
        soup, base_url, re.compile(r'/shop/product/'))
    return _filter_real_products(items, min_name_len=5)


def _parse_keh_search(soup, base_url):
    """KEH Camera: products at /shop/<slug>.html"""
    items = _extract_products_from_links(
        soup, base_url, re.compile(r'/shop/[^/?]+\.html'),
        excluded_url_words=['/search', '/category', '/cart',
                             '/checkout', '/account'])
    return _filter_real_products(items, min_name_len=8)


def _parse_samys_search(soup, base_url):
    """Samy's Camera: products at /p/<category>/<sku>/<slug>/<id>.html"""
    items = _extract_products_from_links(
        soup, base_url, re.compile(r'/p/[^/]+/\d+/'))
    return _filter_real_products(items, min_name_len=8)


def _parse_occamera_search(soup, base_url):
    """OC Camera: products at /product-p/<sku>.htm"""
    items = _extract_products_from_links(
        soup, base_url, re.compile(r'/product-p/[^/]+\.htm', re.I))
    return _filter_real_products(items, min_name_len=8)


def _parse_photocare_search(soup, base_url):
    """Photocare: products at /<slug>_p/<id>.htm"""
    items = _extract_products_from_links(
        soup, base_url, re.compile(r'_p/\d+\.htm', re.I))
    return _filter_real_products(items, min_name_len=8)


def _parse_freestyle_search(soup, base_url):
    """Freestyle Photo: products at /<sku>-<slug> with 5+ digit prefix.
    Examples: /7519606-Kodak-Ektacolor-Pro-400-..."""
    items = _extract_products_from_links(
        soup, base_url, re.compile(r'^/?\d{5,}-'))
    return _filter_real_products(items, min_name_len=8)


def detect_platform(soup, url=None):
    """Returns platform name based on homepage HTML markers."""
    if not soup or soup == 'TIMEOUT':
        return 'generic'
    raw = str(soup)[:50000]  # check first 50KB only for speed
    matches = {}
    for platform, patterns in PLATFORM_DETECTORS.items():
        score = sum(1 for p in patterns if re.search(p, raw, re.I))
        if score:
            matches[platform] = score
    if not matches:
        return 'generic'
    # Return platform with highest match count
    return max(matches, key=matches.get)


def load_platform_cache():
    if not os.path.exists(PLATFORM_DETECTION_CACHE):
        return {}
    try:
        with open(PLATFORM_DETECTION_CACHE, encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def save_platform_cache(cache):
    try:
        with open(PLATFORM_DETECTION_CACHE, 'w', encoding='utf-8') as f:
            json.dump(cache, f, indent=2)
    except Exception:
        pass


async def auto_detect_platform_for_retailer(ret_key, cfg):
    """Visits homepage, detects platform, returns platform name.
    Caches results across runs."""
    cache = load_platform_cache()
    if cfg['home'] in cache:
        return cache[cfg['home']]
    print(f'  Auto-detecting platform for {cfg["name"]} ({cfg["home"]})…', end=' ', flush=True)
    soup = await fetch_smart(cfg['home'], cfg['mode'], timeout=20)
    platform = detect_platform(soup, cfg['home'])
    print(f'-> {platform}')
    cache[cfg['home']] = platform
    save_platform_cache(cache)
    return platform


# ============================================================
# 8. Per-retailer product-page parsers (for individual product URLs)
# ============================================================

def is_404(soup):
    if not soup or soup == 'TIMEOUT': return False
    return 'NOT FOUND 404' in (soup.get_text() or '')


def extract_jsonld_product(soup):
    for script in soup.find_all('script', type='application/ld+json'):
        try:
            data = json.loads(script.string or '')
            cands = data if isinstance(data, list) else [data]
            for d in list(cands):
                if isinstance(d, dict) and '@graph' in d:
                    cands.extend(d['@graph'])
            for d in cands:
                if isinstance(d, dict) and d.get('@type') == 'Product':
                    offers = d.get('offers', {})
                    if isinstance(offers, list): offers = offers[0]
                    price = offers.get('price') or offers.get('lowPrice')
                    avail = (offers.get('availability') or '').lower()
                    return {
                        'name': d.get('name', ''),
                        'price': float(price) if price else None,
                        'in_stock': 'instock' in avail or 'in_stock' in avail,
                    }
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            continue
    return None


def page_says_in_stock(soup):
    text = soup.get_text(' ', strip=True).lower()
    if any(s in text for s in ['out of stock', 'sold out', 'currently unavailable',
                                'temporarily unavailable', 'no longer available',
                                'notify me when']):
        return False
    if any(s in text for s in ['add to cart', 'add to bag', 'buy now', 'in stock']):
        return True
    return None


def find_visible_price(soup):
    for sel in [
        {'class_': re.compile(r'product[-_ ]?price', re.I)},
        {'class_': re.compile(r'price[-_ ]?now|current[-_ ]?price|sale[-_ ]?price', re.I)},
        {'class_': re.compile(r'^price', re.I)},
        {'class_': re.compile(r'price', re.I)},
    ]:
        el = soup.find(**sel)
        if el:
            p = parse_price(el.get_text())
            if p: return p
    return None


def shopify_extract(soup):
    for s in soup.find_all('script'):
        txt = s.string or ''
        m = re.search(r'"price"\s*:\s*(\d+)\s*[,}]', txt)
        if m:
            cents = int(m.group(1))
            if 100 <= cents <= 50000:
                return cents / 100
    return None


def _meta_price_extract(soup):
    """Try various meta tag patterns for prices."""
    patterns = [
        ('meta', {'itemprop': 'price'}),
        ('meta', {'property': 'product:price:amount'}),
        ('meta', {'property': 'og:price:amount'}),
        ('meta', {'name': 'twitter:data1'}),
    ]
    for tag, attrs in patterns:
        el = soup.find(tag, attrs)
        if el:
            content = el.get('content', '')
            p = parse_price(content) or parse_price(f'${content}')
            if p: return p
    return None


def _last_resort_price(soup):
    """Find ANY price-shaped string on the page. Used as a last resort.
    Picks the price that appears most prominently (largest/highest in DOM)."""
    body = soup.find('body') or soup
    candidates = []
    # Search elements within reasonable price-display tags. Include <li>
    # (used by Bootstrap-style themes like Freestyle) and headers.
    for tag_name in ['span', 'div', 'p', 'strong', 'b', 'li',
                     'h1', 'h2', 'h3', 'h4', 'h5']:
        for el in body.find_all(tag_name):
            # Use stripped text and also check the price-only content
            txt = el.get_text(' ', strip=True)
            # Skip tags that contain child elements (we want leaf-level price tags)
            if el.find(['div', 'span', 'p', 'li']): continue
            # Pattern: just a $-price, optionally with surrounding whitespace
            if re.fullmatch(r'\$\s*[0-9,]+(?:\.[0-9]{1,2})?', txt):
                p = parse_price(txt)
                if p and 1 <= p <= 1000:
                    candidates.append(p)
    if candidates:
        # Pick the most common — main price usually repeats more than
        # comparison/strikethrough prices
        from collections import Counter
        counts = Counter(candidates)
        return counts.most_common(1)[0][0]
    return None


def universal_product_parse(soup, ship_text, retailer_label):
    """Works for any product page — tries JSON-LD, meta tags, visible price,
    Shopify inline JSON, then last-resort scan."""
    if soup == 'TIMEOUT': return (None, None, '', 'timeout')
    if not soup: return (None, None, '', 'fetch failed (network)')
    if is_404(soup): return (None, None, '', '404 — wrong URL')
    if page_looks_blocked(soup):
        return (None, None, '', f'bot challenge — visit {retailer_label} manually first')
    # Strategy 1: JSON-LD structured data
    res = extract_jsonld_product(soup)
    if res and res['price']:
        return (res['in_stock'], res['price'], ship_text, '')
    s = page_says_in_stock(soup)
    # Strategy 2: meta tags
    p = _meta_price_extract(soup)
    if p: return (s, p, ship_text, '')
    # Strategy 3: visible price element
    p = find_visible_price(soup)
    if p: return (s, p, ship_text, '')
    # Strategy 4: Shopify inline JSON
    p = shopify_extract(soup)
    if p: return (s, p, ship_text, '')
    # Strategy 5: last-resort scan for price-only elements
    p = _last_resort_price(soup)
    if p: return (s, p, ship_text, '')
    return (None, None, '', 'no JSON-LD or price element')


def parse_bhphoto_product(soup):
    if soup == 'TIMEOUT': return (None, None, '', 'timeout')
    if not soup: return (None, None, '', 'fetch failed')
    if is_404(soup): return (None, None, '', '404')
    if page_looks_blocked(soup):
        return (None, None, '', 'B&H block — visit manually first')
    res = extract_jsonld_product(soup)
    if res and res['price']:
        return (res['in_stock'], res['price'], 'Free shipping over $49 (B&H)', '')
    pm = soup.find('meta', {'property': 'product:price:amount'})
    am = soup.find('meta', {'property': 'product:availability'})
    if pm:
        return (am and 'in stock' in am.get('content', '').lower(),
                float(pm.get('content', 0)) or None,
                'Free shipping over $49 (B&H)', '')
    return (None, None, '', 'no JSON-LD/meta')


def get_parser_for_retailer(ret_key, cfg):
    """Returns the right product-page parser for a retailer."""
    if ret_key == 'bhphoto':
        return parse_bhphoto_product
    name = cfg.get('name', ret_key)
    ship_text = f'Calculated at checkout ({name})'
    return lambda s: universal_product_parse(s, ship_text, name)


# ============================================================
# 9. Discovery
# ============================================================

def detect_pack_size(name_lower):
    if any(h in name_lower for h in PACK_HINTS_5): return 5
    if any(h in name_lower for h in PACK_HINTS_SINGLE): return 1
    return None


def is_expired(name_lower):
    return any(h in name_lower for h in EXPIRED_HINTS)


def normalize_film_name(raw_name):
    n = raw_name.lower()
    for canonical, must_all in FILM_RULES:
        if all(t in n for t in must_all):
            excludes = FILM_EXCLUDES.get(canonical, [])
            if any(t in n for t in excludes):
                continue
            return canonical
    return None


def looks_like_real_product_name(name, brands, formats):
    n = name.lower()
    dollar_count = n.count('$')
    word_count = len(re.findall(r'[a-z]{3,}', n))
    if dollar_count >= 2 and word_count < 4: return False
    if not any(b in n for b in brands): return False
    if not any(re.search(rf'(^|\D){f}(\D|$)', n) for f in formats):
        return False
    return True


def price_passes_sanity(price, pack_size):
    if price is None: return True
    if pack_size >= 5 and price < MIN_PRICE_5_PACK: return False
    if pack_size == 1 and price < MIN_PRICE_SINGLE: return False
    return True


async def discover_one_retailer(ret_key, cfg, brands, formats):
    """For both built-in and custom retailers. Auto-detects platform if needed."""
    # Determine platform
    platform = cfg.get('platform')
    if platform is None:  # custom retailer with no platform set
        platform = await auto_detect_platform_for_retailer(ret_key, cfg)
        cfg['platform'] = platform

    if platform not in PLATFORM_HANDLERS:
        return [], f'unknown platform "{platform}"', {}

    handler = PLATFORM_HANDLERS[platform]
    diagnostics = {'platform': platform, 'queries': {}}
    all_products = []

    for brand in brands:
        for fmt in formats:
            query = f'{brand} {fmt}'
            search_url = handler['search_url'](cfg['home'], query)
            print(f'  searching "{query}" ({platform})…', end=' ', flush=True)
            # JS-heavy sites: skip curl_cffi entirely, go straight to attach
            primary = cfg['mode'] if cfg.get('js_required') else 'curl_cffi'
            soup = await fetch_smart(search_url, cfg['mode'],
                                      timeout=PER_SEARCH_TIMEOUT,
                                      primary_mode=primary)
            if soup is None or soup == 'TIMEOUT':
                err = 'fetch failed'
            elif page_looks_blocked(soup):
                err = 'blocked'
            else:
                try:
                    products = handler['parser'](soup, cfg['home'])
                    diagnostics['queries'][query] = {'count': len(products), 'error': ''}
                    all_products.extend(products)
                    print(f'{len(products)} raw')
                    # Debug: if 0 products from a JS-required site, save HTML
                    # for later inspection so we can fix the parser
                    if len(products) == 0 and cfg.get('js_required'):
                        debug_path = f'_debug_{ret_key}_{brand}_{fmt}.html'
                        try:
                            with open(debug_path, 'w', encoding='utf-8') as f:
                                f.write(str(soup))
                            print(f'    [debug HTML saved: {debug_path}]')
                        except Exception:
                            pass
                    await asyncio.sleep(0.6)
                    continue
                except Exception as e:
                    err = f'parse error: {type(e).__name__}'
            diagnostics['queries'][query] = {'count': 0, 'error': err}
            print(f'⚠ {err}')
            await asyncio.sleep(0.6)

    return all_products, '', diagnostics


async def run_discovery(retailers_cfg, brands, formats):
    print('=' * 100)
    print(f'DISCOVERY — searching {len(brands)} brands × {len(formats)} formats')
    print(f'Brands:  {", ".join(brands)}')
    print(f'Formats: {", ".join(formats)}')
    print('=' * 100)
    discovered = {}
    diagnostics = {}

    for ret_key, cfg in retailers_cfg.items():
        if not cfg.get('enabled', True): continue
        custom_tag = ' [CUSTOM]' if cfg.get('is_custom') else ''
        print(f'\n{cfg["name"]}{custom_tag}:')
        all_products, err, diag = await discover_one_retailer(ret_key, cfg, brands, formats)
        diagnostics[ret_key] = diag

        # Dedupe
        seen, unique = set(), []
        for p in all_products:
            if p['url'] not in seen:
                seen.add(p['url'])
                unique.append(p)

        # Filter + categorize
        bucket_counts = {}
        rejection_reasons = {'no_format': 0, 'negative_filter': 0,
                             'not_real_product': 0, 'rejected_examples': []}
        for p in unique:
            n_low = p['name'].lower()
            if not any(re.search(rf'(^|\D){f}(\D|$)', n_low) for f in formats):
                rejection_reasons['no_format'] += 1
                if len(rejection_reasons['rejected_examples']) < 3:
                    rejection_reasons['rejected_examples'].append(
                        f'no_format: {p["name"][:80]}')
                continue
            if any(neg in n_low for neg in NEGATIVE_FILTERS):
                rejection_reasons['negative_filter'] += 1
                if len(rejection_reasons['rejected_examples']) < 3:
                    rejection_reasons['rejected_examples'].append(
                        f'neg_filter: {p["name"][:80]}')
                continue
            if not looks_like_real_product_name(p['name'], brands, formats):
                rejection_reasons['not_real_product'] += 1
                if len(rejection_reasons['rejected_examples']) < 3:
                    rejection_reasons['rejected_examples'].append(
                        f'not_product: {p["name"][:80]}')
                continue
            # Pack size detection. If the name explicitly mentions 5-pack/pro pack,
            # use 5. If it explicitly says "single" or "1 roll", use 1.
            # Otherwise, fall back to price-based inference: any 120 film priced
            # under $25 is essentially guaranteed to be a single roll (5-packs of
            # any 120 film are $50+). Above $25 it's ambiguous, so default to 1
            # (singles are more common in retail than 5-packs).
            pack = detect_pack_size(n_low)
            if pack is None:
                hint_price = p.get('price')
                if hint_price is not None:
                    pack = 1 if hint_price < 25 else (5 if hint_price > 50 else 1)
                else:
                    pack = 1  # default to single, not 5-pack
            if p.get('price') and not price_passes_sanity(p['price'], pack):
                p['price'] = None
            canonical = normalize_film_name(p['name'])
            if canonical is None:
                canonical = p['name'][:60].strip()
                if not re.search(r'\d{2,3}', canonical[:30]):
                    canonical += f' ({formats[0]})'
            entry = {
                'url': p['url'], 'pack_size': pack, 'name': p['name'],
                'expired': is_expired(n_low), 'price_hint': p.get('price'),
            }
            discovered.setdefault(canonical, {}).setdefault(ret_key, []).append(entry)
            bucket_counts[canonical] = bucket_counts.get(canonical, 0) + 1
        rejected = sum(v for k, v in rejection_reasons.items()
                       if k != 'rejected_examples')
        # Save reasons in diagnostics for the HTML report
        if isinstance(diag, dict):
            diag['rejection_breakdown'] = {k: v for k, v in rejection_reasons.items()
                                           if k != 'rejected_examples'}
            diag['rejected_examples'] = rejection_reasons['rejected_examples']
        if bucket_counts:
            short = ', '.join(
                f'{k.split(" (")[0][:18]}:{v}'
                for k, v in sorted(bucket_counts.items(), key=lambda x: -x[1])[:8])
            print(f'  → {sum(bucket_counts.values())} kept ({rejected} rejected): {short}')
        else:
            print(f'  → no items kept ({rejected} rejected: '
                  f'{rejection_reasons["no_format"]} missing format, '
                  f'{rejection_reasons["negative_filter"]} negative filter, '
                  f'{rejection_reasons["not_real_product"]} not real product)')
            for ex in rejection_reasons['rejected_examples']:
                print(f'      ex: {ex}')
    return discovered, diagnostics


def save_discovery_cache(discovered, diagnostics):
    cache = {'timestamp': datetime.now().isoformat(),
             'data': discovered, 'diagnostics': diagnostics}
    with open(DISCOVERY_CACHE, 'w', encoding='utf-8') as f:
        json.dump(cache, f, indent=2)
    print(f'\nDiscovery cache saved -> {DISCOVERY_CACHE}')


def load_discovery_cache():
    if not os.path.exists(DISCOVERY_CACHE):
        return None, None, None
    try:
        with open(DISCOVERY_CACHE, encoding='utf-8') as f:
            cache = json.load(f)
        ts = datetime.fromisoformat(cache['timestamp'])
        age = (datetime.now() - ts).days
        return cache['data'], age, cache.get('diagnostics', {})
    except Exception:
        return None, None, None


def merge_to_listings(discovered, retailers_cfg):
    listings = []
    for film_name, retailers in (discovered or {}).items():
        for ret_key, entries in retailers.items():
            if ret_key not in retailers_cfg: continue
            if not retailers_cfg[ret_key].get('enabled', True): continue
            for e in entries:
                listings.append((film_name, ret_key, e['url'], e['pack_size'],
                                 e['expired'], e['name'], 'discovered'))
    return listings


# ============================================================
# 10. eBay
# ============================================================

EBAY_QUERIES = [
    ('Kodak Portra 400 (120)',     'kodak portra 400 120 -135 -35mm'),
    ('Kodak Portra 800 (120)',     'kodak portra 800 120 -135 -35mm'),
    ('Kodak Portra 160 (120)',     'kodak portra 160 120 -135 -35mm'),
    ('Kodak Gold 200 (120)',       'kodak gold 200 120 -135 -35mm'),
    ('Kodak Ektar 100 (120)',      'kodak ektar 100 120 -135 -35mm'),
    ('Kodak Ektachrome E100 (120)','kodak ektachrome 120 -135 -35mm'),
    ('Kodak Tri-X 400 (120)',      'kodak tri-x 400 120 -135 -35mm'),
    ('Fuji Provia 100F (120)',     'fuji provia 100f 120 -135 -35mm'),
    ('Fuji Velvia 50 (120)',       'fuji velvia 50 120 -135 -35mm'),
    ('Fuji Velvia 100 (120)',      'fuji velvia 100 120 -135 -35mm'),
    ('CineStill 800T (120)',       'cinestill 800t 120 -135 -35mm'),
    ('CineStill 400D (120)',       'cinestill 400d 120 -135 -35mm'),
]


def _parse_ebay_results(soup, max_listings=5):
    items = []
    nodes = soup.select('li.s-card') or soup.select('li.s-item')
    if not nodes: return []
    for node in nodes:
        title_el = (node.select_one('.s-card__title') or
                    node.select_one('.su-card-container__header') or
                    node.select_one('.s-item__title') or
                    node.select_one('span[role="heading"]') or
                    node.select_one('h3'))
        price_el = (node.select_one('.s-card__price') or
                    node.select_one('.s-item__price') or
                    node.select_one('[class*="price"]'))
        url_el = (node.select_one('a.su-link') or
                  node.select_one('a.s-item__link') or
                  node.select_one('a[href*="/itm/"]'))
        if not (title_el and price_el and url_el): continue
        title = title_el.get_text(' ', strip=True)
        if 'shop on ebay' in title.lower(): continue
        if not title or len(title) < 5: continue
        prices = re.findall(r'\$\s*([0-9,]+(?:\.[0-9]{1,2})?)', price_el.get_text(' ', strip=True))
        if not prices: continue
        price = float(prices[0].replace(',', ''))
        url = (url_el.get('href') or '').split('?')[0]
        if not url or '/itm/' not in url: continue
        ship_el = (node.select_one('.s-card__shipping') or
                   node.select_one('.s-item__shipping') or
                   node.select_one('[class*="shipping"]'))
        shipping = ship_el.get_text(' ', strip=True) if ship_el else ''
        loc_el = (node.select_one('.s-card__location') or
                  node.select_one('.s-item__location') or
                  node.select_one('[class*="location"]'))
        seller_loc = loc_el.get_text(' ', strip=True) if loc_el else ''
        cond_el = (node.select_one('.s-card__subtitle') or
                   node.select_one('.SECONDARY_INFO') or
                   node.select_one('.s-item__subtitle'))
        condition = cond_el.get_text(' ', strip=True) if cond_el else ''
        items.append({'title': title[:120], 'price': price, 'shipping': shipping,
                      'url': url, 'seller_loc': seller_loc, 'condition': condition})
    items.sort(key=lambda x: x['price'])
    return items[:max_listings]


async def check_ebay():
    print('\n' + '=' * 100)
    print('EBAY — searching for cheapest active listings per film')
    print('=' * 100)
    results = []
    now = datetime.now().isoformat(timespec='seconds')
    for film, query in EBAY_QUERIES:
        url = f'https://www.ebay.com/sch/i.html?_nkw={query.replace(" ", "+")}&_sop=15&LH_BIN=1'
        print(f'  · {film[:35]:35s}…', end=' ', flush=True)
        soup = await fetch_smart(url, fallback_mode='attach', timeout=PER_SEARCH_TIMEOUT)
        if soup is None or soup == 'TIMEOUT' or page_looks_blocked(soup):
            print('⚠ search failed/blocked')
            continue
        listings = _parse_ebay_results(soup, max_listings=5)
        if not listings:
            print('no results')
            continue
        print(f'{len(listings)} listings, cheapest ${listings[0]["price"]}')
        for l in listings:
            results.append(EbayListing(
                film=film, title=l['title'], price=l['price'],
                shipping=l['shipping'], url=l['url'],
                seller_loc=l['seller_loc'], condition=l['condition'],
                checked_at=now,
            ))
        await asyncio.sleep(1.0)
    return results


def save_ebay_history(results):
    if not results: return
    df = pd.DataFrame([asdict(r) for r in results])
    if os.path.exists(EBAY_HISTORY_FILE):
        df.to_csv(EBAY_HISTORY_FILE, mode='a', header=False, index=False)
    else:
        df.to_csv(EBAY_HISTORY_FILE, index=False)
    print(f'Saved {len(df)} eBay rows -> {EBAY_HISTORY_FILE}')


# ============================================================
# 11. Main check loop
# ============================================================

async def check_listings(listings, retailers_cfg):
    results = []
    now = datetime.now().isoformat(timespec='seconds')
    debug_saves = {}  # ret_key -> count of debug saves so far
    for film, ret_key, url, pack, expired, prod_name, source in listings:
        cfg = retailers_cfg[ret_key]
        parser = get_parser_for_retailer(ret_key, cfg)
        exp_tag = ' [EXP]' if expired else ''
        custom_tag = ' [C]' if cfg.get('is_custom') else ''
        label = f'{film[:30]:30s} @ {cfg["name"][:14]:14s}{custom_tag}{exp_tag}'
        print(f'  · {label}…', end=' ', flush=True)
        primary = cfg['mode'] if cfg.get('js_required') else 'curl_cffi'
        soup = await fetch_smart(url, fallback_mode=cfg['mode'], primary_mode=primary)
        in_stock, price, ship, err = parser(soup)
        if price is not None and price < 1.0:
            err = f'price ${price} suspiciously low — likely parser grabbed wrong element'
            price = None
        # Auto-correct pack size if discovery got it wrong:
        # If pack=5 but price < $25 → it's actually a single roll
        # If pack=1 but price > $50 → it's actually a 5-pack
        if price is not None:
            if pack == 5 and price < 25:
                pack = 1  # Was misclassified
            elif pack == 1 and price > 50:
                # Look at name for 5-pack hints before reclassifying
                if any(h in (prod_name or '').lower() for h in PACK_HINTS_5):
                    pack = 5
                # Otherwise leave as-is (some single rollers are >$50, like Velvia)
        ppr = round(price / pack, 2) if (price and pack) else None
        # Save debug HTML for first 2 product-page parse failures per retailer
        if (err == 'no JSON-LD or price element' and
                soup is not None and soup != 'TIMEOUT'):
            count = debug_saves.get(ret_key, 0)
            if count < 2:
                debug_path = f'_debug_product_{ret_key}_{count+1}.html'
                try:
                    with open(debug_path, 'w', encoding='utf-8') as f:
                        f.write(str(soup))
                    debug_saves[ret_key] = count + 1
                    print(f'⚠ {err}  [debug saved: {debug_path}]')
                except Exception:
                    print(f'⚠ {err}')
            else:
                print(f'⚠ {err}')
        elif err:
            print(f'⚠ {err}')
        else:
            stock = 'in stock' if in_stock else ('out' if in_stock is False else '?')
            print(f'{stock}  ${price}  (${ppr}/roll)' if price else stock)
        results.append(Listing(
            film=film, retailer=cfg['name'], url=url, pack_size=pack,
            in_stock=in_stock, price_total=price, price_per_roll=ppr,
            shipping_info=ship, error=err, fetcher=cfg['mode'],
            expired=expired, source=source, product_name=prod_name,
            checked_at=now,
        ))
        await asyncio.sleep(0.6)
    return results


# ============================================================
# 12. CSV history
# ============================================================

EXPECTED_COLS = [f.name for f in dc_fields(Listing)]


def migrate_history_if_needed():
    if not os.path.exists(HISTORY_FILE): return
    try:
        with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
            header = f.readline().strip().split(',')
    except Exception:
        return
    if header == EXPECTED_COLS: return
    print(f'Migrating history file ({len(header)} cols → {len(EXPECTED_COLS)})...')
    backup = HISTORY_FILE + '.bak'
    os.rename(HISTORY_FILE, backup)
    try:
        old = pd.read_csv(backup, on_bad_lines='skip')
    except Exception as e:
        print(f'  Couldn\'t read old: {e}.')
        return
    defaults = {f.name: (f.default if f.default is not f.default_factory else None)
                for f in dc_fields(Listing)}
    for col in EXPECTED_COLS:
        if col not in old.columns: old[col] = defaults.get(col, '')
    old = old[EXPECTED_COLS]
    old.to_csv(HISTORY_FILE, index=False)
    print(f'  Migrated. Backup: {backup}.')


def save_history(df):
    if os.path.exists(HISTORY_FILE):
        df.to_csv(HISTORY_FILE, mode='a', header=False, index=False)
    else:
        df.to_csv(HISTORY_FILE, index=False)
    print(f'\nSaved {len(df)} rows -> {HISTORY_FILE}')


def detect_changes():
    if not os.path.exists(HISTORY_FILE): return
    try:
        hist = pd.read_csv(HISTORY_FILE)
    except Exception as e:
        print(f'Could not read history: {e}')
        return
    runs = sorted(hist['checked_at'].unique())
    if len(runs) < 2: return
    prev = hist[hist['checked_at'] == runs[-2]]
    curr = hist[hist['checked_at'] == runs[-1]]
    m = curr.merge(prev, on=['film', 'retailer', 'url'], suffixes=('_now', '_prev'), how='left')
    restocks = m[(m['in_stock_now'] == True) & (m['in_stock_prev'] == False)]
    out_now  = m[(m['in_stock_now'] == False) & (m['in_stock_prev'] == True)]
    drops    = m[m['price_total_now'] < m['price_total_prev']]
    rises    = m[m['price_total_now'] > m['price_total_prev']]
    print('\n' + '=' * 100)
    print(f'CHANGES SINCE LAST RUN ({runs[-2]}  ->  {runs[-1]})')
    print('=' * 100)
    if not restocks.empty:
        print('RESTOCKED:')
        for _, r in restocks.iterrows():
            print(f'   {r.film} @ {r.retailer}  ${r.price_total_now}')
    if not out_now.empty:
        print('NOW OUT OF STOCK:')
        for _, r in out_now.iterrows():
            print(f'   {r.film} @ {r.retailer}')
    if not drops.empty:
        print('PRICE DROPS:')
        for _, r in drops.iterrows():
            print(f'   {r.film} @ {r.retailer}  ${r.price_total_prev} -> ${r.price_total_now}')
    if not rises.empty:
        print('PRICE INCREASES:')
        for _, r in rises.iterrows():
            print(f'   {r.film} @ {r.retailer}  ${r.price_total_prev} -> ${r.price_total_now}')
    if all(x.empty for x in [restocks, out_now, drops, rises]):
        print('No changes since last run.')


# ============================================================
# 13. HTML report
# ============================================================

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<title>Film Tracker — {timestamp}</title>
<style>
  body {{ font-family: -apple-system, Segoe UI, Helvetica, sans-serif; margin: 24px; background: #fafafa; color: #222; }}
  h1 {{ margin-top: 0; }} h2 {{ margin-top: 32px; border-bottom: 2px solid #ddd; padding-bottom: 4px; }}
  .meta {{ color: #666; font-size: 13px; margin-bottom: 24px; }}
  input.filter {{ width: 100%; padding: 8px 12px; font-size: 14px; margin-bottom: 12px;
                  border: 1px solid #ccc; border-radius: 4px; box-sizing: border-box; }}
  table {{ border-collapse: collapse; width: 100%; background: white; box-shadow: 0 1px 3px rgba(0,0,0,0.05); }}
  th, td {{ padding: 8px 12px; text-align: left; border-bottom: 1px solid #eee; font-size: 13px; }}
  th {{ background: #f0f0f0; cursor: pointer; user-select: none; position: sticky; top: 0; }}
  th:hover {{ background: #e0e0e0; }}
  tr:hover td {{ background: #f8f9fb; }}
  .stock-yes {{ color: #1a8e3a; font-weight: 600; }} .stock-no {{ color: #b03030; }} .stock-q {{ color: #999; }}
  .expired {{ background: #fff4d6; }}
  a {{ color: #1166cc; text-decoration: none; }} a:hover {{ text-decoration: underline; }}
  .summary {{ display: flex; gap: 16px; margin-bottom: 24px; flex-wrap: wrap; }}
  .stat {{ background: white; padding: 12px 18px; border-radius: 4px; box-shadow: 0 1px 3px rgba(0,0,0,0.05); }}
  .stat .num {{ font-size: 22px; font-weight: 600; }}
  .stat .label {{ font-size: 12px; color: #666; text-transform: uppercase; }}
  details {{ margin: 12px 0; }} details summary {{ cursor: pointer; font-weight: 600; padding: 8px 0; }}
  .price {{ font-variant-numeric: tabular-nums; text-align: right; }}
  img.plot {{ max-width: 100%; border: 1px solid #ddd; border-radius: 4px; }}
  .manual-check-banner {{ background: linear-gradient(135deg, #fff5f5, #ffe8e8);
    border: 2px solid #d83a3a; border-left: 6px solid #d83a3a;
    border-radius: 8px; padding: 18px 22px; margin: 24px 0;
    box-shadow: 0 2px 8px rgba(216, 58, 58, 0.15); }}
  .manual-check-banner h2 {{ margin: 0 0 12px 0; padding: 0; border: none;
    color: #b03030; font-size: 18px; }}
  .manual-check-banner .count-badge {{ display: inline-block; background: #d83a3a;
    color: white; padding: 2px 10px; border-radius: 12px; font-size: 13px;
    margin-left: 8px; font-weight: 600; }}
  .copy-btn {{ background: #f0f0f0; border: 1px solid #ccc; padding: 2px 8px;
    border-radius: 3px; cursor: pointer; font-size: 11px; margin-left: 6px; }}
  .copy-btn:hover {{ background: #e0e0e0; }}
  .copy-btn.copied {{ background: #d4edda; border-color: #1a8e3a; color: #1a8e3a; }}
  .tax-free-badge {{
    display: inline-block; background: #e8f5e9; color: #1a8e3a;
    padding: 1px 6px; border-radius: 3px; font-size: 10px;
    font-weight: 600; text-transform: uppercase; margin-left: 4px;
    border: 1px solid #1a8e3a;
  }}
  .tax-banner {{
    background: #f0f4f8; border-left: 4px solid #2c5282;
    padding: 12px 18px; margin: 16px 0; font-size: 13px;
    border-radius: 4px; color: #2d3748;
  }}
  .tax-banner strong {{ color: #1a365d; }}
</style></head><body>
<h1>120 Film Tracker</h1>
<div class="meta">Generated: {timestamp} • {n_listings} listings • {n_in_stock} in stock • {n_ebay} eBay listings</div>

<div class="summary">
  <div class="stat"><div class="num">{n_listings}</div><div class="label">Total Checked</div></div>
  <div class="stat"><div class="num">{n_in_stock}</div><div class="label">In Stock</div></div>
  <div class="stat"><div class="num">{n_errors}</div><div class="label">Need Manual Check</div></div>
  <div class="stat"><div class="num">{n_films}</div><div class="label">Films</div></div>
  <div class="stat"><div class="num">{n_ebay}</div><div class="label">eBay Listings</div></div>
</div>

{manual_banner}

{tax_banner}

<h2>Best Deals — Cheapest Listed Price (pre-tax)</h2>
{best_deals_html}

{best_deals_tax_section}

<h2>Full Comparison</h2>
<input type="text" class="filter" placeholder="Filter (e.g. 'portra' or 'in stock')…" oninput="filterTable(this, 'main-table')">
{main_html}

<h2>eBay — Cheapest Active Listings</h2>
<input type="text" class="filter" placeholder="Filter eBay listings…" oninput="filterTable(this, 'ebay-table')">
{ebay_html}

<h2>Price History</h2>
{plot_html}

<details><summary>Discovery Diagnostics — what each retailer's search returned</summary>
{diagnostics_html}
</details>

<script>
function filterTable(input, tableId) {{
  const filter = input.value.toLowerCase();
  document.querySelectorAll('#' + tableId + ' tbody tr').forEach(r => {{
    r.style.display = r.textContent.toLowerCase().includes(filter) ? '' : 'none';
  }});
}}
function copyURL(btn, url) {{
  navigator.clipboard.writeText(url).then(() => {{
    btn.textContent = 'copied!';
    btn.classList.add('copied');
    setTimeout(() => {{ btn.textContent = 'copy'; btn.classList.remove('copied'); }}, 1500);
  }});
}}
document.querySelectorAll('table').forEach(table => {{
  table.querySelectorAll('th').forEach((th, idx) => {{
    th.addEventListener('click', () => {{
      const tbody = table.querySelector('tbody');
      const rows = Array.from(tbody.querySelectorAll('tr'));
      const asc = th.dataset.sort !== 'asc';
      rows.sort((a, b) => {{
        const av = a.children[idx].textContent.trim();
        const bv = b.children[idx].textContent.trim();
        const an = parseFloat(av.replace(/[^0-9.-]/g, ''));
        const bn = parseFloat(bv.replace(/[^0-9.-]/g, ''));
        if (!isNaN(an) && !isNaN(bn)) return asc ? an - bn : bn - an;
        return asc ? av.localeCompare(bv) : bv.localeCompare(av);
      }});
      rows.forEach(r => tbody.appendChild(r));
      table.querySelectorAll('th').forEach(t => t.dataset.sort = '');
      th.dataset.sort = asc ? 'asc' : 'desc';
    }});
  }});
}});
</script></body></html>"""


def _esc(s): return html_mod.escape(str(s) if s is not None else '')

def _stock_html(in_stock):
    if in_stock is True: return '<span class="stock-yes">YES</span>'
    if in_stock is False: return '<span class="stock-no">NO</span>'
    return '<span class="stock-q">?</span>'


def _apply_tax(price, retailer_key, tax_cfg, retailers_cfg):
    """Return after-tax price. Returns price unchanged if tax disabled,
    retailer is tax-free, or price is None."""
    if price is None or not tax_cfg or not tax_cfg.get('enabled'):
        return price
    cfg = (retailers_cfg or {}).get(retailer_key, {})
    if cfg.get('tax_free'):
        return price
    rate = tax_cfg.get('effective_rate', 0.0)
    return round(price * (1 + rate / 100.0), 2)


def _retailer_key_for_name(retailer_name, retailers_cfg):
    """Reverse lookup: given the display name like 'B&H Photo', find the key."""
    if not retailers_cfg: return None
    for key, cfg in retailers_cfg.items():
        if cfg.get('name') == retailer_name:
            return key
    return None


def _build_main_table(df, tax_cfg=None, retailers_cfg=None):
    if df.empty: return '<p>No data.</p>'
    df_sorted = df.sort_values(['film', 'price_per_roll'], na_position='last')
    tax_enabled = tax_cfg and tax_cfg.get('enabled')
    rows = []
    for _, r in df_sorted.iterrows():
        price = f'${r.price_total:.2f}' if pd.notna(r.price_total) else '—'
        ppr = f'${r.price_per_roll:.2f}' if pd.notna(r.price_per_roll) else '—'
        pack = f'{int(r.pack_size)}-pack' if r.pack_size > 1 else 'single'
        exp = 'EXPIRED' if r.expired else ''
        cls = ' class="expired"' if r.expired else ''
        url_disp = (r.url[:40] + '…') if len(r.url) > 40 else r.url
        # Tax columns
        tax_cells = ''
        if tax_enabled:
            ret_key = _retailer_key_for_name(r.retailer, retailers_cfg)
            cfg = (retailers_cfg or {}).get(ret_key, {}) if ret_key else {}
            tax_free = cfg.get('tax_free', False)
            with_tax = _apply_tax(r.price_total if pd.notna(r.price_total) else None,
                                   ret_key, tax_cfg, retailers_cfg)
            ppr_with_tax = _apply_tax(r.price_per_roll if pd.notna(r.price_per_roll) else None,
                                       ret_key, tax_cfg, retailers_cfg)
            with_tax_str = f'${with_tax:.2f}' if with_tax is not None else '—'
            ppr_with_tax_str = f'${ppr_with_tax:.2f}' if ppr_with_tax is not None else '—'
            badge = ' <span class="tax-free-badge">tax-free</span>' if tax_free else ''
            tax_cells = (f'<td class="price">{with_tax_str}{badge}</td>'
                         f'<td class="price">{ppr_with_tax_str}</td>')
        rows.append(
            f'<tr{cls}><td>{_esc(r.film)}</td><td>{_esc(r.retailer)}</td>'
            f'<td>{_stock_html(r.in_stock)}</td><td>{pack}</td><td>{exp}</td>'
            f'<td class="price">{price}</td><td class="price">{ppr}</td>'
            f'{tax_cells}'
            f'<td>{_esc(r.shipping_info)}</td>'
            f'<td><a href="{_esc(r.url)}" target="_blank">{_esc(url_disp)}</a></td></tr>')
    tax_headers = ''
    if tax_enabled:
        rate_label = f'{tax_cfg["effective_rate"]:.3g}%'
        tax_headers = (f'<th>With Tax<br><small>({rate_label})</small></th>'
                       f'<th>Per Roll<br><small>w/ tax</small></th>')
    return ('<table id="main-table"><thead><tr>'
            '<th>Film</th><th>Retailer</th><th>Stock</th><th>Pack</th>'
            '<th>Status</th><th>Price</th><th>Per Roll</th>'
            f'{tax_headers}'
            '<th>Shipping</th><th>URL</th>'
            '</tr></thead><tbody>' + ''.join(rows) + '</tbody></table>')


def _build_best_deals_html(df, tax_cfg=None, retailers_cfg=None,
                            use_tax=False, title_suffix=''):
    """Builds 'cheapest in stock' table. If use_tax=True, ranks by after-tax
    per-roll price; otherwise by listed per-roll price."""
    in_stock = df[df['in_stock'] == True].copy()
    if in_stock.empty: return '<p>Nothing in stock right now.</p>'
    # Compute the comparison price column
    if use_tax and tax_cfg and tax_cfg.get('enabled'):
        def with_tax(row):
            ret_key = _retailer_key_for_name(row['retailer'], retailers_cfg)
            return _apply_tax(row['price_per_roll'], ret_key, tax_cfg, retailers_cfg)
        in_stock['rank_price'] = in_stock.apply(with_tax, axis=1)
    else:
        in_stock['rank_price'] = in_stock['price_per_roll']
    in_stock = in_stock[in_stock['rank_price'].notna()]
    if in_stock.empty: return '<p>No prices available.</p>'
    cheapest = in_stock.sort_values(['expired', 'rank_price']).groupby('film', as_index=False).first()
    rows = []
    for _, r in cheapest.iterrows():
        pack = f'{int(r.pack_size)}-pack' if r.pack_size > 1 else 'single'
        exp = 'EXPIRED' if r.expired else ''
        ret_key = _retailer_key_for_name(r.retailer, retailers_cfg)
        cfg = (retailers_cfg or {}).get(ret_key, {}) if ret_key else {}
        tax_free = cfg.get('tax_free', False)
        badge = ' <span class="tax-free-badge">tax-free</span>' if (tax_free and use_tax) else ''
        if use_tax and tax_cfg and tax_cfg.get('enabled'):
            tot = _apply_tax(r.price_total, ret_key, tax_cfg, retailers_cfg)
            ppr = r.rank_price
            tot_str = f'${tot:.2f}' if tot is not None else '—'
            ppr_str = f'${ppr:.2f}' if pd.notna(ppr) else '—'
        else:
            tot_str = f'${r.price_total:.2f}' if pd.notna(r.price_total) else '—'
            ppr_str = f'${r.price_per_roll:.2f}' if pd.notna(r.price_per_roll) else '—'
        rows.append(
            f'<tr><td>{_esc(r.film)}</td><td>{_esc(r.retailer)}{badge}</td>'
            f'<td>{pack}</td><td>{exp}</td>'
            f'<td class="price">{tot_str}</td><td class="price">{ppr_str}</td>'
            f'<td><a href="{_esc(r.url)}" target="_blank">buy</a></td></tr>')
    return ('<table><thead><tr><th>Film</th><th>Retailer</th><th>Pack</th>'
            '<th>Status</th><th>Total</th><th>Per Roll</th><th>Link</th>'
            '</tr></thead><tbody>' + ''.join(rows) + '</tbody></table>')


def _build_ebay_html(ebay_results, tax_cfg=None):
    if not ebay_results: return '<p>No eBay data this run.</p>'
    apply_tax = (tax_cfg and tax_cfg.get('enabled') and
                 tax_cfg.get('tax_on_ebay', True))
    rows = []
    for r in sorted(ebay_results, key=lambda x: (x.film, x.price)):
        tax_cell = ''
        if apply_tax:
            with_tax = r.price * (1 + tax_cfg['effective_rate'] / 100.0)
            tax_cell = f'<td class="price">${with_tax:.2f}</td>'
        rows.append(
            f'<tr><td>{_esc(r.film)}</td><td>{_esc(r.title)}</td>'
            f'<td class="price">${r.price:.2f}</td>'
            f'{tax_cell}'
            f'<td>{_esc(r.shipping)}</td>'
            f'<td>{_esc(r.condition)}</td>'
            f'<td>{_esc(r.seller_loc)}</td>'
            f'<td><a href="{_esc(r.url)}" target="_blank">view</a></td></tr>')
    headers = ['Film', 'Title', 'Price']
    if apply_tax: headers.append(f'With Tax<br><small>({tax_cfg["effective_rate"]:.3g}%)</small>')
    headers += ['Shipping', 'Condition', 'Location', 'Link']
    th_html = ''.join(f'<th>{h}</th>' for h in headers)
    return (f'<table id="ebay-table"><thead><tr>{th_html}'
            '</tr></thead><tbody>' + ''.join(rows) + '</tbody></table>')


def _build_manual_check_banner(df):
    err_df = df[df['error'] != ''].copy() if not df.empty else pd.DataFrame()
    if err_df.empty: return ''
    rows = []
    for reason, grp in err_df.groupby('error'):
        rows.append(
            f'<tr><td colspan="3" style="background:#fff0f0;font-weight:600;'
            f'padding-top:14px;">⚠ {_esc(reason)} ({len(grp)})</td></tr>')
        for _, r in grp.iterrows():
            url_disp = (r.url[:60] + '…') if len(r.url) > 60 else r.url
            rows.append(
                f'<tr><td>{_esc(r.film)}</td><td>{_esc(r.retailer)}</td>'
                f'<td><a href="{_esc(r.url)}" target="_blank">{_esc(url_disp)}</a>'
                f'<button class="copy-btn" onclick="copyURL(this, \'{_esc(r.url)}\')">copy</button>'
                f'</td></tr>')
    return (f'<div class="manual-check-banner">'
            f'<h2>⚠ URLs to Check Manually <span class="count-badge">{len(err_df)}</span></h2>'
            f'<p style="margin-top:0;color:#666;font-size:13px;">'
            f'These listings couldn\'t be parsed automatically. Click each URL to verify, '
            f'or click <strong>copy</strong> to copy to clipboard.'
            f'</p>'
            f'<table><thead><tr><th>Film</th><th>Retailer</th><th>URL</th></tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table></div>')


def _build_diagnostics_html(diagnostics):
    if not diagnostics: return '<p>No diagnostics.</p>'
    rows = []
    for ret_key, diag in diagnostics.items():
        platform = diag.get('platform', '?') if isinstance(diag, dict) else '?'
        queries = diag.get('queries', {}) if isinstance(diag, dict) else {}
        for query, info in queries.items():
            rows.append(
                f'<tr><td>{_esc(ret_key)}</td><td>{_esc(platform)}</td>'
                f'<td>{_esc(query)}</td>'
                f'<td>{info.get("count", 0)}</td>'
                f'<td>{_esc(info.get("error", ""))}</td></tr>')
    if not rows: return '<p>No diagnostics.</p>'
    return ('<table><thead><tr><th>Retailer</th><th>Platform</th><th>Query</th>'
            '<th>Raw Results</th><th>Error/Note</th></tr></thead><tbody>'
            + ''.join(rows) + '</tbody></table>')


def _build_tax_banner(tax_cfg, retailers_cfg):
    """Renders an info banner explaining what tax is being applied."""
    if not tax_cfg or not tax_cfg.get('enabled'):
        return ''
    state = tax_cfg['state']
    rate = tax_cfg['effective_rate']
    override_note = ' (custom rate)' if tax_cfg.get('rate_override') else ''
    tax_free_keys = tax_cfg.get('tax_free_retailers', set())
    tax_free_names = []
    for key in tax_free_keys:
        cfg = (retailers_cfg or {}).get(key)
        if cfg:
            tax_free_names.append(cfg['name'])
    tax_free_str = ', '.join(tax_free_names) if tax_free_names else 'none'
    return (
        f'<div class="tax-banner">'
        f'<strong>📊 Tax-aware pricing:</strong> Showing list price + '
        f'estimated <strong>{rate:.3g}% {state}</strong> sales tax{override_note}. '
        f'Tax-free retailers: <strong>{_esc(tax_free_str)}</strong>. '
        f'<em>Note: this is a state-level approximation; your actual local tax '
        f'may be higher in cities with local sales taxes.</em>'
        f'</div>')


def write_html_report(df, ebay_results, discovered=None, diagnostics=None,
                      tax_cfg=None, retailers_cfg=None):
    n_listings = len(df)
    n_in_stock = int((df['in_stock'] == True).sum()) if not df.empty else 0
    n_errors = int((df['error'] != '').sum()) if not df.empty else 0
    n_films = df['film'].nunique() if not df.empty else 0
    plot_html = (f'<img class="plot" src="{PLOT_PNG}" alt="price history">'
                 if os.path.exists(PLOT_PNG)
                 else '<p>No plot yet — run again with more history to see trends.</p>')

    # Tax-aware best deals section (only when tax is enabled)
    tax_enabled = tax_cfg and tax_cfg.get('enabled')
    if tax_enabled:
        tax_deals = _build_best_deals_html(df, tax_cfg, retailers_cfg, use_tax=True)
        rate = tax_cfg['effective_rate']
        best_deals_tax_section = (
            f'<h2>Best Deals — Cheapest Total Cost '
            f'(after {rate:.3g}% tax, accounts for tax-free retailers)</h2>'
            f'{tax_deals}')
    else:
        best_deals_tax_section = ''

    rendered = HTML_TEMPLATE.format(
        timestamp=_esc(datetime.now().strftime('%Y-%m-%d %H:%M:%S')),
        n_listings=n_listings, n_in_stock=n_in_stock, n_errors=n_errors,
        n_films=n_films, n_ebay=len(ebay_results),
        manual_banner=_build_manual_check_banner(df),
        tax_banner=_build_tax_banner(tax_cfg, retailers_cfg),
        best_deals_html=_build_best_deals_html(df, tax_cfg, retailers_cfg, use_tax=False),
        best_deals_tax_section=best_deals_tax_section,
        main_html=_build_main_table(df, tax_cfg, retailers_cfg),
        ebay_html=_build_ebay_html(ebay_results, tax_cfg),
        plot_html=plot_html,
        diagnostics_html=_build_diagnostics_html(diagnostics))
    with open(REPORT_HTML, 'w', encoding='utf-8') as f:
        f.write(rendered)
    print(f'Report -> {REPORT_HTML}')


# ============================================================
# 14. Plot
# ============================================================

def make_plot():
    if not os.path.exists(HISTORY_FILE): return
    try:
        hist = pd.read_csv(HISTORY_FILE)
    except Exception as e:
        print(f'Plot: could not read history: {e}')
        return
    hist = hist[hist['price_total'].notna()].copy()
    if hist.empty: return
    hist['checked_at'] = pd.to_datetime(hist['checked_at'])
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    films = sorted(hist['film'].unique())
    n = len(films)
    if n == 0: return
    fig, axes = plt.subplots(n, 1, figsize=(12, 2.8 * n), squeeze=False)
    for i, film in enumerate(films):
        ax = axes[i, 0]
        sub = hist[hist['film'] == film]
        for retailer, grp in sub.groupby('retailer'):
            grp_sorted = grp.sort_values('checked_at')
            ax.plot(grp_sorted['checked_at'], grp_sorted['price_per_roll'],
                    marker='o', markersize=4, label=retailer, linewidth=1.5)
        ax.set_title(film, fontsize=10, loc='left')
        ax.set_ylabel('$ / roll')
        ax.grid(True, alpha=0.3)
        ax.legend(fontsize=7, loc='best', ncol=3)
        plt.setp(ax.xaxis.get_majorticklabels(), rotation=30, ha='right')
    fig.suptitle('Price-per-roll history', fontsize=13, y=1.0)
    fig.tight_layout()
    fig.savefig(PLOT_PNG, dpi=110, bbox_inches='tight')
    plt.close(fig)
    print(f'Plot -> {PLOT_PNG}')


# ============================================================
# 15. Status
# ============================================================

async def cmd_status(retailers_cfg):
    print('=' * 100)
    print('STATUS — homepage + search reachability')
    print('=' * 100)
    for ret_key, cfg in retailers_cfg.items():
        if not cfg.get('enabled', True):
            print(f'{cfg["name"]:18s} (DISABLED in config.txt)')
            continue
        custom_tag = ' [CUSTOM]' if cfg.get('is_custom') else ''
        soup_home = await fetch_smart(cfg['home'], cfg['mode'], timeout=20)
        if soup_home is None:        home = 'FAIL'
        elif soup_home == 'TIMEOUT': home = 'TIMEOUT'
        elif page_looks_blocked(soup_home): home = 'BLOCKED'
        elif page_is_empty_or_failed(soup_home): home = 'EMPTY'
        else:                        home = 'OK'

        # Determine platform
        platform = cfg.get('platform')
        if platform is None:
            platform = detect_platform(soup_home, cfg['home'])
        # Try search
        if platform in PLATFORM_HANDLERS:
            handler = PLATFORM_HANDLERS[platform]
            search_url = handler['search_url'](cfg['home'], 'kodak 120')
            soup_s = await fetch_smart(search_url, cfg['mode'], timeout=20)
            if soup_s is None:        search = 'FAIL'
            elif soup_s == 'TIMEOUT': search = 'TIMEOUT'
            elif page_looks_blocked(soup_s): search = 'BLOCKED'
            else:
                try:
                    n = len(handler['parser'](soup_s, cfg['home']))
                    search = f'OK ({n} results)'
                except Exception as e:
                    search = f'PARSE ERROR ({type(e).__name__})'
        else:
            search = 'unknown platform'
        print(f'{cfg["name"]:18s}{custom_tag} '
              f'[{platform:8s}] home: {home:10s} | search: {search}')
        await asyncio.sleep(0.6)


# ============================================================
# 16. Main
# ============================================================

async def main(force_discover=False, skip_discover=False):
    migrate_history_if_needed()
    retailers_cfg, brands, formats, include_ebay, tax_cfg = parse_config()
    # Mark each retailer with its tax-free status for easy access later
    for key, cfg in retailers_cfg.items():
        cfg['tax_free'] = key.lower() in tax_cfg['tax_free_retailers']
    n_enabled = sum(1 for c in retailers_cfg.values() if c.get('enabled'))
    n_custom = sum(1 for c in retailers_cfg.values() if c.get('is_custom') and c.get('enabled'))
    print(f'Config: {n_enabled}/{len(retailers_cfg)} retailers enabled '
          f'({n_custom} custom), {len(brands)} brands, {len(formats)} formats')
    if tax_cfg['enabled']:
        n_tax_free = sum(1 for c in retailers_cfg.values() if c.get('tax_free'))
        print(f'Tax: {tax_cfg["state"]} {tax_cfg["effective_rate"]:.3f}%'
              f'{" (custom rate)" if tax_cfg["rate_override"] else ""}'
              f' — {n_tax_free} tax-free retailer(s)')

    discovered, diagnostics = None, None
    if not skip_discover:
        cached, age, cached_diag = load_discovery_cache()
        if cached and not force_discover and age is not None and age < DISCOVERY_REFRESH_DAYS:
            print(f'Using cached discovery ({age} days old)')
            discovered = cached
            diagnostics = cached_diag
        else:
            if force_discover: print('Force-refreshing discovery.')
            elif cached is None: print('No cache — running first discovery.')
            else: print(f'Cache is {age} days old; refreshing.')
            discovered, diagnostics = await run_discovery(retailers_cfg, brands, formats)
            save_discovery_cache(discovered, diagnostics)
    else:
        cached, _, cached_diag = load_discovery_cache()
        discovered = cached
        diagnostics = cached_diag

    listings = merge_to_listings(discovered or {}, retailers_cfg)
    if not listings:
        print('\nNothing to check.')
        return

    n_exp = sum(1 for l in listings if l[4])
    print(f'\nWill check {len(listings)} retail listings ({n_exp} expired)\n')
    results = await check_listings(listings, retailers_cfg)
    df = pd.DataFrame([asdict(r) for r in results])
    save_history(df)

    ebay_results = []
    if include_ebay:
        ebay_results = await check_ebay()
        save_ebay_history(ebay_results)
    else:
        print('\nSkipping eBay (disabled in config.txt)')

    detect_changes()
    make_plot()
    write_html_report(df, ebay_results, discovered, diagnostics, tax_cfg, retailers_cfg)
    try: webbrowser.open(os.path.abspath(REPORT_HTML))
    except Exception: pass


def cmd_clear():
    print('This will delete:')
    files = [HISTORY_FILE, EBAY_HISTORY_FILE, DISCOVERY_CACHE,
             REPORT_HTML, PLOT_PNG, PLATFORM_DETECTION_CACHE]
    existing = [f for f in files if os.path.exists(f)]
    for f in existing: print(f'  - {f}')
    if not existing: print('  (nothing to delete)'); return
    if input('Type YES to confirm: ').strip() == 'YES':
        for f in existing: os.remove(f); print(f'  removed {f}')
    else:
        print('Cancelled.')


if __name__ == '__main__':
    arg = sys.argv[1] if len(sys.argv) > 1 else 'run'
    if arg == 'discover':
        asyncio.run(main(force_discover=True))
    elif arg == 'check':
        asyncio.run(main(skip_discover=True))
    elif arg == 'status':
        retailers_cfg, _, _, _, _ = parse_config()
        asyncio.run(cmd_status(retailers_cfg))
    elif arg == 'plot':
        make_plot()
    elif arg == 'clear':
        cmd_clear()
    else:
        asyncio.run(main())