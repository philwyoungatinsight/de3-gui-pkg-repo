.PHONY=default
default: |clean deps build run

.PHONY=FORCE
FORCE:

.PHONY=clean
clean: FORCE
	./run --clean

.PHONY=deps
deps: FORCE
	./run --deps

.PHONY=build
build: FORCE
	./run --build

.PHONY=test
test: FORCE
	./run --test

.PHONY=run
run: FORCE
	./run --run
