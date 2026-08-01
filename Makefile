# Loki Build Configuration for Orange Pi Zero 2W
# 
# PLATFORM NOTES:
# - Linux/Mac: Use this Makefile directly with `make` command
# - Windows: Use build.bat or build.ps1 script instead
#
# Requires: a C compiler (gcc or arm-linux-gnueabihf-gcc)

## Compiler Settings
CC := $(shell command -v arm-linux-gnueabihf-gcc 2>/dev/null)
ifeq ($(CC),)
CC := gcc
endif
CFLAGS := -Wall -Wextra -Icore
ifeq ($(notdir $(CC)),arm-linux-gnueabihf-gcc)
	CFLAGS += -march=armv7-a -mtune=cortex-a7
endif

# GNU Make on Windows is typically provided by Git for Windows, which includes
# this shell; it also exists on the supported Linux SBC environments.
SHELL := /usr/bin/bash
MKDIR = mkdir -p $(1)
 
## Debug/Release Build Modes
DEBUG ?= 1
ifeq ($(DEBUG), 1)
    CFLAGS += -g -O0 -DDEBUG -DLOG_LEVEL=4
    BUILD_DIR := build/debug
    $(info [INFO] Debug build enabled)
else
    CFLAGS += -O3 -DDEBUG=0 -DLOG_LEVEL=2
    BUILD_DIR := build/release
    $(info [INFO] Release build enabled)
endif
 
## Cross-compiler target (customize for your setup)
CROSS_USER ?= pi
CROSS_HOST ?= orange-pi.local
CROSS_PATH ?= /tmp
 
## Maintained native core
# The Python runtime accesses this shared library through loki.py. Root-level
# C files are legacy prototypes and are intentionally excluded.
SOURCES := $(wildcard core/*.c)
OBJECTS := $(patsubst core/%.c,$(BUILD_DIR)/core/%.o,$(SOURCES))
DEPS := $(OBJECTS:.o=.d)
TARGET := loki_core.so
 
## Linker Settings
LDFLAGS := -shared -lm -lpthread
 
## Build Rules
all: $(BUILD_DIR)/$(TARGET)
 
$(BUILD_DIR)/$(TARGET): $(OBJECTS)
	@$(call MKDIR,$(BUILD_DIR)); true
	$(CC) $(CFLAGS) -o $@ $^ $(LDFLAGS)
	@echo "[✓] Successfully built $(TARGET) ($(BUILD_DIR))"
 
$(BUILD_DIR)/core/%.o: core/%.c
	@$(call MKDIR,$(dir $@)); true
	$(CC) $(CFLAGS) -fPIC -MMD -MP -c $< -o $@
	@echo "[CC] $<"
 
## Include dependencies
-include $(DEPS)
 
## Installation target
install: $(BUILD_DIR)/$(TARGET)
	@echo "[→] Uploading to $(CROSS_USER)@$(CROSS_HOST):$(CROSS_PATH)..."
	scp $(BUILD_DIR)/$(TARGET) $(CROSS_USER)@$(CROSS_HOST):$(CROSS_PATH)/
	@echo "[✓] Installation complete"
 
## Run on target
run:
	python3 main.py
 
## Local testing (without hardware)
test:
	python3 -m unittest discover -s tests
 
## Documentation generation (requires Doxygen)
docs:
	@command -v doxygen >/dev/null 2>&1 || { echo "[!] Doxygen not installed. Install with: sudo apt-get install doxygen"; exit 1; }
	@echo "[→] Generating Doxygen documentation..."
	doxygen Doxyfile
	@echo "[✓] Documentation generated in docs/html/"
 
## Clean build artifacts
clean:
	rm -rf $(BUILD_DIR)
	@echo "[✓] Build artifacts removed"
 
## Clean everything including docs
clean-all: clean
	rm -rf docs/ build/
	find . -name "*.o" -delete
	find . -name "*.d" -delete
	@echo "[✓] Fully cleaned"
 
## Static analysis
analyze:
	@echo "[→] Running static analysis..."
	cppcheck --enable=all --suppress=missingIncludeSystem ./
	@echo "[✓] Analysis complete"
 
## Size report
size: $(BUILD_DIR)/$(TARGET)
	@echo "[→] Binary size breakdown:"
	arm-linux-gnueabihf-size $(BUILD_DIR)/$(TARGET)
	arm-linux-gnueabihf-nm -tS $(BUILD_DIR)/$(TARGET) | head -20
 
## Print configuration
info:
	@echo "╔════════════════════════════════════════╗"
	@echo "║    Loki Build Configuration           ║"
	@echo "╠════════════════════════════════════════╣"
	@echo "║ Compiler: $(CC)"
	@echo "║ Build mode: $$([ '$(DEBUG)' = '1' ] && echo 'DEBUG' || echo 'RELEASE')"
	@echo "║ Build dir: $(BUILD_DIR)"
	@echo "║ Cross target: $(CROSS_USER)@$(CROSS_HOST)"
	@echo "║ Target path: $(CROSS_PATH)"
	@echo "╚════════════════════════════════════════╝"
 
.PHONY: all clean clean-all install run test docs analyze size info
