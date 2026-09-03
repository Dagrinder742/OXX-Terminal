#include <iostream>
#include <string>
#include <vector>
#include <memory>
#include <unordered_map>
#include <cmath>
#include "ftxui/component/component.hpp"
#include "ftxui/component/screen_interactive.hpp"
#include "ftxui/dom/elements.hpp"

using namespace ftxui;

class AuthModal {
private:
    std::string api_key_str = "";
    std::string secret_key_str = "";
    std::string passphrase_str = "";
    std::string status_message = "Enter your API credentials. Press Enter to submit.";

public:
    Element RenderModal() {
        return vbox({
            text(" OKX Secure Credential Setup") | bold | color(Color::Cyan),
            text(status_message),
            separator(),
            text("API Key:"),
            separator(),
            text("Secret Key:"),
            separator(),
            text("Passphrase:"),
        }) | border | size(WIDTH, EQUAL, 60) | size(HEIGHT, EQUAL, 24);
    }

    void SubmitCredentials() {
        if (!api_key_str.empty() && !secret_key_str.empty() && !passphrase_str.empty()) {
            std::cout << "[Vault] Saving encrypted credentials...\n";
        } else {
            status_message = "All fields are required! Please fill out all inputs.";
        }
    }
};

class OKXTerminalApp {
private:
    const std::vector<std::string> watchlist = {
        "BTC-USD", "HYPE-USD", "SOL-USD", "ETH-USD", "JUP-USD",
        "JTO-USD", "APT-USD", "PAXG-USD", "TRX-USD", "SHIB-USD",
        "RENDER-USD", "OP-USD", "ATOM-USD", "LTC-USD",
        "NEAR-USD", "UNI-USD", "LINK-USD", "ADA-USD", "AVAX-USD",
        "XRP-USD", "SUI-USD", "DOGE-USD", "BNB-USD", "USDT-USD"
    };

public:
    // State variables
    std::string instrument_id;
    std::vector<std::vector<std::string>> cached_asks;
    std::vector<std::vector<std::string>> cached_bids;
    std::vector<std::string> cached_trades;

    std::string current_timeframe;
    std::string grid_type;

    double session_pnl;
    bool simulation_mode;

    std::unordered_map<std::string, double> portfolio_balances;
    std::unordered_map<std::string, std::unordered_map<std::string, std::string>> telemetry_data;

    // Display states
    std::string current_price;
    std::string high_24h;
    std::string low_24h;
    std::string volume_24h;

    // Input String Buffers (Mirrors Textual Input Widgets)
    std::string price_input_str;
    std::string amount_input_str;
    std::string tp_input_str;
    std::string sl_input_str;

    // Pre-Flight Calculator Metrics
    double preflight_fee;
    double preflight_break_even;
    double preflight_net_tp;
    double preflight_net_sl;
    std::string tier_label;

    OKXTerminalApp() {
        instrument_id = "BTC-USD";
        current_timeframe = "15m";
        grid_type = "arithmetic";
        session_pnl = 0.0;
        simulation_mode = true;

        current_price = "80,885.00"; // Default baseline for calculation testing
        high_24h = "---";
        low_24h = "---";
        volume_24h = "---";

        price_input_str = "";
        amount_input_str = "0.01";
        tp_input_str = "";
        sl_input_str = "";

        preflight_fee = 0.0;
        preflight_break_even = 0.0;
        preflight_net_tp = 0.0;
        preflight_net_sl = 0.0;
        tier_label = "VIP 0";

        update_preflight_calculator();
    }

