"""Domain-aware transform: raw Splunk field dicts -> PackIT `TransferRecord`s.

See docs/components/transform/TECHNICAL_SPEC.md for the empirical grounding
behind every rule here -- this implements findings from a live Splunk
investigation, several of which corrected the original (wrong) design.
"""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass

from app.tools.splunk_xml_parser import RawResult

_ATOM_NS = {
    "a": "http://www.w3.org/2005/Atom",
    "m": "http://schemas.microsoft.com/ado/2007/08/dataservices/metadata",
    "d": "http://schemas.microsoft.com/ado/2007/08/dataservices",
}

_CONSUMING_HOST_RE = re.compile(r"^(?:CPI_[^_]+_)?(?P<target>.+?)_CONSUMING$")
_CPI_PUBLISH_HOST_RE = re.compile(r"^CPI_[^_]+_(?P<target>.+)$")
"""A newly confirmed-live host shape, not previously documented in
CONTEXT.md's Host entry: a bare `CPI_{Source System}_{Target System}` host
(no `_CONSUMING` suffix) on a pre-consumption (`plain_json`) hop -- the
publish-side event that precedes that same target's `_CONSUMING` hop by a
few hundred ms. Confirmed live across three different targets on the same
message (including a PT0/VITAA target), so it's a general pattern, not
PT0-specific. Without recognizing it as target-specific, `group_transfers`
misclassified it as "shared/untargeted" (see that function's docstring) --
since untargeted hops are attached to every target sharing a Message ID,
a multi-target fan-out could end up with one target's own pre-consumption
publish hop sorting chronologically *after* a different target's genuine
terminal hop, becoming that other target's `.latest` and reporting a false
no-status/no-description result despite the dashboard showing Success.
Confirmed by cross-checking a real PT0/VITAA success example (PS
00000000040001498023) against screenshots/results/*.png."""


class UnrecognizedPayloadShape(Exception):
    """A payload didn't match any known envelope/shape -- never guess past this."""


_KNOWN_MESSAGE_TYPES = frozenset(
    {"PackITPackagingSpecification", "DocumentInfoRecord", "PackITPackagingCockpitMasterData"}
)


def _as_determination_dict(message: dict) -> dict:
    """`SINGLEMESSAGEBODY.DETERMINATION` -- the master node of a
    `PackITPackagingSpecification` payload, carrying the PS header beneath it.

    Absent by design on other Message Types: `PackITPackagingCockpitMasterData`
    has a wholly different body (`LABELDATA`, `SNR13_TANGO`, `PLANT_DATA`, ...)
    and `DocumentInfoRecord` another again. An empty dict is the right answer
    there -- every caller field is optional -- but a *present* `DETERMINATION`
    of the wrong shape is a payload we don't understand, and follows the same
    never-guess rule as `_as_objectkey_dict`.
    """
    body = message.get("SINGLEMESSAGEBODY")
    if not isinstance(body, dict):
        return {}
    determination = body.get("DETERMINATION")
    if determination is None:
        return {}
    if not isinstance(determination, dict):
        raise UnrecognizedPayloadShape(f"DETERMINATION is {type(determination).__name__}, not dict")
    return determination


def _strip(value: object) -> str | None:
    """Trim a payload string, mapping empty/absent/non-string to `None`.

    `ZACTCOUNTER` arrives space-padded (`" 2"`) and several DETERMINATION fields
    are present-but-empty (`SUPPLIER`, `PACKINDEX` on a 10-digit SNR10). Neither
    should reach a caller looking like a value.
    """
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _as_objectkey_dict(header: dict) -> dict:
    """`OBJECTKEY` is a dict for every known PackIT message type, but a plain
    full-text Splunk search can also surface unrelated message types (e.g.
    `MaterialBOM/TRS`, confirmed real) whose `OBJECTKEY` is a list of BOM
    line items instead. Never assume the dict shape -- surface it as
    unrecognized so the caller can skip it, rather than crash or guess.
    """
    objectkey = header.get("OBJECTKEY", {})
    if not isinstance(objectkey, dict):
        raise UnrecognizedPayloadShape(f"OBJECTKEY is {type(objectkey).__name__}, not dict")
    return objectkey


def _as_str(value: str | list[str] | None) -> str | None:
    if isinstance(value, list):
        return value[0] if value else None
    return value


