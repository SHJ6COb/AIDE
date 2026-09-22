"""`get_ps_status` -- the one LLM-callable tool for this agent.

One deterministic pipeline (search -> transform -> branch -> catalog-match),
zero LLM involvement inside it. See ADR-0001 and
docs/agents/packspec-status/TECHNICAL_SPEC.md's "Procedure" section for why
this is a single composite function rather than four LLM-orchestrated tools.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Callable

from app.core.config import AgentConfig
from app.core.domain import MessageType, SearchParams, is_underspecified
from app.tools import routing_plan, splunk_client, splunk_xml_parser
from app.tools.catalog import CatalogMatch, match_catalog
from app.tools.routing_plan import RoutingPlanError
from app.tools.transform import TransferRecord, group_transfers

_DEPENDENT_OBJECT_BLOCKED_ROWS = frozenset({57, 58})
"""error_catalog.yaml seq_nrs for the two Dependent-Object-blocking catalog
rows (Cockpit Master Data / DIR "still in progress") -- see CONTEXT.md's
Dependent Object entry: the Target System won't process a PS's own
PackITPackagingSpecification Transfer until its Dependent Object Transfers
are done, so a match against either row is what triggers the branch step."""

_XOE_SYSTEM_CODE = "OE"
"""Target System IDs are `SAPP` + a 2-character system code + `0110` -- `87`,
`99`, `72`, `81`, `45`, `74`, `79`, `T0`, `1M`, `OE`. The xOE line (POE/QOE) is
the one whose code is `OE`.

Confirmed with the domain owner: **Dependent Object and Document Info Record
triggers are only ever sent to the xOE line.** Every other Target System
receives the PackITPackagingSpecification trigger alone. A dependent-object
lookup against a non-xOE target therefore cannot find anything -- not because
the object is late, but because none was ever sent.

Matched as a *segment*, not a bare `"OE"` substring, so a future system code
that happens to contain those letters can't be mistaken for the xOE line."""

OnStep = Callable[[str], None]


def is_xoe_target(target_system: str | None) -> bool:
    """True if this Target System is on the xOE (POE/QOE) line -- the only line
    that receives Dependent Object and DIR triggers at all."""
    if not target_system or len(target_system) < 6:
        return False
    return target_system[4:6].upper() == _XOE_SYSTEM_CODE


def select_live_activations(records: list[TransferRecord]) -> tuple[list[TransferRecord], int]:
    """Drop Transfers belonging to a superseded activation of the same
    Determination Record. Returns `(kept, superseded_count)`.

    Confirmed with the domain owner: `ZACTCOUNTER` is the version of the PS
    structure, incremented on every change+activate, and the Target System
    processes the newest one. So an ERROR carried by an older counter describes
    a version of the PS that has since been replaced -- reporting it as a live
    problem sends someone to fix something that no longer exists.

    Scoped per `(ps_id, seqno)` rather than per PS: `SEQNO` identifies a
    specific Determination Record, and an *extend* creates a new one without
    touching the counter, so two Determination Records of the same PS are
    independent and one can legitimately lag the other.

    **Fails open in three ways, deliberately.** The cost of wrongly dropping a
    record is a false all-clear on a PS that is visibly failing -- far worse
    than the cost of mentioning an obsolete one:

    1. If the newest counter has produced no *terminal* record (nothing with a
       Business Status) the older counter's records are kept, because the newer
       trigger has not actually landed anywhere yet.
    2. A record whose counter is missing or unparseable is always kept.
    3. Records with no `ps_id` are never grouped or dropped.
    """
    groups: dict[tuple[str, str | None], list[TransferRecord]] = {}
    ungrouped: list[TransferRecord] = []
    for record in records:
        if record.ps_id is None or record.activation_counter is None:
            ungrouped.append(record)  # rule 2 and 3
            continue
        groups.setdefault((record.ps_id, record.seqno), []).append(record)

    kept = list(ungrouped)
    superseded = 0
    for group in groups.values():
        counters = sorted({r.activation_counter for r in group}, key=_counter_sort_key, reverse=True)
        newest = counters[0]
        live = [r for r in group if r.activation_counter == newest]
        if len(counters) > 1 and not any(r.current_status for r in live):
            # Rule 1 -- the newest activation was triggered but has not reached
            # a terminal state at any target yet, so the previous one is still
            # the last thing that actually happened. Keep both; the answer says
            # so rather than reporting "nothing found".
            live = live + [r for r in group if r.activation_counter == counters[1]]
        kept.extend(live)
        superseded += len(group) - len(live)
    return kept, superseded


