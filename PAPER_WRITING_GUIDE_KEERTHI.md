# Keerthi's Paper Writing Guide
## Multi-Cloud FinOps Decision Engine

**Who this is for:** Keerthi Rapolu - lead architect, primary paper author.  
**What this document does:** Tells you exactly how to write the Keerthi-owned parts of the paper, what evidence to assemble, which figures and tables to create, and how to pressure-test each claim before submission.  
**What this document is not:** It is not the paper. Do not paste this into the paper. Use it as the execution checklist for producing the paper.

Read this document top to bottom, in order. Do not jump directly into prose.

---

## Part 0 - Paper Positioning

The repository is no longer just a cost-allocation demo. The implemented system is a **post-billing multi-cloud FinOps decision engine** with:

- cross-cloud NEC normalization
- a canonical Unified Cost Allocation Schema (CAS)
- shared-cost allocation logic
- deterministic waste detection
- causal reasoning over billing patterns
- recommendation scoring
- month-end forecasting
- lifecycle-oriented validation outputs

Your paper sections must reflect that system position consistently.

The strongest publishable framing is:

1. Multi-cloud billing is fragmented and difficult to compare correctly.
2. Existing FinOps tooling is mostly descriptive and often vendor-bound.
3. This system converts raw billing data into a reproducible, explainable decision pipeline.
4. The core contribution is not "a dashboard" but a canonical backend decision model with auditable outputs.

Never let the paper drift into "we built some charts." The charts are evidence surfaces. The system contribution is the data model plus decision pipeline.

---

## Part 1 - Read These First

Before writing any section, re-read these files and take notes:

1. [DESIGN_DOCUMENT.md](C:/Users/rapol/Downloads/multicloud-finops-framework/DESIGN_DOCUMENT.md)
2. [PAPER_OUTLINE.md](C:/Users/rapol/Downloads/multicloud-finops-framework/PAPER_OUTLINE.md)
3. [README.md](C:/Users/rapol/Downloads/multicloud-finops-framework/README.md)
4. [docs/NEC_CALCULATIONS.md](C:/Users/rapol/Downloads/multicloud-finops-framework/docs/NEC_CALCULATIONS.md)
5. [docs/DECISION_ENGINE_METHODOLOGY.md](C:/Users/rapol/Downloads/multicloud-finops-framework/docs/DECISION_ENGINE_METHODOLOGY.md)
6. `dbt_project/models/marts/fct_finops_signals.sql`
7. `dbt_project/models/marts/fct_finops_recommendations.sql`
8. `dbt_project/models/marts/fct_month_end_forecast.sql`
9. `dbt_project/models/marts/fct_model_accuracy.sql`
10. `intelligence/forecasting.py`
11. `dashboard/_shared.py`
12. `docs/screenshots/`

The important point is the reading order. Do not start drafting sections before extracting evidence from these files.

### Source authority order

Use the sources in this order when they disagree:

1. current implemented repo artifacts
2. `DESIGN_DOCUMENT.md`
3. this guide
4. `README.md`
5. `PAPER_OUTLINE.md`

`PAPER_OUTLINE.md` is useful, but it is not authoritative for current system framing. Treat it as a secondary planning artifact, mainly for:

- historical section ownership
- venue direction
- paper-length expectations
- reminder notes such as figure reproducibility and methodology disclosure

### Your note-taking template

For each file, extract:

- the exact claim it supports
- the exact formulas it contains
- the exact artifact names it produces
- any limitation or caveat that must be stated in the paper
- any sentence that should become a figure caption, table note, or evaluation explanation

Do this before writing prose. If you skip this, the paper will sound polished but soft.

---

## Part 2 - Non-Negotiable Paper Rules

These rules apply to every Keerthi-owned section.

### Rule 0 - Keep the paper within a realistic workshop/conference envelope

Plan for roughly **10-12 pages in IEEE-style double-column format** before references, unless the actual venue template forces a different limit. This affects how many figures, tables, and worked examples you can keep.

### Rule 1 - Every architectural claim must map to a repo artifact

If you claim a component exists, you must be able to point to at least one of:

- a Python module
- a dbt model
- a test
- a dashboard page
- a materialized mart

### Rule 2 - Every numeric claim must map to a reproducible query

If you write:

- "the system identified X unattributed NEC"
- "the forecast achieves Y accuracy"
- "recommendations are ranked by Z"

then you need a saved query, notebook cell, or script output that reproduces it.

### Rule 3 - Do not overclaim production validation

The repo uses a reproducible synthetic benchmark. That is valuable. It is **not** the same as enterprise production validation.

Use language like:

- "reproducible synthetic benchmark"
- "implemented and evaluated on synthetic multi-cloud billing scenarios"
- "evidence of internal consistency and pipeline behavior"

Avoid language like:

- "proven in production"
- "enterprise validated"
- "guarantees savings"

### Rule 4 - Distinguish system design from evidence

Reviewers will ask:

- What did you build?
- Why is it different?
- How do you know it works?

Those are three different things. Do not blend them.

### Rule 5 - Separate these four savings layers everywhere

Use the same vocabulary everywhere:

1. Waste signal
2. Recoverable savings
3. Actionable savings
4. Realization-adjusted projected savings

Mixing these layers is a credibility failure.

### Rule 6 - Every figure should be reproducible from the repo

Do not include one-off manual diagrams whose content cannot be traced back to the current implementation. Architecture diagrams can be redrawn cleanly, but the entities, stages, formulas, and labels must come from the repo and final paper definitions.

### Rule 7 - If you disclose AI-assisted development, do it in methodology, not as hype

If the final paper includes tooling disclosure, keep it short and factual:

- which tools were used
- what they assisted with
- that the authors verified formulas, code behavior, and paper claims manually

Do not let the tooling disclosure become part of the claimed technical contribution.

---

## Part 3 - Writing Workflow for Every Section

Use this workflow for each section you own.

### Step 1 - Write the one-sentence thesis

Before paragraphs, write one sentence that answers:

"What is the exact purpose of this section in the paper?"

If you cannot do this in one sentence, the section is not conceptually clean yet.

### Step 2 - List the claims

For that section, list:

- 3-5 core claims
- 1-2 boundaries or limitations
- 1 comparison point versus existing practice

### Step 3 - Match each claim to evidence

Create a scratch table with:

