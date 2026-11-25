#pragma once

#include <stdint.h>
#include "esp_err.h"
#include "nvs.h"

#define QUEUE_CAPACITY 16
#define VERSION_CAPACITY 32

typedef struct {
    uint32_t sequence;
    int32_t temperature_centi_c;
} sample_t;

typedef struct {
    uint32_t format;
    uint32_t next_sequence;
    uint32_t dropped;
    uint32_t head;
    uint32_t count;
    char rejected_version[VERSION_CAPACITY];
    sample_t entries[QUEUE_CAPACITY];
} queue_t;

esp_err_t queue_load(nvs_handle_t storage, queue_t *queue);
esp_err_t queue_save(nvs_handle_t storage, const queue_t *queue);
int32_t sample_temperature(uint32_t sequence);
void queue_append(queue_t *queue);
void queue_pop(queue_t *queue);
