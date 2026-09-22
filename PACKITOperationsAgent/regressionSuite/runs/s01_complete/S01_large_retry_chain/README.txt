The 3.4 MB payload: one Message ID retried 100 times

Fixture basis (the frozen facts every expectation here rests on):
splunkExamples/example5/payload5 -- 100 Splunk rows, all one Message ID (0EBD9DC62D031FD0AEE11FCC94BF566A) to one target. Groups to exactly 1 TransferRecord: PS 00000000040001253724, target SAPP870110, plant 0110, SHIP, usage R, status ERROR, description 'SNR13 not found/ Mark for deletion', hop_count 100, spanning ~8h. Catalog: row 2, Target Error, responsible Plant.
