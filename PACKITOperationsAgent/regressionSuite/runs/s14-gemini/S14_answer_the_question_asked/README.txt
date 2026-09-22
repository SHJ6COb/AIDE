Six failures then a success: report the history, name the PI, don't volunteer

Fixture basis (the frozen facts every expectation here rests on):
PS 00000000040000348796 (splunkExamples/example10), captured after the live app answered four questions about it wrongly. Its PackITPackagingSpecification Transfer to SAPP870110 has 11 hops: 6 consecutive ERRORs (6099.801.262 Packaging material doesn't exist in plant 5550, daily 29 Jul - 3 Aug) then a SUCCESS on 4 Aug creating PIs F00SC01107FA131512 and F00SC01107FB131512. It ALSO reached SAPPOE0110, which the live answer missed entirely. It is RCPT, supplier 0000131512. A DocumentInfoRecord for it exists in Splunk even though the PS's own DOCUMENT_LINKS is empty -- so 'there are no linked DIRs for this PS' is not merely noise, it is false.

11 hops sits just under harness._MAX_HOPS_SERIALIZED, so the hop history IS in the payload. Every check below is answerable from data the app already holds.
