A target system named the way people say it, and a filter that cannot be applied

Fixture basis (the frozen facts every expectation here rests on):
Caught live 2026-08-07. 'the latest successful transfer to target system P87' had target_system validated to None by _TARGET_SYSTEM_RE's 6-character minimum, so the host= clause vanished from the SPL entirely, the search covered every system, and the answer confidently named SAPPT00110 -- a system the user never asked about. It also took four minutes, because an unscoped search full-text matching BusinessStatus across seven days is a far heavier query. domain.resolve_target_system now maps P87 -> SAPP870110 before validation, and any value that still cannot be resolved stops the search rather than being dropped from it.
