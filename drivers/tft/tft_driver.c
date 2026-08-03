/**
 * TFT Display Driver Implementation for ILI9486 / ILI9488
 * Raspberry Pi Zero 2W / Orange Pi Zero 2W - SPI0 Interface
 *
 * TFT_TYPE (from board_config.h / config.toml) selects the controller init path:
 *   "ILI9486" — extended power/VCOM sequence for common 480×320 modules
 *   "ILI9488" — shorter generic sequence (compatible default)
 *
 * NOTE: The ILI9488 over a 4-wire SPI bus only supports 18-bit (RGB666) pixel
 * format (COLMOD = 0x66).  Setting COLMOD = 0x55 (16-bit RGB565) has no effect
 * and results in a blank or garbled display.  Pixel data is therefore always
 * sent as three bytes per pixel (R8, G8, B8 – top 6 bits used by the panel).
 */

#include "tft_driver.h"
#include "../../hal/spi/spi.h"
#include "../../hal/gpio/gpio.h"
#include "../../hal/pwm/pwm.h"
#include "../../config/pinout.h"
#include "../../config/board_config.h"
#include "log.h"
#include <string.h>
#include <stdio.h>
#include <unistd.h>

/* ===== COMMON ILI948x COMMANDS (shared by ILI9486 and ILI9488) ===== */
#define ILI948X_SWRESET     0x01  /* Software reset */
#define ILI948X_SLPOUT      0x11  /* Sleep out */
#define ILI948X_DISPOFF     0x28  /* Display off */
#define ILI948X_DISPON      0x29  /* Display on */
#define ILI948X_CASET       0x2A  /* Column address set */
#define ILI948X_PASET       0x2B  /* Page (row) address set */
#define ILI948X_RAMWR       0x2C  /* Memory write */
#define ILI948X_MADCTL      0x36  /* Memory access control (rotation/mirror) */
#define ILI948X_COLMOD      0x3A  /* Interface pixel format */

/* ===== ILI9488-SPECIFIC COMMANDS ===== */
#define ILI9488_PWCTRL1         0xC0  /* Power control 1 */
#define ILI9488_PWCTRL2         0xC1  /* Power control 2 */
#define ILI9488_VMCTRL1         0xC5  /* VCOM control 1 */
#define ILI9488_PGAMCTRL        0xE0  /* Positive gamma control */
#define ILI9488_NGAMCTRL        0xE1  /* Negative gamma control */

/* ===== ILI9486-SPECIFIC COMMANDS ===== */
#define ILI9486_IFMODE      0xB0  /* Interface mode control */
#define ILI9486_FRMCTR1     0xB1  /* Frame rate control (normal mode) */
#define ILI9486_DISCTRL     0xB6  /* Display function control */
#define ILI9486_PWCTRL1     0xC0  /* Power control 1 */
#define ILI9486_PWCTRL2     0xC1  /* Power control 2 */
#define ILI9486_PWCTRL3     0xC2  /* Power control 3 */
#define ILI9486_VMCTRL1     0xC5  /* VCOM control 1 */

/* Backward-compat aliases so the shared init code compiles with either naming */
#define ILI9488_SWRESET     ILI948X_SWRESET
#define ILI9488_SLPOUT      ILI948X_SLPOUT
#define ILI9488_DISPOFF     ILI948X_DISPOFF
#define ILI9488_DISPON      ILI948X_DISPON
#define ILI9488_CASET       ILI948X_CASET
#define ILI9488_PASET       ILI948X_PASET
#define ILI9488_RAMWR       ILI948X_RAMWR
#define ILI9488_MADCTL      ILI948X_MADCTL
#define ILI9488_COLMOD      ILI948X_COLMOD

/* ===== TFT STATE ===== */
typedef struct {
    uint8_t initialized;
    uint8_t rotation;
    uint8_t brightness;
} tft_context_t;

static tft_context_t tft_ctx = {
    .initialized = 0,
    .rotation = TFT_ROTATION,
    .brightness = TFT_BRIGHTNESS,
};

/* ===== LOCAL HELPER FUNCTIONS ===== */

/**
 * Send a command byte to the TFT controller (DC = LOW).
 */
static hal_status_t tft_write_command(uint8_t cmd)
{
    gpio_set(GPIO_TFT_DC, GPIO_LEVEL_LOW);
    return spi_write(SPI_BUS_0, TFT_CS, &cmd, 1);
}

