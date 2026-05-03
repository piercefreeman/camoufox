include upstream.sh

ifneq ($(strip $(CAMOUFOX_RELEASE)),)
release := $(CAMOUFOX_RELEASE)
endif

ifneq ($(strip $(CAMOUFOX_FIREFOX_VERSION)),)
version := $(CAMOUFOX_FIREFOX_VERSION)
endif

export

cf_source_dir := camoufox-$(version)-$(release)
ff_source_tarball := firefox-$(version).source.tar.xz

debs := python3 python3-dev python3-pip p7zip-full msitools wget aria2 libsqlite3-dev
rpms := python3 python3-devel p7zip msitools wget aria2 sqlite-devel
pacman := python python-pip p7zip msitools wget aria2 sqlite

.PHONY: help fetch setup setup-minimal clean set-target distclean build package \
        revert edits run bootstrap mozbootstrap dir \
        package-linux package-macos package-windows vcredist_arch patch unpatch \
        workspace check-arg edit-cfg ff-dbg lint tests update-ubo-assets generate-assets-car \
        generate-openapi generate-openapi-python generate-openapi-cpp \
        validate-fingerprint-example verify-patches

OPENAPI_SCHEMA := schemas/camoufox-profile.openapi.yaml
PY_OPENAPI_MODELS := pythonlib/camoufox/_generated_profile.py
CPP_OPENAPI_OUT := additions/camoucfg/generated/profile
CPP_OPENAPI_TEMPLATES := schemas/openapi-templates/cpp-nlohmann
OPENAPI_GENERATOR_IMAGE ?= openapitools/openapi-generator-cli:v7.22.0
OPENAPI_GENERATOR ?= docker run --rm -v $(CURDIR):/local $(OPENAPI_GENERATOR_IMAGE)
OPENAPI_SCHEMA_ARG ?= /local/$(OPENAPI_SCHEMA)
CPP_OPENAPI_OUT_ARG ?= /local/$(CPP_OPENAPI_OUT)

help:
	@echo "Available targets:"
	@echo "  fetch           - Fetch the Firefox source code"
	@echo "  setup           - Setup Camoufox & local git repo for development"
	@echo "  bootstrap       - Set up build environment"
	@echo "  mozbootstrap    - Sets up mach"
	@echo "  dir             - Prepare Camoufox source directory with BUILD_TARGET"
	@echo "  revert          - Kill all working changes"
	@echo "  edits           - Camoufox developer UI"
	@echo "  clean           - Remove build artifacts"
	@echo "  distclean       - Remove everything including downloads"
	@echo "  build           - Build Camoufox"
	@echo "  set-target      - Change the build target with BUILD_TARGET"
	@echo "  package-linux   - Package Camoufox for Linux"
	@echo "  package-macos   - Package Camoufox for macOS"
	@echo "  package-windows - Package Camoufox for Windows"
	@echo "  run             - Run Camoufox"
	@echo "  lint            - Run Python static analysis"
	@echo "  edit-cfg        - Edit camoufox.cfg"
	@echo "  ff-dbg          - Setup vanilla Firefox with minimal patches"
	@echo "  patch           - Apply a patch"
	@echo "  unpatch         - Remove a patch"
	@echo "  workspace       - Sets the workspace to a patch, assuming its applied"
	@echo "  tests           - Runs the Python integration test suites"
	@echo "  update-ubo-assets - Update the uBOAssets.json file"
	@echo "  generate-openapi - Generate Python and C++ profile models from OpenAPI schema"
	@echo "  validate-fingerprint-example - Validate example/fingerprint.json against the OpenAPI schema"
	@echo "  verify-patches  - Fast Firefox patch verification against the matching source tarball"

_ARGS := $(wordlist 2,$(words $(MAKECMDGOALS)),$(MAKECMDGOALS))
$(eval $(_ARGS):;@:)

