cmake_minimum_required(VERSION 3.11)
project(BloombergTerminal)

set(CMAKE_CXX_STANDARD 17)

include(FetchContent)

# 1. Fetch FTXUI for the terminal interface components
FetchContent_Declare(
  ftxui
  GIT_REPOSITORY https://github.com/ArthurSonzogni/FTXUI
  GIT_TAG v5.0.0
)
FetchContent_MakeAvailable(ftxui)

# 2. Fetch nlohmann/json for native data parsing in C++
FetchContent_Declare(
  json
  GIT_REPOSITORY https://github.com/nlohmann/json
  GIT_TAG v3.11.3
)
FetchContent_MakeAvailable(json)

# Define your main binary target
add_executable(bloomberg_terminal 
  main.cpp 
  chart_widget.cpp
)

# Link your dependencies
target_link_libraries(bloomberg_terminal
  PRIVATE ftxui::dom
  PRIVATE ftxui::screen
  PRIVATE ftxui::component
  PRIVATE nlohmann_json::nlohmann_json
)

file(COPY bridge_daemon.py DESTINATION ${CMAKE_CURRENT_BINARY_DIR})
