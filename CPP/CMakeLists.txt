cmake_minimum_required(VERSION 3.10)

# Project Name: OXX Terminal (C++ Engine)
project(OXX_Terminal_CPP VERSION 1.0.0 LANGUAGES CXX)

# Enforce modern timestamp behavior for downloaded content (Policy CMP0135)
if(POLICY CMP0135)
    cmake_policy(SET CMP0135 NEW)
endif()

# Standardize on C++17
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# Suppress MSVC "unsafe" warnings for standard C functions (like localtime)
if(MSVC)
    add_definitions(-D_CRT_SECURE_NO_WARNINGS)
endif()

# Configure output directory for executables
set(CMAKE_RUNTIME_OUTPUT_DIRECTORY ${CMAKE_BINARY_DIR}/bin)

# --------------------------------------------------------------------------------
# DEPENDENCIES: External Libraries
# --------------------------------------------------------------------------------

# 1. OpenSSL for HMAC-SHA256 signing
find_package(OpenSSL REQUIRED)

# 2. nlohmann/json for API Payloads
include(FetchContent)
FetchContent_Declare(
    json
    URL https://github.com/nlohmann/json/releases/download/v3.11.3/json.tar.xz
    DOWNLOAD_EXTRACT_TIMESTAMP TRUE
)
FetchContent_Declare(
    httplib
    URL https://github.com/yhirose/cpp-httplib/archive/refs/tags/v0.14.3.tar.gz
    DOWNLOAD_EXTRACT_TIMESTAMP TRUE
)
FetchContent_Declare(
    ftxui
    URL https://github.com/ArthurSonzogni/ftxui/archive/refs/tags/v5.0.0.tar.gz
    DOWNLOAD_EXTRACT_TIMESTAMP TRUE
)
FetchContent_MakeAvailable(json httplib ftxui)

# --------------------------------------------------------------------------------
# LIBRARIES: OXX Core Logic
# --------------------------------------------------------------------------------

# 1. PnL Accountant Module
add_library(oxx_accountant STATIC
    Accountant.cpp
    Accountant.hpp
)

# 2. Security & Auth Module
add_library(oxx_security STATIC
    Auth.cpp
    SecurityUtils.hpp
)
target_link_libraries(oxx_security PRIVATE OpenSSL::SSL OpenSSL::Crypto)

# 2. Strategy Engine Module
add_library(oxx_strategy STATIC
    StrategyEngine.cpp
    StrategyEngine.hpp
)

# 3. OKX Private Client Module
add_library(oxx_private STATIC
    OKXPrivateClient.cpp
    OKXPrivateClient.hpp
)
target_link_libraries(oxx_private PRIVATE oxx_security OpenSSL::SSL OpenSSL::Crypto httplib::httplib nlohmann_json::nlohmann_json)

# 3. OKX Private Client Module
add_library(oxx_private STATIC
    OKXPrivateClient.cpp
    OKXPrivateClient.hpp
)
target_link_libraries(oxx_private PRIVATE oxx_security OpenSSL::SSL OpenSSL::Crypto httplib::httplib nlohmann_json::nlohmann_json)

# --------------------------------------------------------------------------------
# EXECUTABLES: Production Consolidation
# --------------------------------------------------------------------------------

# The main OXX Terminal C++ application
# add_executable(oxx_terminal main.cpp)
# target_link_libraries(oxx_terminal PRIVATE oxx_private oxx_strategy oxx_accountant)

# --------------------------------------------------------------------------------
# FUTURE: TUI & API INTEGRATION (Placeholders)
# --------------------------------------------------------------------------------

# We will eventually add FetchContent here for:
# - FTXUI (Terminal User Interface)
# - IXWebSocket (Exchange Streams)
# - nlohmann_json (API Payloads)