@dataclass(frozen=True)
class Hop:
    """One processing attempt (Initial Trigger or Retrigger) for a Transfer."""

    message_id: str | None
    message_type: str
    host: str | None
    target_system: str | None
    time: str | None
    business_status: str | None  # "ERROR" | "SUCCESS" | None (undetermined at this stage)
    description: str | None
    ps_id: str | None
    dir_key: str | None
    plant: str | None
    det_type: str | None
    usage: str | None

    message_codes: tuple[str, ...] = ()
    """Structured SAP message codes (`Id/Number`) behind `description`.

    A machine key where `description` is prose. `/RB9X/PD4P_EAI/109` and
    `/RB9X/PD4P_EAI/009` are the only structural difference between two errors
    that behave very differently at the target -- see `_extract_message_codes`
    and the Reprocessing cadence entry in the triggers-and-hops topic."""

    supplier: str | None = None
    """`SUPPLIER` from `OBJECTKEY`.

    Part of the business object's identity, and on an inbound (RCPT)
    Determination Record it is what a Customer Index is on an outbound one --
    i.e. *which* supplier this packaging rule is for. It was not extracted at
    all until 2026-08-07, so "give me the object key details" answered without
    it on exactly the record type where it matters most."""

    dependent_ps_links: list[dict] | None = None
    envelope: str = "atom"  # "atom" | "plain_json"

    # --- Business-object identity, beyond PS_ID -------------------------------
    # PS_ID alone does not identify what replicated. Confirmed with the domain
    # owner: OBJECTKEY is the business object's key, and two of its fields carry
    # meaning the app previously discarded entirely.
    seqno: str | None = None
    """Which **Determination Record** of the PS this Transfer concerns -- a
    stable ID, each new record taking the next available number from source.
    A PS extended to another plant/index/supplier gains a new `SEQNO` while its
    structure (and `activation_counter`) is untouched, so "PS X is stuck" can be
    true of one Determination Record and false of every other."""

    activation_counter: str | None = None
    """`ZACTCOUNTER` -- the version of the PS structure, incremented on every
    change+activate and left alone by an extend. The Target System processes the
    newest counter, so an ERROR on a superseded one describes a version that has
    since been replaced. Whitespace-stripped: the raw value is space-padded
    (`" 2"`). See `pipeline.select_live_activations`."""

    # --- Determination body ---------------------------------------------------
    # SINGLEMESSAGEBODY.DETERMINATION is the master node of a PS payload, with
    # the PS header beneath it. Every field below is optional: Cockpit Master
    # Data carries a wholly different body and has no DETERMINATION at all.
    snr13: str | None = None
    """`MATNR_SNR13` -- the actual number the catalog's "10- or 13-digit number"
    errors are about. `MATNR` + `PACKINDEX`, or the bare 10-digit SNR10 when
    `PACKINDEX` is empty. An engineer cannot act on "the SNR13"; they act on
    `028100944104Y`."""

    matnr: str | None = None
    packindex: str | None = None
    packspec_status: str | None = None
    """`HEADER.STATUS` -- the PS's own status, a letter: `A` = Active, `N` = New,
    `DL` = deletion indicator.

    **Not** the same concept as TOPICSTRING's numeric code, despite the two
    moving together (corrected 2026-08-08). That numeric segment is the
    *Determination Record's* Workflow Status -- `60` Accepted, `35`/`37` VitAA
    waits -- on a different object. They correlate because a PS goes Active when
    its Determination Record is Accepted. See the packaging-specification
    knowledge topic."""

    change_number: str | None = None
    """`AENNR`. On the normal replication path this is the constant
    `00000001` and says nothing.

    It earns its place only in combination with `activation_counter`:
    `00000002` with an **empty** counter is a PS replicated to PT0 for
    aftermarket approval *before it was ever activated*. Without it that
    record reads as an ordinary failure, when in fact nothing has gone wrong
    and no activation has happened yet."""

    ps_group: str | None = None
    sales_channel: str | None = None
    """`PACK_USAGE` -- real values are `OE`, `OES`, `IAM`.

    **Not** `LABEL_SALESCHANL`, which this read until 2026-08-06 and which is
    a different field entirely: it is empty on every inbound (RCPT) record
    while `PACK_USAGE` is populated on all 254 records in the corpus and
    agrees with the `TOPICSTRING` Sales Channel segment every time. The SAP
    field carrying Sales Channel really is called `PACK_USAGE`; the separate
    Usage concept (Regular/Alternative) is `ABRVW`. See `CONTEXT.md`.
    """

    document_links: list[dict] | None = None
    """`DOCUMENT_LINKS` -- the PS -> Document Info Record edge, each entry the
    same four-part key `_compute_dir_key` builds. This is how a PS's DIRs are
    found; Message ID cannot do it, being per trigger *per message type*."""


