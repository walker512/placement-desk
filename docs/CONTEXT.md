# Declared deployment context: costs, sites and directed flows

An additive offline review of the **existing solver's actual deterministic witnesses**. This does not search for cheapest or geographically permitted placements. A forbidden flow demonstrates a problem with this witness, not impossibility of a different allowed placement. Site kind `local` or `cloud` and region names are human declarations, not verified locations. A plan can mix them.

## Run the complete synthetic example

```sh
python -m placement_desk.context analyze examples/context-deployment.json examples/context-assumptions.json --out context-review
python -m placement_desk.context verify context-review
python -m unittest discover -s tests -v
```

The three plans use identical node IDs in separate inventories. `local` places all nodes at an office, `cloud` uses two declared cloud sites, and `hybrid` combines the office with a cloud site. These are synthetic names and prices. Healthy hybrid placement sends one GiB between two office nodes, with exact modeled reservation charges of 9/10 USD for 3/2 hours. Losing node `b` repacks beta on cloud node `c`, making this witness's flow cross a declared boundary; the extra declared fee is 1/10 USD, so modeled charges are 1 USD. All three inventory nodes remain charged during failure. The local spare's unknown price produces a partial known subtotal, not a zero-price spare; a cloud directed rate is also intentionally unknown.

Each case is an **independent whole-duration scenario**, not a phase in one calendar timeline. Never sum healthy and failure scenarios into a bill. Every failure scenario may restart and repack all replicas, exactly as documented by the original solver. Traffic does not model movement from the healthy placement, migration, startup traffic, retransmission or downtime.

## Exact sidecar contract

See `examples/context-assumptions.json` for the complete schema. Every listed object requires exactly its documented keys; extra or missing fields are rejected. Decimal floats and boolean-as-integer fields are rejected. Nonnegative rational currency values use `{"numerator": integer, "denominator": positive_integer}`; each integer is bounded by 10^15. Products and sums retain exact reduced rational values and can exceed the input bound. No exchange rate or rounding is inferred.

Top-level keys:

- `schema`: integer 1.
- `input_sha256`: SHA-256 of the **original complete placement input bytes**, not parsed/reformatted JSON. Any input edit, including whitespace, requires an intentionally updated binding. Hashes do not authenticate the author or declarations.
- `currency`: one identifier for all rates; no currency conversion. Identifier syntax is the same ASCII 1–48-character syntax used by the placement model.
- `duration_hours`: strictly positive rational hours for each independent case.
- `assumptions`: 1–4000 Unicode characters recording human price source/date, measurement assumptions and billing conditions. It is an unverified statement, not a source fetch. No credentials belong here.
- `sites`: at most 24 objects `{id,kind,region}`. `kind` is `local` or `cloud`; `region` is an identifier or `null` for unknown. Sites must have unique IDs. Zone is **not** used as region.
- `nodes`: at most 24 objects `{plan,node,site,hourly_rate}`. Exactly one mapping per original `(plan,node)` must exist. `site` references a declared site; `hourly_rate` is a rational currency/hour or `null`. Repeated node IDs across plans are valid. Every inventory node is reserved for the full duration, including unused or failed nodes; no refund, shutdown, failover timing or amortization is inferred.
- `egress_rates`: at most 64 objects `{from_site,to_site,per_gib}`. Unique directed pairs of distinct known sites. `per_gib` is rational currency per 1,073,741,824 bytes or `null`. Missing pairs are unknown, not zero; reverse-direction prices are not inferred.
- `flows`: at most 24 objects `{id,from,to,bytes,allowed_site_pairs,allowed_region_pairs}`. IDs are unique. Each endpoint is exactly `{workload,replica}`, with a real zero-based replica index from the input. `bytes` is an integer 0..10^15 or `null`, representing the explicitly declared total in that direction over the **entire duration in each case**. No averaging, all-to-all expansion, inference from resource requests or multiplication by replica count occurs.

Allowed pair lists contain at most 64 unique two-identifier arrays. Site pair names must reference declared sites. Region lists are declarations of permitted region names, not a registry. `null` means not declared and gives `unknown_not_declared`; an empty list means every pair is forbidden, including an unknown actual region. Otherwise, unknown actual region gives `unknown_region`. Site and region checks are separately reported. A known forbidden pair makes the combined status forbidden; otherwise any unknown makes it unknown, never allowed. This describes literal human allowlists, **not legal or organizational compliance**.

## Costs and unknowns

Node cost = hourly rate × duration. Directed cross-site fee = bytes / 1,073,741,824 × declared rate. Same-site network charges are excluded from this model and contribute zero to this *cross-site component only*, even with unknown bytes; this does not imply free same-site traffic. Explicit zero bytes contributes zero cross-site fee even when its rate is unknown, with `declared_zero_bytes` shown. Boundary checks still apply to the declared route when volume is zero or unknown.

Each subtotal has `known_subtotal`, `unknown_items`, and `modeled_amount`. If any modeled component is unknown, `modeled_amount` is null. A known subtotal is not a complete amount. No declared flows means no modeled cross-site charges and `not_evaluated_no_declared_flows`, not proof that the deployment has no traffic.

Infeasible and search-limited cases have no placement witness and therefore no evaluated flows, combined charges or locality conclusion. Inventory reservation charges remain separately computable. The context report includes the original placement results without changing the solver.

## Review artifacts and safety

A new bundle contains exactly:

- `input.json`, `context.json`: exact original supplied bytes.
- `placement.json`: recomputed original solver report with actual witnesses.
- `context-report.json`: deterministic declared costs, endpoints and boundaries.
- `architecture.txt`: plain-text per-case directed architecture and human confirmation checklist.

`verify` reruns the solver and the complete context calculation, then byte-compares all outputs. It detects missing/extra files and inconsistent outputs. Coordinated replacement of both source and outputs can still verify; use an independently trusted signature/hash if provenance matters.

Inputs use the original 1 MiB UTF-8, duplicate-key/depth/type checks and regular non-symlink file reader. Output files are independently limited to 8 MiB and all are generated/preflighted before creating the destination. Existing output directories are never overwritten. An I/O failure can leave a partial new bundle. Parent directories/filesystems must be trusted; this is not a hostile filesystem sandbox. Inspect bundled architecture, locations and assumptions before sharing: no redaction or anonymization is performed. Free text in the architecture is JSON-escaped so embedded line breaks do not become new diagram commands. Artifacts execute nothing.

Exit 0 means computation completed or bundle matched; it does **not** mean affordable, feasible, geographically permitted or safe. Exit 2 means invalid declarations/binding/bundle or filesystem failure. The original placement CLI and its `--require-plan` gate remain unchanged.

## Scope still requiring human confirmation

No network, deployments, current price lookup, hardware profiling, timing, reachability, latency, bandwidth capacity, privacy classification, legal determination, traffic capture or schedule. No taxes, power, storage, API/model usage, support, licensing, billing minimums, discounts, spot interruption pricing, FX conversion or migration fees. These are **modeled reservation-plus-cross-site charges, never complete total cost**. Region feasibility and cost optimization are not searched. Confirm the real target platform and measurements separately.

Original implementation and wholly synthetic examples by walker512. No third-party code, real infrastructure data or private prices. This extension has no browser UI; no browser acceptance, Windows/macOS run, hosted CI, real hardware or competitor runtime comparison is claimed.
