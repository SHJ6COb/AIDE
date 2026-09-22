# PACKITOperationsAgent

A single UI interface acting as an operations support agent: it answers internal users' queries about the status of Packaging Specification data flow (within PACKIT) and suggests actions accordingly.

## Language

The glossary lives in **topic files** under
[`app/agents/packspec_status/knowledge/`](app/agents/packspec_status/knowledge/),
one file per concept. This page is the index — it holds no definitions of its
own, deliberately: a second copy of the text is a second thing to keep true,
and this session alone found three "confirmed" claims here that the real
payloads contradicted.

Each topic file declares in its front matter when it is relevant
(`loads_when`). Every turn currently receives all of them; the declarations
are what selective loading will key off once it is switched on. See
[`app/core/knowledge.py`](app/core/knowledge.py).

**Add a term to the topic file it belongs to, never to this page.**

| Topic | Loads when | Terms defined |
|---|---|---|
| [`activation-counter`](app/agents/packspec_status/knowledge/activation-counter.md) | `has_superseded_activations` | Activation Counter |
| [`dependent-objects`](app/agents/packspec_status/knowledge/dependent-objects.md) | `has_dependent_objects` | Dependent Object, Packaging Cockpit Master Data |
| [`determination-record`](app/agents/packspec_status/knowledge/determination-record.md) | always | Determination Record, Determination Type, Customer Index, Usage, Workflow Status, Suggested Action, Packaging Planner, End User |
| [`document-info-record`](app/agents/packspec_status/knowledge/document-info-record.md) | `mentions_documents` | Document Info Record (DIR) |
| [`identifiers`](app/agents/packspec_status/knowledge/identifiers.md) | always | SNR10 / SNR13, Sales Channel, Message ID |
| [`splunk-payload`](app/agents/packspec_status/knowledge/splunk-payload.md) | always | Splunk Record, Return Message |
| [`packaging-specification`](app/agents/packspec_status/knowledge/packaging-specification.md) | always | PACKIT, Packaging Specification (PS), Packspec Status, Change Number, PS Group |
| [`replication-flow`](app/agents/packspec_status/knowledge/replication-flow.md) | always | Source System, PDMI, Packspec Payload, Solace, TOPICSTRING, Subscriber, Message Type, Replication Status, Transfer, Expert View |
| [`routing`](app/agents/packspec_status/knowledge/routing.md) | `is_routing_question` | Additional Routing, PT0 |
| [`target-systems`](app/agents/packspec_status/knowledge/target-systems.md) | `has_target_system` | Target System, POE, PXG, Cockpit data model, Packaging Instructions, CS03 BOM, PSTE, Import Configuration |
| [`triggers-and-hops`](app/agents/packspec_status/knowledge/triggers-and-hops.md) | `has_multiple_hops` | Host, Initial Trigger, Reprocessing cadence, Retrigger, Re-publish |
