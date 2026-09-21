# CascadeShift technical note

## Scope

CascadeShift is a synthetic research prototype for a particular failure mode in tool use. Within an action, its rules apply synchronously in one ordered pass. The requested action can complete while that pass leaves a hard constraint false. The prototype asks whether an agent with access to a rule snapshot can make a constraint-safe change after a valid configuration shift.

This note documents what the completed v1 archive can establish, what it cannot establish, and why a v2 interface repair does not change the historical result. It is a methods and pilot note, not a demonstrated agent capability.

## The v1 question and design

The v1 study used a fixed synthetic access-management world with 128 rules. A task required a visible goal, such as granting access, and one or more hard final-state constraints, such as retaining payroll access. An oracle verified that a safe plan existed before an agent was evaluated. This supports a useful distinction: an available safe plan is not the same thing as an agent having the information or behavior needed to find it.

The study contained 20 hand-authored parent tasks. Each parent appeared in an unchanged baseline world and in shifted worlds. The protocol recorded three information conditions: C0 had no rule-discovery tools; C1 queried the frozen baseline rule snapshot; C2 queried the rule snapshot active in the evaluated world. Three repeats produced 450 episodes: 20 parents, 30 shifted worlds, three conditions, and three repeats across the scheduled cells. Configuration changes were already active before each episode. The design did not test a live system changing underneath an agent during execution.

The historical evaluation used one local model/runtime configuration, recorded under the local alias `qwen3.8-27b`. The associated Q6_K_XL GGUF artifact and projection file have pinned identifiers in [Provenance](PROVENANCE.md). Those identifiers trace the local artifacts to a third-party conversion based on `Qwen/Qwen3.8-27B`; they do not show equivalence to full-precision upstream weights. Provider seeds were unsupported, execution order was fixed as C0, C1, then C2, and no second-model replication was completed. The 20 parents are templates in one synthetic corpus, not a random sample of real administrative tasks.

