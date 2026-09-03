#include "StrategyEngine.hpp"
#include <cmath>
#include <algorithm>
#include <numeric>
#include <iostream>
#include <ctime>

// --------------------------------------------------------------------------------
// 1. OKX Grid Validator
// --------------------------------------------------------------------------------
OKXGridValidator::OKXGridValidator(double min_order_val, int min_grids, int max_grids)
    : min_order_val(min_order_val), min_grids(min_grids), max_grids(max_grids) {}

std::pair<bool, std::string> OKXGridValidator::validate_setup(double lower_price, double upper_price,
                                                               int grid_count, double total_investment,
                                                               double current_market_price) {
    if (lower_price >= upper_price) {
        return {false, "Error: Lower price must be strictly less than upper price."};
    }
    if (current_market_price < lower_price || current_market_price > upper_price) {
        return {false, "Error: Price is outside grid range."};
    }
    if (grid_count < min_grids || grid_count > max_grids) {
        return {false, "Error: Grid count must be between " + std::to_string(min_grids) + " and " + std::to_string(max_grids)};
    }
    double investment_per_grid = total_investment / grid_count;
    if (investment_per_grid < min_order_val) {
        return {false, "Error: Investment per grid is below OKX minimum."};
    }
    return {true, "Validation Passed"};
}

// --------------------------------------------------------------------------------
// 3. Grid Strategy Engine
// --------------------------------------------------------------------------------
GridStrategyEngine::GridStrategyEngine(const std::string& inst_id, double lower_bound, double upper_bound,
                                       int grids, double investment_amount, const std::string& grid_type)
    : inst_id(inst_id), lower_bound(lower_bound), upper_bound(upper_bound),
      grids(grids), investment_amount(investment_amount), grid_type(grid_type) {
    _initialize_grid();
}

void GridStrategyEngine::_initialize_grid() {
    if (grids <= 1) return;

    if (grid_type == "geometric") {
        double ratio = std::pow(upper_bound / lower_bound, 1.0 / (grids - 1));
        for (int i = 0; i < grids; ++i) {
            grid_levels.push_back(lower_bound * std::pow(ratio, i));
        }
    } else {
        double step = (upper_bound - lower_bound) / (grids - 1);
        for (int i = 0; i < grids; ++i) {
            grid_levels.push_back(lower_bound + (i * step));
        }
    }
    std::sort(grid_levels.begin(), grid_levels.end());
}

std::optional<TradingSignal> GridStrategyEngine::process_tick(double current_price) {
    if (!active) {
        for (size_t i = 0; i < grid_levels.size(); ++i) {
            if (current_price >= grid_levels[i]) {
                last_grid_index = static_cast<int>(i);
            }
        }
        active = true;
        std::string anchor = last_grid_index ? std::to_string(grid_levels[*last_grid_index]) : "None";
        return TradingSignal{"LOG", current_price, 0.0, "GridBot: Active, Anchor=" + anchor};
    }

    std::optional<int> new_index;
    for (size_t i = 0; i < grid_levels.size(); ++i) {
        if (current_price >= grid_levels[i]) {
            new_index = static_cast<int>(i);
        }
    }

    if (new_index && last_grid_index) {
        if (*new_index > *last_grid_index) {
            last_grid_index = new_index;
            double sz = (investment_amount / grids) / current_price;
            return TradingSignal{"SELL", grid_levels[*new_index], sz, "GridBot"};
        } else if (*new_index < *last_grid_index) {
            last_grid_index = new_index;
            double sz = (investment_amount / grids) / current_price;
            return TradingSignal{"BUY", grid_levels[*new_index], sz, "GridBot"};
        }
    }
    return std::nullopt;
}

void GridStrategyEngine::update_position(const std::string& side, double price, double size) {
    if (side == "BUY" || side == "buy") {
        double new_pos = current_pos + size;
        if (new_pos > 0) {
            avg_price = ((avg_price * current_pos) + (price * size)) / new_pos;
        }
        current_pos = new_pos;
    } else if (side == "SELL" || side == "sell") {
        if (current_pos > 0) {
            realized_pnl += (price - avg_price) * std::min(current_pos, size);
        }
        current_pos -= size;
    }
}

double GridStrategyEngine::calculate_pnl(double current_price) const {
    double unrealized = (current_pos != 0) ? current_pos * (current_price - avg_price) : 0.0;
    return realized_pnl + unrealized;
}

// --------------------------------------------------------------------------------
// 4. DCA Strategy Engine
// --------------------------------------------------------------------------------
DCAStrategyEngine::DCAStrategyEngine(const std::string& inst_id, double base_order_size, double drop_trigger_pct)
    : inst_id(inst_id), base_order_size(base_order_size), drop_trigger_pct(drop_trigger_pct) {}

