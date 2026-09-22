Additional Routing: the target was never configured to receive it

Fixture basis (the frozen facts every expectation here rests on):
PS 00000000040001253724 really exists at plant 0110 / SHIP and reached SAPP870110. Asking about it at SAPP790110 finds nothing there, so the pipeline broadens the search, resolves plant 0110 / SHIP, and queries the frozen routing plan, which returns SAPP870110 only. Expected RoutingCheck: requested_target_was_configured=False, configured_target_systems=('SAPP870110',). harness._not_found_answer then states this deterministically, regardless of the model's own wording.