- claim
- evidence source
- artifact name
- whether it needs a figure, table, equation, or example

### Step 4 - Draft the structure before prose

For each section, outline:

1. Problem or context
2. Design or method
3. Example or walkthrough
4. Evidence or validation
5. Limitation or boundary

### Step 5 - Write reviewer-facing prose

Every paragraph should answer one likely reviewer question. If a paragraph is just descriptive and does not answer a question, it is probably filler.

### Step 6 - Validate after writing

After the draft, ask:

- Can I point to a concrete artifact for every design statement?
- Are all formulas consistent with repo implementation?
- Have I stated at least one limitation?
- Would a skeptical systems reviewer accept the evidence type?

---

## Section 1 - Introduction

### Why this section exists

The Introduction sells the paper. Its job is to make reviewers care about the problem, understand the gap, see the paper's contribution, and trust that the contribution is concrete.

### What reviewers expect

- a real systems problem, not a vague cloud-cost complaint
- why multi-cloud makes the problem harder than single-cloud FinOps
- why existing tooling is insufficient
- a crisp statement of what the paper contributes
- a short roadmap paragraph so the paper feels organized

### Common mistakes

- spending too much time on generic cloud adoption trends
- sounding like product marketing
- listing features instead of research contributions
- saying "dashboard" too often
- failing to name the specific technical gaps: schema heterogeneity, discount semantics, unattributed spend, non-auditable recommendation logic

### Detailed writing checklist

1. Open with the multi-cloud cost-management problem in operational terms.
2. Explain why AWS, Azure, and GCP billing cannot be compared naively.
3. Introduce FinOps as the operational motivation, not as a history lesson.
4. State the gap in current tooling:
   - descriptive reporting
   - weak cross-cloud normalization
   - opaque savings estimates
   - poor explainability
5. Position the project as a decision engine, not a dashboard.
6. Write the contributions list as 4-6 bullet points.
7. Add one short motivation example:
   - RI/SP/CUD semantics hide real cost
   - unattributed NEC blocks accountable optimization
   - a single "savings" number is unsafe
8. End with the paper roadmap paragraph.

### Required tables

- `Table 1` - Paper contributions at a glance
  - columns: Contribution, Problem addressed, Artifact in system, Evidence type

### Required figures

- `Figure 1` - End-to-end system overview
  - billing inputs -> normalization -> unified mart -> signals -> recommendations -> forecast -> lifecycle/validation

### Required examples

- one motivating example of misleading raw billing semantics
- one motivating example of unattributed spend blocking action
- one motivating example of why projected savings must be separated from raw waste

### Evidence checklist

- README problem framing
- DESIGN_DOCUMENT decision-engine positioning
- CAS existence in `fct_unified_billing`
- canonical decision marts:
  - `fct_finops_signals`
  - `fct_finops_recommendations`
  - `fct_month_end_forecast`
  - `fct_action_lifecycle`
  - `fct_model_accuracy`

### Validation checklist

- Contributions listed in the Introduction must all appear later in the paper.
- No contribution bullet should be purely UI-focused.
- Every contribution bullet must reference a real implemented artifact.
- Numbers in the Introduction must match benchmark tables exactly.

### Reviewer-objection checklist

- "This sounds like a dashboard, not a systems contribution."
- "What is actually novel here versus vendor tooling?"
- "Why is multi-cloud materially different?"
- "Where is the technical substance beyond reporting?"

If any of those objections feel valid after re-reading the Introduction, rewrite it.

### Definition of Done

- problem statement is concrete
- gap is specific
- contributions are crisp and defensible
- roadmap is clear
- introduction does not overclaim

### Minimum acceptable version

- 4 paragraphs plus a contribution list
- one architecture figure
- one roadmap paragraph

### Strong version

- sharply motivates the decision-engine framing
- includes one concrete NEC example and one governance example
- contributions sound like systems contributions, not project tasks

### Publication-ready version

- opening is memorable but technical
- contributions are precise, scoped, and later substantiated
- introduction creates a clear expectation that the paper will present architecture, formulas, and evidence

---

## Section 3 - Unified Cost Allocation Schema Design

### Why this section exists

This is one of the most important technical sections in the paper. It explains how three incompatible cloud billing schemas are mapped into one canonical structure that downstream algorithms can safely use.

### What reviewers expect

- exact schema problem statement
- explicit differences across AWS, Azure, and GCP
- clear mapping rationale
- why your canonical schema is sufficient for downstream decision logic
- acknowledgment of tradeoffs and schema evolution risk

### Common mistakes

- dumping a giant field list with no design rationale
- describing the schema without explaining why those fields were chosen
- pretending all three clouds expose identical concepts
- hiding tradeoffs such as grain mismatch, nullability, and cloud-specific semantics

### Detailed writing checklist

1. Start with the problem:
   - AWS CUR, Azure Cost Export, and GCP Billing Export expose different schemas and discount semantics.
2. Explain the role of CAS:
   - a canonical contract for all downstream stages
   - not just a reporting convenience
3. State the implemented CAS size and scope:
   - 31 columns in `fct_unified_billing`
4. Explain the design principles used to choose columns:
   - cross-cloud comparability
   - preservation of billing semantics
   - downstream support for attribution, NEC, governance, and decision logic
5. Group the CAS fields into logical families:
   - identity
   - time
   - cloud/account/project scope
   - pricing and NEC fields
   - ownership and tags
   - allocation outputs
   - governance and waste flags
6. Explain the major schema differences by cloud:
   - AWS effective-cost fields and fee rows
   - Azure amortized export and unused reservation rows
   - GCP credit-array semantics and unused reservation labeling
7. Explain the most important mapping decisions:
   - `list_cost`
   - `nec`
   - `nec_waste`
   - `discount_type`
   - `is_commitment_waste`
   - `allocated_team`
8. Explicitly discuss null behavior and cloud-specific fields.
9. Add a schema evolution subsection:
   - providers change billing exports
   - schema validators and layered modeling isolate breakage
10. End with why CAS enables the rest of the system.

### Required tables

- `Table 2` - CAS column families and purpose
  - columns: Column group, Representative fields, Why needed downstream
- `Table 3` - Cross-cloud mapping table
  - columns: CAS field, AWS source, Azure source, GCP source, Notes/tradeoffs
