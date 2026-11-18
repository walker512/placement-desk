# Placement Desk

**Can these replicas fit on this deployment plan, including after losing a node or a zone?**

An offline planning CLI for a small, explicit set of CPU/RAM/GPU requirements. Compare candidate node inventories against the same workloads, request single-node and/or single-zone loss cases, and inspect an actual placement witness for every feasible case.

It solves a bounded **declared packing problem**, not hardware sizing, performance benchmarking or deployment automation. No cloud APIs, cluster credentials, live pricing, model downloads or deployment commands are used.

## Quick start

Python 3.11+ with no runtime dependencies. From the source directory:

```sh
python -m placement_desk analyze examples/deployment.json --out placement-review --require-plan three-zones
python -m placement_desk verify placement-review --require-plan three-zones
python -m unittest discover -s tests -v
```

Always use a new output directory. Optionally install with `python -m pip install .`, then replace `python -m placement_desk` with `placement-desk`. The build backend is setuptools. There is no implied package-registry release.

### The supplied example

Two inference replicas each require 2,000 CPU millicores, 4,096 MiB RAM and one indivisible `synthetic-gpu` unit. Replicas of this workload must occupy different zones. Every node provides 4,000 millicores, 8,192 MiB and one GPU unit.

| Plan | Healthy | Any one node lost | Any one zone lost |
|---|---|---|---|
| Two nodes in two zones | Feasible | Infeasible in model | Infeasible in model |
| Three nodes in three zones | Feasible | Feasible in model | Feasible in model |

The labels and numbers are **synthetic declarations**, not measurements of an actual GPU model. The extra node is not automatically a deployment recommendation: price, latency, data consistency and recovery time are absent from this packing-only example. The optional context workflow below adds human-declared reservation and cross-site charges, not real prices or recovery timing.

To demonstrate a limited search:

```sh
python -m placement_desk analyze examples/limited-search.json --out limited-review --require-plan three-zones
```

This exits **3**, with `unknown_search_limit`. The lower candidate-check budget has not proved the plan impossible. It has stopped before finding or exhausting a solution.

## What is in a bundle?

- `input.json`: complete original input bytes, including every workload and node declaration.
- `report.json`: healthy and requested failure cases, exact removed nodes, candidate-check counts, status, feasible replica placement and remaining capacities.
- `review.md`: concise plan/case comparison and critical scope limitations.

`verify` recomputes all outputs, including rerunning the deterministic bounded search. It detects inconsistencies, not a coordinated replacement of input and output. It does not authenticate the declarations, author or hardware. A separate trusted signature/hash is necessary for provenance.

## Model contract

Every object has exactly the documented fields. Unknown fields are rejected rather than silently ignored.

```json
{
  "schema": 1,
  "candidate_limit": 20000,
  "failure_modes": ["node", "zone"],
  "workloads": [{
    "id": "worker",
    "replicas": 2,
    "resources": {"cpu_millis": 1000, "ram_mib": 1024, "gpu_units": 0},
    "accelerator": null,
    "spread": "node"
  }],
  "plans": [{
    "id": "candidate",
    "nodes": [
      {"id": "n1", "zone": "zone-a", "capacity": {"cpu_millis": 2000, "ram_mib": 4096, "gpu_units": 0}, "accelerator": null},
      {"id": "n2", "zone": "zone-b", "capacity": {"cpu_millis": 2000, "ram_mib": 4096, "gpu_units": 0}, "accelerator": null}
    ]
  }]
}
```

- CPU uses integer millicores; RAM uses integer MiB. Node capacity should be **allocatable capacity after externally determined system reservations**, not a marketing total. The tool does not infer overhead.
- A replica is indivisible and must fit entirely on one node. Resource consumption is additive; there is no overcommit or inter-node sharding.
- GPU units are whole abstract units, not VRAM, FLOPS, throughput or interchangeable performance. A GPU workload requires an explicit accelerator label matching the node exactly. This checks a string, not driver/architecture/model compatibility. CPU-only workloads use `null` and may run on GPU nodes without consuming GPU units.
- `spread: none` permits colocating replicas. `node` requires distinct nodes; `zone` requires distinct zones, **within the same workload**. Different workloads may share nodes/zones if resources fit.
- Every plan uses the same entire workload set. There is no priority, partial placement or best-effort dropping of replicas.
- `failure_modes` controls which extra cases are checked. An empty list checks **healthy placement only**, not resilience. `node` removes each individual node in turn. `zone` removes all nodes with each distinct zone label in turn. Each case is an independent single failure, not cumulative or multi-zone loss.
- Quantities and labels must be supplied explicitly. Missing/unknown capacity is rejected; do not invent numbers to obtain a result. `unknown_search_limit` refers only to computation stopped by its budget, not unknown hardware data.

