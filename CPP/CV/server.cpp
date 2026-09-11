#include "crow_all.h"
#include <fstream>
#include <iostream>

std::string read_agent_memory() {
    std::ifstream file("agent_memory.json");
    if (!file.is_open()) {
        return "{\"error\": \"agent_memory.json not found\"}";
    }
    std::string str((std::istreambuf_iterator<char>(file)),
                     std::istreambuf_iterator<char>());
    return str;
}

int main() {
    crow::SimpleApp app;

    CROW_ROUTE(app, "/api/status")([](){
        std::string memory_data = read_agent_memory();
        crow::response res(memory_data);
        res.add_header("Content-Type", "application/json");
        res.add_header("Access-Control-Allow-Origin", "*");
        return res;
    });

    CROW_ROUTE(app, "/")([](){
        return "OXX Terminal C++ Backend Active. Hit /api/status for agent telemetry.";
    });

    app.port(8080).multithreaded().run();
}
