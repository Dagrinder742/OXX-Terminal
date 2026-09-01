#include "chart_widget.hpp"
#include <vector>

namespace TerminalUI {

ftxui::Element RenderTrendChart(const std::vector<int>& price_data) {
    using namespace ftxui;

    // Added '&' inside the capture brackets to capture price_data by reference
    auto router = [&](int width, int height) {
        std::vector<int> output(width, 0);
        for (int i = 0; i < width && i < price_data.size(); ++i) {
            output[i] = price_data[i];
        }
        return output;
    };

    return window(text(" Trend: EMA-9 vs EMA-21 ") | bold,
                  graph(router) | color(Color::Cyan) | flex
    );
}

}

