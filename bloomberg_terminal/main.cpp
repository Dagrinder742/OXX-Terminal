#include <ftxui/component/component.hpp>
#include <ftxui/component/screen_interactive.hpp>
#include <ftxui/dom/elements.hpp>
#include <iostream>
#include <thread>
#include <chrono>
#include "market_state.hpp"
#include "chart_widget.hpp"

int main() {
    using namespace ftxui;

    // Initialize screen and market data state
    auto screen = ScreenInteractive::Fullscreen();
    MarketState state;

    // Mock initial data injection to verify UI rendering
    state.current_price = 77705.4;
    state.high_price = 79859.6;
    state.low_price = 76889.1;
    state.volume = 329.56;
    state.price_history = {50, 52, 51, 55, 60, 58, 62, 65, 63, 67, 70, 68, 72};

    // Main UI Renderer Loop
    auto renderer = Renderer([&] {
        using namespace ftxui;

        // 1. Ticker Header Panel
        auto header_text = hbox({
            text(" OXX TUI > BTC-USD ") | bold | color(Color::Green),
            text(" | Price: " + std::to_string(state.current_price)) | color(Color::Yellow),
            text(" | High: " + std::to_string(state.high_price)),
            text(" | Low: " + std::to_string(state.low_price)),
            text(" | Vol: " + std::to_string(state.volume))
        }) | border | color(Color::Gold1);

        // 2. Chart Panel (Using our modular chart widget)
        auto chart_panel = TerminalUI::RenderTrendChart(state.price_history);

        // 3. Order Book & System Logs Subpanel
        auto order_book = window(text(" Order Book ") | bold,
            vbox({
                text("Asks (Sells) [Price / Amt]") | color(Color::Red),
                text("77715.2   0.0089"),
                text("77711.5   0.0730"),
            })
        );

        auto system_logs = window(text(" System Logs ") | bold,
            vbox({
                text("Status: ONLINE") | color(Color::Cyan),
                text("Engine: Native C++ Core"),
            })
        );

        auto bottom_row = hbox({
            order_book | flex,
            system_logs | flex
        });

        // Master Grid Assembly
        return vbox({
            header_text,
            hbox({
                // Left Control Sidebar placeholder
                vbox({
                    window(text(" Quick Actions ") | bold,
                        vbox({
                            text(" [ BUY (LONG) ] ") | color(Color::Blue) | bold,
                            text(" [ SELL (SHORT) ] ") | color(Color::Red) | bold,
                        })
                    )
                }) | size(WIDTH, EQUAL, 30),
                // Right Display Panels
                vbox({
                    chart_panel | flex,
                    bottom_row
                }) | flex
            }) | flex
        }) | color(Color::Gold1);
    });

    // Event handling to let you press 'q' to cleanly exit the terminal
    auto component = CatchEvent(renderer, [&](Event event) {
        if (event == Event::Character('q') || event == Event::Character('Q')) {
            screen.Exit();
            return true;
        }
        return false;
    });

    // Launch the interactive TUI event loop
    screen.Loop(component);
    return 0;
}
