# catalog — Functional Specification

## Purpose

When a Packaging Specification's transfer fails, look up whether Bosch's internal PackIT troubleshooting documentation ("PackIT (PD7) Interface Error - General Hints to resolve") already has a known cause and fix for that exact error — and if so, surface it (including who's responsible for acting on it: the plant, or a support team). If there's no documented answer, say so plainly rather than guessing, and point the user to raise a support ticket.

## Why this matters

This is what separates the agent from just re-displaying the Splunk dashboard: the dashboard shows *that* something failed and the raw error text; this component is what lets the agent explain *why* and *what to do about it*, grounded in real internal knowledge rather than invented plausible-sounding advice.
