/**
 * @file retry.c
 * @brief Retry logic implementation
 */

#include "retry.h"
#include "log.h"
#include <unistd.h>

/* ===== DEFAULT RETRY STRATEGIES ===== */

const retry_config_t RETRY_AGGRESSIVE = {
    .max_attempts = 10,
    .initial_delay_ms = 1,
    .backoff_factor = 2,
};

const retry_config_t RETRY_BALANCED = {
    .max_attempts = 5,
    .initial_delay_ms = 10,
    .backoff_factor = 2,
};

const retry_config_t RETRY_CONSERVATIVE = {
    .max_attempts = 3,
    .initial_delay_ms = 50,
    .backoff_factor = 2,
};

const retry_config_t RETRY_NONE = {
    .max_attempts = 1,
    .initial_delay_ms = 0,
    .backoff_factor = 1,
};

/* ===== PUBLIC IMPLEMENTATION ===== */

int is_retryable_error(hal_status_t error)
{
    /* These errors might succeed on retry */
    switch (error) {
        case HAL_TIMEOUT:
        case HAL_BUSY:
            return 1;
        
        /* These are permanent failures */
        case HAL_INVALID_PARAM:
        case HAL_NOT_SUPPORTED:
            return 0;
        
        /* Generic error might be transient */
        case HAL_ERROR:
        case HAL_NOT_READY:
            return 1;
        
        default:
            return 0;
    }
}

hal_status_t retry_execute(retry_operation_t operation, void *context,
                           const retry_config_t config, const char *func_name,
                           const char *file, int line)
{
    if (operation == NULL) {
        return HAL_INVALID_PARAM;
    }

    hal_status_t result = HAL_ERROR;
    uint32_t delay_ms = config.initial_delay_ms;

    for (uint8_t attempt = 1; attempt <= config.max_attempts; attempt++) {
        result = operation(context);
        if (result == HAL_OK) {
            return HAL_OK;
        }

        if (!is_retryable_error(result)) {
            LOG_ERROR("[%s() at %s:%d] Non-retryable error: %d", func_name, file, line, result);
            return result;
        }

        if (attempt < config.max_attempts) {
            LOG_WARN("[%s() at %s:%d] Retrying (%d/%d)... waiting %u ms",
                    func_name, file, line, attempt, config.max_attempts, delay_ms);
            usleep(delay_ms * 1000);
            delay_ms = (delay_ms * config.backoff_factor);
            if (delay_ms > 5000) {
                delay_ms = 5000;  /* Cap at 5 seconds */
            }
        }
    }

    LOG_ERROR("[%s() at %s:%d] Failed after %d attempts", 
             func_name, file, line, config.max_attempts);
    
    return result;
}
