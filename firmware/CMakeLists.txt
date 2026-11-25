cmake_minimum_required(VERSION 3.16)

set(LAB_VERSION "1.0.0" CACHE STRING "Firmware version advertised in the OTA manifest")
set(LAB_FORCE_SELF_TEST_FAILURE OFF CACHE BOOL "Reject this image on its first boot")
set(LAB_SERVER_PORT "8765" CACHE STRING "HTTP port on the QEMU host")
set(PROJECT_VER "${LAB_VERSION}")
set(COMPONENTS main)
include($ENV{IDF_PATH}/tools/cmake/project.cmake)
project(esp32_ota_lab)
