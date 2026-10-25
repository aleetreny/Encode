.PHONY: demo demo-check test record-demo incidents

demo:
	./scripts/demo.sh

demo-check:
	./scripts/demo.sh --check-only

test:
	pytest -q && cd frontend && npm run build

record-demo:
	python3 scripts/record_demo_stream.py

incidents:
	python3 scripts/build_incident_library.py