CSTS is the central outcome. An episode passes only if the visible goal and all hard constraints hold in the final world state. The score avoids calling a successful API response a successful task when that response causes a later constraint failure. Stateful tool environments and terminal state checks are established ideas, including in [ToolSandbox](https://aclanthology.org/2025.findings-naacl.65/), [AppWorld](https://aclanthology.org/2024.acl-long.850/), and [tau-bench](https://proceedings.iclr.cc/paper_files/paper/2025/hash/1b126cc38b8638e07bef37e7b2bb72bf-Abstract-Conference.html). CascadeShift's narrow proposed distinction is the matched frozen-versus-active rule-snapshot contrast. The comparison is limited and does not establish priority over adjacent work.

[EnvTrustBench](https://arxiv.org/abs/2605.08828) is the closest identified overlap on stale, incorrect, or malicious environment-facing claims and oracle-judged outcomes. [STALE](https://arxiv.org/abs/2605.06527) examines later evidence that invalidates stored memories, and [FraudBench](https://arxiv.org/abs/2608.18136) studies policy-grounded action over mutable accounts. This bounded comparison leaves a narrower question: whether discovery from a frozen rule snapshot versus an active rule snapshot changes outcomes under synthetic rule changes. It is not an exhaustive literature survey.

## The v1 result

The archived matrix is complete: 450 unique cells with 20 parents and three conditions. On shifted worlds, C1 passed 53 of 90 episodes and C2 passed 51 of 90. On unchanged worlds, C1 passed 47 of 60 and C2 passed 41 of 60. For each parent, the preregistered primary estimand is:

```text
(C2 - C1 on shifted worlds) - (C2 - C1 on unchanged worlds)
```

The analysis averages the 20 parent values, then resamples parents. It gives +9.2 percentage points with a 95% parent-bootstrap percentile interval of -1.7 to +20.8. The raw shifted-world C2-minus-C1 difference is -2.2 points, but pooled counts do not reconstruct the parent-weighted estimand because parents have unequal shifted-case counts. The interval spans zero, so the result is inconclusive.

Three scripts make the historical numerical record inspectable. `scripts/recompute_results.py` reconstructs the matrix and the primary estimate from archive bytes. `scripts/replay_study.py` replays 587 archived business actions through the freeze-matched transition and scoring code and finds agreement on all 450 archived final verdicts. `scripts/audit_visibility.py` compares discovery responses across the frozen and current rule backends. These are meaningful consistency checks. They do not repeat model inference, establish the circumstances of the original live run, or provide an independent simulator implementation.

The action replay checks that retained traces, transition logic, and final verdicts agree. Archive-engine agreement is not evidence of a model effect. The primary statistic is a corpus-stability summary under the stated resampling assumption.

## The treatment-coverage problem

The direct visibility audit found that C1 and C2 gave identical responses for every valid rule inspection, schema, and archive-observed discovery request in 14 of 30 shifted worlds. Nine of those 14 worlds were plan-invalidating. In those worlds, the rule-only discovery interface did not expose a frozen/current difference, even though a configuration change had occurred.

This finding requires careful wording. It does not show that no agent could solve any of the 14 worlds, or that every unexposed fact was necessary for every action. It does show that much of the intended treatment was absent at the discovery interface. The prototype could return rules, but it could not return changed policy, application, role, conflict, employee, or state values through a separate record or configuration read surface. The oracle could see a safe plan that the documented agent interface did not make observable.

The numerical result is still the result of the implemented interface. The treatment-coverage defect changes its interpretation. It makes the v1 study weak evidence about the broader construct described as current configuration freshness, because a substantial share of the selected shifts did not create an observable contrast between C1 and C2.

Fixed condition order adds another limitation. Even the unchanged worlds had different raw C1 and C2 counts, 47 of 60 versus 41 of 60. The primary adjustment accounts for that observed baseline gap mechanically, but it cannot identify whether time, order, or ordinary provider variation contributed. The model did not support seeds, and the protocol did not counterbalance condition order. This is why the archive should not be read as causal evidence.

## Secondary measures that may be misread

Two labels in the historical analysis describe useful archive properties but do not support the stronger interpretations sometimes attached to them.

First, H2 used a `silent_violation` flag triggered when an episode called `finish_task` and failed CSTS. The flag includes both a task that reached its goal but broke a hard constraint and a task that failed its goal while preserving the constraint. In the shifted C0 records, 31 episodes carried the flag. They split into 25 goal-passed, hard-constraint-failed episodes and 6 goal-failed, hard-constraint-passed episodes. The historical flag is retained, but "finished but failed" is a more accurate public description. A strict hard-constraint-only measure would need its own definition and analysis.

Second, H5 treated a retrieved rule as relevant when it overlapped the rules used by one deterministic oracle plan. Across all 58 failing C2 episodes, 43 retrieved at least one rule from that closure and 30 inspected one. Only one retrieved a complete nonempty closure, and none inspected one. This is a partial retrieval diagnostic. There can be more than one safe plan, so overlap with one oracle plan does not establish that the agent had enough information, nor does a failure after overlap establish a reasoning failure.

The archive also reports discovery-budget exhaustion in 110 of 150 C1 episodes and 108 of 150 C2 episodes. Those outcomes were retained rather than excluded. They are a property of the specified interface and budget, and may have contributed to later failure.

## Measurement v2

The v2 work is a separate development repair. It defines six hand-built cases that expose one action-relevant configuration fact through the actual tool interface. For each case, the construction gate checks four facts: the baseline plan passes in the baseline world, fails in the active world, a corrected plan passes in the active world, and restoring the declared witness fact restores the baseline plan. The cases also make the information delivery explicit: frozen and current conditions use the same tool schema, while a full-information condition is a diagnostic control.

The v2 scorer separates goal satisfaction, hard-constraint satisfaction, CSTS, a call to `finish_task`, an explicit boolean success assertion, false success claims, and an asserted success with a hard-constraint violation. This corrects an ambiguity in the older finished-but-failed label. All six construction cases pass. That validates the development fixtures and interface assumptions. It does not measure model performance.

A bounded provider diagnostic stopped after seven episode records and 15 requests. Six records were terminally scored, but none executed a business action. The selected provider returned `finish_task` together with other calls, while the declared caller contract required `finish_task` to be the only tool call in a response. The runner rejected those mixed batches. Two full-information records returned prose rather than structured tool calls. The seventh record stopped at provider validation and is invalid rather than a scored outcome. A separate three-call smoke screen passed, but it did not test the full mixed-batch behavior.

The repository preserves a sanitized, source-derived summary of that stopped diagnostic. The raw provider record is not public. The summary is not independently reproducible model data and supports neither a condition comparison nor a null or efficacy claim. The offline measurement repair passed construction tests; the provider diagnostic did not qualify the full protocol.

## A proposed next study

Any follow-up should use a new protocol, not rewrite v1. Before model execution, every selected shift should prove that C1 and C2 differ on a declared action-relevant fact, that necessary records are accessible through the documented tools, and that an accessible-fact witness and plan witness pass. The full tool contract needs a representative preflight that exercises typed calls, terminal completion, and failure handling. A typed finish signal should have a reliable contract rather than relying on a mixed-batch rejection discovered during a diagnostic.

The next protocol should preregister the estimand, precision target, design cluster, counterbalancing, budget, stop rules, exclusions, and handling of invalid runs. It should separate goal misses from hard-constraint failures. It should cover multiple worlds and model/runtime configurations only after the preflight is successful. A null or negative result would be informative if the measurement is usable. No larger study has been launched, and this note makes no prediction about its outcome.

## What readers can conclude

Readers can inspect a complete synthetic archive, recompute the stated v1 result, replay the archive against the frozen engine, and inspect a direct discovery-response audit. They can also run the v2 six-case construction checks. The public evidence supports an inconclusive result for one implemented rule-snapshot interface and a transparent account of a measurement repair.

The evidence supports no conclusion about production agents, enterprise controls, other models, a general benefit from fresh configuration access, or independent replication. It also does not establish that CascadeShift is the first benchmark to evaluate dynamic tools, policies, or terminal state integrity.

For commands and their exact boundaries, read [Reproducibility](REPRODUCIBILITY.md). For a practical follow-up design, read [Future study](docs/future-study.md).
