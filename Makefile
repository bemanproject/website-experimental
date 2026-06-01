.PHONY: all install build start serve trunk-check

all: start

install: # Install dependencies
	yarn install

start: install # Install dependencies and start local development server
	python3 scripts/run-staged-website.py start

build: # Generate static content for GitHub Pages deployment
	python3 scripts/run-staged-website.py build

serve: # Build and serve the staged static site
	python3 scripts/run-staged-website.py serve

lint: # Run code quality checks
	trunk check
