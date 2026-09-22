# regressionSuite — intensive regression testing for the PACKIT Operations Agent

Finds where the product breaks, hallucinates, or reports wrong results, by
holding the data behind every answer completely still and checking whether the
prose faithfully reports it.

## The core idea

An *expected result set* only means something if the data behind it cannot
move. Live Splunk changes minute to minute, so against live data a wrong answer
and a changed backend look identical — exactly the ambiguity a regression suite
exists to remove. So:

| Layer | Frozen? | Why |
|---|---|---|
| Splunk data | **frozen** | every real capture in `splunkExamples/`, replayed over HTTP |
| Additional Routing plan | **frozen** | reconstructed from the routing-plan spec (see caveat below) |
| The app | **real** | `ui.server.create_app`, unmodified, unmocked |
| Splunk + routing clients | **real** | the actual 4-call job flow and `Request-Filter` call run over the network |
| The LLM | **real** | the configured Model Farm model runs for real on every turn |

Only three environment values differ from a normal run: the two backend base
URLs and a scratch database. Everything between the browser and the model is
the shipping code path. That means any deviation is attributable to the app —
and since the LLM is the one live component, a deviation that survives a stable
backend is an LLM-layer failure, which is what hallucination *is*.

## What the model can and cannot see

`harness._summarize_status_result` hands the composing turn only:

```
primary_records[] : message_type, target_system, ps_id, status, description, hop_count
dependent_objects : same shape, split into DIR / cockpit lists
catalog_matches[] : seq_nr, error_category, responsible, summary, solution
time_range_searched
routing_check     : plant, determination_type, configured_target_systems,
                    requested_target_system, requested_target_was_configured
```

**Plant, determination type, usage, timestamps and message IDs never reach the
model.** Several scenarios ask for exactly those on purpose: a confident,
specific answer to a question with no grounded path to an answer is the
cleanest hallucination signal available.

Only user questions and final assistant prose persist between turns — the
injected data block does not. So every follow-up forces a fresh tool call whose
arguments the model must reconstruct from earlier prose. The follow-ups are
written to lean on that ("that one", "the other target") rather than repeating
the PS ID.

## The frozen corpus

257 events from 7 captures, deduped, rigidly time-shifted so the newest event
always sits 20 minutes before the run. Relative spacing is preserved exactly,
so the 100-hop retry chain still spans its real ~8 hours, and every time-window
scenario is reproducible forever instead of only until the captures age out:

- `-15m` (the app's default) → finds nothing, every time
- `-1h` → the tail of the retry chain
- `-24h` / `-7d` → effectively everything

They group into 55 `TransferRecord`s across 8 distinct situations:

| PS | target(s) | plant | det | status | description | records | hops |
|---|---|---|---|---|---|---|---|
| 00000000040001253724 | SAPP870110 | 0110 | SHIP | ERROR | SNR13 not found/ Mark for deletion | 1 | **100** |
| 00000000040001399187 | SAPP990110 | 0500 | SHIP | ERROR | SNR13 not found/ Mark for deletion | 1 | 100 |
| 00000000040001497551 | SAPPOE0110 | 929P | SHIP | ERROR | Cockpit master data dependent object still in progress | **48** | 1–2 |
| 00000000040000434427 | SAPP720110 **and** SAPPOE0110 | 0780 | SHIP | ERROR | T141 Bom item status Invalid… (differs per target) | 2 | 1 |
| 00000000040000681411 | SAPPOE0110 | 1810 | SHIP | ERROR | SNR13 Plant Status Invalid | 1 | 1 |
| 00000000040001399043 | SAPP810110 | 8160 | RCPT | ERROR | Error while saving the Det rule… | 1 | 1 |
| 00000000040000588527 | SAPPOE0110 | — | — | **SUCCESS** | MARA / MARM data has been updated… | 1 | 3 |

The large payload the suite is built around is `example5/payload5` — 3.4 MB,
100 Splunk rows, all one Message ID, collapsing to a single 100-hop record.

### SPL emulation

`corpus.search` parses the exact template `splunk_client.build_spl` emits and
refuses to run anything it doesn't model, so the suite fails loudly rather than
returning results that don't reflect the real query. Term matching is
boundary-anchored rather than substring, which matters: plant `0110` must not
match target system `SAPP870110`, and naive `in` would.

### Routing-plan provenance — read this before citing any number

The Splunk corpus is real captured data. **The routing plan is not.** The repo
holds no saved routing-plan response body, only a screenshot of the Postman
call. `harness/routing_fixture.py` is reconstructed from
`docs/components/routing-plan/TECHNICAL_SPEC.md`, which records the real
554-entry plan's structure and several exact confirmed facts. Every entry there
either restates one of those facts or is a Plant × Determination Type pair the
frozen Splunk corpus itself proves must exist. That is sufficient for "given a
known backend response, does the product report it faithfully?" — it is not
evidence about production. Re-derive from a real capture before treating any
routing number as a claim about the live plan.

## Adjudication

`harness/judge.py` is deliberately dumb and fully deterministic: regexes over
the reply, plus assertions about the SPL the app actually built and how many
backend calls it made — read from the fake backends' request log, the only
reliable evidence of what was really asked for as opposed to what the prose
claims. A passing check is not proof an answer is good; a failing check is
proof something concrete is wrong.

## Running it

```bash
python -m regressionSuite.run_scenarios              # all scenarios
python -m regressionSuite.run_scenarios S01 S04      # by slug prefix
python -m regressionSuite.run_scenarios --headed     # watch it
```

Output lands in `runs/<name>/<scenario>/`:

```
NN_<query>.txt      query, probe rationale, verbatim reply, verdict, SPL sent
shots/NN_*.png      full-page screenshot after each turn
backend_calls.json  every backend call that turn caused
verdicts.json       machine-readable adjudication
```

Serve the frozen stack by hand for exploratory poking:

```bash
python -m regressionSuite.harness.serve_under_test   # app on :8010, backends on :8099
```

## Layout

| Path | What |
|---|---|
| `scenarios.py` | the scenario catalogue — queries, follow-ups, expectations, and what each turn probes |
| `harness/corpus.py` | frozen Splunk corpus: load, time-shift, SPL emulation, re-serialize |
| `harness/routing_fixture.py` | frozen Additional Routing plan (spec-derived — see caveat) |
| `harness/fake_backends.py` | the two backends over real HTTP, with a request log |
| `harness/serve_under_test.py` | launches the real app against the frozen backends |
| `harness/judge.py` | deterministic adjudication |
| `run_scenarios.py` | Playwright runner |