- `Table 4` - Semantic mismatch table
  - columns: Issue, AWS behavior, Azure behavior, GCP behavior, CAS resolution

### Required figures

- `Figure 2` - CAS architecture figure
  - per-cloud raw exports -> staging -> NEC intermediate models -> unified `fct_unified_billing`
- `Figure 3` - Schema transformation pipeline
  - raw fields -> normalized cloud-specific fields -> canonical CAS fields

### Required examples

- one worked example of how `list_cost`, `nec`, and `nec_waste` differ by cloud
- one worked example of a field present in one cloud but absent in another
- one example of a nullable CAS field and why null is acceptable

### Evidence checklist

- DESIGN_DOCUMENT Section 5 CAS definition
- `fct_unified_billing`
- staging models:
  - `stg_aws_cur.sql`
  - `stg_azure_cost.sql`
  - `stg_gcp_billing.sql`
- intermediate models:
  - `int_aws_nec.sql`
  - `int_azure_nec.sql`
  - `int_gcp_nec.sql`
- ingestion schema validators in `ingestion/schemas/`

### Validation checklist

- CAS column count in paper matches implementation.
- Mapping table uses actual source fields from code/docs.
- If you claim cross-cloud comparability, show the exact fields that make that possible.
- If you describe `nec`, `nec_waste`, or `discount_type`, definitions must match the NEC section exactly.

### Reviewer-objection checklist

- "Why these 31 columns and not more or fewer?"
- "Is this just an ad hoc field union?"
- "How does this survive schema drift from providers?"
- "What exactly is normalized versus left cloud-specific?"

### Definition of Done

- the section explains the schema as a design decision, not a spreadsheet dump
- mapping logic is explicit
- tradeoffs are named
- the reader understands why later algorithms depend on CAS

### Minimum acceptable version

- one CAS overview figure
- one cloud mapping table
- one paragraph on schema evolution

### Strong version

- schema principles are explicit
- includes a semantic mismatch table
- clearly explains why the schema is sufficient for allocation, NEC, and decision logic

### Publication-ready version

- reviewers can understand the entire data-contract layer from this section alone
- the mapping table is precise enough that another researcher could reimplement the schema logic

---

## Section 4 - Cost Allocation Strategies (Keerthi-owned portions only)

This section covers only the Keerthi-owned part:

- shared cost distribution
- allocation architecture
- allocation flow diagrams
- system-level integration

Do not rewrite Rishika-owned tag and untagged attribution content here. Coordinate boundaries cleanly.

### Why this section exists

Reviewers need to see how costs move from normalized billing records into team-accountable cost views, especially for shared infrastructure that does not naturally map to one owner.

### What reviewers expect

- formal allocation strategies
- why shared-cost distribution is needed
- where allocation occurs in the system
- how allocation outputs feed downstream analysis
- clear boundary between direct attribution and shared-cost spreading

### Common mistakes

- talking about allocation only conceptually, with no formulas
- not distinguishing direct cost from shared cost
- failing to show how allocation affects downstream NEC-by-team analysis
- mixing Keerthi-owned shared-cost logic with Rishika-owned attribution logic in a confusing way

### Detailed writing checklist

1. Open by explaining why normalized cost is still not decision-ready without team-accountable allocation.
2. Distinguish:
   - direct allocation
   - shared-cost allocation
   - unattributed cost
3. Explain where shared-cost logic lives in the pipeline.
4. Define the three distribution strategies formally:
   - proportional
   - even
   - weighted
5. For each strategy, state:
   - formula
   - when it is appropriate
   - what bias it introduces
6. Explain the architecture path:
   - normalized cloud rows
   - allocation layer
   - `allocated_team`
   - `allocated_nec`
   - downstream team-scoped marts and charts
7. Include one end-to-end shared-infrastructure walkthrough:
   - one shared subscription/project/account
   - cost fan-out across teams
   - preservation of total cost
8. Explain system-level integration:
   - team-level NEC
   - waste attribution by team
   - recommendation ownership
9. State tradeoffs:
   - allocation fairness versus operational simplicity
   - policy-driven weights versus empirical usage-driven weights
10. End with a short note that allocation quality affects downstream governance and optimization confidence.

### Required tables

- `Table 5` - Shared-cost strategy comparison
  - columns: Strategy, Formula, Required inputs, Best use case, Main drawback
- `Table 6` - Allocation integration points
  - columns: Allocation output field, Consumed by, Why it matters

### Required figures

- `Figure 4` - Allocation architecture diagram
  - CAS -> allocation engine -> team allocation outputs -> team-level marts
- `Figure 5` - Shared-cost allocation workflow
  - identify shared rows -> select strategy -> distribute -> validate sum preservation

### Required examples

- one example of proportional allocation
- one example of even allocation
- one example of weighted allocation
- one example showing total allocated cost equals original shared cost

### Mathematical formulas to include

Use formal notation, not just prose:

```text
Proportional:
share_i = direct_nec_i / sum_j direct_nec_j
allocated_shared_i = shared_pool * share_i

Even:
share_i = 1 / N
allocated_shared_i = shared_pool / N

Weighted:
share_i = weight_i / sum_j weight_j
allocated_shared_i = shared_pool * share_i
```

### Evidence checklist

- `allocation/shared_cost.py`
- `allocation/nec_model.py`
- `dashboard/pages/02_allocation.py`
- any shared-cost examples in DESIGN_DOCUMENT and README
- `fct_unified_billing` fields:
  - `allocated_team`
  - `allocated_nec`
  - `is_shared_cost`

### Validation checklist

- confirm formulas match implementation
- verify cost preservation:
  - sum of allocated shares equals original shared pool
- verify the paper clearly states shared-cost logic is policy-driven
- confirm section boundary with Rishika's attribution subsection is explicit

### Reviewer-objection checklist

- "Why these three strategies?"
- "How do you know allocation does not distort totals?"
- "What happens when there is no defensible weighting signal?"
- "Is the allocation engine separate from NEC, or does it double-count?"

### Definition of Done

- formulas are explicit
- architecture is shown
- one preserved-sum example is included
- system integration is clear

### Minimum acceptable version

- one strategy comparison table
- one workflow figure
- formulas for all three strategies

### Strong version

- includes policy rationale and tradeoff analysis
- includes one shared-infra real example from repo scenarios
- explains downstream impact on team-scoped intelligence

### Publication-ready version

