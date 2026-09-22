# Frozen Splunk captures

Real `output_mode=xml` results, saved byte-for-byte as the gateway returned
them. Tests and the regression suite read these directly rather than
transcribing them into fixtures, so the parser always sees the same bytes
production would.

| dir | Message Type | what it is | why it was captured |
|---|---|---|---|
| `example1` | PS | PS `…434427`, 2 targets, 2 `DOCUMENT_LINKS` | multi-target fan-out; the PS→DIR edge |
| `example2` | PS | PS `…681411`, empty `DOCUMENT_LINKS` | the no-documents case |
| `example3` | PS | PS with empty `PACKINDEX` (`F00C2G8057`) | SNR13 == SNR10; the only **RCPT** record, which is what separates `PACK_USAGE` from `LABEL_SALESCHANL` |
| `example4` | PS | 100 events | retrigger chain at scale |
| `example5` | PS | PS `…253724`, 100 target attempts | the 3.4 MB payload; SNR13 `028100944104Y` |
| `example6` | PS | PS `…497551`, 48 re-publishes | Re-publish vs Retrigger |
| `example7` | **DIR** | Document Type **`L01`**, topic `…/SAPPD70110/L01/_/_/_` | captured 2026-08-07. Proves the Document-Type discriminator: `L01` populates `OBJECTLINKSWORKSTEP` and leaves `OBJECTLINKSPACKITPACKSPEC` empty |
| `example8` | **Cockpit** | **standalone (explicit) trigger**, topic `…/SAPPD70110/_/_` | captured 2026-08-07. A pure SNR10 master-data change: `PS_ID` is **empty**, `SEQNO` is `00000`, and only `SNR10_MATERIAL` is populated |
| `example9` | **DIR** | Document Type `PAC`, topic `…/SAPPD70110/PAC/_/_/_` | captured 2026-08-07. The PS-linked case at the **SOLACE (pre-consumption)** stage, where field names are ALL-CAPS — the counterpart to the consumed camelCase capture in `screenshots/dependentObjects/DocumentInfoRecord` |
| `example10` | PS + Cockpit + DIR | PS `00000000040000348796`, **6 ERROR hops then a SUCCESS**, two targets | captured 2026-08-07 after the app answered four live questions about it wrongly. The only mixed hop history in the corpus, so the only fixture that can test "a terminal Success does not mean every hop succeeded". Also carries a real `SUPPLIER` on an RCPT record, real PI numbers in its Status Description, a **second** target the first answer missed, and a `DocumentInfoRecord` that exists in Splunk while the PS's own `DOCUMENT_LINKS` is empty |

`additionalRouting/` and `URLHierarchy/` hold screenshots, not captures.

## Why 7–9 exist

Until 2026-08-07 the whole repo held **one** DIR event and **one** Cockpit
event, so every claim about those two Message Types rested on a single sample
each — which had already produced three wrong "confirmed" entries in the
glossary. These were pulled by
`scripts/live_survey_dependent_objects.py` over a 30-day window.
