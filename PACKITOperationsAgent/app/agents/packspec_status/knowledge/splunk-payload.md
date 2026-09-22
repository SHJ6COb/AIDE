---
concept: splunk-payload
summary: How to read a Splunk record end to end — the three layers it nests, the traps that silently break parsing, and what it can and cannot answer before a hop to PD7 is needed.
loads_when: always
---

Splunk is where answering starts. Almost every question arrives as *"what happened to this
packaging specification"*, and the record in front of you can settle most of it — provided
you can get through the wrapping.

**Splunk Record**:
One `<result>` element in a Splunk result set — **one hop to one Target System**, not one message. A message that fans out to several targets appears as several records sharing a `MESSAGEID` and differing by `host`. Reading the first and stopping is how a second target gets missed.
_Avoid_: Event, message (a message can span several records)

**Return Message**:
One `ReturnMsgSet` entry inlined on a record's OData entry, carrying `Type`, `Id`, `Number`, `Message` and `MessageV1`–`V4` — the error text for that hop. `MessageV*` are the substitution values **already interpolated** into `Message`, not extra facts. Empty-`Type` entries numbered `000` are padding, and counting them overstates what happened.
_Avoid_: Log line, error (a record carries several, and not all are errors)

## A record nests three layers

```
<results preview='0'>                  ← Splunk result set
  <meta><fieldOrder>…                     the field list
  <result offset='0'>                  ← ONE HOP, not one message
    <field k='host'>   …_CONSUMING        the target system
    <field k='_time'>  …                  when this hop happened
    <field k='source'> PackITPackagingSpecification
    <field k='_raw'>                   ← everything below lives in here, escaped
        <entry>                        ← SAP OData Atom entry
          SemaMsgSet('<MESSAGEID>')       the message
          <d:Uuid>                        = MESSAGEID
          <d:BusinessStatus>              this hop's outcome
          <Ret_msgs>                      ReturnMsgSet entries — the error text
          <d:Payload>                  ← the business JSON, as a string
              SINGLEMESSAGES[]
                SINGLEMESSAGEHEADER → OBJECTKEY
                TOPICSTRING
                SINGLEMESSAGEBODY
                  DETERMINATION      ← the Determination Record
                    DOCUMENT_LINKS
                    HEADER           ← the Packaging Specification
                      CONTENTS
                      LEVELS → LEVEL_ELEMENTS
  <result offset='1'>                  ← the same message at another target
```

**One `<result>` is one hop, not one message.** A message that fans out to three target
systems appears as three results sharing a `MESSAGEID` and differing by `host`. Reading the
first result and stopping is how a second target gets missed.

The service is `/sap/opu/odata/RB9X/PDDE_SEMSAP_IN_SRV/`, and each result's OData host
differs by target — `rb3poea6…:44326` and `rb3p72a4…:44300` are two systems, not two
addresses for one.

## Fields on the result itself

`_bkt` · `_cd` · `_indextime` · `_raw` · `_serial` · `_si` · `_sourcetype` · `_time` ·
`host` · `index` · `linecount` · `source` · `sourcetype` · `splunk_server`

Of these, three carry answers: **`host`** names the target system (strip the `_CONSUMING`
suffix), **`_time`** is when the hop happened, and **`source`** is the Message Type.

## Traps that break parsing silently

Every one of these has produced a wrong or empty answer in practice.

**The content is doubly HTML-escaped.** `_raw` holds `&quot;` where a quote belongs, and
unescaping once is not enough. A single pass leaves `&amp;quot;` and every field lookup
fails while the file still looks like data.

**Values arrive wrapped in highlight markup.** `<sg h='1'>00000000040000434427</sg>` is a
Splunk search decoration, not part of the value. Comparing a wrapped value against a bare
one silently finds nothing.

**Numbers are unquoted.** `"TRGQTY":16`, not `"TRGQTY":"16"`. A pattern expecting a quoted
value matches every string field and misses every numeric one.

**A capture file's extension may lie.** Files named `.json` in this repo hold Splunk XML.
Parse by content, never by name.

**`___` and `__________` are placeholders, not values.** They appear where a slot is unused,
particularly on DIR records. Reporting one as a supplier code is a plausible-looking
fabrication.

**Zero-padding differs between wire and screen.** A PS ID is 20 digits on the wire and
unpadded in the UI; document numbers are 25 versus 7; worksteps 20 versus 10. The same
object, two renderings — and `AENNR` appears as both `'00000001'` and `'1'` in the same
corpus.

**`ZACTCOUNTER` carries a leading space** — `' 3'`, not `'3'`.

## Reading an outcome

**`d:BusinessStatus` is this hop's outcome**, and it is per hop — one target can be in
error while another succeeded, at the same moment, on the same message.

