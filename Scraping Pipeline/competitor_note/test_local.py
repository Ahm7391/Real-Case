"""
Local exercise of the whole request path with Ollama stubbed out.

Everything except the actual HTTP call to Ollama is the real thing: real
routing, real auth, real Pydantic parsing, real guard, real cleanup, real
fallback. The stub lets us make the model misbehave on purpose, which is the
only way to find out whether the guard actually catches it.

    python test_local.py

Rewritten 2026-07-17 for the market-wide payload (the per-competitor schema it
used to test no longer exists).
"""

import os

os.environ["COMPETITOR_NOTE_TOKEN"] = "test-token"
os.environ["OLLAMA_MODEL"] = "qwen2.5:7b-instruct"
# A second, non-default entry on purpose: an allowlist test whose only entry is
# the default proves nothing, since pick_model() returns the default either way.
# Ollama is stubbed here, so this name need not be installed.
os.environ["OLLAMA_MODEL_ALLOWLIST"] = "qwen2.5:7b-instruct,qwen2.5:14b-instruct"

import main  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

client = TestClient(main.app)
AUTH = {"Authorization": "Bearer test-token"}

MC = {"competitor": "Manca Villa", "room": "Standard", "price": 450000,
      "ota": "Booking.com", "window": "+14 Days"}
MP = {"competitor": "The Villas Umalas", "room": "2 Bedroom Villa", "price": 3250000,
      "ota": "tiket.com", "window": "+30 Days"}
LM = {"competitor": "Nari Homestay", "room": "Deluxe", "price": 510000,
      "ota": "Booking.com", "window": "+3 Days"}
EB = {"competitor": "Manca Villa", "room": "Standard", "price": 450000,
      "ota": "Booking.com", "window": "+30 Days"}

# The full payload: we have a booking, and we are pricier than the market floor.
FULL = {
    "as_of": "2026-07-16", "currency": "IDR", "model": "qwen2.5:7b-instruct", "language": "en",
    "competitor_count": 5,
    "market_cheapest": MC, "market_priciest": MP,
    "last_minute_cheapest": LM, "early_book_cheapest": EB,
    "most_fluctuating": {"competitor": "The Villas Umalas", "cv_pct": 18.4,
                         "rooms_measured": 3},
    "competitor_min": 450000, "competitor_max": 3250000,
    "our_price": 920000, "our_booking_date": "2026-08-01", "our_nights": 2,
    "vs_min_pct": 104.4, "vs_max": "below", "vs_max_pct": 71.7, "skip_reason": None,
    "occupied_rooms": 8, "total_rooms": 11, "occupancy_pct": 72.7,
}

# We undercut the market floor, so Laravel sends vs_min_pct NEGATIVE. This is
# the payload that used to silently force the fallback.
UNDERCUT = dict(FULL, our_price=400000, vs_min_pct=-11.1, vs_max_pct=-87.7)

# The skip case. Note what is NOT here: our_booking_date, our_nights,
# vs_max_pct, and all three occupancy keys. Laravel omits them entirely rather
# than nulling them.
SKIP = {
    "as_of": "2026-07-16", "currency": "IDR", "model": "qwen2.5:7b-instruct", "language": "en",
    "competitor_count": 5,
    "market_cheapest": MC, "market_priciest": MP,
    "last_minute_cheapest": LM, "early_book_cheapest": EB,
    "most_fluctuating": None,
    "competitor_min": 450000, "competitor_max": 3250000,
    "our_price": None, "vs_min_pct": None, "vs_max": None,
    "skip_reason": "no_booking",
}

results = []


def check(name, condition, detail=""):
    results.append((name, condition, detail))
    print(f"{'PASS' if condition else 'FAIL'}  {name}")
    if not condition and detail:
        print(f"      {detail}")


def stub(*replies):
    """Make the fake model return these replies in order. Returns prompts seen."""
    seen = []

    async def fake(model, prompt):
        seen.append(prompt)
        return replies[min(len(seen) - 1, len(replies) - 1)]

    main.ask_ollama = fake
    return seen