@dataclass(frozen=True)
class TransferRecord:
    """One Message ID's full processing history to one Target System,
    chronologically ordered.

    A Message ID is not always a 1:1 key for a Transfer -- confirmed live
    (three independent real examples) that a single Message ID can fan out
    to more than one Target System, each with its own independent hop chain
    and independent outcome (e.g. resolved on one target, still failing on
    another). `group_transfers` keys each `TransferRecord` by
    (message_id, target_system) for exactly this reason -- grouping by
    message_id alone would silently collapse two real, independent outcomes
    into whichever one happened to sort chronologically last.
    """

    message_id: str
    message_type: str
    ps_id: str | None
    dir_key: str | None
    target_system: str | None
    hops: list[Hop]  # earliest first

    @property
    def latest(self) -> Hop:
        return self.hops[-1]

    @property
    def earliest(self) -> Hop:
        return self.hops[0]

    @property
    def current_status(self) -> str | None:
        return self.latest.business_status

    @property
    def current_description(self) -> str | None:
        return self.latest.description

    def identity(self, field: str) -> str | None:
        """First non-`None` value of `field` across this Transfer's hops.

        Identity and DETERMINATION fields describe the business object, not the
        attempt, so any hop that carries one carries the same one -- but not
        every hop carries them. `.latest` is specifically the wrong place to
        look: the shared `SOLACE` broker hop and pre-consumption hops are
        attached to every target group (see `group_transfers`), so a Transfer's
        newest hop can easily be the one with the least detail.
        """
        return next((value for hop in self.hops if (value := getattr(hop, field, None)) is not None), None)

    @property
    def snr13(self) -> str | None:
        return self.identity("snr13")

    @property
    def seqno(self) -> str | None:
        return self.identity("seqno")

    @property
    def activation_counter(self) -> str | None:
        return self.identity("activation_counter")

    @property
    def document_links(self) -> list[dict]:
        return self.identity("document_links") or []

    @property
    def document_link_keys(self) -> tuple[str, ...]:
        """The linked Document Info Records, each rendered as the same
        four-part key `_compute_dir_key` builds, so a link the PS *declares*
        and a DIR Transfer actually *found* are directly comparable.

        A tuple rather than a list because the summary layer hoists shared
        values through a set, and because the empty case is meaningful: `()`
        says this PS declares no linked documents, which is a fact worth
        stating (a DIR trigger is optional), not missing information.
        """
        return tuple(
            key
            for link in self.document_links
            if isinstance(link, dict)
            and (
                key := _compute_dir_key(
                    link.get("DOCUMENT_TYPE"),
                    link.get("DOCUMENT_NUMBER"),
                    link.get("DOCUMENT_PART"),
                    link.get("DOCUMENT_VERSION"),
                )
            )
        )


def _derive_target_system(host: str | None, message_type: str) -> str | None:
    """Strip `CPI_{source}_` and `_CONSUMING` to get the Target System.

    Does not apply to `DocumentInfoRecord`, whose hosts are content-server
    names (`STCENxxx_PUBLISHING`) with no Target System concept at all --
    confirmed live, see transform TECHNICAL_SPEC.md fact 6.
    """
    if host is None or host == "SOLACE" or message_type == "DocumentInfoRecord":
        return None
    match = _CONSUMING_HOST_RE.match(host) or _CPI_PUBLISH_HOST_RE.match(host)
    return match.group("target") if match else None


def _compute_dir_key(document_type: str | None, document_number: str | None, document_part: str | None, document_version: str | None) -> str | None:
    """`DocumentInfoRecord`'s own identifying key: Document Type + Document
    Number + Document Part + Document Version, distinct from the PS's own key
    -- see `agents/packspec_status/knowledge/document-info-record.md`.

    A DIR's `OBJECTKEY` carries no PS_ID, which is why the key is built from
    the document's own four fields. That is *not* the same as the DIR carrying
    no PS at all: it does, in a link array beside the key --
    `SINGLEMESSAGEBODY.OBJECTLINKSPACKITPACKSPEC` pre-consumption and
    `DocumentMessageRoot.hasPackItPackagingSpecificationLink` published
    (confirmed 2026-08-06 from a real capture, correcting an earlier claim
    here that no PS field existed at either stage). There is no `SEQNO` in it
    -- a DIR names the PS and the scope, never one Determination Record --
    so the document's own four fields remain the only always-present
    identifier for the record itself.
    """
    if not document_type or not document_number:
        return None
    return f"{document_type}-{document_number}-{document_part or '000'}-{document_version or '00'}"


