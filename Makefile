.PHONY: test release-manifest
test:
	python3 -m unittest discover -s tests -p 'test_*.py'
	@for script in scripts/*.sh; do bash -n "$$script" || exit; done
release-manifest:
	python3 scripts/release.py
