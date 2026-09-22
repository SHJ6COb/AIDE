Dependent-object branch: 48 failing transfers, nothing to find underneath

Fixture basis (the frozen facts every expectation here rests on):
splunkExamples/example6/payload6 -- PS 00000000040001497551, target SAPPOE0110, plant 929P, SHIP. 48 separate Message IDs, all ERROR, all 'Cockpit master data dependent object still in progress'. Catalog row 57 (Source Error) is a dependent-object-blocking row, so the pipeline fires two extra searches (DocumentInfoRecord + PackITPackagingCockpitMasterData). The corpus contains NO such records for this PS, so both dependent-object lists come back EMPTY -- which per the pipeline's own docstring is a real, informative answer (check the Source system), not a lookup failure.
