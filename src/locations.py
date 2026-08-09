"""Normalize the wildly inconsistent location strings every job board emits.

Boards write the same place a dozen ways — "US, CA, Santa Clara" (Workday),
"New York, New York, USA" (Amazon), "USA - Remote" (Eightfold), "Remote in UK",
"Hybrid: Sunnyvale, CA". A location filter is only usable if all of those collapse
onto the same handful of buckets, so every raw string is parsed into:

    Place(raw, city, state, country, metro, remote)

`metro` is the label the UI filters on. Cities inside one job market share a metro
("Mountain View", "Palo Alto", "Oakland" -> "SF Bay Area") because nobody searching
for jobs thinks of those as different places. Unmapped US cities fall back to their
state ("Other · TX"), unmapped foreign cities to their country.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

# --- US states -------------------------------------------------------------
_STATE_NAMES = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR",
    "california": "CA", "colorado": "CO", "connecticut": "CT", "delaware": "DE",
    "florida": "FL", "georgia": "GA", "hawaii": "HI", "idaho": "ID",
    "illinois": "IL", "indiana": "IN", "iowa": "IA", "kansas": "KS",
    "kentucky": "KY", "louisiana": "LA", "maine": "ME", "maryland": "MD",
    "massachusetts": "MA", "michigan": "MI", "minnesota": "MN", "mississippi": "MS",
    "missouri": "MO", "montana": "MT", "nebraska": "NE", "nevada": "NV",
    "new hampshire": "NH", "new jersey": "NJ", "new mexico": "NM", "new york": "NY",
    "north carolina": "NC", "north dakota": "ND", "ohio": "OH", "oklahoma": "OK",
    "oregon": "OR", "pennsylvania": "PA", "rhode island": "RI",
    "south carolina": "SC", "south dakota": "SD", "tennessee": "TN", "texas": "TX",
    "utah": "UT", "vermont": "VT", "virginia": "VA", "washington": "WA",
    "west virginia": "WV", "wisconsin": "WI", "wyoming": "WY",
    "district of columbia": "DC", "washington dc": "DC", "washington d.c.": "DC",
    "puerto rico": "PR",
}
_STATE_CODES = set(_STATE_NAMES.values())

# --- countries -------------------------------------------------------------
_COUNTRIES = {
    "united states": "United States", "united states of america": "United States",
    "usa": "United States", "us": "United States", "u.s.": "United States",
    "u.s.a.": "United States", "america": "United States",
    "canada": "Canada", "ca-canada": "Canada",
    "united kingdom": "United Kingdom", "uk": "United Kingdom",
    "england": "United Kingdom", "scotland": "United Kingdom",
    "great britain": "United Kingdom", "gb": "United Kingdom",
    "ireland": "Ireland", "germany": "Germany", "deutschland": "Germany",
    "france": "France", "netherlands": "Netherlands", "the netherlands": "Netherlands",
    "spain": "Spain", "italy": "Italy", "portugal": "Portugal", "poland": "Poland",
    "sweden": "Sweden", "norway": "Norway", "denmark": "Denmark", "finland": "Finland",
    "switzerland": "Switzerland", "austria": "Austria", "belgium": "Belgium",
    "czech republic": "Czechia", "czechia": "Czechia", "romania": "Romania",
    "india": "India", "china": "China", "japan": "Japan", "singapore": "Singapore",
    "south korea": "South Korea", "korea": "South Korea", "taiwan": "Taiwan",
    "hong kong": "Hong Kong", "australia": "Australia", "new zealand": "New Zealand",
    "israel": "Israel", "brazil": "Brazil", "mexico": "Mexico", "argentina": "Argentina",
    "chile": "Chile", "colombia": "Colombia", "costa rica": "Costa Rica",
    "united arab emirates": "United Arab Emirates", "uae": "United Arab Emirates",
    "saudi arabia": "Saudi Arabia", "egypt": "Egypt", "south africa": "South Africa",
    "nigeria": "Nigeria", "kenya": "Kenya", "turkey": "Turkey", "ukraine": "Ukraine",
    "philippines": "Philippines", "indonesia": "Indonesia", "vietnam": "Vietnam",
    "thailand": "Thailand", "malaysia": "Malaysia", "pakistan": "Pakistan",
    "bangladesh": "Bangladesh", "sri lanka": "Sri Lanka", "nepal": "Nepal",
    "greece": "Greece", "hungary": "Hungary", "bulgaria": "Bulgaria",
    "serbia": "Serbia", "croatia": "Croatia", "lithuania": "Lithuania",
    "latvia": "Latvia", "estonia": "Estonia", "luxembourg": "Luxembourg",
}

# Cities that belong to a shared job market, keyed by the metro label the UI shows.
_METRO_CITIES: dict[str, tuple[str, ...]] = {
    "SF Bay Area": (
        "san francisco", "sf", "south san francisco", "mountain view", "palo alto",
        "menlo park", "sunnyvale", "santa clara", "san jose", "cupertino", "fremont",
        "redwood city", "redwood shores", "oakland", "berkeley", "emeryville",
        "san mateo", "foster city", "burlingame", "belmont", "milpitas", "campbell",
        "los gatos", "los altos", "brisbane", "alameda", "hayward", "pleasanton",
        "san ramon", "dublin, ca", "walnut creek", "newark, ca", "union city",
        "bay area", "san francisco bay area", "silicon valley", "sausalito",
        "san carlos", "daly city", "richmond, ca", "livermore", "santa cruz",
        "scotts valley", "morgan hill", "saratoga", "sunnyvale, ca",
    ),
    "Seattle": (
        "seattle", "bellevue", "redmond", "kirkland", "renton", "bothell",
        "sammamish", "issaquah", "everett", "tacoma", "tukwila", "kent, wa",
        "puget sound", "greater seattle",
    ),
    "New York": (
        "new york", "new york city", "nyc", "manhattan", "brooklyn", "queens",
        "long island city", "jersey city", "hoboken", "newark, nj", "white plains",
        "yonkers", "stamford", "greenwich, ct", "new york metropolitan area",
    ),
    "Los Angeles": (
        "los angeles", "la, ca", "santa monica", "culver city", "el segundo",
        "playa vista", "venice, ca", "burbank", "glendale", "pasadena", "hawthorne",
        "torrance", "long beach", "irvine", "costa mesa", "santa ana", "anaheim",
        "newport beach", "orange county", "woodland hills", "sherman oaks",
        "marina del rey", "manhattan beach", "beverly hills", "westwood",
        "thousand oaks", "van nuys", "north hollywood", "inglewood",
    ),
    "San Diego": ("san diego", "carlsbad", "la jolla", "poway", "chula vista", "oceanside"),
    "Boston": (
        "boston", "cambridge, ma", "cambridge", "somerville", "waltham", "burlington, ma",
        "lexington, ma", "watertown", "needham", "newton, ma", "quincy", "andover",
        "billerica", "marlborough", "framingham", "woburn", "bedford, ma",
    ),
    "Austin": ("austin", "round rock", "cedar park", "georgetown, tx", "san marcos"),
    "Dallas–Fort Worth": (
        "dallas", "fort worth", "plano", "irving", "richardson", "frisco", "addison",
        "arlington, tx", "mckinney", "grapevine", "westlake, tx", "las colinas",
    ),
    "Houston": ("houston", "the woodlands", "sugar land", "katy"),
    "Chicago": (
        "chicago", "evanston", "naperville", "schaumburg", "oak brook", "deerfield",
        "northbrook", "rosemont", "downers grove", "aurora, il",
    ),
    "DC Area": (
        "washington", "washington dc", "washington, dc", "arlington, va", "alexandria",
        "mclean", "reston", "herndon", "tysons", "vienna, va", "bethesda", "rockville",
        "chantilly", "fairfax", "annapolis", "columbia, md", "silver spring",
        "gaithersburg", "springfield, va", "ashburn", "sterling, va",
    ),
    "Denver–Boulder": (
        "denver", "boulder", "broomfield", "louisville, co", "longmont",
        "lakewood, co", "englewood", "aurora, co", "colorado springs", "fort collins",
    ),
    "Atlanta": ("atlanta", "alpharetta", "marietta", "sandy springs", "duluth, ga"),
    "Portland": ("portland", "beaverton", "hillsboro", "vancouver, wa", "tigard"),
    "Phoenix": ("phoenix", "tempe", "scottsdale", "chandler", "mesa, az", "gilbert", "peoria, az"),
    "Research Triangle": (
        "raleigh", "durham", "chapel hill", "cary", "morrisville",
        "research triangle park", "rtp",
    ),
    "Salt Lake City": ("salt lake city", "lehi", "provo", "draper", "sandy, ut", "american fork"),
    "Philadelphia": ("philadelphia", "king of prussia", "malvern", "wayne, pa", "conshohocken"),
    "Pittsburgh": ("pittsburgh",),
    "Detroit": ("detroit", "ann arbor", "dearborn", "troy, mi", "warren, mi", "auburn hills"),
    "Minneapolis": ("minneapolis", "st. paul", "saint paul", "bloomington, mn", "eden prairie"),
    "Miami": ("miami", "fort lauderdale", "boca raton", "coral gables", "west palm beach"),
    "Nashville": ("nashville", "franklin, tn", "brentwood, tn"),
    "Madison": ("madison, wi", "madison"),
    "Columbus": ("columbus, oh", "dublin, oh", "new albany"),
    "Charlotte": ("charlotte",),
    "Las Vegas": ("las vegas", "henderson, nv", "reno"),
    "Toronto": ("toronto", "mississauga", "markham", "waterloo", "kitchener", "ottawa", "north york"),
    "Vancouver BC": ("vancouver, bc", "vancouver, british columbia", "burnaby", "richmond, bc"),
    "Montreal": ("montreal", "montréal", "quebec city"),
    "London": ("london", "greater london", "cambridge, uk", "oxford", "reading, uk", "slough"),
    "Dublin": ("dublin, ireland", "dublin, ie"),
    "Berlin": ("berlin",),
    "Munich": ("munich", "münchen"),
    "Paris": ("paris",),
    "Amsterdam": ("amsterdam", "utrecht", "eindhoven"),
    "Zurich": ("zurich", "zürich", "lausanne", "geneva"),
    "Bangalore": ("bangalore", "bengaluru"),
    "Hyderabad": ("hyderabad",),
    "Pune": ("pune",),
    "Mumbai": ("mumbai", "navi mumbai"),
    "Delhi NCR": ("new delhi", "delhi", "gurgaon", "gurugram", "noida"),
    "Chennai": ("chennai",),
    "Singapore": ("singapore",),
    "Tokyo": ("tokyo", "yokohama"),
    "Seoul": ("seoul",),
    "Sydney": ("sydney", "melbourne", "brisbane, australia"),
    "Tel Aviv": ("tel aviv", "tel-aviv", "herzliya", "haifa", "jerusalem"),
    "Shanghai": ("shanghai",),
    "Beijing": ("beijing",),
    "Shenzhen": ("shenzhen", "guangzhou"),
    "Taipei": ("taipei", "hsinchu"),
    "São Paulo": ("são paulo", "sao paulo"),
    "Mexico City": ("mexico city", "ciudad de méxico", "guadalajara"),
    "Warsaw": ("warsaw", "kraków", "krakow", "wrocław", "wroclaw"),
}

# Longest-first so "san francisco bay area" wins over "san francisco".
_CITY_TO_METRO: dict[str, str] = {}
for _metro, _cities in _METRO_CITIES.items():
    for _c in _cities:
        _CITY_TO_METRO.setdefault(_c, _metro)
_CITY_KEYS = sorted(_CITY_TO_METRO, key=len, reverse=True)

_REMOTE_RE = re.compile(
    r"\b(remote|work from home|wfh|virtual|telecommute|distributed|anywhere)\b")
_HYBRID_RE = re.compile(r"\bhybrid\b")
_NOISE = re.compile(
    r"\b(remote|hybrid|onsite|on-site|work from home|wfh|virtual|telecommute|"
    r"distributed|anywhere|in office|in-office|flexible|multiple locations|"
    r"various locations|other|office|hq|headquarters|metro area|greater|area|"
    r"region|and surrounding|remote optional|field|based|"
    r"united states of)\b")
# Deliberately does NOT split on bare "or"/"and": those swallow the state codes
# OR (Oregon) and IN (Indiana), which silently dumped every Portland and
# Indianapolis posting into the "Unspecified" bucket.
_SPLIT = re.compile(r"\s*(?:[,;/|]|\s[-–—]\s)\s*")
_DC_RE = re.compile(r"\b(d\.?c\.?|district of columbia)\b")
_LEAD_PREP = re.compile(r"^(?:in|at|near)\s+")
# States whose name, standing alone with no city, is really the city.
_BARE_STATE_METRO = {"NY": "New York", "DC": "DC Area"}
# Feeds write Los Angeles neighbourhoods as "<city>, LA", so a bare or
# neighbourhood-qualified "LA" means Los Angeles. Only a genuine Louisiana city
# next to it makes LA the state.
_LOUISIANA_CITIES = frozenset({
    "new orleans", "baton rouge", "shreveport", "lafayette", "metairie",
    "lake charles", "kenner", "bossier city", "monroe", "alexandria",
    "houma", "slidell", "hammond", "covington", "gonzales", "ruston",
})


@dataclass(frozen=True)
class Place:
    raw: str
    city: str
    state: str        # 2-letter US code, else ""
    country: str      # e.g. "United States", else ""
    metro: str        # UI filter label, e.g. "SF Bay Area" / "Other · TX" / "India"
    remote: bool
    hybrid: bool

    @property
    def label(self) -> str:
        if self.city and self.state:
            return f"{self.city}, {self.state}"
        if self.city and self.country and self.country != "United States":
            return f"{self.city}, {self.country}"
        return self.city or self.country or self.raw


@lru_cache(maxsize=20000)
def parse(raw: str) -> Place:
    """Parse one raw location string. Cached — the same strings recur constantly."""
    text = (raw or "").strip()
    low = text.lower()
    remote = bool(_REMOTE_RE.search(low))
    hybrid = bool(_HYBRID_RE.search(low))

    # Tokens are classified before any metro lookup. Doing it the other way round
    # matches the wrong place whenever a state name is also a city name elsewhere:
    # "Bellevue, Washington" would hit the DC-area city "Washington" and land in
    # the wrong metro. Consuming "washington" as the state first leaves only
    # "bellevue" to match, which correctly resolves to Seattle.
    tokens = [t.strip(" .-") for t in _SPLIT.split(low) if t.strip(" .-")]
    country, state, city = "", "", ""
    # "Washington, DC" would otherwise consume "washington" as the state WA and
    # strand "dc" as the city. Claiming DC up front stops that.
    state_from_code = False
    if _DC_RE.search(low):
        state = "DC"
    leftovers: list[str] = []
    for tok in tokens:
        clean = re.sub(r"\s+", " ", _NOISE.sub(" ", tok)).strip(" .-")
        clean = _LEAD_PREP.sub("", clean)
        if not clean:
            continue
        if not state and len(clean) == 2 and clean.upper() in _STATE_CODES:
            state, state_from_code = clean.upper(), True
        elif not state and clean in _STATE_NAMES:
            state, state_from_code = _STATE_NAMES[clean], False
        elif not country and clean in _COUNTRIES:
            country = _COUNTRIES[clean]
        else:
            leftovers.append(clean)

    if (state == "LA" and state_from_code
            and not any(c in _LOUISIANA_CITIES for c in leftovers)):
        state, metro = "CA", "Los Angeles"
    else:
        metro = _metro_for(leftovers)
    # A bare state name that is also a major city ("New York") means the city.
    if not metro and not leftovers and state in _BARE_STATE_METRO:
        metro = _BARE_STATE_METRO[state]
    if state:
        country = country or "United States"
    if leftovers:
        # Prefer a leftover that names a known city over a stray qualifier.
        city = next((t for t in leftovers if t in _CITY_TO_METRO), leftovers[-1])
        city = _titlecase(city)

    if not metro:
        if country == "United States" and state:
            metro = f"Other · {state}"
        elif country:
            metro = country
        elif remote:
            metro = "Remote"
        else:
            metro = "Unspecified"
    elif not country:
        # A recognized metro implies its country even when the string omitted it.
        country = _METRO_COUNTRY.get(metro, "")
        if country == "United States" and not state:
            state = _METRO_STATE.get(metro, "")

    return Place(raw=text, city=city, state=state, country=country,
                 metro=metro, remote=remote, hybrid=hybrid)


def _metro_for(tokens: list[str]) -> str:
    """Exact token match first, then a longest-key substring scan for things like
    'san francisco bay' and 'seattle' inside a longer phrase."""
    for tok in tokens:
        if tok in _CITY_TO_METRO:
            return _CITY_TO_METRO[tok]
    for tok in tokens:
        for city_key in _CITY_KEYS:
            if _contains_place(tok, city_key):
                return _CITY_TO_METRO[city_key]
    return ""


def _contains_place(haystack: str, needle: str) -> bool:
    """Substring match on word boundaries so 'la, ca' doesn't fire inside 'atlanta'."""
    idx = haystack.find(needle)
    while idx != -1:
        before_ok = idx == 0 or not haystack[idx - 1].isalnum()
        end = idx + len(needle)
        after_ok = end == len(haystack) or not haystack[end].isalnum()
        if before_ok and after_ok:
            return True
        idx = haystack.find(needle, idx + 1)
    return False


