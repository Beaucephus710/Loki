# Loki

Loki is an embedded C project for a dragon-themed interactive device that runs on a single-board computer and talks to attached hardware such as a TFT display, SD card, flash memory, EEPROM, and a Flipper Zero over UART.

## What this repository teaches

This repo is most useful if you want to learn how to build a hardware-oriented C project with:

- a small hardware abstraction layer
- separate device drivers for SPI, I2C, UART, GPIO, and PWM devices
- structured logging instead of `printf`
- safer dynamic memory helpers
- retry logic for unreliable bus operations
- a simple top-level startup and shutdown flow

## What is in the codebase

Main source files in the current root-level layout include:

- `main.c` — program entry point, signal handling, and example hardware tests
- `system.c` / `system.h` — system startup, subsystem initialization, and shutdown
- `log.c` / `log.h` — leveled logging macros and logger implementation
- `memory.c` / `memory.h` — tracked allocation helpers such as `malloc_safe()` and `free_safe()`
- `retry.c` / `retry.h` — retry strategies for transient hardware failures
- `gpio.c` / `gpio.h` — GPIO abstraction
- `spi.c` / `spi.h` — SPI abstraction
- `i2c.c` / `i2c.h` — I2C abstraction
- `uart.c` / `uart.h` — UART abstraction
- `pwm.c` / `pwm.h` — PWM abstraction
- `tft_driver.c` / `tft_driver.h` — TFT display driver
- `sdcard_driver.c` / `sdcard_driver.h` — SD card driver
- `flash_driver.c` / `flash_driver.h` — flash memory driver
- `eeprom_driver.c` / `eeprom_driver.h` — EEPROM driver
- `flipper_uart.c` / `flipper_uart.h` — Flipper Zero UART protocol support
- `board_config.h` — board-level settings such as frequencies and timing
- `pinout.h` — pin mappings used by the project

## How the program flows

At a high level, `main.c` shows a teachable embedded application structure:

1. print a startup banner
2. initialize logging
3. install signal handlers for graceful shutdown
4. call `system_init()`
5. run sample hardware tests
6. enter a loop waiting for Flipper messages
7. call `system_shutdown()` before exit

That pattern is a good starting point for your own SBC or hardware-control application.

## Concepts worth learning from Loki

### 1. Layered design

The project separates responsibilities:

- low-level bus access lives in HAL-style modules like GPIO, SPI, I2C, UART, and PWM
- chip or peripheral behavior lives in driver files
- app behavior stays in `main.c` and `system.c`

This makes the code easier to debug and extend.

### 2. Logging discipline

The logging system gives you levels such as:

- `LOG_CRITICAL()`
- `LOG_ERROR()`
- `LOG_WARN()`
- `LOG_INFO()`
- `LOG_DEBUG()`

That is much better than scattering raw prints everywhere because it keeps diagnostics consistent.

### 3. Safer memory usage

The memory helpers encourage patterns like:

- allocate with `malloc_safe()`
- release with `free_safe()`
- report memory usage in debug workflows

That is a practical pattern for learning C without losing track of heap allocations.

### 4. Retry logic for hardware work

Hardware communication can fail temporarily. The retry helpers show how to wrap operations like SPI, I2C, or EEPROM access with a reusable retry policy instead of duplicating error-handling code.

### 5. Graceful shutdown

The signal handling in `main.c` demonstrates a clean exit path. That matters for embedded Linux software that may be stopped through SSH, a service manager, or a terminal.

## Build basics

Common commands documented in this repo are:

```bash name=build-commands.sh
make
make DEBUG=1
make DEBUG=0
make test
make analyze
make docs
make clean
```

If your environment is missing the ARM cross-compiler, builds that depend on `arm-linux-gnueabihf-gcc` will fail until the toolchain is installed.

## Local configuration UI

Loki uses the same USB-network addresses as a typical Pwnagotchi setup:
Loki is `10.0.0.2` and the connected computer is `10.0.0.1`. Install the
included systemd-networkd profile on Loki once, then restart networking:

```bash
sudo install -D -m 644 network/loki-usb0.network /etc/systemd/network/10-loki-usb0.network
sudo systemctl enable --now systemd-networkd
sudo systemctl restart systemd-networkd
```

Set the computer's USB Ethernet interface to the static address
`10.0.0.1/24`, connect to Loki over USB, and open `http://10.0.0.2:8080`.
On Linux, this can be configured with:

```bash
sudo ip address replace 10.0.0.1/24 dev <usb-interface>
sudo ip link set <usb-interface> up
```

The UI accepts connections only from that USB subnet. Edit values, save them,
then restart Loki for the updated configuration to take effect. Configure the
WPA-SEC plugin key outside the repository:

```bash
export LOKI_WPA_SEC_API_KEY="your-key"
python3 main.py
```

For a systemd-managed Loki process, persist the key in an override instead of
adding it to `config.toml`:

```bash
sudo systemctl edit loki
# Add: [Service]
# Add: Environment=LOKI_WPA_SEC_API_KEY=your-key
```

Set `[web_ui].enabled = false` in `config.toml` to disable the editor. For a
strictly local-only UI instead, set `[web_ui].host = "127.0.0.1"`.

## Raspberry Pi Zero W installation (step-by-step)

Use this path if you want to run Loki directly on a Raspberry Pi Zero W.

1. Prepare the board with **Raspberry Pi OS Lite (32-bit)**, enable SSH, and connect it to Wi-Fi.
2. SSH into the Pi:
   ```bash
   ssh pi@raspberrypi.local
   ```
3. Install build dependencies on the Pi:
   ```bash
   sudo apt-get update
   sudo apt-get install -y git make gcc
   ```
4. Clone the repository and enter it:
   ```bash
   git clone https://github.com/Fomorianshifter/Loki.git
   cd Loki
   ```
5. Build natively for Pi Zero W (ARMv6):
   ```bash
   make clean
   make DEBUG=1 CC=gcc CFLAGS="-Wall -Wextra -march=armv6zk -mtune=arm1176jzf-s -mfpu=vfp -mfloat-abi=hard -I."
   ```
6. Run the binary:
   ```bash
   sudo ./build/debug/loki_app
   ```
7. For an optimized release build:
   ```bash
   make clean
   make DEBUG=0 CC=gcc CFLAGS="-Wall -Wextra -march=armv6zk -mtune=arm1176jzf-s -mfpu=vfp -mfloat-abi=hard -I."
   sudo ./build/release/loki_app
   ```

If you cross-compile from another machine, ensure your compile flags target ARMv6, not the default ARMv7 settings in this repository's Makefile.

## Good ways to study this project

If you are learning from this repo, a strong reading order is:

1. `README.md`
2. `main.c`
3. `system.c` and `system.h`
4. `log.*`, `memory.*`, and `retry.*`
5. `spi.*`, `i2c.*`, `uart.*`, `gpio.*`, and `pwm.*`
6. the device drivers
7. `BUILD.md` and `DEPLOYMENT.md`

## Hardware focus

The repository was originally documented around Orange Pi Zero 2W hardware, and much of the current checked-in code and documentation still reflects that. The code also includes Raspberry Pi and Flipper-related intent in various places, so treat board assumptions as something to verify before wiring real hardware.

## Important note

This README now focuses only on the most teachable and durable information. For deeper platform setup, deployment details, troubleshooting, and build workflow notes, use the companion docs already in the repository such as:

- `BUILD.md`
- `BUILD_WINDOWS.md`
- `DEPLOYMENT.md`
- `CONTRIBUTING.md`
- `QUICK_REFERENCE.md`

## License

MIT License. See `LICENSE`.
