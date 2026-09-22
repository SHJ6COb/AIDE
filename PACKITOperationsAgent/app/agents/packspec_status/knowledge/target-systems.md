---
concept: target-systems
summary: What a Target System does with a payload, which systems exist, and what each renders.
loads_when: has_target_system
---

**Target System**:
A downstream R/3 or S/4 system that receives a Packspec Payload, validates it, and — on success — renders it into artifacts that differ by system capability. An R/3 Target System (no EWM module) renders Packaging Instructions and a CS03 BOM only. An S/4 Target System with EWM (current instances: P1M, Q1M, C1M, X1M) renders a PackSpec object — the same `/SCWM/PACKSPEC` model PACKIT itself wraps in the Source System — *in addition to* Packaging Instructions and a CS03 BOM; the two aren't alternatives, an S/4-EWM target gets both. On validation failure, an error is thrown back instead.
_Avoid_: Assuming every Target System renders the same set of objects — whether a PackSpec object exists downstream at all depends on whether that system has the EWM module.

**POE**:
A specific, major R/3 Target System, deliberately kept as PACKIT's "always available" system: it hosts a custom Cockpit data model (see that entry) that's the actual data source for the Cockpit app on PXG (see PXG). Being migrated to S/4 P1M in phases, one subset of plants per phase — see Import Configuration for what changes, per plant, once a plant migrates.

**PXG**:
The Fiori Launchpad system hosting the Cockpit app that shopfloor users log into to view Packaging Specification/Dependent Object data. Reads its data from POE's Cockpit data model (see POE, Cockpit data model) — not from whichever system currently does the "real" PackSpec/Packaging Instructions/CS03 BOM processing for a given plant, which can be a different system after migration.

**Cockpit data model**:
A custom data model maintained in POE, replicating the `/SCWM` PackSpec object model and its Dependent Object data models, purpose-built to power the Cockpit app on PXG (see POE, PXG). Populated from the `PackITPackagingCockpitMasterData` Message Type's payload — distinct from Packaging Cockpit Master Data (the Dependent Object/payload itself, see that entry), which is what arrives; the Cockpit data model is where it's stored and rendered in POE specifically for the Fiori app, independent of whether POE is still that plant's real PackSpec/Packaging Instructions/CS03 BOM processing system.

**Packaging Instructions**:
A Target System artifact rendered from a validated Packspec Payload, alongside the CS03 BOM.
**A PI is generated *by the target*, and its number is not the material number** — confirmed 2026-08-07. Its number is **SNR13 + a two-letter form code + the supplier without leading zeros**, and **one trigger routinely creates more than one**, differing only in that form code. Confirmed on two independent captures:

| capture | SNR13 | supplier | PIs created |
|---|---|---|---|
| `example10` | `F00SC01107` | `0000131512` | `F00SC01107FA131512`, `F00SC01107FB131512` |
| `example3` | `F00C2G8057` | `0000018740` | `F00C2G8057BA18740`, `F00C2G8057BB18740` |

So every PI of one PS shares a long prefix with the SNR13 *and* with its siblings — which is precisely why truncating one is easy and destructive.
_Avoid_: Calling the SNR13 "the PI". They share a prefix, which is exactly why it is easy to truncate one into the other — an answer that reported "PI F00SC01107" named the material and dropped the part that identifies the actual Packaging Instruction, leaving nothing an engineer could look up. Quote the PI number as it appears in the Status Description, in full.

**CS03 BOM**:
A standard SAP Material Bill of Material (viewed via transaction CS03) created in a Target System from a rendered Packspec Payload. A genuinely separate object from the Packaging Specification it originated from — related by data lineage, not identity.

**PSTE**:
A 15-digit derived material number built from the 10-digit product number, an index, and a "PS" suffix (confirmed real format: `0123456789-100PS`). Distinct from both the 10-digit product number (SNR10) and the 13-digit material number (SNR13) it's derived from. Its own BOM (the "PSTE 15 digit BOM") is created/changed as part of a Target System's CS03 BOM processing, layered on top of the material's own 13-digit BOM once that already exists — confirmed live in real success-path Status Description text on both an R/3 target ("Since SNr13 digit BOM exist, Change Initiated to include SNr15 (PSTE) BOM in it!", "Creating BOM for material 0265.025.049-B7LPS", "PSTE 15 digit BOM Creation Initiated") and an S/4-EWM target ("PSTE Material ... added to FERT Bom"). Also carries its own plant-specific status that can independently block processing (confirmed real via the error catalog's "Material status 50 'Invalid'/'Blocked' is not selected for BOM item" rows).
_Avoid_: Assuming PSTE stands for something confirmed — only its numbering shape and BOM behavior are confirmed, not what the acronym expands to.

**Import Configuration**:
A per-plant/per-connection configuration maintained on a Target System — also called "Interface Settings," the same layer the error catalog's rows 8/9/10/34 concern (e.g. "Relevant Import Config not maintained"). Does plant mapping, and decides which objects actually get created from a received payload for that plant. Distinct from whether a PackSpec object can exist at all — that's structural, gated by EWM module presence (see Target System) — Import Configuration decides object creation *within* what a given Target System is structurally capable of. Confirmed real via the POE→P1M phased migration (see POE): once a plant moves, the losing system's Import Configuration for that plant is narrowed to maintain only Cockpit Master Data — DIR, Packaging Instructions, and CS03 BOM stop being created there for that plant, permanently, even though Additional Routing keeps sending it all three Message Types for that plant unchanged.
