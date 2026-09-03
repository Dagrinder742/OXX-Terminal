#define NOMINMAX
#include "OKXPublicClient.hpp"
#include "UIComponents.hpp"
#include <ixwebsocket/IXNetSystem.h>
#include <ftxui/dom/elements.hpp>
#include <ftxui/component/component.hpp>
#include <ftxui/component/screen_interactive.hpp>
#include <iostream>
#include <mutex>
#include <map>
#include <thread>
#include <chrono>
#include <iomanip>
#include <sstream>
#include <algorithm>

using namespace ftxui;
using namespace oxx::ui;

// Thread-safe state for the TUI
struct TickerData {
    std::string price = "0.0";
    std::string change_24h = "0.0%";
    std::string high = "0.0";
    std::string low = "0.0";
    std::string range_pct = "0%";
};

struct AppState {
    std::mutex mtx;
    std::string focus_pair = "BTC-USD";
    std::string current_price = "Connecting...";
    std::string high_24h = "0.0";
    std::string low_24h = "0.0";
    std::string vol_24h = "0.0";

    std::map<std::string, TickerData> watchlist;
    std::vector<std::pair<std::string, std::string>> asks;
    std::vector<std::pair<std::string, std::string>> bids;
    std::vector<std::vector<std::string>> trades;
    std::vector<std::string> logs = {"OXX C++ Engine Live. Monitoring market data..."};
};

AppState app_state;

// WebSocket Callback to update state
void on_ws_data(const std::string& channel, const nlohmann::json& data) {
    std::lock_guard<std::mutex> lock(app_state.mtx);
    if (channel == "tickers") {
        for (const auto& t : data) {
            std::string id = t.value("instId", "Unknown");

            try {
                double last = std::stod(t.value("last", "0.0"));
                double open = std::stod(t.value("open24h", "1.0"));
                double high = std::stod(t.value("high24h", "1.0"));
                double low = std::stod(t.value("low24h", "1.0"));

                double change = ((last - open) / (open != 0 ? open : 1.0)) * 100.0;
                double rpi = (high != low) ? ((last - low) / (high - low)) * 100.0 : 0.0;

                std::stringstream ss_chg, ss_rpi;
                ss_chg << (change >= 0 ? "+" : "") << std::fixed << std::setprecision(2) << change << "%";
                ss_rpi << std::fixed << std::setprecision(1) << rpi << "%";

                app_state.watchlist[id] = {
                    t.value("last", "0.0"), ss_chg.str(), t.value("high24h", "0.0"),
                    t.value("low24h", "0.0"), ss_rpi.str()
                };

                if (id == app_state.focus_pair) {
                    app_state.current_price = t.value("last", "0.0");
                    app_state.high_24h = t.value("high24h", "0.0");
                    app_state.low_24h = t.value("low24h", "0.0");
                    app_state.vol_24h = t.value("vol24h", "0.0");
                }
            } catch (...) {
                // Fail silently on malformed numbers
            }
        }
    } else if (channel == "books") {
        app_state.asks.clear(); app_state.bids.clear();
        if (!data.empty()) {
            auto first_snap = data[0];
            auto asks = first_snap["asks"];
            auto bids = first_snap["bids"];
            for (int i=0; i<(std::min)(5, (int)asks.size()); ++i) app_state.asks.push_back({asks[i][0], asks[i][1]});
            for (int i=0; i<(std::min)(5, (int)bids.size()); ++i) app_state.bids.push_back({bids[i][0], bids[i][1]});
        }
    } else if (channel == "trades") {
        for (const auto& tr : data) {
            app_state.trades.insert(app_state.trades.begin(), {
                tr.value("px", "0"), tr.value("sz", "0"), tr.value("side", "buy"), tr.value("ts", "0")
            });
            if (app_state.trades.size() > 10) app_state.trades.pop_back();
        }
    }
}

int main() {
    ix::initNetSystem();

    std::vector<std::string> symbols = {"BTC-USD", "ETH-USD", "SOL-USD", "HYPE-USD", "LTC-USD", "NEAR-USD", "XRP-USD"};
    OKXPublicClient publicClient("BTC-USD", symbols);
    publicClient.set_callback(on_ws_data);
    publicClient.connect();

    auto screen = ScreenInteractive::Fullscreen();

    auto renderer = Renderer([&] {
        std::lock_guard<std::mutex> lock(app_state.mtx);

        auto header = UIComponents::Header(app_state.focus_pair, app_state.current_price,
                                           app_state.high_24h, app_state.low_24h, app_state.vol_24h);

        // Sidebar Data
        std::map<std::string, std::string> pf = {{"fee", "$0.00"}, {"hurdle", "$0.00"}, {"net_tp", "$0.00"}};
        auto sidebar = UIComponents::Sidebar("0.00 USD", pf);

        // Center Stack
        auto chart = UIComponents::ChartPlaceholder(app_state.focus_pair, "15m");
        auto feeds = hbox({
            UIComponents::OrderBook(app_state.asks, app_state.bids, "0.10"),
            UIComponents::LastTrades(app_state.trades)
        });

        // Market Hubs - Split Watchlist
        std::vector<std::vector<std::string>> hubA_data, hubB_data;
        int count = 0;
        for (const auto& [id, d] : app_state.watchlist) {
            std::vector<std::string> row = {id, d.price, d.change_24h, d.range_pct};
            if (count++ < 4) hubA_data.push_back(row); else hubB_data.push_back(row);
        }

        auto hubs = hbox({
            UIComponents::MarketHub(" MARKET HUB A ", hubA_data),
            UIComponents::MarketHub(" MARKET HUB B ", hubB_data)
        });

        auto logs = hbox({
            UIComponents::MarketHub(" Order History ", {}),
            UIComponents::ExecutionLog(app_state.logs)
        });

        return vbox({ header, hbox({sidebar, vbox({chart, feeds, hubs, logs}) | flex}) | flex });
    });

    auto component = CatchEvent(renderer, [&](Event event) {
        if (event == Event::Escape) { screen.ExitLoopClosure()(); return true; }
        return false;
    });

    std::thread refresh([&] { while(true) { std::this_thread::sleep_for(std::chrono::milliseconds(100)); screen.PostEvent(Event::Custom); } });
    refresh.detach();

    screen.Loop(component);
    publicClient.stop();
    ix::uninitNetSystem();
    return 0;
}