- the section reads like a carefully designed allocation subsystem, not a billing afterthought
- a reviewer could compare strategies and understand why the repo exposes all three

---

## Section 5 - Net Effective Cost Modeling

### Why this section exists

This section establishes financial correctness. If reviewers do not trust NEC, they will not trust any downstream results.

### What reviewers expect

- why raw billing cost is misleading
- exact NEC definitions
- per-cloud formulas
- explicit treatment of commitment waste
- worked examples
- some form of validation or consistency check

### Common mistakes

- treating NEC as obvious
- giving only one cloud's formula
- not separating `nec_used` from `nec_waste`
- hand-waving validation
- failing to explain why `unblended_cost` is wrong for commitment-backed usage

### Detailed writing checklist

1. Start by defining the problem with naive cost fields.
2. Define all core terms:
   - `list_cost`
   - `nec_used`
   - `nec_waste`
   - `nec`
   - `discount_type`
3. Explain why NEC is the cross-cloud economic baseline.
4. Write AWS formulas:
   - `Usage`
   - `DiscountedUsage`
   - `SavingsPlanCoveredUsage`
   - `RIFee`
   - `SavingsPlanRecurringFee`
5. Write Azure formulas:
   - normal amortized usage
   - `UnusedReservation`
   - `UnusedSavingsPlan`
6. Write GCP formulas:
   - cost plus negative credits
   - clamping at zero
   - unused reservation/CUD treatment
7. Explain waste separation rationale:
   - used cost must not absorb idle commitment cost
   - waste is an optimization signal, not consumed workload cost
8. Include 3-5 worked examples with numbers.
9. Include one subsection explicitly titled "Why naive cost approaches fail."
10. Add validation methodology:
   - formula-level validation
   - cross-cloud consistency checks
   - back-comparison to cloud-native semantics where possible
11. End by connecting NEC to downstream metrics such as commitment utilization, savings, and waste detection.

### Required tables

- `Table 7` - NEC term definitions
  - columns: Term, Definition, Why it exists
- `Table 8` - Per-cloud NEC formula summary
  - columns: Cloud, Row type, `nec_used`, `nec_waste`, Notes
- `Table 9` - Naive-cost versus NEC comparison
  - columns: Scenario, Naive field result, NEC result, Why NEC is correct

### Required figures

- `Figure 6` - NEC decomposition figure
  - list cost -> NEC used + savings; commitment fee rows isolated as waste
- `Figure 7` - Cross-cloud NEC treatment comparison
  - small panel diagram for AWS, Azure, GCP semantics

### Required examples

- AWS RI-covered usage example
- AWS unused RI or unused SP example
- Azure unused reservation example
- GCP credit-based discount example
- one "negative NEC would occur without clamp" example for GCP

### NEC equations to include

Use exact notation consistent with implementation:

```text
AWS:
nec_used =
  reservation_effective_cost           for DiscountedUsage
  savings_plan_effective_cost          for SavingsPlanCoveredUsage
  unblended_cost                       for Usage

nec_waste =
  reservation_unused_upfront_fee + reservation_unused_recurring_fee
                                        for RIFee
  savings_plan_recurring_commitment - savings_plan_used_commitment
                                        for SavingsPlanRecurringFee

Azure:
nec_used = billed_cost                 for non-UnusedReservation/non-UnusedSavingsPlan rows
nec_waste = billed_cost                for UnusedReservation/UnusedSavingsPlan rows

GCP:
nec_used = max(list_cost + total_credit_amount, 0)
nec_waste = list_cost                  for unused reservation rows
```

### Comparison against naive approaches

You must explicitly compare against at least these naive baselines:

- AWS `unblended_cost`
- "single billed amount" without waste separation
- "discounted total cost" without identifying idle commitment rows

### Evidence checklist

- `docs/NEC_CALCULATIONS.md`
- `allocation/nec_model.py`
- `int_aws_nec.sql`
- `int_azure_nec.sql`
- `int_gcp_nec.sql`
- tests:
  - `tests/test_nec_model.py`
  - any dbt-level checks on intermediate models

### Validation checklist

- formula names exactly match implementation field names
- examples sum correctly
- NEC definitions are identical everywhere in the paper
- waste rows are never accidentally described as consumed cost

### Reviewer-objection checklist

- "Why is NEC needed if cloud bills already have cost fields?"
- "Is NEC really comparable across all three providers?"
- "How do you avoid double-counting fees and covered usage?"
- "What evidence shows the formulas are internally consistent?"

### Definition of Done

- reviewer can reconstruct NEC logic for all three clouds
- worked examples make the need for NEC obvious
- validation methodology is concrete
- naive baselines are explicitly shown to be misleading

### Minimum acceptable version

- one term-definition table
- one formula table
- one worked example per cloud

### Strong version

- includes a naive-versus-NEC comparison table
- includes one equation block and one decomposition figure
- clearly isolates `nec_waste`

### Publication-ready version

- this section becomes a reusable reference for other researchers implementing cross-cloud NEC
- financial semantics are precise enough that reviewers trust downstream results

---

## Decision Intelligence Sections

This guide groups the Keerthi-owned decision-intelligence material into one execution block. In the paper, you may split it into separate sections or subsections, but the writing workflow should be coordinated.

Covered here:

- Waste Detection Engine
- Causal Reasoning Engine
- Impact Simulation Engine
- Recommendation Scoring
- Forecasting
- Lifecycle Validation

### Why these sections exist

These sections are where the paper moves from "normalized cost accounting" to "decision support." They must show that the system:

- identifies optimization or governance signals
- explains them
- maps them to actions
- ranks actions reproducibly
- estimates impact conservatively
- validates outcomes or at least tracks them in a lifecycle-ready way

### What reviewers expect

- a clear decision pipeline
- deterministic methods, not vague heuristics
- interpretable signals and actions
- auditable scoring
- evidence of validation, even if benchmarked on synthetic data

### Common mistakes

- collapsing all intelligence layers into one blurry section
- sounding like ML without actually presenting a real model
- giving scores without formulas
- mixing governance recommendations with savings recommendations carelessly
- presenting forecast numbers without minimum-data conditions or uncertainty bounds

---

### Subsection - Waste Detection Engine

#### Why this subsection exists

It defines what the system considers waste and how waste is surfaced from billing data.

#### What reviewers expect