def _titlecase(s: str) -> str:
    return " ".join("-".join(p.capitalize() if p.islower() else p for p in w.split("-"))
                    for w in s.split())


_METRO_STATE = {
    "SF Bay Area": "CA", "Los Angeles": "CA", "San Diego": "CA", "Seattle": "WA",
    "New York": "NY", "Boston": "MA", "Austin": "TX", "Dallas–Fort Worth": "TX",
    "Houston": "TX", "Chicago": "IL", "DC Area": "DC", "Denver–Boulder": "CO",
    "Atlanta": "GA", "Portland": "OR", "Phoenix": "AZ", "Research Triangle": "NC",
    "Salt Lake City": "UT", "Philadelphia": "PA", "Pittsburgh": "PA",
    "Detroit": "MI", "Minneapolis": "MN", "Miami": "FL", "Nashville": "TN",
    "Madison": "WI", "Columbus": "OH", "Charlotte": "NC", "Las Vegas": "NV",
}
_METRO_COUNTRY = {m: "United States" for m in _METRO_STATE}
_METRO_COUNTRY.update({
    "Toronto": "Canada", "Vancouver BC": "Canada", "Montreal": "Canada",
    "London": "United Kingdom", "Dublin": "Ireland", "Berlin": "Germany",
    "Munich": "Germany", "Paris": "France", "Amsterdam": "Netherlands",
    "Zurich": "Switzerland", "Bangalore": "India", "Hyderabad": "India",
    "Pune": "India", "Mumbai": "India", "Delhi NCR": "India", "Chennai": "India",
    "Singapore": "Singapore", "Tokyo": "Japan", "Seoul": "South Korea",
    "Sydney": "Australia", "Tel Aviv": "Israel", "Shanghai": "China",
    "Beijing": "China", "Shenzhen": "China", "Taipei": "Taiwan",
    "São Paulo": "Brazil", "Mexico City": "Mexico", "Warsaw": "Poland",
})


def summarize(raw_locations: list[str]) -> dict:
    """Collapse a job's location list into the fields the UI and CSV need."""
    places = [parse(x) for x in raw_locations if (x or "").strip()]
    if not places:
        return {"metros": [], "countries": [], "states": [], "labels": [],
                "remote": False, "us": False}
    metros, countries, states, labels = [], [], [], []
    for p in places:
        for bucket, value in ((metros, p.metro), (countries, p.country),
                              (states, p.state), (labels, p.label)):
            if value and value not in bucket:
                bucket.append(value)
    remote = any(p.remote for p in places)
    if remote and "Remote" not in metros:
        metros.append("Remote")
    return {
        "metros": metros,
        "countries": countries,
        "states": states,
        "labels": labels,
        "remote": remote,
        "us": "United States" in countries,
    }
