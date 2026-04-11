.PHONY: tree validate ingest review promote query lint test index

tree:
	find . -maxdepth 4 | sort

validate:
	python scripts/lint/main.py --mode validate

ingest:
	python scripts/ingest/main.py --help

review:
	python scripts/review/main.py --help

promote:
	python scripts/promote/main.py --help

query:
	python scripts/query/main.py --help

index:
	python scripts/index/main.py --target all --rebuild

lint:
	python scripts/lint/main.py --mode lint

test:
	pytest -q
