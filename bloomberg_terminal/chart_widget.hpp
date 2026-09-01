#pragma once
#include <ftxui/dom/elements.hpp>

namespace TerminalUI {
    // Returns a renderable FTXUI Element containing your dynamic chart data
    ftxui::Element RenderTrendChart(const std::vector<int>& price_data);
}

