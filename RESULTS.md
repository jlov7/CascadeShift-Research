# Results

## Historical v1 archive

The complete v1 archive contains 450 episodes from 20 hand-authored parent tasks, 30 shifted worlds, three conditions, and three repeats. The historical primary result is inconclusive.

| Quantity | Result |
| --- | --- |
| Shifted C1 | 53/90 CSTS passes |
| Shifted C2 | 51/90 CSTS passes |
| Baseline C1 | 47/60 CSTS passes |
| Baseline C2 | 41/60 CSTS passes |
| Adjusted primary estimate | +9.2 pp |
| 95% parent-bootstrap percentile interval | -1.7 to +20.8 pp |

For each parent, the estimand subtracts its C2-minus-C1 difference in unchanged worlds from its C2-minus-C1 difference in shifted worlds. The analysis then averages the 20 parent values. The pooled raw counts do not reconstruct this estimate because parents have unequal numbers of shifted cases. The shifted-world raw contrast favors C1 by 2.2 points; the parent-weighted adjustment reverses the sign. The interval includes zero.

The study used one local model/runtime, one synthetic corpus, fixed condition order, and provider repeats without supported seeds. The discovery interface exposed rules only. In 14 of 30 shifted worlds, including 9 of 15 plan-invalidating worlds, a direct audit found no C1/C2 difference in the discovery responses. This does not invalidate the archive arithmetic, but it limits the result to the implemented interface and makes it weak evidence about broader configuration freshness.

`scripts/recompute_results.py` recomputes the matrix and primary estimate. `scripts/replay_study.py` replays 587 archived actions and all 450 final verdicts against freeze-matched engine code. `scripts/audit_visibility.py` compares the discovery responses. These are deterministic archive checks. They do not rerun a model or independently reproduce the study.

H2 is best described as a finished-but-failed flag because it counts any `finish_task` episode that failed CSTS, including goal misses. H5 is a partial oracle-closure overlap measure, not a reasoning-failure measure. See [Technical note](TECHNICAL-NOTE.md).

## Measurement-v2 development diagnostic

The six offline construction cases pass. They verify visible fact changes, plan failure and recovery, and the separate scoring fields. A bounded provider diagnostic stopped after seven records and 15 requests. Its public summary is source-derived and incomplete. It does not support a model comparison, a null result, or an efficacy claim. See [Technical note](TECHNICAL-NOTE.md) and [Future study](docs/future-study.md).