fetch:
	# Fetching the Firefox source tarball...
	aria2c -x16 -s16 -k1M -o $(ff_source_tarball) "https://archive.mozilla.org/pub/firefox/releases/$(version)/source/firefox-$(version).source.tar.xz"; \

setup-minimal:
	# Note: Only docker containers are intended to run this directly.
	# Run this before `make dir` or `make build` to avoid setting up a local git repo.
	if [ ! -f $(ff_source_tarball) ]; then \
		make fetch; \
	fi
	# Create new cf_source_dir
	rm -rf $(cf_source_dir)
	mkdir -p $(cf_source_dir)
	tar -xJf $(ff_source_tarball) -C $(cf_source_dir) --strip-components=1
	# Copy settings & additions
	cd $(cf_source_dir) && bash ../scripts/copy-additions.sh $(version) $(release)

setup: setup-minimal
	# Initialize local git repo for development
	cd $(cf_source_dir) && \
		git init -b main && \
		git add -f -A && \
		git commit -m "Initial commit" && \
		git tag -a unpatched -m "Initial commit"

ff-dbg: setup
	# Only apply patches to help debug vanilla Firefox
	make patch ./patches/chromeutil.patch
	make patch ./patches/browser-init.patch
	echo "LOCAL_INCLUDES += ['/camoucfg']" >> $(cf_source_dir)/dom/base/moz.build
	touch $(cf_source_dir)/_READY
	make checkpoint
	make build

revert:
	cd $(cf_source_dir) && git reset --hard unpatched

dir:
	@if [ ! -d $(cf_source_dir) ]; then \
		make setup; \
	fi
	python3 scripts/patch.py $(version) $(release)
	touch $(cf_source_dir)/_READY

set-target:
	python3 scripts/patch.py $(version) $(release) --mozconfig-only

mozbootstrap:
	cd $(cf_source_dir) && MOZBUILD_STATE_PATH=$$HOME/.mozbuild ./mach --no-interactive bootstrap --application-choice=browser

bootstrap: dir
	(sudo apt-get -y install $(debs) || sudo dnf -y install $(rpms) || sudo pacman -Sy $(pacman))
	make mozbootstrap

diff:
	@cd $(cf_source_dir) && git diff first-checkpoint $(_ARGS)

first-checkpoint:
	cd $(cf_source_dir) && \
		git tag -d first-checkpoint || true && \
		git add -A && \
		git reset -q _READY || true && \
		git commit -m "Checkpoint" -uno && \
		git tag -a first-checkpoint -m "Checkpoint"

checkpoint:
	cd $(cf_source_dir) && git commit -m "Checkpoint" -uno

clean:
	cd $(cf_source_dir) && git clean -fdx && ./mach clobber
	make revert

distclean:
	rm -rf $(cf_source_dir) $(ff_source_tarball)

build: unbusy
	@if [ ! -f $(cf_source_dir)/_READY ]; then \
		make dir; \
	fi
	cd $(cf_source_dir) && ./mach build $(_ARGS)

edits:
	python3 ./scripts/developer.py $(version) $(release)

package-linux:
	python3 scripts/package.py linux \
		--includes \
			settings/chrome.css \
			bundle/fontconfig \
		--version $(version) \
		--release $(release) \
		--arch $(arch) \
		--fonts windows macos linux

package-macos:
	python3 scripts/package.py macos \
		--includes \
			settings/chrome.css \
		--version $(version) \
		--release $(release) \
		--arch $(arch) \
		--fonts windows linux

