#include "chart_widget.hpp"
#include <vector>
#include <algorithm>

namespace TerminalUI {

ftxui::Element RenderTrendChart(const std::vector<int>& price_data) {
    using namespace ftxui;

    auto router = [&](int width, int height) {
        std::vector<int> output(width, 0);
        if (price_data.empty()) return output;

        // Map your price history across the available terminal width columns
        for (int i = 0; i < width; ++i) {
            int data_index = (i * price_data.size()) / width;
            if (data_index < price_data.size()) {
                // Scale the value to fit within the container height
                output[i] = price_data[data_index] % height; 
            }
        }
        return output;
    };

    return window(text(" Trend: EMA-9 vs EMA-21 ") | bold,
                  graph(router) | color(Color::Cyan) | flex
    );
}

}

