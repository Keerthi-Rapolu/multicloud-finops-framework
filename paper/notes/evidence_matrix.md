# Evidence Matrix

## Section 1

| Claim | Current evidence |
|---|---|
| Multi-cloud billing semantics are inconsistent across AWS, Azure, and GCP. | Provider documentation cited in Sections 1 and 2. |
| The benchmark contains substantial unattributed NEC. | Current benchmark snapshot: `$29,874.07` unattributed NEC. |
| The system produces persistent recommendation outputs. | Current benchmark snapshot: `95` recommendations. |

## Section 3

| Claim | Current evidence |
|---|---|
| CAS normalizes provider-specific exports into one contract. | Implemented manuscript description of identity, pricing, resource, ownership, and allocation field families. |
| Provider semantics are preserved before canonicalization. | NEC section and related-work discussion of provider-specific cost semantics. |

## Section 4

| Claim | Current evidence |
|---|---|
| Shared-cost allocation preserves economic totals. | Benchmark note: Azure shared-cost fan-out preserved totals with zero delta. |
| Allocation outputs are consumed by downstream decision logic. | Allocation and decision-intelligence sections. |

## Section 5

| Claim | Current evidence |
|---|---|
| NEC differs materially from naive list-cost reporting. | Aggregate list cost `$67,065.52` vs. NEC `$52,021.31`. |
| Commitment waste is tracked separately from consumed workload cost. | Explicit waste figure: `$136.80`. |

## Section 6

| Claim | Current evidence |
|---|---|
| Recommendations are generated from explicit signal mappings. | Deterministic signal-to-action table and score formula. |
| Forecasting is accurate enough for benchmark-scale support. | `68` evaluations, MAE `$7.86`, MAPE `2.98%`, within-10-percent `95.59%`. |
| Lifecycle validation is implemented but not yet realized. | `95` recommendations remain in `recommended` state, `$0` realized savings. |

## Section 7

| Claim | Current evidence |
|---|---|
| The artifact is reproducible. | Local LaTeX build path, repository manuscript structure, benchmark-backed numbers in the paper. |

## Gaps

- Restore figure assets if the submission requires the earlier chart and architecture figure set.
- Restore query scripts and exported benchmark tables if the artifact appendix is needed.
- Replace the generic affiliation line in `main.tex` with submission-ready author information.