/**
 * Send data bytes to the TFT controller (DC = HIGH).
 */
static hal_status_t tft_write_data(const uint8_t *data, uint32_t length)
{
    gpio_set(GPIO_TFT_DC, GPIO_LEVEL_HIGH);
    return spi_write(SPI_BUS_0, TFT_CS, data, length);
}

/**
 * Delay in milliseconds
 */
static void delay_ms(uint32_t ms)
{
    usleep(ms * 1000);
}

/**
 * Hardware reset
 */
static void tft_reset(void)
{
    gpio_set(GPIO_TFT_RST, GPIO_LEVEL_LOW);
    delay_ms(10);
    gpio_set(GPIO_TFT_RST, GPIO_LEVEL_HIGH);
    delay_ms(120);
}

/**
 * Set address window for pixel writing
 */
static hal_status_t tft_set_address_window(uint16_t x0, uint16_t y0, uint16_t x1, uint16_t y1)
{
    uint8_t buf[4];

    tft_write_command(ILI9488_CASET);
    buf[0] = (x0 >> 8) & 0xFF;
    buf[1] = x0 & 0xFF;
    buf[2] = (x1 >> 8) & 0xFF;
    buf[3] = x1 & 0xFF;
    tft_write_data(buf, 4);

    tft_write_command(ILI9488_PASET);
    buf[0] = (y0 >> 8) & 0xFF;
    buf[1] = y0 & 0xFF;
    buf[2] = (y1 >> 8) & 0xFF;
    buf[3] = y1 & 0xFF;
    tft_write_data(buf, 4);

    return HAL_OK;
}

/**
 * ILI9486 extended power / VCOM / frame-rate init sequence.
 * Called after SLPOUT to program controller-specific registers
 * that are not required (or differ) for ILI9488.
 */
static void tft_init_sequence_ili9486(void)
{
    uint8_t data[4];

    /* Interface mode: SDO not used, VSYNC/HSYNC disabled */
    tft_write_command(ILI9486_IFMODE);
    data[0] = 0x00;
    tft_write_data(data, 1);

    /* Frame rate: fosc / 1, 60 Hz */
    tft_write_command(ILI9486_FRMCTR1);
    data[0] = 0xB0;
    data[1] = 0x11;
    tft_write_data(data, 2);

    /* Display function control */
    tft_write_command(ILI9486_DISCTRL);
    data[0] = 0x02;
    data[1] = 0x42;
    tft_write_data(data, 2);

    /* Power control 1: GVDD = 4.45 V */
    tft_write_command(ILI9486_PWCTRL1);
    data[0] = 0x19;
    data[1] = 0x1A;
    tft_write_data(data, 2);

    /* Power control 2: DDVDH = VCI×2 */
    tft_write_command(ILI9486_PWCTRL2);
    data[0] = 0x45;
    tft_write_data(data, 1);

    /* Power control 3: operational amplifier current */
    tft_write_command(ILI9486_PWCTRL3);
    data[0] = 0x33;
    tft_write_data(data, 1);

    /* VCOM control: VCOMH = 4.025 V, VCOML = −1.0 V */
    tft_write_command(ILI9486_VMCTRL1);
    data[0] = 0x00;
    data[1] = 0x28;
    tft_write_data(data, 2);

    delay_ms(5);
}

/* ===== PUBLIC IMPLEMENTATION ===== */

