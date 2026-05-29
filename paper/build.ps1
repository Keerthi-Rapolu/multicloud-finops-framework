$ErrorActionPreference = "Stop"

pdflatex -interaction=nonstopmode main.tex | Out-Host

if (Test-Path ".\references.bib") {
    bibtex main | Out-Host
}

pdflatex -interaction=nonstopmode main.tex | Out-Host
pdflatex -interaction=nonstopmode main.tex | Out-Host

Write-Host "Build complete: paper/main.pdf"