- a finite taxonomy
- explicit signals and thresholds
- confidence treatment
- clear caveat that some signals are billing proxies, not runtime telemetry

#### Common mistakes

- using "waste" as an informal label
- mixing governance gaps and usage waste without saying so
- hiding thresholds
- claiming telemetry accuracy when only billing-derived proxies exist

#### Detailed writing checklist

1. Define the waste taxonomy:
   - unused commitment
   - underutilized commitment
   - idle compute proxy
   - zombie resource
2. For each type, state:
   - trigger condition
   - required inputs
   - confidence level
   - known limitation
3. Explain where thresholds come from.
4. Explain why `unused_commitment` is deterministic while `idle_compute_proxy` is not.
5. Include one example finding per waste type.
6. State clearly that billing-side idle detection is a proxy and not runtime telemetry.

#### Required tables

- `Table 10` - Waste taxonomy
  - columns: Waste type, Detection signal, Threshold, Confidence basis, Limitation

#### Required figures

- `Figure 8` - Waste detection flow
  - unified billing -> detector -> typed findings with confidence

#### Required examples

- one example each for unused commitment, idle compute proxy, zombie resource, underutilized commitment

#### Evidence checklist

- `intelligence/waste_detector.py`
- `config/waste_thresholds.yml`
- `tests/test_waste_detector.py`
- dashboard waste page screenshots

#### Validation checklist

- thresholds reported in paper match config
- confidence rationale matches implementation
- caveats on proxy detection are explicit

#### Reviewer-objection checklist

- "Is this just threshold hacking?"
- "What is deterministic versus approximate?"
- "How do you know idle compute without telemetry?"

#### Definition of Done

- taxonomy is explicit
- thresholds are visible
- proxy limitations are acknowledged

#### Minimum acceptable version

- one taxonomy table
- one flow diagram

#### Strong version

- includes representative examples and detector limitations

#### Publication-ready version

- reader can understand exactly what is and is not being claimed about waste detection accuracy

---

### Subsection - Causal Reasoning Engine

#### Why this subsection exists

It explains how the system moves from detected signals to interpretable explanations at team or account scope.

#### What reviewers expect

- structured facts, not hand-written narrative
- how temporal reasoning is used when multiple months exist
- anomaly treatment
- root-cause ranking logic

#### Common mistakes

- calling it "causal" without defining what evidence is actually used
- implying true causal inference when the system is really structured reasoning over billing facts
- not explaining single-month versus multi-month behavior

#### Detailed writing checklist

1. Define the engine as structured reasoning over billing-derived facts.
2. Explain the two operating modes:
   - single-month mode
   - multi-month mode
3. List the fact types used.
4. Explain trend and anomaly logic:
   - month-over-month change
   - z-score anomaly threshold
5. Explain how root causes are ranked by confidence.
6. Include one team-level walkthrough:
   - signal set
   - derived facts
   - resulting ranked explanation
7. State limits:
   - no external observability
   - no deep causal inference over infrastructure events

#### Required tables

- `Table 11` - Causal fact types and evidence
  - columns: Fact type, Trigger source, Scope, Confidence basis

#### Required figures

- `Figure 9` - Causal reasoning pipeline
  - findings + historical aggregates -> facts -> ranked root causes

#### Required examples

- one single-month example
- one multi-month anomaly example

#### Evidence checklist

- `intelligence/causal_engine.py`
- `tests/test_causal_engine.py`
- decision/intelligence screenshots
- `fct_finops_signals.sql` for anomaly and trend signal creation

#### Validation checklist

- use "structured reasoning" language consistently
- do not imply intervention-based causal inference
- anomaly thresholds match implementation

#### Reviewer-objection checklist

- "Why call this causal reasoning?"
- "What exactly is the evidence chain?"
- "How does this differ from a simple anomaly alert?"

#### Definition of Done

- the reader understands what evidence enters the engine
- confidence and ranking are transparent
- the causal terminology is carefully scoped

#### Minimum acceptable version

- fact table plus one pipeline figure

#### Strong version

- includes one fully worked walkthrough

#### Publication-ready version

- reviewers see this as an explainability layer over cost signals, not inflated causal language

---

### Subsection - Impact Simulation Engine and Recommendation Scoring

#### Why this subsection exists

It explains how findings turn into actions and how the system prioritizes them in an auditable way.

#### What reviewers expect

- explicit signal-to-action mapping
- conservative recovery assumptions
- risk treatment
- priority-score formula
- evidence that ranking is deterministic

#### Common mistakes

- giving action labels without mapping logic
- describing scoring qualitatively without equations
- forgetting to separate recoverable, actionable, and projected savings
- hiding assumptions behind "business logic"

#### Detailed writing checklist

1. Explain that recommendations are derived from canonical signals, not free-form text.
2. Show the signal-to-action mapping table.
3. State recovery assumptions for each action type.
4. Explain risk, urgency, governance severity, and low-risk bonus inputs.
5. Present the full priority-score formula.
6. Explain confidence calibration:
   - boost from coincident signals
   - boost from longer data windows
   - penalty for anomaly-only support
7. Separate:
   - modeled opportunity
   - estimated savings
   - actionable savings
   - projected realized savings
8. Include one recommendation walkthrough from raw signal to final rank.
9. State that governance findings and optimization findings are both first-class but represent different operational categories.

#### Required tables

- `Table 12` - Signal-to-action mapping
  - columns: Signal type, Action, Recovery rate, Risk level, Evidence type
- `Table 13` - Priority-score components
  - columns: Component, Meaning, Range, Why included

#### Required figures

- `Figure 10` - Decision pipeline figure
  - signal -> root cause -> action -> score -> recommendation
- `Figure 11` - Savings hierarchy figure
  - waste signal -> recoverable -> actionable -> projected realized

#### Required examples

- one commitment waste recommendation
- one idle compute recommendation
- one governance recommendation with zero direct savings

#### Required formulas

Use equations consistent with implementation and methodology docs:

```text
priority_score =
  0.35 * normalized_savings
  + 0.25 * confidence
  + 0.20 * governance_severity
  + 0.10 * urgency
  + 0.10 * low_risk_bonus
```

Also define:

```text
normalized_savings = estimated_savings / max_savings_in_scope
```

And explain that realization-adjusted projection is computed after actionability and realization-rate modeling.

