# packspec-status agent — Functional Specification

## What it does

An internal Bosch user (a packaging engineer, brand/product manager, or supply chain ops person) asks, in plain language, about the status of a Packaging Specification — e.g. "what's the status of PS 400001438900", "why did this shipment's packaging fail", "is anything blocking PS X at plant 0780". The agent:

1. Figures out what's actually being asked (which PS, which plant, which kind of transaction).
2. Looks up its current Replication Status — whether it made it through Bosch's PDMI/Solace pipeline into the target SAP system(s) — and, if it's stuck on a Dependent Object, says so.
3. If there's an error, explains what it means in plain language.
4. If there's a **documented, known fix** for that error, says what it is and who's responsible for it (the plant, or a support team).
5. If there's **no documented fix**, says so honestly rather than guessing, and tells the user to raise a support ticket.

## What it explicitly does not do (for this slice)

- It doesn't check Workflow Status (the SAP approval stage) — only Replication Status (the post-approval data-flow stage). Workflow Status is a separate, later capability.
- It doesn't take any action on the user's behalf — no retriggering transfers, no editing records, no filing tickets automatically. It's read-only and informational. Automatically filing an mServiceHub ticket is a stated future goal, not this slice.
- It never invents a plausible-sounding fix that isn't backed by the internal Docupedia troubleshooting document. If it doesn't know, it says so.

## Who it's for

Internal staff only — packaging engineers, brand/product managers, supply chain ops. Not external vendors, suppliers, or customers.

## Example interaction

> **User**: What's happening with PS 400001438900 at plant 0780?
>
> **Agent**: PS 400001438900 (SHIP, plant 0780) failed with a Business Error: the packaging material (6000.409.798) has an invalid plant status in the target system. Per the documented fix, the Plant team needs to change that material's plant status to 40 (valid) — or use a different packaging material in the spec. If the status is actually correct as-is, the Determination Record should be deleted instead.

> **User**: Why is this other PS stuck?
>
> **Agent**: I don't have a documented fix for that specific error message. Please raise a ticket via mServiceHub so the support team can investigate.
