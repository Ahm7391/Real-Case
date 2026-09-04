# competitor-note

FastAPI service that turns already-computed market pricing figures into a short
two-section briefing. Laravel (LokaPro) renders it as one market-wide insight
box under the competitor accordion.

Notes are **English only**. The `language` field is still accepted for contract
compatibility and then ignored — see "Why English only" below.

## The rule

**The model does no arithmetic.** Laravel computes every number from the exact
table cells it renders and ships them pre-computed. Qwen only turns the struct
into prose.

The note sits directly beneath tables containing those same numbers, so a model
that writes 450,500 where the table says 450,000 does not produce a rounding
error — it produces a visible contradiction, and users stop trusting every
number on the page. Two layers prevent that:

- `verify_numbers()` extracts every numeric token from the note and rejects any
  we did not send (`450,000` == `450.000` == `450000`). One retry, with the
  offending number quoted back to the model.
- `fallback_note()` writes the same two sections deterministically. This is what
  makes the guard affordable: correct prose is always available without the
  model, so we can reject its output twice and walk away.

## What the guard does not cover

It polices **numbers, not claims**, and that gap is real. `qwen2.5:3b` produced
"our latest confirmed booking was made at our Standard rooms" — every digit
correct, but "Standard" is a competitor's room name and we never send a room
type of our own. It also merged the priciest-room fact with the volatility fact
because both named the same property. Neither is catchable by anything in
`main.py`.

That is why the default is `qwen2.5:7b-instruct` rather than a 3B. The numbers
were never the reason for the bigger model; the sentences around them were.

## Run

```bash
pip install -r requirements.txt
cp .env.example .env          # set COMPETITOR_NOTE_TOKEN to match Laravel's
uvicorn main:app --host 127.0.0.1 --port 8001
```

`.env` is loaded automatically from beside `main.py`. Bind to `127.0.0.1` and
reverse-proxy it — the token is the only thing between the open internet and a
box that runs models.

Check what is actually configured before debugging anything else:

```bash
curl -s localhost:8001/health     # -> {"ok":true,"models":[...],"default":"..."}
```

## Test

`python test_local.py` — drives the whole request path (routing, auth, parsing,
guard, cleanup, fallback) with Ollama stubbed, so the model can be made to
misbehave on purpose. No Ollama needed, no model downloads.

That covers everything except the real HTTP call to Ollama. Verify that
separately with a live payload once the service is up.

## Gotchas that will cost you an hour

**Absent keys, not null.** Two paths omit keys from the JSON entirely rather
than nulling them: `skip_reason` set (drops `our_booking_date`, `our_nights`,
`vs_max_pct`) and a property with no room types (drops all three `occupancy_*`).
Every such field has a default for that reason. Make one required and a normal
request 422s in a way that looks like a Laravel bug.

**Failure is silent, by design.** Laravel treats any non-200, or a 200 without a
non-empty `note`, as null and just hides the card. Failing is safe — but a
broken service looks identical to a missing feature. Laravel also
negative-caches failures for 120s, so a fix can take two minutes to appear.
Debug against this service with curl, never through the Laravel page.

**A rendered card does not prove the model ran.** `fallback_note()` returns 200
with good prose when Ollama is unreachable, when the model is missing, or when
the guard rejects twice. If notes suddenly read stiffer and more formulaic,
that is the fallback. Check the service log, not the UI.

**The allowlist fails closed and quietly.** `OLLAMA_MODEL_ALLOWLIST` exists so a
token-holder cannot make this box pull and run an arbitrary model. A model that
is pulled but not allowlisted is silently replaced by the default; an allowlisted
model that is *not installed* gets forwarded to Ollama, 404s, and lands in the
fallback with no error surfaced. Keep the allowlist and what `ollama list` shows
in agreement.

## Why English only

`qwen2.5:3b` would not hold Indonesian against an English FACTS block — asked
for `"id"` it replied in English anyway, while `fallback_note()` answered in
Indonesian. The card's language flipped depending on whether the guard passed.
The team reads English, so one language is both simpler and honest about what
the model actually does. `language` is typed `str` (not a `Literal`) so an old
payload still sending `"id"` gets a note rather than a 422.
