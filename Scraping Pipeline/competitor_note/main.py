"""
Competitor-note service.

Laravel (LokaPro) computes every figure shown on the Competitor page and POSTs
them here already-calculated. This service asks a local Ollama model to phrase
them as a short note, then verifies the model did not invent, round, or mistype
a single digit before handing the prose back.

The model does no arithmetic. It copies numbers out of a FACTS block into
sentences. The note renders directly below the tables containing those same
numbers, so one wrong digit is a visible contradiction, not a rounding error.

Two layers protect against that:
  verify_numbers() rejects any numeric token we did not send.
  fallback_note()  produces correct prose without the model at all.

The second is what makes the first affordable: we can throw away the model's
output twice and still have something true to render.

-------------------------------------------------------------------------------
2026-07-16 CONTRACT BREAK. The UI moved from a per-competitor dropdown to an
accordion showing every competitor at once, with ONE market-wide insight box at
the bottom of the page. The payload changed shape accordingly:

  GONE:  competitor, ota, lowest, highest, most_volatile, most_stable,
         insufficient_data          (these were per-competitor-per-OTA)
  NEW:   competitor_count, market_cheapest, market_priciest,
         last_minute_cheapest, early_book_cheapest, most_fluctuating
  KEPT:  competitor_min/max, our_* , vs_*, skip_reason, occupancy_*

Prices are pooled ACROSS competitors AND across OTAs: "cheapest in the market"
means cheapest anywhere it is listed, so every pick carries its competitor, room,
OTA and date window to keep the claim checkable against the table above.

The note now has two labelled sections the Revenue team asked for by name:
  MARKET CONDITION - cheapest overall, cheapest per booking segment, volatility
  OUR CONDITION    - our price against the market band, plus our occupancy

2026-07-17 ENGLISH ONLY. The `language` field is still accepted but ignored.
qwen2.5:3b would not hold Indonesian against an English FACTS block — asked for
"id" it replied in English anyway, while the fallback answered in Indonesian, so
the card's language flipped depending on whether the guard passed. The team
reads English, so one language is both simpler and honest about what the model
actually does.

-------------------------------------------------------------------------------
2026-07-20 CALLBACK MODE. TRANSPORT CHANGE ONLY.

Nothing about the model, the prompt, the FACTS block, verify_numbers() or
fallback_note() changed in this revision. Read that as a hard boundary: if you
are reviewing this file and find a behavioural difference in the PROSE, it is a
bug I introduced by accident, not an intended change.

WHAT CHANGED AND WHY
Laravel used to POST here and hold the socket open until the note came back.
Ollama on CPU takes minutes, so a PHP-FPM worker and the user's browser request
sat blocked for the whole generation, and the window grew with the competitor
count. Laravel now hands over the payload and hangs up.

  OLD:  Laravel --POST payload--> here ...(minutes of Ollama)... --200 {note}--> Laravel
  NEW:  Laravel --POST payload + job_id + callback_url--> here
        here --202 {"status":"accepted"}--> Laravel          (immediately)
        ...(minutes of Ollama, in a background task)...
        here --POST {job_id, note}--> Laravel's callback_url

Laravel stores the note in its `competitor_notes` table keyed by job_id and
shows a spinner meanwhile; the user reloads the page to collect it.

TWO NEW FIELDS, BOTH OPTIONAL:
  job_id        opaque token. Echo it back UNCHANGED in the callback body — it
                is the only thing that tells Laravel which row to write. Do not
                parse, trim, or regenerate it.
  callback_url  full URL to POST the finished note to.

BACKWARD COMPATIBLE ON PURPOSE. When either field is missing the endpoint
behaves exactly as before: generate inline, return 200 {"note": ...}. That path
is what you use to test this service by hand with curl without standing up a
Laravel callback receiver. Do not delete it.

DELIVERY IS BEST-EFFORT, AND THAT IS SAFE. FastAPI background tasks run
in-process, so a worker restart mid-generation drops the job with no callback.
Laravel does not wait forever on that: a row still `pending` after
COMPETITOR_NOTE_PENDING_TTL (default 600s) is re-dispatched with a fresh job_id.
So the failure mode is a delayed note, never a stuck one. This is also why
delivery retries a few times but then gives up rather than queueing forever.

NEW ENV VAR — REQUIRED FOR CALLBACK MODE:
  CALLBACK_URL_ALLOWLIST   comma-separated host[:port] entries this service will
                           POST results to, e.g.
                           "lokapro.ecommerceloka.com,my-tunnel.trycloudflare.com"
                           Without it, anyone holding COMPETITOR_NOTE_TOKEN could
                           make this box POST to a host of their choosing — the
                           same hole ALLOWED_MODELS closes for model names.
                           An empty allowlist disables callback mode entirely.
                           For local testing add the Cloudflare Tunnel hostname.

Dependencies unchanged: fastapi, uvicorn[standard], httpx, pydantic>=2
(python-dotenv optional).

Requires the matching Laravel side: CompetitorNoteService::noteState() +
CompetitorAggregateController::noteData() and ::noteCallback().
-------------------------------------------------------------------------------
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import secrets
from typing import Literal, Optional
from urllib.parse import urlparse

import httpx
from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

try:  # load .env sitting next to this file, if one exists
    from dotenv import load_dotenv

    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
except ImportError:
    pass  # env vars set by systemd/shell instead

log = logging.getLogger("competitor-note")

# Callback mode made logging load-bearing. The note now arrives minutes after
# the request, on a page load nobody is watching, so the log is the only place
# that distinguishes "delivered" from "silently dead" — and delivery success is
# reported at INFO.
#
# The root logger defaults to WARNING and uvicorn configures only its own
# loggers, never root, so without this every log.info() here is dropped and a
# working callback looks identical to one that never fired. basicConfig is a
# no-op when root already has handlers, hence the explicit setLevel: it keeps
# our INFO lines alive even under a caller that configured logging first.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log.setLevel(logging.INFO)

# -- Config -------------------------------------------------------------------

OCCUPANCY_THRESHOLD = 0.70
COMPETITOR_THRESHOLD = 0.05

AUTH_TOKEN = os.environ.get("COMPETITOR_NOTE_TOKEN", "")

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
OLLAMA_TIMEOUT = float(os.environ.get("OLLAMA_TIMEOUT", "60"))

# Ollama keeps a model resident for 5 minutes after a call by default; a 7B is
# ~5GB (measured: 5.12GB for qwen2.5:7b-instruct). This box has other work to do,
# so we hand the memory back sooner.
#
# "0" unloads the instant the reply is sent. The default here is deliberately NOT
# 0: generate_note() may call twice — first attempt, then a retry with the bad
# number quoted back — and 0 makes that second call pay a full cold load, on
# exactly the requests that are already struggling. A short non-zero value
# outlives the retry (which fires within a second) and still frees the RAM.
#
# Reloading costs ~5s on NVMe and more on slower disks. Callback mode is what
# makes that affordable: nobody is holding a socket waiting for the note.
OLLAMA_KEEP_ALIVE = os.environ.get("OLLAMA_KEEP_ALIVE", "30")

# The model only rephrases figures that are already calculated, so capability
# barely matters for the numbers — verify_numbers() and fallback_note() absorb
# digit slips either way. It matters for the CLAIMS around them, which nothing
# in this file can police: qwen2.5:3b invented a room type for us ("our Standard
# rooms", borrowed from a competitor) and merged the priciest-room fact with the
# volatility fact. That is why the default moved 3b -> 7b-instruct on 2026-07-17.
DEFAULT_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5:3b")

# The payload names a model. Passing that to Ollama unchecked would let anyone
# holding the token make this box pull and run an arbitrary model, so the name
# is only honoured if it is on this list; otherwise we quietly use the default.
ALLOWED_MODELS = {
    m.strip()
    for m in os.environ.get("OLLAMA_MODEL_ALLOWLIST", DEFAULT_MODEL).split(",")
    if m.strip()
}

# Hosts we are willing to POST a finished note to. See the 2026-07-20 block
# above for why this exists. Empty set => callback mode is off and every request
# is served synchronously, whatever the payload asks for.
CALLBACK_HOST_ALLOWLIST = {
    h.strip().lower()
    for h in os.environ.get("CALLBACK_URL_ALLOWLIST", "").split(",")
    if h.strip()
}

# Delivering the note is a plain POST of a short JSON body; it does not wait on
# Ollama, so it gets a short timeout.
CALLBACK_TIMEOUT = float(os.environ.get("CALLBACK_TIMEOUT", "15"))

# Seconds to wait before each delivery attempt after the first. Laravel's
# pending_ttl re-dispatch is the real safety net, so this stays short — it is
# here to ride out a deploy or a momentary network blip, not an outage.
CALLBACK_RETRY_DELAYS = (2, 10, 30)

app = FastAPI(title="competitor-note", docs_url=None, redoc_url=None)


# -- Contract -----------------------------------------------------------------
#
# Mirrors what Laravel's noteData() sends. Two ways fields go MISSING (absent
# from the JSON, not null) — every one of them therefore needs a default, or a
# normal request 422s in a way that reads like a Laravel bug:
#
#   1. skip_reason set -> compare() returns ONLY our_price/vs_min_pct/vs_max/
#      skip_reason. our_booking_date, our_nights, vs_max_pct are absent.
#   2. property has no room types -> occupancy() returns null and Laravel merges
#      nothing, so occupied_rooms/total_rooms/occupancy_pct are all absent.
#
# By contrast most_fluctuating / last_minute_cheapest / early_book_cheapest are
# always PRESENT but may be null.


class MarketPick(BaseModel):
    """One cell singled out of the market: who, which room, where, when."""

    competitor: str
    room: str
    price: int
    ota: str = ""
    # "+3 Days" | "+7 Days" | "+14 Days" | "+30 Days" — the table's column label.
    window: str = ""


class Fluctuation(BaseModel):
    competitor: str
    cv_pct: float
    # How many of that property's rooms had enough observations to measure.
    # Laravel already refuses to name a "most fluctuating" property unless at
    # least two properties are ranked and the winner's cv_pct > 0.
    rooms_measured: int = 0


class NoteRequest(BaseModel):
    as_of: str
    currency: str = "IDR"
    model: Optional[str] = None
    # Accepted for contract compatibility and then ignored: notes are English
    # only. qwen2.5:3b could not hold Indonesian against an English FACTS block
    # anyway — it replied in English regardless — and the team reads English.
    # Typed str rather than Literal so a payload still sending "id" gets a note
    # instead of a 422, which Laravel would render as a missing card.
    language: str = "en"

    # -- Async delivery (2026-07-20) --
    # Both present => generate in the background and POST the result to
    # callback_url, echoing job_id back. Either absent => synchronous, as before.
    # Optional so hand-testing with curl needs neither.
    job_id: Optional[str] = None
    callback_url: Optional[str] = None

    # -- MARKET CONDITION --
    competitor_count: int = 0
    market_cheapest: MarketPick
    market_priciest: MarketPick
    last_minute_cheapest: Optional[MarketPick] = None
    early_book_cheapest: Optional[MarketPick] = None
    most_fluctuating: Optional[Fluctuation] = None

    # Same values as market_cheapest.price / market_priciest.price. Laravel
    # sends them under these names so its compare() could stay untouched; the
    # vs_* figures below are computed against them.
    competitor_min: int
    competitor_max: int

    # -- OUR CONDITION --
    our_price: Optional[int] = None
    our_booking_date: Optional[str] = None
    our_nights: Optional[int] = None
    vs_min_pct: Optional[float] = None
    vs_max: Optional[Literal["below", "equal", "above"]] = None
    vs_max_pct: Optional[float] = None
    skip_reason: Optional[Literal["no_booking", "currency_mismatch"]] = None

    occupied_rooms: Optional[int] = None
    total_rooms: Optional[int] = None
    occupancy_pct: Optional[float] = None

    @property
    def compares(self) -> bool:
        """True when we have a price of our own worth talking about."""
        return self.skip_reason is None and self.our_price is not None

    @property
    def has_occupancy(self) -> bool:
        # All three or nothing: the prose names the counts as well as the
        # percentage, and a partial payload would render "None of our None
        # rooms are occupied (72.7%)" straight into the card.
        return (
            self.occupancy_pct is not None
            and self.occupied_rooms is not None
            and self.total_rooms is not None
        )

    @property
    def picks(self) -> list[MarketPick]:
        """Every MarketPick actually present, for string/number harvesting."""
        return [
            p
            for p in (
                self.market_cheapest,
                self.market_priciest,
                self.last_minute_cheapest,
                self.early_book_cheapest,
            )
            if p is not None
        ]


class NoteResponse(BaseModel):
    note: str


def get_suggestion(p: NoteRequest) -> Optional[str]:
    # We need occupancy rate and prices to make a suggestion
    if not p.compares or not p.has_occupancy:
        return None

    our_price = p.our_price
    comp_price = p.competitor_min

    if our_price is None or comp_price is None or comp_price == 0 or our_price == 0:
        return None

    # Calculate current occupancy in percentage
    if p.occupied_rooms is not None and p.total_rooms and p.total_rooms > 0:
        occupancy_rate = (p.occupied_rooms / p.total_rooms) * 100
    elif p.occupancy_pct is not None:
        occupancy_rate = p.occupancy_pct
    else:
        return None

    occ_threshold_pct = OCCUPANCY_THRESHOLD * 100

    occ_relation = "above occupancy threshold" if occupancy_rate >= occ_threshold_pct else "below occupancy threshold"
    
    if our_price < comp_price:
        our_relation = "lower than competitor"
    elif our_price > comp_price:
        our_relation = "higher than competitor"
    else:
        our_relation = "equal to competitor"

    if occupancy_rate >= occ_threshold_pct:
        if our_price < comp_price:
            # Price could possibly be increased up to xx%
            xx = (comp_price / our_price) * 100
            return f"Price could possibly be increased up to {fmt_pct(xx)}% due to {occ_relation}, and our price is {our_relation}."
        else:
            return f"Suggest to hold the price due to {occ_relation}, and our price is {our_relation}."
    else:
        if our_price < comp_price:
            return f"Suggest to hold the price due to {occ_relation}, and our price is {our_relation}."
        else:
            # Price could possibly be increased down to xx% or limit lower yy%
            xx = (comp_price / our_price) * 100
            target_yy_price = comp_price * (1 - COMPETITOR_THRESHOLD)
            yy = (target_yy_price / our_price) * 100
            return f"Price could possibly be increased down to {fmt_pct(xx)}% or limit lower {fmt_pct(yy)}% due to {occ_relation}, and our price is {our_relation}."


# -- Auth ---------------------------------------------------------------------


def require_token(authorization: str = Header(default="")) -> None:
    scheme, _, presented = authorization.partition(" ")
    if scheme.lower() != "bearer" or not AUTH_TOKEN:
        raise HTTPException(status_code=401, detail="unauthorized")
    # compare_digest, not ==, so the comparison does not leak the token
    # prefix through timing.
    if not secrets.compare_digest(presented, AUTH_TOKEN):
        raise HTTPException(status_code=401, detail="unauthorized")


# -- Number handling ----------------------------------------------------------

# A run of digits that may carry , or . separators inside it. Requiring a digit
# at both ends keeps a sentence-final period out of the token.
_NUM = re.compile(r"\d[\d.,]*\d|\d")


def norm(token: str) -> str:
    """785,000 == 785.000 == 785000 -> '785000'. Also 12.3 -> '123'.

    Both sides of every comparison go through this, so collapsing the decimal
    point is safe: it only means we cannot tell 12.3 from 123, and 123 is not a
    figure we ever send.
    """
    return token.replace(",", "").replace(".", "").lstrip("0") or "0"


def numeric_tokens(text: str) -> list[str]:
    return _NUM.findall(text)


def fmt_price(value: int) -> str:
    """785000 -> '785,000', matching how the Laravel table above renders it."""
    return f"{value:,}"


def fmt_pct(value: float) -> str:
    return f"{value:.1f}".rstrip("0").rstrip(".")


def allowed_numbers(p: NoteRequest) -> set[str]:
    """Every numeric token the note is permitted to contain.

    Anything outside this set was invented, computed, or mistyped by the model.
    """
    allowed: set[str] = set()

    def allow(value) -> None:
        if value is None:
            return
        # Sign never survives to the note: build_facts renders every percentage
        # through abs(), and _NUM cannot capture a leading minus. Allowing the
        # signed form only would put "-111" in the set while the note correctly
        # says "11.1%" -> norm "111" -> rejected, and a vs_min_pct below zero
        # (we are cheaper than the market) would silently force the fallback
        # every time. Compare on magnitude, which is all we ever print.
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            value = abs(value)
        allowed.add(norm(str(value)))
        if isinstance(value, float):
            # A model handed 12.3 will sometimes write "about 12%". That is not
            # an invented figure, so tolerate the rounded and 1-dp forms.
            allowed.add(norm(f"{value:.1f}"))
            allowed.add(norm(str(round(value))))
        if isinstance(value, int):
            # Keep both groupings allowed even though we only ever print commas:
            # the model sometimes regroups 450,000 as 450.000 on its own, and
            # that is a copy, not an invention.
            allowed.add(norm(fmt_price(value)))
            allowed.add(norm(fmt_price(value).replace(",", ".")))

    for value in (
        p.competitor_count,
        p.competitor_min,
        p.competitor_max,
        p.our_price,
        p.our_nights,
        p.vs_min_pct,
        p.vs_max_pct,
        p.most_fluctuating.cv_pct if p.most_fluctuating else None,
        p.most_fluctuating.rooms_measured if p.most_fluctuating else None,
        p.occupied_rooms,
        p.total_rooms,
        p.occupancy_pct,
    ):
        allow(value)

    for pick in p.picks:
        allow(pick.price)

    # Digits riding inside the strings we send. This is NOT cosmetic: the window
    # labels are "+3 / +7 / +14 / +30 Days", and 14 and 30 fall outside the small
    # range() below — omit these and the guard rejects a note that correctly
    # writes "+14 Days", every single time.
    # REVIEW: worth a test that asserts "+14 Days" and "+30 Days" survive the
    # guard; this is the most likely place a future edit reintroduces the bug.
    #
    # NOTE (2026-07-20): job_id is deliberately NOT harvested here. It is a hex
    # token full of digits that never reaches the prompt, and feeding it to the
    # guard would whitelist arbitrary numbers for no reason.
    strings: list[str] = [p.as_of, p.our_booking_date or ""]
    for pick in p.picks:
        strings += [pick.competitor, pick.room, pick.ota, pick.window]
    if p.most_fluctuating:
        strings.append(p.most_fluctuating.competitor)

    for s in strings:
        for token in numeric_tokens(s):
            allowed.add(norm(token))

    # Ordinary prose counts: "all three competitors", "the two cheapest".
    for n in range(11):
        allowed.add(norm(str(n)))

    # Add the calculated suggestion percentages to allowed numbers
    suggestion = get_suggestion(p)
    if suggestion:
        for token in numeric_tokens(suggestion):
            allowed.add(norm(token))

    return allowed


def verify_numbers(note: str, p: NoteRequest) -> Optional[str]:
    """Return the first numeric token in the note we never sent, or None."""
    allowed = allowed_numbers(p)
    for token in numeric_tokens(note):
        if norm(token) not in allowed:
            return token
    return None


# -- Prompt -------------------------------------------------------------------

SYSTEM = (
    "You write a short factual briefing about hotel pricing for a revenue team. "
    "You are given FACTS that are already calculated. "
    "Copy every number from FACTS digit for digit. "
    "Never calculate, derive, round, or invent a number. "
    "Never write a number that does not appear in FACTS. "
    "Write exactly two labelled sections: 'INSIGHT:' and 'SUGGESTION:'. "
    "Under 'INSIGHT:', list exactly 4 numbered points. "
    "Under 'SUGGESTION:', list exactly 2 numbered points. "
    "Neutral and descriptive."
)


def build_facts(p: NoteRequest) -> str:
    cur = p.currency

    def money(value: int) -> str:
        return f"{cur} {fmt_price(value)}"

    def describe(pick: MarketPick) -> str:
        where = f" on {pick.ota}" if pick.ota else ""
        when = f" in the {pick.window} window" if pick.window else ""
        return f"{pick.room} at {pick.competitor} for {money(pick.price)}{where}{when}"

    # INSIGHT point 1
    pt1 = f"Lowest price: {money(p.market_cheapest.price)} ({p.market_cheapest.room} at {p.market_cheapest.competitor})"

    # INSIGHT point 2
    pt2 = f"Highest price: {money(p.market_priciest.price)} ({p.market_priciest.room} at {p.market_priciest.competitor})"

    # INSIGHT point 3
    if p.most_fluctuating:
        pt3 = (
            f"Most fluctuating: {p.most_fluctuating.competitor} "
            f"(average variation {fmt_pct(p.most_fluctuating.cv_pct)}% across {p.most_fluctuating.rooms_measured} room type(s))"
        )
    else:
        pt3 = "No property stands out as fluctuating; prices are steady across the market."

    # INSIGHT point 4
    lm_desc = describe(p.last_minute_cheapest) if p.last_minute_cheapest else "no Last Minute prices available"
    eb_desc = describe(p.early_book_cheapest) if p.early_book_cheapest else "no Early Book prices available"
    pt4 = f"Last minute cheapest is {lm_desc}. Early book cheapest is {eb_desc}."

    # SUGGESTION point 1
    if p.compares and p.has_occupancy:
        pt_s1 = f"Our latest booking price is {money(p.our_price)} per night, occupancy rate: {fmt_pct(p.occupancy_pct)}%"
    elif p.compares:
        pt_s1 = f"Our latest booking price is {money(p.our_price)} per night, occupancy rate: N/A"
    elif p.has_occupancy:
        pt_s1 = f"No booking price available, occupancy rate: {fmt_pct(p.occupancy_pct)}%"
    else:
        pt_s1 = "No booking price or occupancy rate available"

    # SUGGESTION point 2
    suggestion_text = get_suggestion(p)
    if suggestion_text:
        pt_s2 = suggestion_text
    else:
        pt_s2 = "Suggestion not available due to missing price or occupancy data."

    lines = [
        "[FACTS FOR INSIGHT]",
        f"1. {pt1}",
        f"2. {pt2}",
        f"3. {pt3}",
        f"4. {pt4}",
        "",
        "[FACTS FOR SUGGESTION]",
        f"1. {pt_s1}",
        f"2. {pt_s2}",
    ]
    return "\n".join(lines)


def build_prompt(p: NoteRequest, correction: Optional[str] = None) -> str:
    prompt = (
        "FACTS\n"
        f"{build_facts(p)}\n\n"
        "RULES\n"
        "1. Every number you write must appear in FACTS above, character for character.\n"
        "2. Copy the statements from FACTS directly, preserving the numbers exactly. Do not calculate or round any numbers.\n"
        "3. Write the briefing using the exact labels and structure shown below.\n\n"
        "TASK\n"
        "Write the briefing exactly in this format:\n"
        "INSIGHT:\n"
        "1. [Cheapest competitor price and room type from INSIGHT Fact 1]\n"
        "2. [Highest competitor price and room type from INSIGHT Fact 2]\n"
        "3. [Property with the most fluctuating price and details from INSIGHT Fact 3]\n"
        "4. [Last minute cheapest and early book cheapest details from INSIGHT Fact 4]\n"
        "SUGGESTION:\n"
        "1. [Our latest booking price and occupancy rate from SUGGESTION Fact 1]\n"
        "2. [Pricing suggestion statement from SUGGESTION Fact 2]"
    )

    if correction:
        prompt += (
            f"\n\nYour previous attempt contained the number {correction}, which does "
            "not appear in FACTS. That is not allowed. Rewrite the briefing using "
            "only the numbers listed in FACTS."
        )

    return prompt


# -- Reply cleanup ------------------------------------------------------------

_THINK = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_OPEN_THINK = re.compile(r"<think>.*", re.DOTALL | re.IGNORECASE)
_FENCE = re.compile(r"^```[a-zA-Z]*\s*|\s*```$", re.MULTILINE)
# The "here is..." branch must NOT require a trailing newline: the model often
# writes "Here is the briefing: MARKET CONDITION: ..." all on one line, and
# demanding \n let that preamble through into the card.
_PREAMBLE = re.compile(
    r"^\s*(here(?:'s| is| are)[^:\n]*:\s*|sure[,!][^\n]*\n|certainly[,!][^\n]*\n)",
    re.IGNORECASE,
)
_MD = re.compile(r"[*_`#>]|^\s*[-•]\s+", re.MULTILINE)


def clean_reply(raw: str) -> str:
    """Strip model scaffolding and pin the note to exactly the required point-based format."""
    text = _THINK.sub(" ", raw)
    text = _OPEN_THINK.sub(" ", text)  # reasoning block that never closed
    text = _FENCE.sub(" ", text)
    text = _PREAMBLE.sub("", text)
    
    # We will clean up markdown but preserve the list points structure.
    lines = []
    for line in text.splitlines():
        cleaned = line.strip()
        cleaned = cleaned.replace("**", "").replace("*", "").replace("_", "").replace("`", "").strip()
        if not cleaned:
            continue
        lines.append(cleaned)

    insight_points = []
    suggestion_points = []
    current_section = None

    for line in lines:
        upper = line.upper()
        if "INSIGHT" in upper:
            current_section = "insight"
            continue
        elif "SUGGESTION" in upper:
            current_section = "suggestion"
            continue

        match = re.match(r"^(\d+)\.\s*(.*)", line)
        if match:
            num = int(match.group(1))
            content = match.group(2).strip()
            if current_section == "insight":
                insight_points.append((num, content))
            elif current_section == "suggestion":
                suggestion_points.append((num, content))
        else:
            if current_section == "insight" and insight_points:
                num, prev = insight_points[-1]
                insight_points[-1] = (num, prev + " " + line)
            elif current_section == "suggestion" and suggestion_points:
                num, prev = suggestion_points[-1]
                suggestion_points[-1] = (num, prev + " " + line)

    out_lines = ["INSIGHT:"]
    for i in range(1, 5):
        pt = next((c for n, c in insight_points if n == i), "")
        if pt:
            out_lines.append(f"{i}. {pt}")
        else:
            out_lines.append(f"{i}. [Missing data]")

    out_lines.append("SUGGESTION:")
    for i in range(1, 3):
        pt = next((c for n, c in suggestion_points if n == i), "")
        if pt:
            out_lines.append(f"{i}. {pt}")
        else:
            out_lines.append(f"{i}. [Missing data]")

    return "\n".join(out_lines)


# -- Fallback -----------------------------------------------------------------


def fallback_note(p: NoteRequest) -> str:
    """Deterministic prose covering the same points in the exact required layout."""
    cur = p.currency

    def money(value: int) -> str:
        return f"{cur} {fmt_price(value)}"

    def describe(pick: MarketPick) -> str:
        where = f" on {pick.ota}" if pick.ota else ""
        when = f" in the {pick.window} window" if pick.window else ""
        return f"{pick.room} at {pick.competitor} for {money(pick.price)}{where}{when}"

    # INSIGHT points
    pt1 = f"Lowest price: {money(p.market_cheapest.price)} ({p.market_cheapest.room} at {p.market_cheapest.competitor})"
    pt2 = f"Highest price: {money(p.market_priciest.price)} ({p.market_priciest.room} at {p.market_priciest.competitor})"

    if p.most_fluctuating:
        pt3 = (
            f"Most fluctuating: {p.most_fluctuating.competitor} "
            f"(average variation {fmt_pct(p.most_fluctuating.cv_pct)}% across {p.most_fluctuating.rooms_measured} room type(s))"
        )
    else:
        pt3 = "No property stands out as fluctuating; prices are steady."

    lm_desc = describe(p.last_minute_cheapest) if p.last_minute_cheapest else "no Last Minute prices available"
    eb_desc = describe(p.early_book_cheapest) if p.early_book_cheapest else "no Early Book prices available"
    pt4 = f"Last minute cheapest is {lm_desc}. Early book cheapest is {eb_desc}."

    # SUGGESTION points
    if p.compares and p.has_occupancy:
        pt_s1 = f"Our latest booking price is {money(p.our_price)} per night, occupancy rate: {fmt_pct(p.occupancy_pct)}%"
    elif p.compares:
        pt_s1 = f"Our latest booking price is {money(p.our_price)} per night, occupancy rate: N/A"
    elif p.has_occupancy:
        pt_s1 = f"No booking price available, occupancy rate: {fmt_pct(p.occupancy_pct)}%"
    else:
        pt_s1 = "No booking price or occupancy rate available"

    suggestion_text = get_suggestion(p)
    if suggestion_text:
        pt_s2 = suggestion_text
    else:
        pt_s2 = "Suggestion not available due to missing price or occupancy data."

    lines = [
        "INSIGHT:",
        f"1. {pt1}",
        f"2. {pt2}",
        f"3. {pt3}",
        f"4. {pt4}",
        "SUGGESTION:",
        f"1. {pt_s1}",
        f"2. {pt_s2}",
    ]
    return "\n".join(lines)


# -- Ollama -------------------------------------------------------------------


def pick_model(requested: Optional[str]) -> str:
    return requested if requested in ALLOWED_MODELS else DEFAULT_MODEL


async def ask_ollama(model: str, prompt: str) -> str:
    async with httpx.AsyncClient(timeout=OLLAMA_TIMEOUT) as client:
        resp = await client.post(
            f"{OLLAMA_URL}/api/chat",
            json={
                "model": model,
                "stream": False,
                "think": False,  # ignored by non-reasoning models
                # TOP-LEVEL on purpose. keep_alive nested inside "options" is
                # silently ignored by Ollama, which reads as "the setting does
                # not work" rather than as a mistake.
                # "keep_alive": OLLAMA_KEEP_ALIVE,
                "messages": [
                    {"role": "system", "content": SYSTEM},
                    {"role": "user", "content": prompt},
                ],
                # REVIEW: num_predict is unset, so Ollama's default cap applies.
                # Two sections are longer than the old single paragraph — if
                # notes come back truncated mid-sentence, raise it here.
                "options": {"temperature": 0.2},
            },
        )
        resp.raise_for_status()
        return resp.json().get("message", {}).get("content", "")


# -- Generation ---------------------------------------------------------------


async def generate_note(payload: NoteRequest) -> str:
    """Produce the note: ask the model, verify, retry once, else fall back.

    Lifted verbatim out of the endpoint on 2026-07-20 so both the synchronous
    and the callback path run the SAME code. The logic is unchanged from when it
    lived inline — two attempts, the offending number quoted back on the retry,
    fallback_note() if the guard is still unhappy.

    Never raises. The fallback is always available, so there is no failure mode
    that justifies returning nothing.
    """
    model = pick_model(payload.model)

    correction: Optional[str] = None
    for _ in range(2):  # first attempt, then one retry with the bad number quoted
        try:
            raw = await ask_ollama(model, build_prompt(payload, correction))
        except Exception:
            break  # model unreachable or erroring; the fallback is just as true

        note = clean_reply(raw)
        if not note:
            break

        offender = verify_numbers(note, payload)
        if offender is None:
            return note
        correction = offender

    return fallback_note(payload)


# -- Callback delivery --------------------------------------------------------


def callback_allowed(url: str) -> bool:
    """Is this a URL we are willing to POST a note to?

    Host-based allowlist. Without it, the callback_url field would be a
    server-side request forgery primitive for anyone holding the token: they
    could point this box at an internal address and read the response through
    our logs, or just use us to hammer a third party.

    Checked against netloc, so the port is part of the entry — "example.com" and
    "example.com:8443" are different hosts here, on purpose.
    """
    if not CALLBACK_HOST_ALLOWLIST:
        return False

    try:
        parsed = urlparse(url)
    except ValueError:
        return False

    if parsed.scheme not in ("http", "https"):
        return False

    return parsed.netloc.lower() in CALLBACK_HOST_ALLOWLIST


async def deliver_note(payload: NoteRequest) -> None:
    """Generate, then POST the result back to Laravel. Runs after the response.

    This is the whole background half of callback mode. It is fire-and-forget by
    construction: nothing awaits it and nothing sees what it returns, so it must
    swallow everything and report failures to the log.

    THE BODY LARAVEL EXPECTS (CompetitorAggregateController::noteCallback):
        {"job_id": "<echoed unchanged>", "note": "<prose>"}
        {"job_id": "<echoed unchanged>", "error": "<why>"}   on failure

    Laravel's reply is a retry signal, not just a status:
        200  stored, or already stored -> done
        404  unknown job_id: the row was pruned, or this is a duplicate -> STOP,
             retrying cannot make an absent row appear
        422  we sent a malformed body -> STOP, retrying sends the same body
        5xx / network -> transient, worth another attempt

    Giving up is safe. Laravel re-dispatches a row still `pending` after its
    pending_ttl, so an undelivered note becomes a delayed note, not a lost page.
    """
    job_id = payload.job_id
    url = payload.callback_url

    # Both are checked in the endpoint before this is scheduled; belt and braces
    # so this function is safe to call directly from a test.
    if not job_id or not url or not callback_allowed(url):
        log.warning("competitor-note: refusing to deliver, bad job_id or callback_url")
        return

    try:
        note = await generate_note(payload)
        body = {"job_id": job_id, "note": note}
    except Exception as exc:
        # generate_note() is written not to raise, so this is a real bug rather
        # than a slow model. Tell Laravel anyway: a row that gets an error is
        # marked failed immediately instead of holding a spinner until its TTL.
        log.exception("competitor-note: generation failed for job %s", job_id)
        body = {"job_id": job_id, "error": f"generation failed: {type(exc).__name__}"}

    headers = {"Authorization": f"Bearer {AUTH_TOKEN}"}

    for attempt, delay in enumerate((0,) + CALLBACK_RETRY_DELAYS):
        if delay:
            await asyncio.sleep(delay)

        try:
            async with httpx.AsyncClient(timeout=CALLBACK_TIMEOUT) as client:
                resp = await client.post(url, json=body, headers=headers)

            if resp.status_code < 300:
                log.info("competitor-note: delivered job %s", job_id)
                return

            if resp.status_code in (404, 422):
                log.warning(
                    "competitor-note: job %s rejected with %s, not retrying",
                    job_id,
                    resp.status_code,
                )
                return

            log.warning(
                "competitor-note: delivery attempt %s for job %s got HTTP %s",
                attempt + 1,
                job_id,
                resp.status_code,
            )
        except Exception as exc:
            log.warning(
                "competitor-note: delivery attempt %s for job %s failed: %s",
                attempt + 1,
                job_id,
                exc,
            )

    log.error("competitor-note: gave up delivering job %s", job_id)


# -- Endpoint -----------------------------------------------------------------


@app.get("/health")
async def health() -> dict:
    return {
        "ok": True,
        "models": sorted(ALLOWED_MODELS),
        "default": DEFAULT_MODEL,
        # Surfaced so a deploy can be checked without reading the env: if this is
        # empty, every request is served synchronously and Laravel's spinner
        # would spin until its pending_ttl expires.
        "callback_hosts": sorted(CALLBACK_HOST_ALLOWLIST),
    }


@app.post(
    "/competitor-note",
    # response_model is gone (2026-07-20): this endpoint now answers with either
    # {"note": ...} at 200 or {"status": "accepted", ...} at 202, and a single
    # response_model cannot describe both. NoteResponse is kept as the documented
    # shape of the synchronous reply.
    response_model=None,
    dependencies=[Depends(require_token)],
)
async def competitor_note(
    payload: NoteRequest, background: BackgroundTasks
) -> JSONResponse:
    """Accept a payload; answer fast if we can, or generate inline if asked to.

    TWO MODES, chosen by what the payload carries — see the 2026-07-20 block at
    the top of this file for the full picture.

    ASYNC (what Laravel does): job_id + callback_url present and the host is
    allowlisted. Queue the work and return 202 straight away. The 202 means
    "accepted for generation", NOT "the note is good" — Laravel only records
    that it is waiting.

    SYNC (curl, and any caller that has no callback receiver): generate inline
    and return the note at 200, exactly as this endpoint always did. An
    unallowlisted callback_url falls into this branch deliberately: refusing the
    request outright would turn a config mistake on the VPS into a hard failure
    on a page that could have shown a note.
    """
    wants_callback = bool(payload.job_id and payload.callback_url)

    if wants_callback and callback_allowed(payload.callback_url):
        background.add_task(deliver_note, payload)
        return JSONResponse(
            status_code=202,
            content={"status": "accepted", "job_id": payload.job_id},
        )

    if wants_callback:
        # Asked for a callback we will not make. Log loudly — this is almost
        # always CALLBACK_URL_ALLOWLIST missing the hostname (a fresh Cloudflare
        # Tunnel gets a new one every restart), and the symptom on the Laravel
        # side is a note that quietly never arrives.
        log.warning(
            "competitor-note: callback_url %r not in CALLBACK_URL_ALLOWLIST; "
            "falling back to a synchronous reply",
            payload.callback_url,
        )

    note = await generate_note(payload)
    return JSONResponse(status_code=200, content={"note": note})
