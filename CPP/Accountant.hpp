#ifndef OXX_ACCOUNTANT_HPP
#define OXX_ACCOUNTANT_HPP

#include <string>
#include <vector>
#include <map>
#include <ctime>

struct FillRecord {
    std::string time;
    std::string inst_id;
    std::string side;
    double price;
    double size;
    double fee;
    std::string tag;
};

struct Position {
    double size;
    double avg_price;
};

struct PreflightMetrics {
    double fee;
    double break_even;
    double net_tp;
    double net_sl;
};

struct SessionSummary {
    double net;
    double fees;
};

class PnLAccountant {
public:
    PnLAccountant(double taker_fee_rate = 0.0035, double maker_fee_rate = 0.0020);

    void update_tier_data(double taker, double maker, const std::string& level = "VIP 0");

    PreflightMetrics calculate_preflight_metrics(double price, double size, double tp_price = 0.0, double sl_price = 0.0);

    void record_confirmed_fill(const std::string& inst_id, const std::string& side, double price, double size, const std::string& tag = "Manual");

    SessionSummary get_session_summary(const std::map<std::string, double>& current_market_prices);

private:
    double taker_rate;
    double maker_rate;
    std::string tier_label;
    double realized_pnl_gross;
    double total_fees_paid;
    std::map<std::string, Position> positions;
    std::vector<FillRecord> fills;

    std::string get_current_time_str();
};

#endif // OXX_ACCOUNTANT_HPP
