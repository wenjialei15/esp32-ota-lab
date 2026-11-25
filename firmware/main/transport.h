#pragma once

#include <stdbool.h>
#include "queue.h"

void network_start(void);
bool publish_sample(const sample_t *sample, const char *version);
bool find_update(const char *current, const char *rejected, char version[VERSION_CAPACITY]);
esp_err_t stage_update(const char *version);
