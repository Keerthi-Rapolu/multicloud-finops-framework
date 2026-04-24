.PHONY: help data dbt test pipeline dashboard demo clean

MONTH ?= 2026-03
SCENARIO ?= normal

help:
	@echo "Multi-Cloud FinOps Framework"
	@echo ""
	@echo "Usage: make <target> [MONTH=YYYY-MM] [SCENARIO=name]"
	@echo ""
	@echo "  data       Generate synthetic data and land to data/raw/"
	@echo "  dbt        Run all dbt models (staging → intermediate → marts)"
	@echo "  test       Run unit tests"
	@echo "  pipeline   Full pipeline: data + dbt + test"
	@echo "  dashboard  Launch the Streamlit dashboard (reads from DuckDB)"
	@echo "  demo       pipeline then dashboard (single command for local demo)"
	@echo "  clean      Remove dbt target artifacts and DuckDB file"
	@echo ""
	@echo "Examples:"
	@echo "  make pipeline"
	@echo "  make pipeline MONTH=2026-04 SCENARIO=untagged-heavy"
	@echo "  make data SCENARIO=ri-heavy MONTH=2026-03"

data:
	python load_synthetic.py --month $(MONTH) --scenario $(SCENARIO) --force

dbt:
	cd dbt_project && dbt run --full-refresh

test:
	pytest tests/ -v

pipeline: data dbt test

dashboard:
	@echo ""
	@echo "Dashboard running at: http://localhost:8501"
	@echo ""
	streamlit run dashboard/app.py

demo: pipeline dashboard

clean:
	rm -rf dbt_project/target dbt_project/dbt_packages
	rm -f finops_dbt.duckdb