def _counter_sort_key(counter: str) -> tuple[int, int | str]:
    """Sort activation counters numerically where possible, lexically
    otherwise -- so `10` beats `9`, without assuming the field is always
    numeric (it is a string in the payload and space-padded)."""
    return (0, int(counter)) if counter.isdigit() else (1, counter)


@dataclass(frozen=True)
class DependentObjectsView:
    """Populated only when a `PackITPackagingSpecification` TransferRecord is
    blocked on a Dependent Object (see CONTEXT.md's Dependent Object entry
    and catalog rows 57/58) -- tells the caller *which* dependent object(s)
    are actually stuck, not just that the parent PS is blocked.

    Both lists can legitimately come back empty even when this is populated
    -- confirmed live (see docs/components/transform/TECHNICAL_SPEC.md's
    Dependent Object blocking section): a dependent object stuck at the
    Source system before ever being published into PDMI never becomes a
    Splunk-visible Transfer at all, so there's nothing to find. That's a
    real, informative answer (check the Source system directly, per catalog
    rows 57/58's own solution text), not a lookup failure.

    `missing_is_anomalous` decides which of two opposite meanings an empty
    `cockpit_master_data` carries -- see its own comment below. Without it the
    same empty list was being described the same way regardless of target, and
    on a non-xOE target that description asserted something about the Source
    system the data could not support.
    """

    document_info_records: list[TransferRecord]
    cockpit_master_data: list[TransferRecord]

    missing_is_anomalous: bool = False
    """True only when the blocked Transfer's target is on the xOE line.
    Confirmed with the domain owner: a PS trigger to POE **always** carries a
    Dependent Object trigger, so its absence there is a genuine finding worth
    reporting. On any other target no dependent trigger is ever sent, so an
    empty list means nothing at all and must not be commented on. A missing DIR
    is never anomalous on its own -- that trigger is optional even on xOE."""

    linked_document_keys: tuple[str, ...] = ()
    """The DIR keys the PS's own payload declares via `DOCUMENT_LINKS`, whether
    or not a Transfer was found for each. Lets the answer distinguish "this PS
    declares no linked documents" (a fact) from "it declares two and neither has
    appeared" (a different fact) -- indistinguishable when only the found
    Transfers are reported."""


@dataclass(frozen=True)
class RoutingCheck:
    """Populated only when a search scoped to a specific `target_system`
    found nothing there, but the same PS/criteria *was* found on other
    targets -- letting us resolve its real Plant/Determination Type and ask
    the Additional Routing plan whether the requested target was ever
    configured to receive it at all. See CONTEXT.md's Additional Routing
    entry and `app/tools/routing_plan.py`.

    If the broader (target-unscoped) search *also* finds nothing, or finds
    records with no resolvable Plant/Determination Type, this stays `None`
    -- there's nothing to check the routing plan against, and the honest
    answer is just "not found," not a routing question.
    """

    plant: str
    determination_type: str
    configured_target_systems: tuple[str, ...]
    requested_target_system: str
    requested_target_was_configured: bool


@dataclass(frozen=True)
class StatusResult:
    """`get_ps_status`'s own return type -- the fully-summarized result of
    the deterministic pipeline, before the LLM composes
    `plain_language_answer` from it in the harness's second turn. See
    docs/agents/packspec-status/TECHNICAL_SPEC.md's Output Context.
    """

    primary_records: list[TransferRecord]
    dependent_objects: DependentObjectsView | None
    catalog_matches: list[CatalogMatch]
    routing_check: RoutingCheck | None = None

    superseded_count: int = 0
    """How many Transfers were dropped as belonging to an older activation of
    the same Determination Record (see `select_live_activations`). Reported so
    the answer can say older activations exist rather than pretending they
    never did -- silently shrinking a result set is how a tool loses trust."""


def _run_search(config: AgentConfig, params: SearchParams) -> list[TransferRecord]:
    pages = splunk_client.search(config, params)
    raw_results = [result for page in pages for result in splunk_xml_parser.parse_results(page)]
    return group_transfers(raw_results)


