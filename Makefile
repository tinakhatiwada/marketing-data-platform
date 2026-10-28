.PHONY: install demo demo-anomaly dashboard test lint docs clean

install:            ## install the package with dev tools
	pip install -e ".[dev]"

demo:               ## full pipeline on 90 days of synthetic data → DuckDB
	adpulse run --mode demo --days 90

demo-anomaly:       ## same, with a spend spike on the last day to show alerting
	-adpulse run --mode demo --inject-anomaly
	@echo "(exit code 1 above is expected: the spend-anomaly check failed the run)"
	@adpulse run --mode demo > /dev/null 2>&1 && echo "re-ran clean demo to restore normal data"

dashboard:          ## local Streamlit dashboard over the demo warehouse
	streamlit run app.py

test:               ## unit + end-to-end tests
	pytest -q

lint:
	ruff check src tests scripts app.py

docs:               ## dbt docs (lineage graph + column definitions) as one HTML file
	cd dbt && dbt docs generate --profiles-dir . --target local --static
	@echo "open dbt/target/static_index.html"

clean:
	rm -rf warehouse dbt/target dbt/logs