std::optional<TradingSignal> DCAStrategyEngine::process_tick(double current_price) {
    if (!active) {
        active = true;
        last_purchase_price = current_price;
        return TradingSignal{"BUY", current_price, base_order_size / current_price, "DCABot"};
    }

    if (last_purchase_price) {
        double drop = ((*last_purchase_price - current_price) / *last_purchase_price) * 100.0;
        if (drop >= drop_trigger_pct) {
            last_purchase_price = current_price;
            return TradingSignal{"BUY", current_price, base_order_size / current_price, "DCABot"};
        }
    }
    return std::nullopt;
}

void DCAStrategyEngine::update_position(const std::string& side, double price, double size) {
    if (side == "BUY" || side == "buy") {
        double new_pos = current_pos + size;
        if (new_pos > 0) {
            avg_price = ((avg_price * current_pos) + (price * size)) / new_pos;
        }
        current_pos = new_pos;
    } else if (side == "SELL" || side == "sell") {
        if (current_pos > 0) {
            realized_pnl += (price - avg_price) * std::min(current_pos, size);
        }
        current_pos -= size;
    }
}

double DCAStrategyEngine::calculate_pnl(double current_price) const {
    double unrealized = (current_pos != 0) ? current_pos * (current_price - avg_price) : 0.0;
    return realized_pnl + unrealized;
}

// --------------------------------------------------------------------------------
// 5. Strategy Manager
// --------------------------------------------------------------------------------
std::string StrategyManager::start_grid_bot(const std::string& inst_id, double lower, double upper,
                                            int grids, double investment, const std::string& grid_type) {
    std::string bot_id = "grid_" + inst_id + "_" + std::to_string(std::time(nullptr));
    active_bots[bot_id] = std::make_unique<GridStrategyEngine>(inst_id, lower, upper, grids, investment, grid_type);
    return bot_id;
}

std::string StrategyManager::start_dca_bot(const std::string& inst_id, double base_amount, double drop_pct) {
    std::string bot_id = "dca_" + inst_id + "_" + std::to_string(std::time(nullptr));
    active_bots[bot_id] = std::make_unique<DCAStrategyEngine>(inst_id, base_amount, drop_pct);
    return bot_id;
}

void StrategyManager::update_bot_fill(const std::string& bot_id, const std::string& side, double price, double size) {
    auto it = active_bots.find(bot_id);
    if (it != active_bots.end()) {
        it->second->update_position(side, price, size);
    }
}

double StrategyManager::get_total_session_pnl(const std::map<std::string, double>& current_prices) {
    double total = 0.0;
    for (auto const& [id, bot] : active_bots) {
        auto it = current_prices.find(bot->get_inst_id());
        if (it != current_prices.end()) {
            total += bot->calculate_pnl(it->second);
        } else {
            total += bot->get_realized_pnl();
        }
    }
    return total;
}

int StrategyManager::stop_all() {
    int count = static_cast<int>(active_bots.size());
    active_bots.clear();
    return count;
}

// --------------------------------------------------------------------------------
// Technical Indicators
// --------------------------------------------------------------------------------
std::vector<std::optional<double>> StrategyManager::calculate_ema(const std::vector<double>& data, int period) {
    std::vector<std::optional<double>> ema(data.size(), std::nullopt);
    if (data.size() < static_cast<size_t>(period)) return ema;

    double multiplier = 2.0 / (period + 1);
    double initial_sma = std::accumulate(data.begin(), data.begin() + period, 0.0) / period;
    ema[period - 1] = initial_sma;

    for (size_t i = period; i < data.size(); ++i) {
        ema[i] = (data[i] - *ema[i - 1]) * multiplier + *ema[i - 1];
    }
    return ema;
}

std::vector<std::optional<double>> StrategyManager::calculate_rsi(const std::vector<double>& data, int period) {
    std::vector<std::optional<double>> rsi(data.size(), std::nullopt);
    if (data.size() <= static_cast<size_t>(period)) return rsi;

    std::vector<double> deltas;
    for (size_t i = 1; i < data.size(); ++i) deltas.push_back(data[i] - data[i - 1]);

    double avg_gain = 0, avg_loss = 0;
    for (int i = 0; i < period; ++i) {
        if (deltas[i] > 0) avg_gain += deltas[i];
        else avg_loss -= deltas[i];
    }
    avg_gain /= period;
    avg_loss /= period;

    if (avg_loss == 0) rsi[period] = 100.0;
    else {
        double rs = avg_gain / avg_loss;
        rsi[period] = 100.0 - (100.0 / (1.0 + rs));
    }

    for (size_t i = period + 1; i < data.size(); ++i) {
        double gain = (deltas[i - 1] > 0) ? deltas[i - 1] : 0.0;
        double loss = (deltas[i - 1] < 0) ? -deltas[i - 1] : 0.0;
        avg_gain = (avg_gain * (period - 1) + gain) / period;
        avg_loss = (avg_loss * (period - 1) + loss) / period;

        if (avg_loss == 0) rsi[i] = 100.0;
        else {
            double rs = avg_gain / avg_loss;
            rsi[i] = 100.0 - (100.0 / (1.0 + rs));
        }
    }
    return rsi;
}