def _strip_message_type(source: str | None) -> str | None:
    """Splunk's `source` field sometimes carries a `Native/` prefix depending
    on hop stage (confirmed live) -- always take the last path segment.
    """
    if not source:
        return source
    return source.rsplit("/", 1)[-1]


def _extract_ret_msgs(entry: ET.Element) -> list[str]:
    """Non-empty `Message` values from the inline-expanded `Ret_msgs` feed.

    `Ret_msgs` is an OData navigation property, inline-expanded via
    `<link rel=".../Ret_msgs"><m:inline><feed>...`. That `<link>` appears
    *before* `<content>` in standard Atom entry ordering, so it must be
    found explicitly by relation -- a bare `.//m:properties` search would
    return the *first* nested `ReturnMsg`'s properties in document order,
    not the outer entry's own (this cost real debugging time to discover).
    """
    messages: list[str] = []
    for link in entry.findall("a:link", _ATOM_NS):
        if "Ret_msgs" not in (link.get("rel") or ""):
            continue
        inline = link.find("m:inline", _ATOM_NS)
        feed = inline.find("a:feed", _ATOM_NS) if inline is not None else None
        if feed is None:
            continue
        for msg_entry in feed.findall("a:entry", _ATOM_NS):
            props = msg_entry.find("a:content/m:properties", _ATOM_NS)
            if props is None:
                continue
            message_el = props.find("d:Message", _ATOM_NS)
            if message_el is not None and message_el.text:
                messages.append(message_el.text)
    return messages


def _extract_message_codes(entry: ET.Element) -> list[str]:
    """The structured SAP message codes from the `Ret_msgs` feed, as `Id/Number`.

    Parsed alongside `Message` since the beginning and then discarded, which
    left free error *text* as the only thing anything could classify on -- and
    text is exactly what the catalog's regexes already have to fight with.

    The code is what actually distinguishes two errors that look alike:
    `/RB9X/PD4P_EAI/109` ("SNR13 not found/ Mark for deletion") against
    `/RB9X/PD4P_EAI/009` ("... Packaging material doesn't exist in plant ..."),
    identical in `Type` and `Id` and in their catalog category, but with very
    different target reprocessing behaviour -- minutes apart versus once a day.
    See the Reprocessing cadence entry in the triggers-and-hops knowledge topic.

    Only `Type == "E"` rows are kept: the feed also carries blank padding rows
    (`Type` empty, `Number` `000`) that are not messages at all.
    """
    codes: list[str] = []
    for link in entry.findall("a:link", _ATOM_NS):
        if "Ret_msgs" not in (link.get("rel") or ""):
            continue
        inline = link.find("m:inline", _ATOM_NS)
        feed = inline.find("a:feed", _ATOM_NS) if inline is not None else None
        if feed is None:
            continue
        for msg_entry in feed.findall("a:entry", _ATOM_NS):
            props = msg_entry.find("a:content/m:properties", _ATOM_NS)
            if props is None:
                continue
            fields = {name: (props.find(f"d:{name}", _ATOM_NS)) for name in ("Type", "Id", "Number")}
            values = {name: (el.text or "").strip() if el is not None else "" for name, el in fields.items()}
            if values["Type"] != "E" or not values["Id"]:
                continue
            codes.append(f"{values['Id']}/{values['Number']}" if values["Number"] else values["Id"])
    return codes


def _ps_id_from_dependent_links(links: object) -> str | None:
    """The PS a `DocumentInfoRecord` names, at the pre-consumption stage.

    A DIR's `OBJECTKEY` is purely the document's own key, so without this a
    DIR hop knows nothing about the Packaging Specification it belongs to --
    and `SOLACE` is where the overwhelming majority of DIR events sit
    (236,405 against 9,075 at the `STCENxxx_PUBLISHING` stage, measured over
    30 days on 2026-08-07), so this is the common case, not an edge one.

    Returns `None` for an `L01` document, whose link array is empty because
    it points at a Workstep instead -- normal, not a failure.
    """
    if not isinstance(links, list) or not links or not isinstance(links[0], dict):
        return None
    return _strip(links[0].get("PS_ID"))