def _is_dependent_object_blocked(record: TransferRecord) -> bool:
    if record.message_type != MessageType.PACKAGING_SPECIFICATION.value:
        return False
    matches = match_catalog(record.current_description)
    return any(m.seq_nr in _DEPENDENT_OBJECT_BLOCKED_ROWS for m in matches)


def _lookup_dependent_objects(config: AgentConfig, params: SearchParams, blocked_records: list[TransferRecord]) -> DependentObjectsView | None:
    """Look for the Dependent Objects and Document Info Records a blocked PS is
    waiting on -- but only where they can exist.

    Confirmed with the domain owner: DIR and Dependent Object triggers are sent
    **only to the xOE line** (POE/QOE). Against any other target these searches
    cannot match, because no such trigger was ever produced. Previously they ran
    regardless: two Splunk jobs per blocked PS that were guaranteed to return
    nothing, whose empty result was then reported as "the dependent object
    hasn't been published yet" -- a claim about the Source system that the data
    never supported. Returning `None` for a non-xOE target says "not applicable
    here", which is different from "looked and found nothing".

    The DIR half is driven by `DOCUMENT_LINKS` off the PS's own payload rather
    than by a blind PS-ID search: Message ID is per trigger *per message type*,
    so it cannot link the two, and the links are already in hand.

    NOT VERIFIED AGAINST REAL DATA: the repo contains no `DocumentInfoRecord`
    payload at all, so the document-number search below is written from the
    documented DIR key shape and has never been exercised end to end. The domain
    owner reports a published DIR also carries `hasPackagingSpecification`
    pointing back at the PS -- which would make a reverse lookup possible too --
    but `CONTEXT.md` currently claims the opposite and neither can be settled
    without a capture. Treat empty DIR results here as unproven, not as fact.
    """
    if not any(is_xoe_target(record.target_system) for record in blocked_records):
        return None

    ps_ids = sorted({record.ps_id for record in blocked_records if record.ps_id})
    document_keys = sorted({key for record in blocked_records for key in record.document_link_keys})

    dir_records: list[TransferRecord] = []
    for document_number in sorted({link["DOCUMENT_NUMBER"] for record in blocked_records for link in record.document_links if link.get("DOCUMENT_NUMBER")}):
        dir_records.extend(
            _run_search(config, SearchParams(document_number=document_number, time_range=params.time_range, message_type=MessageType.DOCUMENT_INFO_RECORD))
        )

    cockpit_records: list[TransferRecord] = []
    for ps_id in ps_ids:
        cockpit_records.extend(
            _run_search(config, SearchParams(ps_id=ps_id, time_range=params.time_range, message_type=MessageType.COCKPIT_MASTER_DATA))
        )
    # A dependent object belonging to a superseded activation is no more
    # current than a superseded PS Transfer would be.
    cockpit_records, _ = select_live_activations(cockpit_records)

    return DependentObjectsView(
        document_info_records=dir_records,
        cockpit_master_data=cockpit_records,
        missing_is_anomalous=True,
        linked_document_keys=tuple(document_keys),
    )


def _catalog_context(record: TransferRecord) -> dict[str, str | None]:
    # customer_index/sales_channel are not currently extracted onto
    # TransferRecord/Hop -- see transform.py -- so context-scoped rows that
    # need them (e.g. row 7) fail closed via catalog.py's own rule, not here.
    return {"plant": record.latest.plant, "determination_type": record.latest.det_type}


def _match_catalog_for_records(records: list[TransferRecord]) -> list[CatalogMatch]:
    matches_by_seq_nr: dict[int | str, CatalogMatch] = {}
    for record in records:
        if record.current_status != "ERROR" or not record.current_description:
            continue
        for match in match_catalog(record.current_description, context=_catalog_context(record)):
            matches_by_seq_nr.setdefault(match.seq_nr, match)
    return list(matches_by_seq_nr.values())


def _resolve_plant_and_det_type(records: list[TransferRecord]) -> tuple[str | None, str | None]:
    plant = next((r.latest.plant for r in records if r.latest.plant), None)
    det_type = next((r.latest.det_type for r in records if r.latest.det_type), None)
    return plant, det_type


