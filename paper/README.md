# Paper Workspace

This directory contains the LaTeX manuscript for the Multi-Cloud FinOps Decision Engine paper.

## Build

From this directory:

```powershell
powershell -ExecutionPolicy Bypass -File .\build.ps1
```

The output PDF is `main.pdf`.

## Structure

- `main.tex`: paper entrypoint
- `sections/`: per-section manuscript files
- `references.bib`: bibliography
- `notes/evidence_matrix.md`: section-to-evidence checklist
- `figures/FIGURE_PLAN.md`: figure plan and restoration notes

## Current State

The manuscript compiles, but this workspace has been partially reconstructed after local generated artifacts disappeared. The current LaTeX draft contains the paper text and bibliography, but some earlier generated figure assets, query outputs, and helper scripts may need to be regenerated or restored separately.