## Important failure-case semantics

**Each failure case permits restarting and fully repacking ALL replicas on surviving nodes, including replicas that previously occupied healthy nodes.** It does not preserve the healthy placement or prove that only lost replicas can be rescheduled.

There is no time dimension, data transfer, persistent volume, startup ordering, network connectivity, disruption budget, recovery deadline, quorum/service behavior or live migration model. A feasible post-loss packing does not guarantee service continuity or successful automatic recovery. Validate those separately in the intended runtime.

## Results and bounded search

- `model_feasible`: found a full assignment satisfying all modeled capacity, accelerator-label and spread constraints. A separate witness checker checks completeness, resources and spread before the report is written.
- `model_infeasible`: the finite deterministic search exhausted all candidate assignments without finding one. This conclusion applies **only to the declared model**.
- `unknown_search_limit`: the search needed another candidate check after its budget was consumed. No feasible witness or infeasibility conclusion is emitted.

The solver uses depth-first backtracking, not a greedy-only fit heuristic. Workloads are ordered by number of accelerator-label-eligible nodes, then descending GPU/RAM/CPU demand, then workload ID. Replica indices ascend; nodes are tried by ascending ID. Every attempted replica/node pair counts, including rejected capacity/label/spread candidates. Every case has its own budget. No symmetry reduction or optimality claim is made. A valid witness reached on the final permitted check succeeds; fully exhausted search on that check can still prove model infeasibility.

The per-plan `all_requested_cases` summary is infeasible if any requested case is proved infeasible, otherwise unknown if any case is unknown, otherwise feasible. Individual statuses are preserved. This is not a ranking or cost optimizer. More budget can be necessary, but it is capped intentionally.

Exit codes:

- **0**: analysis written or recomputation matched. By default, this does not require any feasible plan.
- **2**: invalid input, unknown required plan, inconsistent bundle, size/encoding/type violation, filesystem or argument error.
- **3**, when `--require-plan PLAN` is used: the named plan is not feasible in **all requested cases**, including when any required result is unknown.

Selecting a missing required plan is an error. The underlying analysis may already have been written; do not treat the existence of an output directory alone as a passed gate.

## Limits, privacy and safety

At most 3 plans, 8 nodes per plan, 12 workloads and **12 total replicas**. CPU/RAM are integers 1–1,000,000,000; GPUs 0–64; candidate checks 1–20,000 per case. With both failure modes there are at most 17 cases per plan and 51 cases total. Search may be expensive near the limit but cannot grow its recursion beyond the bounded replica count.

Inputs are at most 1 MiB. Output files have an independent 8 MiB bound and are serialized and checked before destination creation. JSON duplicate keys, depth beyond the limit, floats, non-finite values, malformed Unicode and boolean-as-integer fields are rejected. IDs are 1–48 ASCII letters/digits/dot/underscore/hyphen starting with a letter.

Only ordinary non-symlink input files are accepted. Leaf symlinks and special files are rejected; this is not a security sandbox against malicious parent-directory replacement or a filesystem administrator. Output directories are never overwritten. An I/O failure after creation may leave a partial bundle; verify completeness before relying on it.

No telemetry or automatic redaction. Inventories may reveal internal infrastructure names. Inspect the complete input before sharing. Credentials are neither needed nor appropriate. Errors do not echo supplied contents. Do not include secrets in public reports; no private reporting address is designated by this source release.

## Related tools and boundaries

