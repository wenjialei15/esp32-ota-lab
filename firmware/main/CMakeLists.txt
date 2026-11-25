idf_component_register(
    SRCS "main.c" "queue.c" "transport.c"
    PRIV_REQUIRES app_update esp_eth esp_event esp_http_client esp_https_ota esp_netif esp_timer json nvs_flash
)
target_compile_definitions(${COMPONENT_LIB} PRIVATE
    LAB_SERVER_PORT=${LAB_SERVER_PORT}
    LAB_FORCE_SELF_TEST_FAILURE=$<BOOL:${LAB_FORCE_SELF_TEST_FAILURE}>
)
