#include <inttypes.h>
#include <stdio.h>
#include "esp_app_desc.h"
#include "esp_log.h"
#include "esp_ota_ops.h"
#include "esp_system.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "nvs_flash.h"
#include "queue.h"
#include "transport.h"

static const char *TAG = "ota_lab";

static void verify_trial(const esp_partition_t *running, const char *version,
                         esp_err_t storage_status, nvs_handle_t storage, queue_t *queue)
{
    esp_ota_img_states_t state;
    if (esp_ota_get_state_partition(running, &state) != ESP_OK ||
        state != ESP_OTA_IMG_PENDING_VERIFY) {
        return;
    }
    int32_t temperature = sample_temperature(1);
    if (!LAB_FORCE_SELF_TEST_FAILURE && storage_status == ESP_OK &&
        temperature >= 1800 && temperature <= 4000) {
        ESP_ERROR_CHECK(esp_ota_mark_app_valid_cancel_rollback());
        ESP_LOGI(TAG, "TRIAL_CONFIRMED version=%s slot=%s", version, running->label);
        return;
    }

    if (storage_status == ESP_OK) {
        snprintf(queue->rejected_version, sizeof(queue->rejected_version), "%s", version);
        esp_err_t saved = queue_save(storage, queue);
        if (saved != ESP_OK) {
            ESP_LOGW(TAG, "Failed to remember rejected version: %s", esp_err_to_name(saved));
        }
    }
    ESP_LOGW(TAG, "TRIAL_REJECTED version=%s slot=%s", version, running->label);
    ESP_ERROR_CHECK(esp_ota_mark_app_invalid_rollback_and_reboot());
}

static bool commit_queue(nvs_handle_t storage, queue_t *queue, const queue_t *next)
{
    esp_err_t result = queue_save(storage, next);
    if (result != ESP_OK) {
        ESP_LOGE(TAG, "NVS commit failed: %s", esp_err_to_name(result));
        return false;
    }
    *queue = *next;
    return true;
}

void app_main(void)
{
    const esp_partition_t *running = esp_ota_get_running_partition();
    const char *version = esp_app_get_description()->version;
    nvs_handle_t storage = 0;
    queue_t queue = {0};
    esp_err_t ready = nvs_flash_init();
    if (ready == ESP_OK) {
        ready = nvs_open("telemetry", NVS_READWRITE, &storage);
    }
    if (ready == ESP_OK) {
        ready = queue_load(storage, &queue);
    }
    verify_trial(running, version, ready, storage, &queue);
    ESP_ERROR_CHECK(ready);
    ESP_LOGI(TAG, "BOOT version=%s slot=%s next=%" PRIu32 " rejected=%s",
             version, running->label, queue.next_sequence, queue.rejected_version);
    esp_log_level_set("esp-tls", ESP_LOG_NONE);
    esp_log_level_set("transport_base", ESP_LOG_NONE);
    esp_log_level_set("HTTP_CLIENT", ESP_LOG_NONE);
    network_start();

    int64_t next_check = 0;
    for (;;) {
        queue_t next = queue;
        uint32_t previously_dropped = queue.dropped;
        queue_append(&next);
        if (commit_queue(storage, &queue, &next)) {
            if (queue.dropped != previously_dropped) {
                ESP_LOGW(TAG, "QUEUE_OVERFLOW dropped=%" PRIu32, queue.dropped);
            }
            uint32_t waiting = queue.count;
            while (queue.count && publish_sample(&queue.entries[queue.head], version)) {
                next = queue;
                queue_pop(&next);
                if (!commit_queue(storage, &queue, &next)) {
                    break;
                }
            }
            if (queue.count) {
                ESP_LOGI(TAG, "QUEUED count=%" PRIu32 " sequence=%" PRIu32,
                         queue.count, queue.next_sequence - 1);
            } else if (waiting > 1) {
                ESP_LOGI(TAG, "QUEUE_FLUSHED count=%" PRIu32, waiting);
            }
        }

        if (esp_timer_get_time() >= next_check) {
            char offered[VERSION_CAPACITY];
            if (find_update(version, queue.rejected_version, offered)) {
                ESP_LOGI(TAG, "OTA_DOWNLOAD version=%s", offered);
                esp_err_t result = stage_update(offered);
                if (result == ESP_OK) {
                    ESP_LOGI(TAG, "OTA_STAGED version=%s", offered);
                    esp_restart();
                }
                ESP_LOGW(TAG, "OTA_ABORT version=%s error=%s", offered, esp_err_to_name(result));
            }
            next_check = esp_timer_get_time() + 2000000;
        }
        vTaskDelay(pdMS_TO_TICKS(1000));
    }
}