hal_status_t tft_init(void)
{
    if (tft_ctx.initialized) {
        return HAL_OK;
    }

    /* Log effective compile-time TFT configuration */
    LOG_INFO("TFT init: controller=%s  %ux%u  SPI_FREQ=%u Hz  CS=%u  DC=%u  RST=%u  BL=%u  rot=%u  brightness=%u%%",
             TFT_TYPE,
             (unsigned)TFT_WIDTH, (unsigned)TFT_HEIGHT,
             (unsigned)TFT_SPI_FREQ,
             (unsigned)TFT_CS,
             (unsigned)GPIO_TFT_DC,
             (unsigned)GPIO_TFT_RST,
             (unsigned)GPIO_TFT_BL,
             (unsigned)TFT_ROTATION,
             (unsigned)TFT_BRIGHTNESS);

    /* Initialize SPI0 — cs_line selects /dev/spidev0.0 or /dev/spidev0.1 */
    spi_config_t spi_cfg = {
        .frequency = TFT_SPI_FREQ,
        .mode = SPI_MODE_0,
        .bits_per_word = 8,
        .bit_order = SPI_MSB_FIRST,
        .cs_line = (TFT_CS == SPI0_CS0) ? 0 : 1,
    };
    if (spi_init(SPI_BUS_0, &spi_cfg) != HAL_OK) {
        return HAL_ERROR;
    }

    /* Configure GPIO control pins */
    gpio_config_t gpio_dc = {
        .pin = GPIO_TFT_DC,
        .mode = GPIO_MODE_OUTPUT,
        .pull = GPIO_PULL_NONE,
    };
    gpio_configure(&gpio_dc);

    gpio_config_t gpio_rst = {
        .pin = GPIO_TFT_RST,
        .mode = GPIO_MODE_OUTPUT,
        .pull = GPIO_PULL_NONE,
    };
    gpio_configure(&gpio_rst);

    /* Initialize PWM backlight — skip when BL pin is not wired */
#if defined(GPIO_TFT_BL) && (GPIO_TFT_BL != 255)
    pwm_config_t pwm_cfg = {
        .pin = GPIO_TFT_BL,
        .frequency = PWM_FREQ_DEFAULT,
        .duty_cycle = tft_ctx.brightness,
    };
    pwm_init(PWM_CHANNEL_0, &pwm_cfg);
    pwm_enable(PWM_CHANNEL_0);
#endif

    /* Hardware reset */
    tft_reset();

    /* ---- Software reset + sleep-out ---- */

    tft_write_command(ILI9488_SWRESET);
    delay_ms(150);

    tft_write_command(ILI9488_SLPOUT);
    delay_ms(120);

    /* ---- Controller-specific power-up sequence ---- */
    if (strcmp(TFT_TYPE, "ILI9486") == 0) {
        tft_init_sequence_ili9486();
    } else {
        /* ILI9488 / generic path */

        /* Power control 1: VRH = 4.60V */
        tft_write_command(ILI9488_PWCTRL1);
        { uint8_t d[] = {0x17, 0x15}; tft_write_data(d, 2); }

        /* Power control 2: SAP */
        tft_write_command(ILI9488_PWCTRL2);
        { uint8_t d[] = {0x41}; tft_write_data(d, 1); }

        /* VCOM control */
        tft_write_command(ILI9488_VMCTRL1);
        { uint8_t d[] = {0x00, 0x12, 0x80}; tft_write_data(d, 3); }

        /* Positive gamma */
        tft_write_command(ILI9488_PGAMCTRL);
        { uint8_t d[] = {0x00,0x03,0x09,0x08,0x16,0x0A,0x3F,0x78,
                         0x4C,0x09,0x0A,0x08,0x16,0x1A,0x0F};
          tft_write_data(d, 15); }

        /* Negative gamma */
        tft_write_command(ILI9488_NGAMCTRL);
        { uint8_t d[] = {0x00,0x16,0x19,0x03,0x0F,0x05,0x32,0x45,
                         0x46,0x04,0x0E,0x0D,0x35,0x37,0x0F};
          tft_write_data(d, 15); }
    }

    /* Memory access control: default orientation (landscape) */
    tft_write_command(ILI9488_MADCTL);
    { uint8_t d[] = {0x48}; tft_write_data(d, 1); }

    /* Pixel format: 18bpp RGB666 — only valid SPI mode for ILI9488 */
    tft_write_command(ILI9488_COLMOD);
    { uint8_t d[] = {0x66}; tft_write_data(d, 1); }

    /* Display on */
    tft_write_command(ILI9488_DISPON);
    delay_ms(100);

    /* Clear to black */
    tft_ctx.initialized = 1;  /* must be set before tft_clear */
    tft_clear();

    return HAL_OK;
}

