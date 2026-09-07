.PHONY: setup dev verify doctor migrate integration stop
setup dev verify doctor migrate integration stop:
	python3 scripts/dev.py $@
