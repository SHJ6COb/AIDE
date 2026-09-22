# splunk-client — Functional Specification

## Purpose

Given a set of search criteria (a PS ID, a plant, a time range, etc.), retrieve the matching raw event records from the Splunk index that backs the "Productive PackIT Overview" dashboard — the same data an end user could find by using that dashboard themselves, but reachable programmatically so the agent can reason over it.

## What it doesn't do

It doesn't interpret or summarize the results — that's the `transform` component's job. This component's only responsibility is: given criteria, return the matching raw data, reliably and without silently dropping or misrepresenting anything Splunk returned.
