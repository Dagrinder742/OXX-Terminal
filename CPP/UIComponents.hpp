#ifndef OXX_UI_COMPONENTS_HPP
#define OXX_UI_COMPONENTS_HPP

#include <ftxui/dom/elements.hpp>
#include <ftxui/component/component.hpp>
#include <map>
#include <string>
#include <vector>

namespace oxx::ui {

using namespace ftxui;

// --- Steelers Star Theme Constants ---
const Color SteelersGold = Color::Yellow;
const Color StarBlue = Color::RGB(51, 153, 255);
const Color StarRed = Color::RGB(255, 51, 51);
const Color DeepBlack = Color::Black;

// --- Component Interface ---
class UIComponents {
public:
    static Element Header(const std::string& inst_id, const std::string& price,
                          const std::string& high, const std::string& low, const std::string& vol);

    static Element Sidebar(const std::string& balance, const std::map<std::string, std::string>& preflight);

    static Element MarketHub(const std::string& title, const std::vector<std::vector<std::string>>& data);

    static Element OrderBook(const std::vector<std::pair<std::string, std::string>>& asks,
                             const std::vector<std::pair<std::string, std::string>>& bids,
                             const std::string& spread);

    static Element LastTrades(const std::vector<std::vector<std::string>>& trades);

    static Element ExecutionLog(const std::vector<std::string>& logs);

    static Element ChartPlaceholder(const std::string& inst_id, const std::string& timeframe);
};

} // namespace oxx::ui

#endif // OXX_UI_COMPONENTS_HPP