package-windows:
	python3 scripts/package.py windows \
		--includes \
			settings/chrome.css \
			~/.mozbuild/vs/VC/Redist/MSVC/14.38.33135/$(vcredist_arch)/Microsoft.VC143.CRT/*.dll \
		--version $(version) \
		--release $(release) \
		--arch $(arch) \
		--fonts macos linux

run:
	cd $(cf_source_dir) \
	&& rm -rf ~/.camoufox obj-x86_64-pc-linux-gnu/tmp/profile-default \
	&& printf '{"debug":true}\n' > /tmp/camoufox-debug-profile.json \
	&& CAMOU_CONFIG_PATH=/tmp/camoufox-debug-profile.json ./mach run $(args)

edit-cfg:
	@if [ ! -f $(cf_source_dir)/obj-x86_64-pc-linux-gnu/dist/bin/camoufox.cfg ]; then \
		echo "Error: camoufox.cfg not found. Apply config.patch first."; \
		exit 1; \
	fi
	$(EDITOR) $(cf_source_dir)/obj-x86_64-pc-linux-gnu/dist/bin/camoufox.cfg

check-arg:
	@if [ -z "$(_ARGS)" ]; then \
		echo "Error: No file specified. Usage: make <command> ./patches/file.patch"; \
		exit 1; \
	fi

grep:
	grep "$(_ARGS)" -r ./patches/*.patch

patch:
	@make check-arg $(_ARGS);
	cd $(cf_source_dir) && patch -p1 -i ../$(_ARGS)

unpatch:
	@make check-arg $(_ARGS);
	cd $(cf_source_dir) && patch -p1 -R -i ../$(_ARGS)

workspace:
	@make check-arg $(_ARGS);
	@if (cd $(cf_source_dir) && patch -p1 -R --dry-run --force -i ../$(_ARGS)) > /dev/null 2>&1; then \
		echo "Patch is already applied. Unapplying..."; \
		make unpatch $(_ARGS); \
	else \
		echo "Patch is not applied. Proceeding with application..."; \
	fi
	make first-checkpoint || true
	make patch $(_ARGS)

lint:
	uv run --group dev --locked ruff check pythonlib/camoufox
	uv run --group dev --locked ty check pythonlib/camoufox

tests:
	CAMOUFOX_EXECUTABLE_PATH=$(CURDIR)/$(cf_source_dir)/obj-x86_64-pc-linux-gnu/dist/bin/camoufox-bin \
		uv run --group dev --group playwright-tests --locked pytest \
			--integration \
			-vv \
			$(if $(filter true,$(headful)),, --headless) \
			__tests__/build-tester/ \
			__tests__/playwright/async/ \
			__tests__/service-tester/

unbusy:
	rm -rf $(cf_source_dir)/obj-x86_64-pc-linux-gnu/dist/bin/camoufox-bin \
		$(cf_source_dir)/obj-x86_64-pc-linux-gnu/dist/bin/camoufox

path:
	@realpath $(cf_source_dir)/obj-x86_64-pc-linux-gnu/dist/bin/camoufox-bin

update-ubo-assets:
	bash ./scripts/update-ubo-assets.sh

generate-assets-car:
	bash ./scripts/generate-assets-car.sh

generate-openapi: generate-openapi-python generate-openapi-cpp

generate-openapi-python:
	uvx --from datamodel-code-generator datamodel-codegen \
		--input $(OPENAPI_SCHEMA) \
		--input-file-type openapi \
		--output $(PY_OPENAPI_MODELS) \
		--output-model-type pydantic_v2.BaseModel \
		--target-python-version 3.10 \
		--use-standard-collections \
		--use-union-operator \
		--field-constraints \
		--snake-case-field \
		--extra-fields forbid \
		--disable-timestamp

generate-openapi-cpp:
	rm -rf $(CPP_OPENAPI_OUT)
	$(OPENAPI_GENERATOR) generate \
		-i $(OPENAPI_SCHEMA_ARG) \
		-g cpp-tiny \
		-o $(CPP_OPENAPI_OUT_ARG) \
		-t /local/$(CPP_OPENAPI_TEMPLATES) \
		--global-property models,modelTests=false \
		--type-mappings number=double \
		--additional-properties hideGenerationTimestamp=true,modelPackage=camoucfg

validate-fingerprint-example:
	uv run python scripts/validate_fingerprint_example.py

verify-patches:
	uv run scripts/verify_firefox_patches.py

vcredist_arch := $(shell echo $(arch) | sed 's/x86_64/x64/')