def _parse_atom_hop(raw: str, message_type: str, host: str | None, time: str | None) -> Hop:
    # ET.ParseError must propagate uncaught past this function -- parse_hop()
    # relies on it to detect "not Atom" and fall back to plain-JSON parsing.
    entry = ET.fromstring(raw)

    try:
        # The outer entry's own properties live at entry/content/m:properties
        # -- never a bare './/m:properties' (see _extract_ret_msgs docstring).
        props = entry.find("a:content/m:properties", _ATOM_NS)
        if props is None:
            raise UnrecognizedPayloadShape("Atom entry missing content/m:properties")

        uuid_el = props.find("d:Uuid", _ATOM_NS)
        message_id = uuid_el.text if uuid_el is not None else None

        business_status_el = props.find("d:BusinessStatus", _ATOM_NS)
        business_status = business_status_el.text if business_status_el is not None else None

        payload_el = props.find("d:Payload", _ATOM_NS)
        payload = json.loads(payload_el.text) if payload_el is not None and payload_el.text else {}

        ps_id = plant = det_type = usage = dir_key = supplier = None
        seqno = activation_counter = change_number = None
        snr13 = matnr = packindex = packspec_status = ps_group = sales_channel = None
        document_links = None
        if "SINGLEMESSAGES" in payload:
            message = payload["SINGLEMESSAGES"][0]
            header = message["SINGLEMESSAGEHEADER"]
            objectkey = _as_objectkey_dict(header)
            ps_id = objectkey.get("PS_ID")
            plant = objectkey.get("WERKS")
            det_type = objectkey.get("DETTYPE")
            usage = objectkey.get("ABRVW")
            supplier = _strip(objectkey.get("SUPPLIER"))
            seqno = _strip(objectkey.get("SEQNO"))
            activation_counter = _strip(objectkey.get("ZACTCOUNTER"))

            # AENNR is read only for what it says *together with* the
            # activation counter. On the normal replication path it is the
            # constant 00000001 (the active revision) and discriminates
            # nothing -- an earlier comment here concluded from that it never
            # needed reading at all, and cited "00000002 never reaches
            # replication data". That is false: a VITAA/PT0-bound Transfer
            # replicates the PS *before* it is Active, and carries
            # AENNR 00000002 with an EMPTY ZACTCOUNTER (confirmed against
            # PS 00000000040001498023 in tests/fixtures/
            # multi_target_fanout_page.xml, whose two halves five days apart
            # show 00000002/"" at PT0 then 00000001/"1" once activated).
            # That pair is the only signal distinguishing "sitting at
            # aftermarket approval, never activated" from "nothing found".
            change_number = _strip(objectkey.get("AENNR"))

            determination = _as_determination_dict(message)
            snr13 = _strip(determination.get("MATNR_SNR13"))
            matnr = _strip(determination.get("MATNR"))
            packindex = _strip(determination.get("PACKINDEX"))
            sales_channel = _strip(determination.get("PACK_USAGE"))
            links = determination.get("DOCUMENT_LINKS")
            document_links = links if isinstance(links, list) else None
            ps_header = determination.get("HEADER")
            if isinstance(ps_header, dict):
                packspec_status = _strip(ps_header.get("STATUS"))
                ps_group = _strip(ps_header.get("PS_GROUP"))
        elif "DocumentMessageRoot" in payload:
            # DIR's published-stage shape -- confirmed real, camelCase fields.
            # No confirmed status field here yet (transform TECHNICAL_SPEC.md's
            # open gap), but the DIR key itself is reliably present.
            dmr = payload["DocumentMessageRoot"]
            dir_key = _compute_dir_key(
                dmr.get("documentType"), dmr.get("documentNumber"), dmr.get("documentPart"), dmr.get("documentVersion")
            )
            plant = (dmr.get("hasResponsibilityData") or {}).get("hasPlant")

            # The DIR names its PS here, and this is the *authoritative*
            # direction of that edge: a PS's own DOCUMENT_LINKS is only a
            # snapshot of what was linked when that PS trigger was built, and
            # a document attached later never refreshes it. Confirmed real
            # (screenshots/dependentObjects/DocumentInfoRecord). Reading it
            # is what lets a DIR hop answer "which PS is this document for".
            #
            # An `L01` document links to a Workstep instead, leaving this
            # array empty -- confirmed against splunkExamples/example7 -- so
            # absence here is normal, not a parse failure.
            ps_links = dmr.get("hasPackItPackagingSpecificationLink")
            if isinstance(ps_links, list) and ps_links and isinstance(ps_links[0], dict):
                ps_id = _strip(ps_links[0].get("hasPackagingSpecification"))
                activation_counter = _strip(ps_links[0].get("activationCounter"))
                change_number = _strip(ps_links[0].get("activationStatusIndicator"))
                plant = plant or _strip(ps_links[0].get("hasPlant"))
    except (json.JSONDecodeError, KeyError, IndexError) as exc:
        # Truncated/malformed Payload JSON or an unexpected SINGLEMESSAGES
        # shape (e.g. an empty array) -- surface as the one documented
        # exception type rather than leaking a low-level parsing exception
        # to callers, confirmed necessary by direct parse_hop() fuzz testing.
        raise UnrecognizedPayloadShape(f"malformed Atom payload: {exc}") from exc

    description = "\n".join(_extract_ret_msgs(entry)) or None
    message_codes = tuple(_extract_message_codes(entry))

    return Hop(
        message_id=message_id,
        message_type=message_type,
        host=host,
        target_system=_derive_target_system(host, message_type),
        time=time,
        business_status=business_status,
        description=description,
        message_codes=message_codes,
        ps_id=ps_id,
        dir_key=dir_key,
        plant=plant,
        det_type=det_type,
        usage=usage,
        supplier=supplier,
        dependent_ps_links=None,
        envelope="atom",
        seqno=seqno,
        activation_counter=activation_counter,
        snr13=snr13,
        matnr=matnr,
        packindex=packindex,
        packspec_status=packspec_status,
        change_number=change_number,
        ps_group=ps_group,
        sales_channel=sales_channel,
        document_links=document_links,
    )


