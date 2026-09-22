Underspecified and off-topic questions must never reach production data

Fixture basis (the frozen facts every expectation here rests on):
harness._is_underspecified blocks any search with no self-sufficient field, no free-text term, and fewer than two identifying fields (or one plus status). 'Show me all errors' is status-only and must be blocked; 'failed transfers to SAPP870110' is target+status and must be allowed, returning PS 00000000040001253724's ERROR record.
