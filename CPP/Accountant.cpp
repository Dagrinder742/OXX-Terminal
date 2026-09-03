#include "Accountant.hpp"
#include <cmath>
#include <algorithm>
#include <iomanip>
#include <sstream>

PnLAccountant::PnLAccountant(double taker_fee_rate, double maker_fee_rate)
    : taker_rate(std::abs(taker_fee_rate)),
      maker_rate(std::abs(maker_fee_rate)),
      tier_label("PENDING"),
      realized_pnl_gross(0.0),
      total_fees_paid(0.0) {}

void PnLAccountant::update_tier_data(double taker, double maker, const std::string& level) {
    taker_rate = std::abs(taker);
    maker_rate = std::abs(maker);
    tier_label = level;
    std::transform(tier_label.begin(), tier_label.end(), tier_label.begin(), ::toupper);
}

PreflightMetrics PnLAccountant::calculate_preflight_metrics(double price, double size, double tp_price, double sl_price) {
    if (price <= 0 || size <= 0) {
        return {0.0, 0.0, 0.0, 0.0};
    }

    double entry_fee = price * size * taker_rate;

    // HURDLE: (Entry * (1 + Taker)) / (1 - Maker)
    double break_even = (price * (1.0 + taker_rate)) / (1.0 - maker_rate);

    double total_est_friction = entry_fee;
    double net_tp = 0.0;
    double net_sl = 0.0;

    if (tp_price > 0) {
        double tp_exit_fee = tp_price * size * maker_rate;
        net_tp = ((tp_price - price) * size) - (entry_fee + tp_exit_fee);
        total_est_friction = entry_fee + tp_exit_fee;
    }

    if (sl_price > 0) {
        double sl_exit_fee = sl_price * size * taker_rate;
        net_sl = ((sl_price - price) * size) - (entry_fee + sl_exit_fee);
        if (tp_price <= 0) {
            total_est_friction = entry_fee + sl_exit_fee;
        }
    }

    return {total_est_friction, break_even, net_tp, net_sl};
}

void PnLAccountant::record_confirmed_fill(const std::string& inst_id, const std::string& side, double price, double size, const std::string& tag) {
    double fee_usd = price * size * taker_rate;
    total_fees_paid += fee_usd;

    std::string side_upper = side;
    std::transform(side_upper.begin(), side_upper.end(), side_upper.begin(), ::toupper);

    FillRecord fill = {
        get_current_time_str(),
        inst_id,
        side_upper,
        price,
        size,
        fee_usd,
        tag
    };
    fills.push_back(fill);

    Position& pos = positions[inst_id];
    double curr_sz = pos.size;
    double curr_avg = pos.avg_price;

    if (side_upper == "BUY") {
        double new_sz = curr_sz + size;
        if (curr_sz < 0) {
            double covered = std::min(std::abs(curr_sz), size);
            realized_pnl_gross += (curr_avg - price) * covered;
        }
        if (new_sz > 0) {
            pos.avg_price = ((curr_avg * std::max(0.0, curr_sz)) + (price * size)) / new_sz;
        }
        pos.size = new_sz;
    } else if (side_upper == "SELL") {
        double new_sz = curr_sz - size;
        if (curr_sz > 0) {
            double sold = std::min(curr_sz, size);
            realized_pnl_gross += (price - curr_avg) * sold;
        }
        if (new_sz < 0) {
            pos.avg_price = ((curr_avg * std::min(0.0, curr_sz)) + (price * -size)) / new_sz;
        }
        pos.size = new_sz;
    }
}

SessionSummary PnLAccountant::get_session_summary(const std::map<std::string, double>& current_market_prices) {
    double unrealized_gross = 0.0;
    for (auto const& [inst, pos] : positions) {
        if (pos.size == 0) continue;

        auto it = current_market_prices.find(inst);
        double mark_price = (it != current_market_prices.end()) ? it->second : pos.avg_price;
        unrealized_gross += (mark_price - pos.avg_price) * pos.size;
    }

    return { (realized_pnl_gross + unrealized_gross) - total_fees_paid, total_fees_paid };
}

std::string PnLAccountant::get_current_time_str() {
    std::time_t t = std::time(nullptr);
    std::tm tm = *std::localtime(&t);
    std::ostringstream oss;
    oss << std::put_time(&tm, "%H:%M:%S");
    return oss.str();
}
