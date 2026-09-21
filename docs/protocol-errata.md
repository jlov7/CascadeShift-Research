# Historical v1 protocol notes

This page records limits in the historical v1 material. It does not amend the archive, the original protocol, or the reported arithmetic.

- The completed archive used a single protocol seed for candidate enumeration and selection rather than the child-seed derivation described in the original protocol.
- Deduplication left ten distinct operator kinds rather than twelve.
- The freeze manifest does not record the Python interpreter used for the historical evaluation.
- The study ran conditions in fixed C0, C1, C2 order, and the provider did not support seeds.
- The v1 discovery interface returned rules only. A later direct audit found no C1/C2 discovery-response difference in 14 of 30 shifted worlds, including 9 of 15 plan-invalidating worlds.
- The historical H2 flag groups finished episodes that failed CSTS. It includes goal misses and is better described as "finished but failed." H5 records partial overlap with one oracle-plan closure and is not a reasoning-failure measure.

The maintained interpretation is in [Results](../RESULTS.md) and [Technical note](../TECHNICAL-NOTE.md).