#### Evidence checklist

- `dbt_project/models/marts/fct_finops_signals.sql`
- `dbt_project/models/marts/fct_finops_recommendations.sql`
- `dashboard/_shared.py`
- `tests/test_scoring.py`
- `tests/test_decision_engine.py`
- `tests/test_impact_simulator.py`

#### Validation checklist

- score formula matches code/docs exactly
- action mappings match canonical tables
- recovery rates are consistent across prose, tables, and figures
- governance recommendations are not mislabeled as direct savings

#### Reviewer-objection checklist

- "Why these weights?"
- "Are recommendations deterministic or page-local heuristics?"
- "How is confidence calibrated?"
- "Do governance findings pollute the savings ranking?"

#### Definition of Done

- formula is explicit
- signal-to-action mapping is explicit
- savings layers are separated
- a full recommendation walkthrough is included

#### Minimum acceptable version

- one mapping table
- one score formula
- one savings hierarchy figure

#### Strong version

- includes a recommendation walkthrough and confidence-calibration explanation

#### Publication-ready version

- reviewers can trace any recommendation from signal to ranking without ambiguity

---

### Subsection - Forecasting

#### Why this subsection exists

Forecasting turns the system from retrospective diagnosis into forward-looking decision support.

#### What reviewers expect

- a clearly defined forecast model
- minimum-data conditions
- uncertainty treatment
- backtesting or accuracy evidence

#### Common mistakes

- claiming predictive sophistication that is not present
- not stating that the model is deterministic and lightweight
- giving forecast confidence without explaining how it is computed

#### Detailed writing checklist

1. Define the forecasting objective:
   - projected month-end NEC
   - projected waste and unattributed spend
   - projected savings after realization adjustment
2. State the formal method:
   - current month run rate
   - trailing 3-month average
   - 70/30 blend when enough history exists
3. Explain the fallback when fewer than 3 prior months exist.
4. Explain realization-rate logic by action mix.
5. Explain confidence and error bounds.
6. Explain forecast risk levels.
7. Include one numeric example:
   - current MTD NEC
   - historical average
   - blended forecast
8. Include backtesting methodology using the first-half-month proxy.
9. State limitations:
   - not a probabilistic model
   - dependent on recent billing stability

#### Required tables

- `Table 14` - Forecast output fields
  - columns: Output, Meaning, Source logic
- `Table 15` - Forecast backtest summary
  - columns: Evaluations, MAE, MAPE, Within-10-percent rate, Method

#### Required figures

- `Figure 12` - Forecasting data flow
  - monthly rollup + recommendations -> forecast outputs
- `Figure 13` - Forecast versus actual chart
  - per month: actual NEC, forecast NEC, error band

#### Required examples

- one worked 70/30 blend example
- one sparse-history fallback example

#### Evidence checklist

- `intelligence/forecasting.py`
- `fct_month_end_forecast.sql`
- `fct_forecast_backtest`
- `fct_model_accuracy.sql`
- `tests/test_forecasting.py`

#### Validation checklist

- formula exactly matches implementation
- confidence interpretation is explained
- backtest metrics are correctly defined
- uncertainty bounds are not oversold as statistical guarantees

#### Reviewer-objection checklist

- "Why this forecast model instead of something more advanced?"
- "Is there enough data for the blend to be meaningful?"
- "What evidence shows the forecast is at least directionally useful?"

#### Definition of Done

- model is explicit
- fallback logic is explicit
- backtest evidence is included
- limitations are honest

#### Minimum acceptable version

- one formula paragraph
- one backtest table

#### Strong version

- includes forecast-versus-actual figure and uncertainty explanation

#### Publication-ready version

- reviewers see the forecast as lightweight, transparent, and appropriately scoped

---

### Subsection - Lifecycle Validation

#### Why this subsection exists

This subsection shows that recommendations are not treated as one-shot outputs. The system tracks recommendation status and supports realized-versus-expected comparison.

#### What reviewers expect

- lifecycle states
- realized-versus-expected savings logic
- why this matters for calibration and trust

#### Common mistakes

- mentioning lifecycle tracking only in passing
- not stating current scope limitations
- implying mature production workflow automation when the repo implements local/demo persistence

#### Detailed writing checklist

1. Define the lifecycle states:
   - recommended
   - approved/rejected
   - implemented
   - verified
2. Explain where lifecycle state is stored.
3. Explain expected versus realized savings comparison.
4. Explain how accuracy percentage is computed and aggregated.
5. Connect lifecycle validation to future recommendation calibration.
6. State current limitation:
   - demo/local state machine, not enterprise workflow orchestration

#### Required tables

- `Table 16` - Recommendation lifecycle states
  - columns: State, Meaning, Required evidence
- `Table 17` - Model-accuracy summary
  - columns: Action type, Evaluation count, Avg accuracy, Avg confidence, Calibration gap

#### Required figures

- `Figure 14` - Lifecycle validation flow
  - recommendation -> action state -> realized savings -> accuracy/calibration mart

#### Required examples

- one example recommendation with expected savings and realized savings

#### Evidence checklist

- `fct_action_lifecycle.sql`
- `fct_model_accuracy.sql`
- `data/recommendation_actions_flat.csv`
- dashboard lifecycle-related logic in `_shared.py`

#### Validation checklist

- lifecycle states in prose match actual implementation
- any accuracy metric described is reproducible from `fct_model_accuracy`
- demo/local limitation is clearly stated

#### Reviewer-objection checklist

- "Is this real closed-loop validation or only a placeholder?"
- "What is already implemented versus future work?"

#### Definition of Done

- lifecycle is concrete
- validation outputs are concrete
- current scope boundary is honest

#### Minimum acceptable version

- one lifecycle-state table
- one diagram

#### Strong version

- includes model-accuracy summary table

#### Publication-ready version

- reviewers see a credible closed-loop direction, even if benchmarked in a synthetic/demo setting

---

## Section 8 - Conclusion and Future Work

### Why this section exists

The Conclusion should leave reviewers with a clear memory of what the system contributed, what was validated, and what remains open.

### What reviewers expect

- concise recap of contributions
- honest limitations
- concrete future directions

### Common mistakes

- repeating the abstract
- adding brand-new claims
- vague future work like "more optimization"
- hiding limitations until the very end

### Detailed writing checklist

