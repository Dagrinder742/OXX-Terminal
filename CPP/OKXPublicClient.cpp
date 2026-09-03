#include "OKXPublicClient.hpp"
#include <iostream>

const std::string OKXPublicClient::WS_URL = "wss://ws.okx.com:8443/ws/v5/public";

OKXPublicClient::OKXPublicClient(const std::string& inst_id, const std::vector<std::string>& wl)
    : instrument_id(inst_id), watchlist(wl) {

    webSocket.setUrl(WS_URL);

    webSocket.setOnMessageCallback([this](const ix::WebSocketMessagePtr& msg) {
        this->handle_message(msg);
    });
}

OKXPublicClient::~OKXPublicClient() {
    stop();
}

void OKXPublicClient::connect() {
    std::cout << "[OKX_Public] Connecting to WebSocket..." << std::endl;
    webSocket.start();
}

void OKXPublicClient::stop() {
    webSocket.stop();
}

void OKXPublicClient::subscribe() {
    nlohmann::json ticker_args = nlohmann::json::array();
    ticker_args.push_back({{"channel", "tickers"}, {"instId", instrument_id}});

    for (const auto& inst : watchlist) {
        if (inst != instrument_id) {
            ticker_args.push_back({{"channel", "tickers"}, {"instId", inst}});
        }
    }

    nlohmann::json subscribe_msg = {
        {"op", "subscribe"},
        {"args", ticker_args}
    };

    // Add order book and trades for the focus instrument
    subscribe_msg["args"].push_back({{"channel", "books"}, {"instId", instrument_id}});
    subscribe_msg["args"].push_back({{"channel", "trades"}, {"instId", instrument_id}});

    webSocket.send(subscribe_msg.dump());
    std::cout << "[OKX_Public] Subscribed to channels (count: " << subscribe_msg["args"].size() << ")" << std::endl;
}

void OKXPublicClient::handle_message(const ix::WebSocketMessagePtr& msg) {
    if (msg->type == ix::WebSocketMessageType::Message) {
        try {
            auto data = nlohmann::json::parse(msg->str);

            if (data.contains("event") && data["event"] == "subscribe") {
                std::cout << "[OKX_Public] Subscription Confirmed." << std::endl;
                return;
            }

            if (data.contains("arg") && data.contains("data")) {
                std::string channel = data["arg"]["channel"];
                if (callback) {
                    callback(channel, data["data"]);
                }
            }
        } catch (const std::exception& e) {
            std::cerr << "[OKX_Public] JSON Parse Error: " << e.what() << std::endl;
        }
    } else if (msg->type == ix::WebSocketMessageType::Open) {
        std::cout << "[OKX_Public] Connection Open. Sending subscriptions..." << std::endl;
        subscribe();
    } else if (msg->type == ix::WebSocketMessageType::Error) {
        std::cerr << "[OKX_Public] Connection Error: " << msg->errorInfo.reason << std::endl;
    } else if (msg->type == ix::WebSocketMessageType::Close) {
        std::cout << "[OKX_Public] Connection Closed." << std::endl;
    }
}