def _parse_plain_json_hop(raw: str, message_type: str, host: str | None, time: str | None) -> Hop:
    if message_type not in _KNOWN_MESSAGE_TYPES:
        # A broad full-text search can surface unrelated message types (e.g.
        # "MaterialBOM/TRS", confirmed real) that happen to match a search
        # term elsewhere in their payload -- never guess at their shape.
        raise UnrecognizedPayloadShape(f"unrecognized message type: {message_type!r}")

    try:
        payload = json.loads(raw)
        if "SINGLEMESSAGES" not in payload:
            raise UnrecognizedPayloadShape("plain-JSON payload missing SINGLEMESSAGES")

        message = payload["SINGLEMESSAGES"][0]
        header = message["SINGLEMESSAGEHEADER"]
        objectkey = _as_objectkey_dict(header)

        body = message.get("SINGLEMESSAGEBODY") or {}
        dependent_ps_links = body.get("OBJECTLINKSPACKITPACKSPEC")

        # Same DETERMINATION body as the Atom path -- a pre-consumption hop
        # carries the full payload too, it just has no BusinessStatus yet. Read
        # it here as well so a Transfer whose only hops are pre-consumption
        # still knows its own SNR13 and identity.
        determination = _as_determination_dict(message)
        ps_header = determination.get("HEADER")
        ps_header = ps_header if isinstance(ps_header, dict) else {}
        links = determination.get("DOCUMENT_LINKS")

        dir_key = None
        if message_type == "DocumentInfoRecord":
            dir_key = _compute_dir_key(
                objectkey.get("DOCUMENTTYPE"),
                objectkey.get("DOCUMENTNUMBER"),
                objectkey.get("DOCUMENTPART"),
                objectkey.get("DOCUMENTVERSION"),
            )
    except (json.JSONDecodeError, KeyError, IndexError) as exc:
        # Truncated JSON or an unexpected SINGLEMESSAGES shape (e.g. an empty
        # array) -- surface as the one documented exception type, confirmed
        # necessary by direct parse_hop() fuzz testing.
        raise UnrecognizedPayloadShape(f"malformed plain-JSON payload: {exc}") from exc

    return Hop(
        message_id=header.get("MESSAGEID"),
        message_type=message_type,
        host=host,
        target_system=_derive_target_system(host, message_type),
        time=time,
        business_status=None,  # pre-consumption hops carry no status yet
        description=None,
        ps_id=objectkey.get("PS_ID") or _ps_id_from_dependent_links(dependent_ps_links),
        dir_key=dir_key,
        plant=objectkey.get("WERKS"),
        det_type=objectkey.get("DETTYPE"),
        usage=objectkey.get("ABRVW"),
        supplier=_strip(objectkey.get("SUPPLIER")),
        dependent_ps_links=dependent_ps_links,
        envelope="plain_json",
        seqno=_strip(objectkey.get("SEQNO")),
        activation_counter=_strip(objectkey.get("ZACTCOUNTER")),
        snr13=_strip(determination.get("MATNR_SNR13")),
        matnr=_strip(determination.get("MATNR")),
        packindex=_strip(determination.get("PACKINDEX")),
        packspec_status=_strip(ps_header.get("STATUS")),
        change_number=_strip(objectkey.get("AENNR")),
        ps_group=_strip(ps_header.get("PS_GROUP")),
        sales_channel=_strip(determination.get("PACK_USAGE")),
        document_links=links if isinstance(links, list) else None,
    )