1. Restate the central problem in one sentence.
2. Summarize the architecture-level contributions:
   - CAS
   - NEC
   - allocation
   - decision intelligence
   - forecasting/lifecycle readiness
3. Summarize evaluation/evidence in one paragraph.
4. State the key limitations:
   - synthetic benchmark
   - no runtime telemetry
   - no autonomous remediation
   - demo/local workflow persistence
5. Give 3-5 specific future directions:
   - telemetry-backed idle detection
   - real enterprise billing validation
   - stronger action calibration from real realization data
   - production workflow integration
   - scale-out execution platform

### Required tables

No mandatory table here unless space allows.

### Required figures

No new mandatory figure. Reuse earlier evidence.

### Required examples

No example required, but one sentence tying future work to current limitation is useful.

### Evidence checklist

- all contribution bullets from Introduction
- limitations already named in README and DESIGN_DOCUMENT

### Validation checklist

- no new unsupported claims
- limitations align with actual repo scope

### Reviewer-objection checklist

- "Did the authors overstate what was validated?"
- "Do the future-work items logically follow from the current design?"

### Definition of Done

- concise
- honest
- specific

### Minimum acceptable version

- one contribution paragraph
- one limitation paragraph
- one future-work paragraph

### Strong version

- cleanly ties contributions to evidence and limitations to next steps

### Publication-ready version

- closes the paper with confidence and technical restraint

---

## Section A - Figure Creation Guide

This section tells you which figures are mandatory, which are optional, and what each figure must prove.

### Figure principles

Every figure must do one of three things:

- explain architecture
- explain methodology
- present evidence

If a figure only decorates the paper, cut it.

### Mandatory architecture/method figures

- `Figure 1` - End-to-end system overview
- `Figure 2` - CAS architecture / normalization pipeline
- `Figure 4` - Allocation architecture
- `Figure 5` - Shared-cost workflow
- `Figure 6` - NEC decomposition
- `Figure 8` - Waste detection flow
- `Figure 9` - Causal reasoning pipeline
- `Figure 10` - Decision pipeline
- `Figure 11` - Savings hierarchy
- `Figure 12` - Forecasting data flow
- `Figure 14` - Lifecycle validation flow

### Mandatory benchmark/evidence figures

- forecast versus actual chart
- recommendation distribution by risk or action type
- NEC or unattributed-cost summary chart by cloud/team
- one screenshot figure of the dashboard only if it reinforces evidence presentation, not as a substitute for system design

### Optional figures

- per-cloud schema-difference panel
- calibration plot by confidence bucket
- figure showing signal counts by type
- figure showing action-state distribution across lifecycle stages

### Charts you should generate from the benchmark

1. NEC by cloud
2. Unattributed NEC percentage by cloud/team
3. Commitment waste by cloud/team
4. Recommendation counts by signal type and action type
5. Savings layers chart:
   - waste signal
   - recoverable
   - actionable
   - projected realized
6. Forecast backtest chart:
   - actual NEC
   - forecast NEC
   - lower/upper bounds
7. Lifecycle accuracy chart:
   - expected versus realized savings by action type or confidence bucket

### Figure creation checklist

- title states the point, not just the object
- axes are labeled with units
- all dollar values use consistent format
- clouds and teams use consistent colors across figures
- legends are readable in grayscale print if possible
- caption explains the takeaway, not just the content

### Figure caption checklist

Every caption should answer:

- what is shown
- what the reader should notice
- why it matters to the paper's claim

### Definition of Done for figures

- every major section has at least one figure that clarifies a technical idea
- evidence figures are query-backed and reproducible
- no figure exists just to show the dashboard UI

---

## Section B - Experimental Evidence Guide

This section defines the exact evidence package you need for Keerthi-owned claims.

### General rule

For each claim category, produce:

- one summary table
- one supporting figure
- one validation note explaining what the evidence can and cannot prove

---

### B1 - Evidence for NEC Modeling

#### What this evidence must support

- NEC is defined consistently across clouds
- NEC differs materially from naive cost fields when commitments apply
- waste is separated from consumed cost

#### Exact tables to generate

- `Table E1` - NEC worked-example comparison
  - columns: Cloud, Scenario, Naive cost, NEC used, NEC waste, Interpretation
- `Table E2` - Cloud-level NEC summary
  - columns: Cloud, List cost, NEC, NEC waste, Savings, Savings percentage
- `Table E3` - Commitment utilization summary
  - columns: Cloud, Discount type, NEC used, NEC waste, Utilization percentage

#### Exact metrics to report

- total list cost
- total NEC
- total NEC waste
- savings = list cost - NEC
- savings percentage
- commitment utilization percentage

#### Validation note to include

This evidence shows financial normalization behavior and internal consistency. It does not yet prove enterprise-scale external ground-truth validation.

---

### B2 - Evidence for Recommendation Scoring

#### What this evidence must support

- recommendations are generated from canonical signals
- scoring is deterministic and decomposable
- high-ranked items are not arbitrary

#### Exact tables to generate

- `Table E4` - Top recommendations with score decomposition
  - columns: Recommendation ID, Signal type, Action, Estimated savings, Confidence, Governance severity, Urgency, Low-risk bonus, Priority score
- `Table E5` - Signal-to-action summary
  - columns: Signal type, Action type, Count, Avg modeled opportunity, Avg estimated savings, Avg risk
- `Table E6` - Recommendations by risk band
  - columns: Risk band, Count, Total estimated savings, Total projected savings

#### Exact metrics to report

- number of signals
- number of recommendations
- average and max priority score
- total modeled opportunity
- total estimated savings
- total projected realized savings
- share of low-risk recommendations
- share of governance-only recommendations

#### Validation note to include

This evidence shows deterministic ranking behavior and score transparency. It does not prove that ranking is globally optimal.

---

### B3 - Evidence for Forecasting

#### What this evidence must support

- the forecast is explicit
- the system reports uncertainty and minimum-data conditions
- the forecast is backtested

#### Exact tables to generate

- `Table E7` - Forecast output summary
  - columns: Team/cloud, Current MTD NEC, Trailing 3-month avg NEC, Forecast NEC, Projected savings, Optimized NEC, Confidence, Risk level
- `Table E8` - Forecast backtest summary
  - columns: Evaluations, MAE (USD), MAPE (%), Within-10-percent rate, Method