**`Ret_msgs` carries the error text**, as `ReturnMsgSet` entries with `Type`, `Id`,
`Number`, `Message` and `MessageV1`–`V4`. The `MessageV*` values are the substitution
parameters **already interpolated** into `Message` — they are not extra facts.

> **A `Type='S'` return message does not mean the hop succeeded.** Records carry an `S`
> line ("Cockpit Data Model Updated") alongside an `E` while `BusinessStatus` is `ERROR`.
> Read the status, not the last line in the table.

Empty-`Type` entries with `Number` `000` are padding. Counting return messages without
excluding them overstates what happened.

## Reading the identity

`OBJECTKEY` is the business identity, and it is a **join of two objects** — Determination
Record fields (`SEQNO`, `DETTYPE`, `WERKS`, `SUPPLIER`, `ABRVW`, `PACKINDEX`) and
Packaging Specification fields (`PS_ID`, `AENNR`, `ZACTCOUNTER`). Neither alone identifies
what is on the wire.

**An empty `PACKINDEX` together with an empty `SUPPLIER` is meaningful, not missing.** Which
party field is populated is decided by `DETTYPE`: `SHIP` carries a customer index, `RCPT`
carries a supplier, and the repackaging types carry neither.

**The numeric status segment in `TOPICSTRING` is the Determination Record's Workflow
Status**, not the packaging specification's. `60` is Accepted; `35` and `37` are VitAA
waits. The PS's own status is the letter code in `HEADER.STATUS`.

## What a record can answer

Which target systems were reached and when · this hop's outcome and its error text · the
full business identity, including product, plant, customer or supplier, usage and
determination type · the packaging structure, levels and materials · which documents are
linked · the Determination Record's approval status at publish time.

## What it cannot — and where to go instead

The payload carries the **current state**. It carries almost nothing about how that state
came about, because those things were never published:

| Question | Why the record cannot answer it |
|---|---|
| *why* is a value set this way | reason fields are source-only |
| what did it look like before | the previous version was deleted, rendered to a PDF |
| what changed between versions | same — no structured predecessor exists |
| which context does this document apply to | plant/supplier/index scoping does not travel |
| why has nothing arrived at all | a not-yet-valid or unapproved record publishes nothing |

That last row is the important one: **silence in Splunk is a legitimate state**, not
necessarily a failed search. A record awaiting approval, blocked behind a sibling's
approval, or with a future `VALID_FROM` produces no event whatsoever.

When a question falls in this table, no further searching helps — the information was never
on the wire, and the source system is the only place it exists.

## Open — to re-check at the next full payload pull

These came out of live tracing, not from the captures. Each needs a wider pull to settle;
none is settled now, and nothing in this file above depends on them.

**The search clock and the reported clock may not be the same clock.** Two live traces of
PS `00000000040001398976`, run 2026-08-08 22:25 and 2026-08-09 00:22 local, each used the
default `-15m` window and each returned hops whose payload `time` was **~3.7 hours older**
than the search window should allow — 18:41–18:51 in the first, 20:41–20:51 in the second.
The offset was the same both times, so it is systematic rather than noise.

The window filters on Splunk's own `_time`; the hop timestamps an answer quotes come from
the payload. If those differ by hours, then an answer reading *"three attempts between
20:41 and 20:51"*, found by a fifteen-minute search, is quoting two clocks without saying
so. **To validate:** pull `_time` alongside each hop's payload timestamp across many
records and several targets, and establish whether the gap is index lag, a timezone
artefact, or `_time` marking a later pipeline stage than the hop it is attached to. Until
then, treat any reasoning that combines a search window with a quoted hop time as
unverified.

**A hop count has an unstated denominator.** `hops_at_target` is whatever fell inside the
window, but an answer states it as a total ("reprocessed 3 times"). The summary does carry
`time_range_searched`, so the fact is available to the composing turn; nothing requires it
to be used, and no guardrail fires when it is omitted. Worth re-examining once the clock
question above is settled, since the two interact.

**Retry cadence for this record looked roughly two-hourly** across the two traces — three
attempts about five minutes apart, then a gap. One record, two observations, so this is an
observation and not a policy. `packaging-specification.md` already warns against asserting a
retry schedule from the payload; this does not change that.

---

**Derived from:** `splunkExamples/example1–10` and `tests/fixtures/multi_target_fanout_page.xml`, read 2026-08-08 — the envelope structure, field list, OData service and entity, escaping behaviour, and every trap listed above, each of which was hit while parsing these files.

**Verified:** the layer structure, field names, and traps were checked directly against the captures rather than carried from a summary.

**Acceptance question:** A Splunk search returns two results with the same `MESSAGEID`. What does that mean, what must be stripped before the values can be compared, and where in the nesting is the error text?
