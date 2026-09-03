#include "UIComponents.hpp"
#include <ftxui/dom/table.hpp>

namespace oxx::ui {

Element UIComponents::Header(const std::string& inst_id, const std::string& price,
                              const std::string& high, const std::string& low, const std::string& vol) {
    return hbox({
        text(" OXX TUI > " + inst_id) | bold | color(SteelersGold),
        text(" | Price: ") | dim, text(price) | color(Color::Green),
        text(" | High: ") | dim, text(high),
        text(" | Low: ") | dim, text(low),
        text(" | Vol: ") | dim, text(vol)
    }) | border;
}

Element UIComponents::Sidebar(const std::string& balance, const std::map<std::string, std::string>& preflight) {
    auto search_box = vbox({
        text(" Instrument Search ") | dim,
        text(" BTC-USD ") | border | color(Color::Green)
    });

    auto portfolio = vbox({
        text(" Portfolio Balance ") | color(SteelersGold),
        text(balance) | dim
    });

    auto entry_panel = vbox({
        text(" Order Entry Panel ") | color(SteelersGold),
        text(" Price: ") | dim, text("$0.00") | border | color(Color::Green),
        text(" Amount: ") | dim, text("0.001") | border | color(Color::Green),
        hbox({
            text(" 25% ") | border, text(" 50% ") | border, text(" 75% ") | border, text(" 100% ") | border
        })
    });

    auto preflight_panel = vbox({
        text(" ⚙ Tactical Edge (Pre-Flight) ") | color(StarBlue),
        text(" Est. Fee: " + preflight.at("fee")) | dim,
        text(" Hurdle:   " + preflight.at("hurdle")) | dim,
        text(" Net TP:   " + preflight.at("net_tp")) | dim
    }) | border;

    return vbox({
        search_box, portfolio, separator(), entry_panel, preflight_panel, filler(),
        text(" % MANAGE API KEYS ") | border | center | color(SteelersGold)
    }) | size(WIDTH, EQUAL, 40) | border;
}

Element UIComponents::MarketHub(const std::string& title, const std::vector<std::vector<std::string>>& data) {
    Elements rows;
    for (const auto& row : data) {
        Elements cells;
        for (size_t i = 0; i < row.size(); ++i) {
            auto cell_text = text(row[i]) | flex;
            // Apply color to 24H % column (index 2)
            if (i == 2) {
                if (row[i].find('+') != std::string::npos) cell_text = cell_text | color(Color::Green);
                else if (row[i].find('-') != std::string::npos) cell_text = cell_text | color(StarRed);
            }
            cells.push_back(std::move(cell_text));
        }
        rows.push_back(hbox(std::move(cells)));
    }

    return vbox({
        text(title) | color(SteelersGold),
        text("Asset    Price    24H %    RNG %") | dim,
        separator(),
        vbox(std::move(rows))
    }) | border | flex;
}

Element UIComponents::OrderBook(const std::vector<std::pair<std::string, std::string>>& asks,
                                 const std::vector<std::pair<std::string, std::string>>& bids,
                                 const std::string& spread) {
    Elements ask_elems, bid_elems;
    for (const auto& a : asks) ask_elems.push_back(hbox({text(a.first) | color(StarRed) | flex, text(a.second) | dim}));
    for (const auto& b : bids) bid_elems.push_back(hbox({text(b.first) | color(Color::Green) | flex, text(b.second) | dim}));

    return vbox({
        text(" Order Book ") | color(SteelersGold),
        text(" Asks (Sells) [Price / Amt] ") | dim,
        vbox(std::move(ask_elems)),
        text(" Spread: " + spread) | center | bold,
        text(" Bids (Buys) [Price / Amt] ") | dim,
        vbox(std::move(bid_elems))
    }) | border | flex;
}

Element UIComponents::LastTrades(const std::vector<std::vector<std::string>>& trades) {
    Elements trade_rows;
    for (const auto& trade : trades) {
        trade_rows.push_back(hbox({
            text(trade[0]) | color(trade[2] == "buy" ? Color::Green : StarRed) | flex,
            text(trade[1]) | dim | flex,
            text(trade[3]) | dim
        }));
    }
    return vbox({
        text(" Last Trades ") | color(SteelersGold),
        text(" Price (USD)  Amount  Time ") | dim,
        separator(),
        vbox(std::move(trade_rows))
    }) | border | flex;
}

Element UIComponents::ExecutionLog(const std::vector<std::string>& logs) {
    Elements log_elems;
    for (const auto& l : logs) log_elems.push_back(text(l));
    return vbox({
        text(" Execution & Order Log ") | color(Color::Magenta),
        vbox(std::move(log_elems))
    }) | border | flex;
}

Element UIComponents::ChartPlaceholder(const std::string& inst_id, const std::string& timeframe) {
    return vbox({
        text(" Candlestick Price Action ") | color(Color::Cyan),
        hbox({
            text(" 1m ") | border, text(" 5m ") | border, text(" 15m ") | border | bold, text(" 1H ") | border, text(" 1D ") | border
        }),
        filler(),
        text(inst_id + " [" + timeframe + "] | Pure Price Action") | center | bold,
        filler()
    }) | border | size(HEIGHT, EQUAL, 15);
}

} // namespace oxx::ui