def _check_routing_if_target_missing(
    config: AgentConfig, params: SearchParams, primary_records: list[TransferRecord]
) -> RoutingCheck | None:
    """Only fires when the user asked about a specific `target_system` and
    it wasn't found there -- broadens the same search (dropping just
    `target_system`) to see if the PS exists at all, resolves its real
    Plant/Determination Type from whatever's found, and asks the Additional
    Routing plan whether the requested target was ever configured to
    receive that combination. Fails closed (returns `None`, not a guess) on
    any ambiguity: no broader records, no resolvable Plant/Determination
    Type, the broadened search no longer being specific enough to run, or
    the routing-plan call itself failing -- see `RoutingCheck`'s own
    docstring.
    """
    if params.target_system is None or primary_records:
        return None

    broadened = replace(params, target_system=None)
    if is_underspecified(broadened):
        # Dropping `target_system` can take the search below the bar the
        # scope guard enforces on everything the LLM sends -- caught by the
        # `baseline` regression run (S06/q3): "failed transfers to
        # SAPP870110" is target_system + status, which is legitimately
        # specific, but broadening it leaves `status=ERROR` alone and the
        # bare sweep `search index=pdbb sourcetype=Native
        # "<d:BusinessStatus>ERROR</d:BusinessStatus>" | head 200` really
        # did reach the backend -- the query the guard had refused outright
        # one turn earlier, returning 200 of the corpus's 257 events. The
        # guard is applied once in harness.py to the LLM-parsed params;
        # re-deriving params here means re-checking them here too, or it is
        # a side door around it. Fails closed like every other branch: no
        # RoutingCheck, and harness._not_found_answer falls back to its
        # honest "whether it was ever supposed to reach that system isn't
        # something I can check here" caveat.
        return None

    broader_records = _run_search(config, broadened)
    plant, det_type = _resolve_plant_and_det_type(broader_records)
    if not plant or not det_type:
        return None

    try:
        result = routing_plan.query_target_systems(config, plant=plant, determination_type=det_type)
    except RoutingPlanError:
        # Fail closed -- never claim to have checked routing if the call
        # itself failed; the caller falls back to the honest "can't check"
        # caveat instead (see harness.py's _not_found_answer).
        return None

    return RoutingCheck(
        plant=plant,
        determination_type=det_type,
        configured_target_systems=result.target_systems,
        requested_target_system=params.target_system,
        requested_target_was_configured=params.target_system in result.target_systems,
    )


def get_ps_status(params: SearchParams, config: AgentConfig, *, on_step: OnStep | None = None) -> StatusResult:
    """Run the fixed 5-step pipeline (search, transform+branch are steps 1-3
    below, catalog-match, compose) and return one already-summarized
    `StatusResult`. `on_step`, if given, is called with a short present-tense
    status string before each stage that does real work -- the mechanism
    behind the UI's staged-progress display (see ARCHITECTURE.md and
    docs/components/harness/TECHNICAL_SPEC.md). Never called from more than
    one thread concurrently for a single invocation; safe to run this whole
    function in a background thread since it does no I/O beyond the
    already-synchronous, already-live-verified `splunk_client.search`.
    """

    def step(message: str) -> None:
        if on_step is not None:
            on_step(message)

    step("Searching Splunk...")
    primary_records = _run_search(config, params)

    # An ERROR on a superseded activation describes a version of the PS that
    # has since been replaced. Filtering here, before catalog matching, keeps
    # an obsolete error from producing a live-looking documented fix.
    primary_records, superseded_count = select_live_activations(primary_records)

    routing_check = None
    if params.target_system is not None and not primary_records:
        step("Checking Additional Routing...")
        routing_check = _check_routing_if_target_missing(config, params, primary_records)

    dependent_objects = None
    blocked_records = [record for record in primary_records if _is_dependent_object_blocked(record)]
    if blocked_records:
        step("Checking dependent objects...")
        dependent_objects = _lookup_dependent_objects(config, params, blocked_records)

    step("Checking error catalog...")
    catalog_matches = _match_catalog_for_records(primary_records)

    return StatusResult(
        primary_records=primary_records,
        dependent_objects=dependent_objects,
        catalog_matches=catalog_matches,
        routing_check=routing_check,
        superseded_count=superseded_count,
    )