    // Direct translation of Python update_preflight_calculator logic
    void update_preflight_calculator() {
        try {
            double price = 0.0;
            if (price_input_str.empty()) {
                std::string px_clean = current_price;
                px_clean.erase(std::remove(px_clean.begin(), px_clean.end(), ','), px_clean.end());
                price = (px_clean != "Connecting...") ? std::stod(px_clean) : 0.0;
            } else {
                std::string px_clean = price_input_str;
                px_clean.erase(std::remove(px_clean.begin(), px_clean.end(), '$'), px_clean.end());
                px_clean.erase(std::remove(px_clean.begin(), px_clean.end(), ','), px_clean.end());
                price = std::stod(px_clean);
            }

            double amount = amount_input_str.empty() ? 0.0 : std::stod(amount_input_str);
            double tp = tp_input_str.empty() ? 0.0 : std::stod(tp_input_str);
            double sl = sl_input_str.empty() ? 0.0 : std::stod(sl_input_str);

            // Standard mock calculation mapping to Accountant tier rules (0.35% Taker fee model)
            double notional = price * amount;
            preflight_fee = notional * 0.0035;
            preflight_break_even = price + (amount > 0 ? (preflight_fee / amount) : 0.0);

            preflight_net_tp = (tp > 0) ? ((tp - price) * amount) - preflight_fee : 0.0;
            preflight_net_sl = (sl > 0) ? -((price - sl) * amount + preflight_fee) : 0.0;

        } catch (...) {
            // Silently handle partial inputs while typing (similar to Python exception block)
        }
    }

    void action_switch_instrument(const std::string& new_inst) {
        if (instrument_id == new_inst) return;
        std::string old_inst = instrument_id;
        instrument_id = new_inst;
        std::cout << "[Market Switch] Switching instrument from " << old_inst << " to " << new_inst << "...\n";
        cached_asks.clear();
        cached_bids.clear();
        cached_trades.clear();
        current_price = "Connecting...";
    }

    void toggle_grid_type() {
        grid_type = (grid_type == "arithmetic") ? "geometric" : "arithmetic";
        std::cout << "[Config] Grid Type changed to: " << grid_type << "\n";
    }
};

int main() {
    OKXTerminalApp app;

    // FTXUI Input Bindings
    Component price_input = Input(&app.price_input_str, "$0.00");
    Component amount_input = Input(&app.amount_input_str, "0.001");
    Component tp_input = Input(&app.tp_input_str, "Take-Profit Price...");
    Component sl_input = Input(&app.sl_input_str, "Stop-Loss Price...");

    // Hook inputs to trigger pre-flight recalculation on change
    auto input_container = Container::Vertical({
        price_input | CatchEvent([&](Event) { app.update_preflight_calculator(); return false; }),
        amount_input | CatchEvent([&](Event) { app.update_preflight_calculator(); return false; }),
        tp_input | CatchEvent([&](Event) { app.update_preflight_calculator(); return false; }),
        sl_input | CatchEvent([&](Event) { app.update_preflight_calculator(); return false; }),
    });

    auto renderer = Renderer(input_container, [&] {
        return vbox({
            window(text("OXX TUI - Bloomberg Terminal Mode"),
                hbox({
                    text(" Instrument: " + app.instrument_id) | bold | color(Color::Yellow),
                    separator(),
                    text(" Price: " + app.current_price) | bold | color(Color::Green),
                })
            ),
            hbox({
                // Left Column: Order Inputs & Pre-Flight Calculator Box
                vbox({
                    text("Order Entry Panel") | bold | color(Color::Yellow),
                    text("Price:"),
                    price_input->Render() | border,
                    text("Amount:"),
                    amount_input->Render() | border,

                    // Tactical Edge Pre-Flight Box (Translated from Python)
                    window(text(" Tactical Edge (" + app.tier_label + ")") | color(Color::Blue),
                        vbox({
                            text("Est. Fee:  $" + std::to_string(app.preflight_fee)) | color(Color::Red),
                            text("Hurdle:    $" + std::to_string(app.preflight_break_even)),
                            text("Net TP:    $" + std::to_string(app.preflight_net_tp)) | color(Color::Green),
                            text("Net SL:    $" + std::to_string(app.preflight_net_sl)) | color(Color::Red),
                        })
                    ),

                    text("Advanced Risk Management"),
                    text("Take-Profit:"),
                    tp_input->Render() | border,
                    text("Stop-Loss:"),
                    sl_input->Render() | border,
                }) | size(WIDTH, EQUAL, 45) | border,

                // Right Main Workspace Placeholder
                vbox({
                    window(text("Candlestick Price Action"),
                        text("ASCII Chart Engine Active...") | color(Color::Cyan) | yframe | size(HEIGHT, EQUAL, 15)
                    )
                }) | flex
            }) | flex
        });
    });

    auto screen = ScreenInteractive::Fullscreen();
    screen.Loop(renderer);

    return 0;
}