def post(payload):
    return client.post("/competitor-note", json=payload, headers=AUTH)


print("\n--- auth ---")
check("no token -> 401", client.post("/competitor-note", json=FULL).status_code == 401)
check(
    "wrong token -> 401",
    client.post("/competitor-note", json=FULL,
                headers={"Authorization": "Bearer wrong"}).status_code == 401,
)

print("\n--- contract: the keys Laravel omits entirely ---")
stub("MARKET CONDITION: cheap.\nOUR CONDITION: none.")
r = post(SKIP)
check("skip payload, our_*/occupancy ABSENT -> parses (not 422)",
      r.status_code == 200, f"got {r.status_code}: {r.text[:300]}")

print("\n--- the guard ---")

good = (
    "MARKET CONDITION: Across 5 competitors, the cheapest room is the Standard at "
    "Manca Villa for IDR 450,000, and the priciest is the 2 Bedroom Villa at The "
    "Villas Umalas for IDR 3,250,000.\n"
    "OUR CONDITION: Our IDR 920,000 is 104.4% above the cheapest room."
)
stub(good)
check("faithful note kept verbatim", post(FULL).json()["note"] == good)

# The failure this whole service exists to prevent: a digit that is not ours.
prompts = stub(
    "MARKET CONDITION: the cheapest room is IDR 450,500.",  # invented
    "MARKET CONDITION: the cheapest room is IDR 450,000.\n"
    "OUR CONDITION: ours is IDR 920,000, 104.4% above it.",  # behaves on retry
)
note = post(FULL).json()["note"]
check("invented 450,500 is caught", "450,500" not in note, note[:160])
check("retried exactly once", len(prompts) == 2, f"{len(prompts)} calls")
check("retry prompt quotes the offending number back", "450,500" in prompts[1])
check("clean retry output used, not fallback", "450,000" in note and "920,000" in note)

stub("IDR 450,500.", "Still IDR 999,999 sorry.")
note = post(FULL).json()["note"]
check("two strikes -> deterministic fallback",
      note == main.fallback_note(main.NoteRequest(**FULL)), note[:160])
check("fallback itself contains no invented number",
      main.verify_numbers(note, main.NoteRequest(**FULL)) is None)

stub("MARKET CONDITION: the cheapest is IDR 450.000 and the priciest IDR 3.250.000.")
check("dot-grouped 450.000 accepted as 450,000", "450.000" in post(FULL).json()["note"])

stub("MARKET CONDITION: the market spans IDR 2,800,000.", "MARKET CONDITION: IDR 450,000.")
check("model-computed spread (3,250,000-450,000) rejected",
      "2,800,000" not in post(FULL).json()["note"])

print("\n--- REGRESSION: negative percentages (we undercut the market) ---")
# Laravel sends vs_min_pct=-11.1; the note correctly writes "11.1%". allow()
# must compare on magnitude or this note is rejected and the fallback silently
# takes over every time we are the cheaper party.
p_under = main.NoteRequest(**UNDERCUT)
check("guard accepts 11.1 for vs_min_pct of -11.1",
      main.verify_numbers("OUR CONDITION: ours is 11.1% below the cheapest.",
                          p_under) is None,
      f"offender: {main.verify_numbers('ours is 11.1% below.', p_under)}")
check("guard accepts 87.7 for vs_max_pct of -87.7",
      main.verify_numbers("OUR CONDITION: a 87.7% difference.", p_under) is None)

undercut_note = (
    "MARKET CONDITION: the cheapest room is IDR 450,000.\n"
    "OUR CONDITION: our IDR 400,000 is 11.1% below it, a 87.7% difference "
    "against the priciest."
)
stub(undercut_note)
served = post(UNDERCUT).json()["note"]
check("undercut payload keeps the model's note (not the fallback)",
      served == undercut_note,
      "FELL BACK -> the negative-percentage bug is back")

print("\n--- REGRESSION: window labels with digits ---")
p_full = main.NoteRequest(**FULL)
check("'+14 Days' and '+30 Days' survive the guard",
      main.verify_numbers(
          "MARKET CONDITION: cheapest in the +14 Days window; Early Book in the "
          "+30 Days window.", p_full) is None)
