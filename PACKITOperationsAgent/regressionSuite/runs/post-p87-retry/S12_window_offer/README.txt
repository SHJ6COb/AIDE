No window given: offer concrete widths, then honour the reply

Fixture basis (the frozen facts every expectation here rests on):
The corpus newest event sits 20 minutes before the run, so an unqualified question always hits the 15-minute default and finds nothing. PS 00000000040001253724 is found at -24h with SNR13 028100944104Y at SAPP870110. The reply to the offer is a bare fragment (24 hours) naming no PS, so harness._resolve_window_reply rewrites it back into the original question in code rather than leaving turn 1 to re-resolve the reference.
