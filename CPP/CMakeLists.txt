cmake_minimum_required(VERSION 3.10)

# Project Name: OXX Terminal (C++ Engine)
project(OXX_Terminal_CPP VERSION 1.0.0 LANGUAGES CXX)

# --- GLOBAL BUILD OPTIONS (Snowman Standard) ---
if(POLICY CMP0135)
    cmake_policy(SET CMP0135 NEW)
endif()

# Force IXWebSocket to use OpenSSL and ZLIB we provide (Snowman Standard)
# Note: Variable names MUST exactly match library expectations (USE_OPEN_SSL, USE_MBED_TLS)
set(USE_TLS ON CACHE BOOL "" FORCE)
set(USE_OPEN_SSL ON CACHE BOOL "" FORCE)
set(USE_ZLIB ON CACHE BOOL "" FORCE)
set(USE_MBED_TLS OFF CACHE BOOL "" FORCE)

# Disable installation of dependencies (we only need the binary)
set(IXWEBSOCKET_INSTALL OFF CACHE BOOL "" FORCE)
set(FTXUI_ENABLE_INSTALL OFF CACHE BOOL "" FORCE)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

if(MSVC)
    add_definitions(-D_CRT_SECURE_NO_WARNINGS)
    # Suppress warnings from external libraries to focus on OXX Core
    add_compile_options(/wd4244 /wd4267)
endif()

set(CMAKE_RUNTIME_OUTPUT_DIRECTORY ${CMAKE_BINARY_DIR}/bin)

# --------------------------------------------------------------------------------
# DEPENDENCIES: External Libraries
# --------------------------------------------------------------------------------

# 1. OpenSSL (The only security provider allowed)
find_package(OpenSSL REQUIRED)

include(FetchContent)

# 2. ZLIB (Compression for WebSocket speed)
FetchContent_Declare(
    zlib
    URL https://github.com/madler/zlib/archive/refs/tags/v1.3.1.tar.gz
    DOWNLOAD_EXTRACT_TIMESTAMP TRUE
)
FetchContent_MakeAvailable(zlib)

# SATISFY FIND_PACKAGE(ZLIB): Point subsequent searches to our built-in version
set(ZLIB_INCLUDE_DIR "${zlib_SOURCE_DIR};${zlib_BINARY_DIR}" CACHE PATH "Path to ZLIB includes" FORCE)
if (MSVC)
    set(ZLIB_LIBRARY zlibstatic CACHE STRING "Path to ZLIB library" FORCE)
else()
    set(ZLIB_LIBRARY z CACHE STRING "Path to ZLIB library" FORCE)
endif()
set(ZLIB_FOUND TRUE CACHE BOOL "ZLIB found" FORCE)

# Create ZLIB alias for IXWebSocket discovery
if (NOT TARGET ZLIB::ZLIB)
    if (TARGET zlibstatic)
        add_library(ZLIB::ZLIB ALIAS zlibstatic)
    else()
        add_library(ZLIB::ZLIB ALIAS zlib)
    endif()
endif()

# 3. JSON
FetchContent_Declare(
    json
    URL https://github.com/nlohmann/json/releases/download/v3.11.3/json.tar.xz
    DOWNLOAD_EXTRACT_TIMESTAMP TRUE
)

# 4. HTTP (REST)
FetchContent_Declare(
    httplib
    URL https://github.com/yhirose/cpp-httplib/archive/refs/tags/v0.14.3.tar.gz
    DOWNLOAD_EXTRACT_TIMESTAMP TRUE
)

# 5. TUI (FTXUI)
FetchContent_Declare(
    ftxui
    URL https://github.com/ArthurSonzogni/ftxui/archive/refs/tags/v5.0.0.tar.gz
    DOWNLOAD_EXTRACT_TIMESTAMP TRUE
)

# 6. WebSocket (The Firehose)
FetchContent_Declare(
    ixwebsocket
    URL https://github.com/machinezone/IXWebSocket/archive/refs/tags/v11.4.4.tar.gz
    DOWNLOAD_EXTRACT_TIMESTAMP TRUE
)

FetchContent_MakeAvailable(json httplib ftxui ixwebsocket)

# --------------------------------------------------------------------------------
# LIBRARIES: OXX Core Logic
# --------------------------------------------------------------------------------

# 1. PnL Accountant
add_library(oxx_accountant STATIC Accountant.cpp Accountant.hpp)

# 2. Security & Auth
add_library(oxx_security STATIC Auth.cpp SecurityUtils.hpp)
target_link_libraries(oxx_security PRIVATE OpenSSL::SSL OpenSSL::Crypto)

# 3. Strategy Engine
add_library(oxx_strategy STATIC StrategyEngine.cpp StrategyEngine.hpp)

# 4. Private Client (REST)
add_library(oxx_private STATIC OKXPrivateClient.cpp OKXPrivateClient.hpp)
target_link_libraries(oxx_private PUBLIC oxx_security OpenSSL::SSL OpenSSL::Crypto httplib nlohmann_json::nlohmann_json)

# 5. Public Client (WebSocket)
add_library(oxx_public STATIC OKXPublicClient.cpp OKXPublicClient.hpp)
target_link_libraries(oxx_public PUBLIC OpenSSL::SSL OpenSSL::Crypto ixwebsocket::ixwebsocket nlohmann_json::nlohmann_json)

# --------------------------------------------------------------------------------
# EXECUTABLES: Production
# --------------------------------------------------------------------------------

add_executable(oxx_terminal
    main.cpp
    UIComponents.cpp
    UIComponents.hpp
)

# Link everything to the main executable
# We include ftxui targets here because main.cpp uses them directly
target_link_libraries(oxx_terminal PRIVATE
    oxx_public
    oxx_private
    oxx_strategy
    oxx_accountant
    ftxui::screen
    ftxui::dom
    ftxui::component
)
