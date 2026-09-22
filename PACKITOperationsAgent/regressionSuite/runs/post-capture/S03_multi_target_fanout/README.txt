One Message ID, two targets, two different outcomes

Fixture basis (the frozen facts every expectation here rests on):
splunkExamples/example1/payload -- PS 00000000040000434427, plant 0780, SHIP, usage A1, fans out to TWO targets with materially different descriptions:
  SAPP720110 : 'T141 Bom item status Invalid for material 6000.409.798 in plant 0780'
  SAPPOE0110 : 'T141 Bom item status Invalid for material 6000.409.798 in plant 078W\nCockpit Data Model Updated'
Both ERROR. Catalog row 15 (Target Error, responsible Plant) matches both.
