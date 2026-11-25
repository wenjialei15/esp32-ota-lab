#include "transport.h"
#include <inttypes.h>
#include <stdio.h>
#include <string.h>
#include "cJSON.h"
#include "esp_app_desc.h"
#include "esp_eth.h"
#include "esp_event.h"
#include "esp_http_client.h"
#include "esp_https_ota.h"
#include "esp_log.h"
#include "esp_netif.h"

#define STRING_VALUE(value) #value
#define STRINGIFY(value) STRING_VALUE(value)
#define LAB_URL "http://10.0.2.2:" STRINGIFY(LAB_SERVER_PORT)

static const char *TAG = "transport";

void network_start(void)
{
    ESP_ERROR_CHECK(esp_netif_init());
    ESP_ERROR_CHECK(esp_event_loop_create_default());
    esp_netif_config_t netif_conf = ESP_NETIF_DEFAULT_ETH();
    esp_netif_t *netif = esp_netif_new(&netif_conf);
    ESP_ERROR_CHECK(netif ? ESP_OK : ESP_ERR_NO_MEM);

    eth_mac_config_t mac_conf = ETH_MAC_DEFAULT_CONFIG();
    eth_phy_config_t phy_conf = ETH_PHY_DEFAULT_CONFIG();
    phy_conf.phy_addr = 1;
    phy_conf.reset_gpio_num = -1;
    phy_conf.autonego_timeout_ms = 100;
    esp_eth_mac_t *mac = esp_eth_mac_new_openeth(&mac_conf);
    esp_eth_phy_t *phy = esp_eth_phy_new_dp83848(&phy_conf);
    ESP_ERROR_CHECK(mac && phy ? ESP_OK : ESP_ERR_NO_MEM);
    esp_eth_config_t eth_conf = ETH_DEFAULT_CONFIG(mac, phy);
    esp_eth_handle_t eth = NULL;
    ESP_ERROR_CHECK(esp_eth_driver_install(&eth_conf, &eth));
    esp_eth_netif_glue_handle_t glue = esp_eth_new_netif_glue(eth);
    ESP_ERROR_CHECK(glue ? ESP_OK : ESP_ERR_NO_MEM);
    ESP_ERROR_CHECK(esp_netif_attach(netif, glue));
    ESP_ERROR_CHECK(esp_eth_start(eth));
}

bool publish_sample(const sample_t *sample, const char *version)
{
    esp_http_client_config_t config = {
        .url = LAB_URL "/api/telemetry",
        .timeout_ms = 900,
        .disable_auto_redirect = true,
        .method = HTTP_METHOD_POST,
    };
    esp_http_client_handle_t client = esp_http_client_init(&config);
    if (!client) {
        return false;
    }
    char body[160];
    int size = snprintf(body, sizeof(body),
                        "{\"device\":\"esp32-lab\",\"sequence\":%" PRIu32
                        ",\"temperature_centi_c\":%" PRId32 ",\"firmware\":\"%s\"}",
                        sample->sequence, sample->temperature_centi_c, version);
    bool delivered = false;
    if (size > 0 && size < (int)sizeof(body) &&
        esp_http_client_set_header(client, "Content-Type", "application/json") == ESP_OK &&
        esp_http_client_set_post_field(client, body, size) == ESP_OK &&
        esp_http_client_perform(client) == ESP_OK) {
        int status = esp_http_client_get_status_code(client);
        delivered = status == 200 || status == 201;
    }
    esp_http_client_cleanup(client);
    return delivered;
}

typedef struct {
    char text[128];
    size_t length;
    bool overflow;
} manifest_t;

static esp_err_t read_manifest(esp_http_client_event_t *event)
{
    if (event->event_id == HTTP_EVENT_ON_DATA) {
        manifest_t *body = event->user_data;
        size_t received = event->data_len;
        if (received >= sizeof(body->text) - body->length) {
            body->overflow = true;
            return ESP_FAIL;
        }
        memcpy(body->text + body->length, event->data, received);
        body->length += received;
    }
    return ESP_OK;
}

static int version_number(const char *version)
{
    unsigned major, minor, patch;
    char end;
    char canonical[12];
    if (sscanf(version, "%3u.%3u.%3u%c", &major, &minor, &patch, &end) != 3) {
        return -1;
    }
    int length = snprintf(canonical, sizeof(canonical), "%u.%u.%u", major, minor, patch);
    if (length < 0 || length >= (int)sizeof(canonical) || strcmp(canonical, version) != 0) {
        return -1;
    }
    return (int)(major * 1000000 + minor * 1000 + patch);
}

bool find_update(const char *current, const char *rejected, char version[VERSION_CAPACITY])
{
    manifest_t body = {0};
    esp_http_client_config_t config = {
        .url = LAB_URL "/api/manifest",
        .timeout_ms = 900,
        .disable_auto_redirect = true,
        .event_handler = read_manifest,
        .user_data = &body,
    };
    esp_http_client_handle_t client = esp_http_client_init(&config);
    if (!client) {
        return false;
    }
    bool received = esp_http_client_perform(client) == ESP_OK &&
                    esp_http_client_get_status_code(client) == 200;
    esp_http_client_cleanup(client);
    if (!received || body.overflow) {
        return false;
    }
    cJSON *json = cJSON_ParseWithOpts(body.text, NULL, true);
    const char *offered = cJSON_GetStringValue(cJSON_GetObjectItemCaseSensitive(json, "version"));
    bool use = offered && strlen(offered) < VERSION_CAPACITY &&
               version_number(offered) > version_number(current) && strcmp(offered, rejected) != 0;
    if (use) {
        strcpy(version, offered);
    }
    cJSON_Delete(json);
    return use;
}

esp_err_t stage_update(const char *version)
{
    char url[128];
    snprintf(url, sizeof(url), LAB_URL "/images/%s.bin", version);
    esp_http_client_config_t http = {
        .url = url,
        .timeout_ms = 4500,
        .disable_auto_redirect = true,
        .buffer_size = 4096,
    };
    esp_https_ota_config_t config = {.http_config = &http};
    esp_https_ota_handle_t ota = NULL;
    esp_err_t result = esp_https_ota_begin(&config, &ota);
    if (result != ESP_OK) {
        return result;
    }
    esp_app_desc_t image;
    result = esp_https_ota_get_img_desc(ota, &image);
    if (result == ESP_OK &&
        (strncmp(image.version, version, sizeof(image.version)) != 0 ||
         strncmp(image.project_name, esp_app_get_description()->project_name,
                 sizeof(image.project_name)) != 0)) {
        ESP_LOGW(TAG, "OTA image metadata does not match manifest");
        result = ESP_ERR_INVALID_VERSION;
    }
    if (result == ESP_OK) {
        do {
            result = esp_https_ota_perform(ota);
        } while (result == ESP_ERR_HTTPS_OTA_IN_PROGRESS);
        if (result == ESP_OK && esp_https_ota_is_complete_data_received(ota)) {
            return esp_https_ota_finish(ota);
        }
        if (result == ESP_OK) {
            result = ESP_ERR_INVALID_SIZE;
        }
    }
    esp_https_ota_abort(ota);
    return result;
}
