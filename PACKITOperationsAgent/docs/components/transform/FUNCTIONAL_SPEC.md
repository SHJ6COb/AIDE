# transform — Functional Specification

## Purpose

Turn Splunk's raw, technical event records (SAP Gateway XML/JSON, one row per log hop) into the same clean, per-transfer picture the "Productive PackIT" dashboard shows: one row per Message ID, its latest status, a human-readable description of what happened, and the key business fields (which PS, which plant, which determination type, etc.) — reliably and consistently, every time.

## What "reliable" means here

If this component doesn't recognize the shape of what it's been given, it says so loudly (an error) rather than guessing at a plausible-looking answer. Every rule it applies — how to pick which of several log hops is the "latest" one, how to classify a status, how to extract the product/plant/etc. — is backed by a real, confirmed example, not an assumption.
