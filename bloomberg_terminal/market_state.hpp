#pragma once
#include <string>
#include <vector>
#include <map>

struct Trade {
    double price;
    double size;
    std::string side;
};

struct MarketState {
    std::string instrument_id = "BTC-USD";
    double current_price = 0.0;
    double high_price = 0.0;
    double low_price = 0.0;
    double volume = 0.0;
    
    std::vector<Trade> recent_trades;
    std::vector<int> price_history; // For your chart rendering
};

