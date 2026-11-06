.PHONY: deb dev serve test

deb:   ## rebuild the .deb and install it (sudo)
	sh desktop/scripts/reinstall-deb.sh

dev:   ## run the desktop app from this clone (no .deb, no sudo)
	sh desktop/scripts/dev.sh

serve: ## dashboard only, http://127.0.0.1:8765
	bin/tokscope serve

test:
	python3 -m unittest discover -s tests -q
