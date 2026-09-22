Do we have a DIR linked to this PS -- answered from the payload, not a search

Fixture basis (the frozen facts every expectation here rests on):
Written after a real live-app session asked exactly this and the app could not answer. DOCUMENT_LINKS was parsed off the PS payload but only ever surfaced inside dependent_objects, which is populated only when the PS is dependent-object-blocked on an xOE target -- so for any ordinary PS the app held the answer and could not say it. PS 00000000040000434427 declares TWO linked DIRs: PAC-0000000000000000001627019-FRE-00 and PAC-0000000000000000001507973-ARC-00. PS 00000000040001253724 declares NONE, which is normal -- a DIR trigger is optional even on the xOE line.
