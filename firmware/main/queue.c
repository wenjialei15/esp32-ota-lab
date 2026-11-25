#include "queue.h"
#include <string.h>

#define QUEUE_FORMAT 1

esp_err_t queue_load(nvs_handle_t storage, queue_t *queue)
{
    size_t size = sizeof(*queue);
    esp_err_t result = nvs_get_blob(storage, "queue", queue, &size);
    if (result == ESP_ERR_NVS_NOT_FOUND) {
        *queue = (queue_t){.format = QUEUE_FORMAT, .next_sequence = 1};
        return ESP_OK;
    }
    if (result != ESP_OK) {
        return result;
    }
    if (size != sizeof(*queue) || queue->format != QUEUE_FORMAT ||
        queue->next_sequence == 0 || queue->head >= QUEUE_CAPACITY ||
        queue->count > QUEUE_CAPACITY ||
        memchr(queue->rejected_version, '\0', sizeof(queue->rejected_version)) == NULL) {
        return ESP_ERR_INVALID_STATE;
    }
    return ESP_OK;
}

esp_err_t queue_save(nvs_handle_t storage, const queue_t *queue)
{
    esp_err_t result = nvs_set_blob(storage, "queue", queue, sizeof(*queue));
    return result == ESP_OK ? nvs_commit(storage) : result;
}

int32_t sample_temperature(uint32_t sequence)
{
    return 2200 + (int32_t)(sequence % 29) * 7;
}

void queue_pop(queue_t *queue)
{
    queue->head = (queue->head + 1) % QUEUE_CAPACITY;
    queue->count--;
}

void queue_append(queue_t *queue)
{
    if (queue->count == QUEUE_CAPACITY) {
        queue_pop(queue);
        queue->dropped++;
    }
    uint32_t tail = (queue->head + queue->count) % QUEUE_CAPACITY;
    uint32_t sequence = queue->next_sequence++;
    queue->entries[tail] = (sample_t){sequence, sample_temperature(sequence)};
    queue->count++;
}