- [kube-scheduler-simulator](https://github.com/kubernetes-sigs/kube-scheduler-simulator) investigates Kubernetes scheduler behavior. Prefer an actual scheduler-specific tool for actual Kubernetes semantics; this project does not implement its plugins or policies.
- [Kubernetes affinity documentation](https://kubernetes.io/docs/concepts/scheduling-eviction/assign-pod-node/) describes richer node/pod affinity constraints. The three spread modes here are deliberately simpler and not Kubernetes YAML equivalents.
- [llm-capacity-planner](https://github.com/nemmusu/llm-capacity-planner) addresses LLM inference memory/concurrency sizing. This project instead requires explicit per-replica demands; it cannot estimate a model's VRAM or throughput.

These primary documents were inspected, not their runtimes. No head-to-head speed, novelty, exclusivity or superiority is established. The concrete utility is a packaged, bounded, deterministic multi-plan/failure-domain feasibility review with actual placement witnesses. Generic constraint solvers, scheduling tools or custom code can also solve related problems.

This is not AI Cost billing comparison or Component Swap interface-compatibility checking. It answers the narrower question of allocating declared indivisible resources and spread constraints.

## Validation

The historical 0.2 context suite had 54 public synthetic tests passing on Linux/Python 3.12 (zero skipped). The unchanged original 31 tests include 250 independently enumerated small placement problems, fragmentation despite sufficient aggregate resources, accelerator matching, node/zone spreading, single-loss cases, budget exhaustion, feasible witness validation, finite shape bounds, CLI gates, exact UTF-8/LF outputs, source-byte preservation, bundle tampering and bounded file handling.

The 23 added context tests cover the actual CLI bundle loop, failure-dependent directed flows, unknown costs, exact rational products and sums, input binding, allowlist boundaries, output preflight and tampering.

Windows/macOS, hosted CI and real hardware deployments have not been run. Symlink/FIFO cases may skip on unsupported platforms; skips are not passes. That release had no browser UI; the new static architecture report is described below. Synthetic correctness is not real-user adoption, calibrated capacity planning or proof of failover readiness.

MIT license, original code and synthetic examples by walker512. No competitor source or private infrastructure data is included.

## Optional declared deployment context

The additive [context workflow](docs/CONTEXT.md) binds human-supplied site/region mappings, fixed reservation rates, directed per-replica traffic and allowed destination pairs to the exact placement input. It reuses the solver's healthy/failure witnesses, exposes unknown costs and boundaries, and exports a recomputable bundle with plain-text architecture. It does not find optimal placement, infer current pricing, establish compliance or estimate complete total cost. The original model and CLI above remain unchanged.

## Offline architecture diagrams

The independent visual-bundle command adds a static `index.html` to the five
unchanged context-bundle files. No server, JavaScript, remote fonts, API keys or
cloud services are needed by the generated report.

```sh
python -m placement_desk.visualize analyze examples/context-deployment.json examples/context-assumptions.json --out visual-review
python -m placement_desk.visualize verify visual-review
```

Open the generated HTML locally. Jump between local/cloud/hybrid plans and expand
individual failure cases using the native disclosure controls (keyboard Enter
works). Each case shows all declared nodes, zones and sites, removed nodes,
assignment counts, directed node-pair curves and a precise per-flow table. Long
SVG labels are abbreviated; the full inventory table and replica JSON retain exact
identifiers. Curves aggregate multiple flows between the same ordered node pair;
the table records individual directions, bytes, boundary checks and costs. Curves
may overlap in dense examples, so use that table rather than treating line layout
as physical topology. No placement witness means no inferred traffic or combined
cost; unassigned inventory is not falsely displayed as a successful placement.

The original `placement_desk.context verify` still expects its five-file format.
Use `placement_desk.visualize verify` for the six-file visual bundle. It recomputes
all files including HTML, not just a JSON receipt. Core placement and context
results remain byte-for-byte unchanged. Recomputability does not authenticate
sources or prove physical failover, network availability, compliance or cost.
This is an inspectable architecture report, not a drag-and-drop planning editor.

New visual bundles are exclusively created with directory/file modes 0700/0600 on
POSIX, subject to stricter umask. Existing destinations are never overwritten;
partial I/O failures may leave a private incomplete directory that verification
rejects. Legacy outputs are not retroactively protected. Trusted parent directories
are required; hostile same-account replacement, ACLs and encryption are not covered.

Visual candidate validation: **68 tests passed, zero skips**, Linux/Python 3.12
(54 previous plus 14 visual tests). Coverage includes unchanged core outputs,
one SVG per case with unique IDs, flow aggregation/self-loops, unknown/no-flow
semantics, HTML escaping, tampering of every member, bounds, private creation,
failed writes and real CLI commands. Builder Chromium desktop acceptance checked
plan navigation, a hybrid node-loss disclosure, removed-node styling, the directed
local-to-cloud arrow, exact boundary/cost table and keyboard collapse. No mobile,
other-browser, screen-reader or Windows/macOS runtime claim is made. No real
infrastructure was accessed or deployed. This increment does not complete the
original project's performance-calibration or real-world validation requirements.

An offline-built wheel installed in a fresh virtual environment successfully verified the six-file demo outside the source tree. Python 3.11 grammar was checked; the actual runtime used was Python 3.12.