- `Table E9` - Per-month backtest details
  - columns: Billing month, Actual NEC, Forecast NEC, Absolute error, Absolute percent error, Accuracy percent

#### Exact metrics to report

- projected month-end NEC
- projected savings
- optimized NEC
- forecast confidence
- MAE
- MAPE
- within-10-percent rate
- number of evaluations

#### Validation note to include

This evidence supports the utility of a lightweight deterministic forecast on the benchmark. It does not establish superiority over more advanced predictive models.

---

### B4 - Evidence for Governance Metrics and Lifecycle Validation

#### What this evidence must support

- unattributed cost is measurable
- governance signals are surfaced as first-class issues
- recommendation outcomes can be tracked against expectations

#### Exact tables to generate

- `Table E10` - Governance summary
  - columns: Cloud/team, NEC, Unattributed NEC, Tagging gap, Shared-cost concentration, Governance signals count
- `Table E11` - Lifecycle state summary
  - columns: Status, Count, Expected savings sum, Realized savings sum
- `Table E12` - Accuracy and calibration summary
  - columns: Action type or confidence bucket, Evaluation count, Avg accuracy percent, Avg confidence percent, Calibration gap

#### Exact metrics to report

- unattributed NEC
- tagging gap percentage
- governance signal count
- action counts by lifecycle state
- realized versus expected savings
- average accuracy percentage
- calibration gap by bucket

#### Validation note to include

This evidence supports lifecycle readiness and calibration analysis inside the benchmarked system. It does not yet constitute full enterprise workflow validation.

---

### B5 - Evidence assembly order

Generate evidence in this order:

1. NEC summary and worked examples
2. CAS and allocation tables
3. signal and recommendation summaries
4. scoring decomposition table
5. forecast summary and backtest
6. lifecycle and calibration tables

This order matters because later tables depend on earlier definitions being stable.

---

## Section C - Final Paper Readiness Checklist

Use this at the very end. Do not submit without checking every line.

### Technical accuracy

- all formulas match implementation
- all field names are used consistently
- all sections distinguish design from evaluation
- all numbers in abstract, intro, results, and conclusion match final tables
- all limitations are technically honest

### Novelty and contribution clarity

- contributions are systems contributions, not task lists
- CAS contribution is explicit
- NEC contribution is explicit
- decision-engine contribution is explicit
- forecast/lifecycle contribution is scoped correctly
- the paper clearly differentiates itself from descriptive FinOps tooling and from FOCUS as a specification

### Reproducibility

- every reported number comes from a saved query, notebook, or script
- artifact names in the paper match repo artifacts
- synthetic benchmark setup is documented clearly
- evaluation tables can be regenerated from repo state

### Figures

- all mandatory figures exist
- captions explain the takeaway
- style and colors are consistent
- exported figures are high resolution and readable in two-column format
- no figure is purely decorative

### Tables

- every major claim has at least one supporting table
- tables use consistent units and terminology
- table captions state the point
- tables are not overloaded with low-value columns

### Citations

- FinOps motivation is cited
- multi-cloud and billing heterogeneity context is cited
- vendor-tool gap statements are cited carefully
- any comparison to FOCUS is cited correctly
- no claim about industry prevalence is left uncited unless framed clearly as motivation rather than measured result

### Methodology disclosure

- if AI-assisted development or writing support is disclosed, it is described briefly and factually
- the disclosure makes clear that final technical verification was performed by the authors
- tooling disclosure is not presented as part of the novelty claim

### Limitations

- synthetic benchmark limitation is explicit
- no runtime telemetry limitation is explicit
- no autonomous remediation limitation is explicit
- demo/local lifecycle persistence limitation is explicit
- any GCP/AWS/Azure semantics caveats are included where relevant

### Artifact readiness

- repo structure in paper matches actual repo
- screenshots used in paper correspond to current system behavior
- notebooks or query files used for evidence are cleaned and rerunnable
- benchmark outputs are stored or reproducible

### GitHub readiness

- README framing matches paper framing
- docs referenced in paper exist and are current
- no stale file names or outdated screenshots remain
- benchmark data and commands required for reproduction are present

### Submission readiness

- page count and figure/table count fit the target venue envelope
- abstract, introduction, and conclusion use the same framing
- section ownership boundaries are clean between you and Rishika
- the paper does not oversell evaluation beyond the evidence
- all figures and tables are referenced in the text
- the paper reads as one coherent systems story, not two stitched project reports

---

## Final Definition of Done

You are done only when all of the following are true:

1. Every Keerthi-owned section has:
   - a thesis
   - explicit claims
   - evidence
   - at least one figure or table
   - a limitation statement
2. Every numeric claim in those sections is reproducible.
3. Every formula matches implementation.
4. The paper consistently presents the system as a multi-cloud FinOps decision engine.
5. The benchmark evidence is strong enough for a workshop/conference-quality systems submission without pretending to be production validation.

If even one of those is false, the paper is not ready.

---

## Practical Execution Order

Follow this order exactly:

1. Lock terminology and definitions first.
2. Build the evidence tables next.
3. Create the mandatory figures after the tables are stable.
4. Write Section 3 and Section 5 first.
5. Write the decision-intelligence sections next.
6. Write the Introduction after the technical sections exist.
7. Write the Conclusion last.
8. Run the final readiness checklist.

This sequence reduces rewrite churn. If you write the Introduction first, you will almost certainly overpromise.

### Current coordination note

As of 2026-05-29, Keerthi's paper-writing work is intentionally paused until Rishika completes her current tasks. Do not treat the remaining items in this guide as abandoned; treat them as queued work. Resume Keerthi-owned writing only after:

1. Rishika's pending tasks are complete.
2. Shared repo artifacts needed by both authors are stable.
3. Any figures, benchmark outputs, or section-boundary dependencies from Rishika's side are finalized enough to avoid rewrite churn.

When resuming, restart from this guide's execution order rather than jumping straight into prose edits.

---

## One-Sentence Reminder

The paper will be strongest if it argues this clearly and repeatedly:

**The contribution is an explainable, reproducible, multi-cloud FinOps decision engine built on canonical NEC normalization, explicit allocation semantics, auditable scoring, and lifecycle-aware validation outputs.**

---

*This guide is for the `multicloud-finops-framework` repository and is intended to support production of a submission-ready systems paper draft without guesswork.*