hal_status_t tft_write_pixels(uint16_t x, uint16_t y, uint16_t width, uint16_t height,
                              const color_t *data)
{
    if (data == NULL || width == 0 || height == 0) {
        return HAL_INVALID_PARAM;
    }
    if (!tft_ctx.initialized) {
        return HAL_NOT_READY;
    }

    tft_set_address_window(x, y, x + width - 1, y + height - 1);
    tft_write_command(ILI9488_RAMWR);

    /* Convert RGB565 pixel array to 18bpp RGB666 (3 bytes/pixel) */
    uint32_t pixel_count = (uint32_t)width * height;
    enum { CHUNK = 64 };
    uint8_t buf[CHUNK * 3];
    uint32_t i = 0;

    while (i < pixel_count) {
        uint32_t n = pixel_count - i;
        if (n > CHUNK) n = CHUNK;
        for (uint32_t j = 0; j < n; j++) {
            color_t px = data[i + j];
            buf[j * 3 + 0] = (uint8_t)((px >> 8) & 0xF8);  /* R */
            buf[j * 3 + 1] = (uint8_t)((px >> 3) & 0xFC);  /* G */
            buf[j * 3 + 2] = (uint8_t)((px << 3) & 0xF8);  /* B */
        }
        hal_status_t st = tft_write_data(buf, n * 3);
        if (st != HAL_OK) return st;
        i += n;
    }

    return HAL_OK;
}

hal_status_t tft_fill_rect(uint16_t x, uint16_t y, uint16_t width, uint16_t height, color_t color)
{
    if (width == 0 || height == 0) {
        return HAL_INVALID_PARAM;
    }
    if (!tft_ctx.initialized) {
        return HAL_NOT_READY;
    }

    tft_set_address_window(x, y, x + width - 1, y + height - 1);
    tft_write_command(ILI9488_RAMWR);

    /* Pre-fill a chunk buffer with the 18bpp encoding of the colour */
    uint8_t r = (uint8_t)((color >> 8) & 0xF8);
    uint8_t g = (uint8_t)((color >> 3) & 0xFC);
    uint8_t b = (uint8_t)((color << 3) & 0xF8);

    enum { TFT_FILL_CHUNK_PIXELS = 256 };
    uint8_t chunk[TFT_FILL_CHUNK_PIXELS * 3];
    for (uint32_t i = 0; i < TFT_FILL_CHUNK_PIXELS; i++) {
        chunk[i * 3 + 0] = r;
        chunk[i * 3 + 1] = g;
        chunk[i * 3 + 2] = b;
    }

    uint32_t remaining = (uint32_t)width * height;
    while (remaining > 0) {
        uint32_t pixels = (remaining > TFT_FILL_CHUNK_PIXELS) ? TFT_FILL_CHUNK_PIXELS : remaining;
        hal_status_t st = tft_write_data(chunk, pixels * 3);
        if (st != HAL_OK) return st;
        remaining -= pixels;
    }

    return HAL_OK;
}

hal_status_t tft_clear(void)
{
    return tft_fill_rect(0, 0, TFT_WIDTH, TFT_HEIGHT, COLOR_BLACK);
}

hal_status_t tft_set_brightness(uint8_t brightness)
{
    if (brightness > 100) {
        brightness = 100;
    }
    tft_ctx.brightness = brightness;
    return pwm_set_duty(PWM_CHANNEL_0, brightness);
}

hal_status_t tft_set_rotation(uint8_t rotation)
{
    if (rotation > 3) {
        return HAL_INVALID_PARAM;
    }
    if (!tft_ctx.initialized) {
        return HAL_NOT_READY;
    }

    tft_ctx.rotation = rotation;
    tft_write_command(ILI948X_MADCTL);

    uint8_t madctl = 0x00;
    switch (rotation) {
        case 0: madctl = 0x48; break;  /* 0°   – landscape default */
        case 1: madctl = 0x28; break;  /* 90°  */
        case 2: madctl = 0x88; break;  /* 180° */
        case 3: madctl = 0xE8; break;  /* 270° */
    }
    tft_write_data(&madctl, 1);

    return HAL_OK;
}

hal_status_t tft_deinit(void)
{
    if (!tft_ctx.initialized) {
        return HAL_OK;
    }

    tft_write_command(ILI9488_DISPOFF);
#if defined(GPIO_TFT_BL) && (GPIO_TFT_BL != 255)
    pwm_disable(PWM_CHANNEL_0);
    pwm_deinit(PWM_CHANNEL_0);
#endif
    spi_deinit(SPI_BUS_0);

    tft_ctx.initialized = 0;
    return HAL_OK;
}