def parse_hop(result: RawResult) -> Hop:
    """Parse one raw Splunk result into a `Hop`.

    Envelope shape is determined by hop stage, not by Message Type -- try
    Atom/OData first (the Target-processed shape), fall back to plain JSON
    (the pre-consumption shape) on XML parse failure. See transform
    TECHNICAL_SPEC.md fact 2 for why this dispatch is stage-based, not
    Message-Type-based.

    Raises only `UnrecognizedPayloadShape` on any malformed or unrecognized
    input (confirmed by direct fuzz testing: truncated JSON, an empty
    `SINGLEMESSAGES` array, and a non-dict `OBJECTKEY` all previously leaked
    raw `json.JSONDecodeError`/`KeyError`/`IndexError` to callers of this
    function specifically, even though `group_transfers` already handled
    them) -- safe to call directly, not just via `group_transfers`.
    """
    message_type = _strip_message_type(_as_str(result.get("source"))) or ""
    host = _as_str(result.get("host"))
    time = _as_str(result.get("_time"))
    raw = result.raw()

    try:
        return _parse_atom_hop(raw, message_type, host, time)
    except ET.ParseError:
        return _parse_plain_json_hop(raw, message_type, host, time)


def group_transfers(results: list[RawResult]) -> list[TransferRecord]:
    """Parse and group raw results into `TransferRecord`s by (Message ID,
    Target System).

    Message ID is confirmed stable across an entire retry chain (generated
    once at Source System publish time; a Retrigger reuses it) -- see
    CONTEXT.md's Message ID entry. Hops within a Transfer are sorted
    chronologically; `.latest` gives the current Replication Status.

    Grouping is NOT by Message ID alone -- confirmed live (three independent
    real examples) that one Message ID can fan out to more than one Target
    System with independent outcomes; see `TransferRecord`'s docstring.
    Hops with no determinable target (the shared `SOLACE` broker hop, or any
    pre-consumption hop for a Message Type with no Target System concept at
    all, e.g. `DocumentInfoRecord`) are attached to every target-specific
    group sharing that Message ID, since they're shared context for however
    many targets that message eventually reaches -- if there's only ever
    one target (or none, as for DIR), this produces exactly one
    `TransferRecord`, unchanged from before.

    Any payload shape that doesn't match a known pattern is skipped, not
    guessed at -- callers that need to know about skipped rows should
    inspect `results` vs. the returned records' hop counts themselves.
    """
    hops_by_message_id: dict[str, list[Hop]] = {}
    for result in results:
        try:
            hop = parse_hop(result)
        except UnrecognizedPayloadShape:
            continue
        if hop.message_id is None:
            continue
        hops_by_message_id.setdefault(hop.message_id, []).append(hop)

    records = []
    for message_id, hops in hops_by_message_id.items():
        targeted = [h for h in hops if h.target_system is not None]
        untargeted = [h for h in hops if h.target_system is None]
        target_systems = sorted({h.target_system for h in targeted}) if targeted else [None]

        for target_system in target_systems:
            group_hops = sorted(
                untargeted + [h for h in targeted if h.target_system == target_system],
                key=lambda h: h.time or "",
            )
            records.append(
                TransferRecord(
                    message_id=message_id,
                    message_type=group_hops[-1].message_type,
                    ps_id=group_hops[-1].ps_id,
                    dir_key=group_hops[-1].dir_key,
                    target_system=target_system,
                    hops=group_hops,
                )
            )
    return records