check("'+3 Days' survives the guard",
      main.verify_numbers("Last Minute is cheapest in the +3 Days window.",
                          p_full) is None)
check("room name '2 Bedroom Villa' does not trip the guard",
      main.verify_numbers("The 2 Bedroom Villa costs IDR 3,250,000.", p_full) is None)

print("\n--- occupancy ---")
check("occupancy 8 of 11 (72.7%) passes the guard",
      main.verify_numbers("OUR CONDITION: 8 of our 11 rooms are occupied (72.7%).",
                          p_full) is None)
partial = main.NoteRequest(**{k: v for k, v in FULL.items()
                             if k not in ("occupied_rooms", "total_rooms")})
check("partial occupancy is suppressed, never renders 'None of our None'",
      "None" not in main.fallback_note(partial),
      main.fallback_note(partial))

print("\n--- cleanup ---")
stub(
    "<think>3250000 - 450000 = 2800000, let me mention that</think>\n"
    "```\n"
    "Here is the briefing: **MARKET CONDITION:** the cheapest is IDR 450,000.\n"
    "```"
)
note = post(FULL).json()["note"]
check("<think> block stripped, and its arithmetic with it",
      "2800000" not in note and "<think>" not in note, note[:160])
check("code fence stripped", "```" not in note, note[:160])
check("markdown stripped", "**" not in note, note[:160])
check("single-line 'Here is...' preamble stripped",
      not note.lower().startswith("here is"), note[:160])

check("newline-form preamble stripped",
      main.clean_reply("Here is the briefing:\nMARKET CONDITION: x.")
      == "MARKET CONDITION: x.")

print("\n--- REGRESSION: note is pinned to exactly two lines ---")
# The model emits the label on its own line and one sentence per line about
# half the time; `pre-line` would render that as a ragged list.
ragged = (
    "MARKET CONDITION:\n"
    "The cheapest room is IDR 450,000.\n"
    "The priciest is IDR 3,250,000.\n"
    "OUR CONDITION:\n"
    "Ours is IDR 920,000.\n"
    "Occupancy is 72.7%."
)
cleaned = main.clean_reply(ragged)
check("8-line model output collapses to 2 lines",
      cleaned.count("\n") == 1, repr(cleaned))
check("the break sits before OUR CONDITION",
      cleaned.split("\n")[1].startswith("OUR CONDITION"), repr(cleaned))
check("already-2-line output stays 2 lines",
      main.clean_reply("MARKET CONDITION: a.\nOUR CONDITION: b.").count("\n") == 1)
check("fallback is 2 lines too",
      main.fallback_note(p_full).count("\n") == 1)

print("\n--- model allowlist ---")
check("non-default allowlisted model honoured",
      main.pick_model("qwen2.5:14b-instruct") == "qwen2.5:14b-instruct")
check("off-list model falls back to default (no arbitrary pull)",
      main.pick_model("evil/backdoor:latest") == "qwen2.5:7b-instruct")
check("null model -> default", main.pick_model(None) == "qwen2.5:7b-instruct")

print("\n--- ollama down ---")


async def boom(model, prompt):
    raise RuntimeError("connection refused")


main.ask_ollama = boom
r = post(FULL)
check("ollama unreachable -> 200 with fallback, not 500", r.status_code == 200)
check("fallback note is non-empty", bool(r.json()["note"].strip()))

print("\n--- fallback prose ---")
for label, payload in (("FULL", FULL), ("UNDERCUT", UNDERCUT), ("SKIP", SKIP)):
    print(f"\n{label}:")
    for line in main.fallback_note(main.NoteRequest(**payload)).split("\n"):
        print("  |", line)

skip_note = main.fallback_note(main.NoteRequest(**SKIP))
check("\nskip fallback never states a price of ours",
      "works out to" not in skip_note, skip_note)

failed = [n for n, ok, _ in results if not ok]
print(f"\n{len(results) - len(failed)}/{len(results)} passed")
if failed:
    print("FAILED: " + ", ".join(failed))
    raise SystemExit(1)
