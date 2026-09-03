#ifndef OXX_STRATEGY_ENGINE_HPP
#define OXX_STRATEGY_ENGINE_HPP

#include <string>
#include <vector>
#include <map>
#include <optional>
#include <memory>

// Signal Structure for Bot Communication
struct TradingSignal {
    std::string type;   // BUY, SELL, LOG
    double price;
    double size;
    std::string tag;
};

// --------------------------------------------------------------------------------
// 1. OKX Grid Validator
// --------------------------------------------------------------------------------
class OKXGridValidator {
public:
    OKXGridValidator(double min_order_val = 1.0, int min_grids = 2, int max_grids = 150);

    std::pair<bool, std::string> validate_setup(double lower_price, double upper_price,
                                               int grid_count, double total_investment,
                                               double current_market_price);

private:
    double min_order_val;
    int min_grids;
    int max_grids;
};

// --------------------------------------------------------------------------------
// 2. Base Strategy Engine (Interface)
// --------------------------------------------------------------------------------
class StrategyEngine {
public:
    virtual ~StrategyEngine() = default;
    virtual std::optional<TradingSignal> process_tick(double current_price) = 0;
    virtual void update_position(const std::string& side, double price, double size) = 0;
    virtual double calculate_pnl(double current_price) const = 0;

    virtual std::string get_inst_id() const = 0;
    virtual double get_current_pos() const = 0;
    virtual double get_realized_pnl() const = 0;
};

// --------------------------------------------------------------------------------
// 3. Grid Strategy Engine
// --------------------------------------------------------------------------------
class GridStrategyEngine : public StrategyEngine {
public:
    GridStrategyEngine(const std::string& inst_id, double lower_bound, double upper_bound,
                       int grids, double investment_amount, const std::string& grid_type = "arithmetic");

    std::optional<TradingSignal> process_tick(double current_price) override;
    void update_position(const std::string& side, double price, double size) override;
    double calculate_pnl(double current_price) const override;

    std::string get_inst_id() const override { return inst_id; }
    double get_current_pos() const override { return current_pos; }
    double get_realized_pnl() const override { return realized_pnl; }

private:
    std::string inst_id;
    double lower_bound;
    double upper_bound;
    int grids;
    double investment_amount;
    std::string grid_type;

    std::vector<double> grid_levels;
    std::optional<int> last_grid_index;
    bool active = false;

    double realized_pnl = 0.0;
    double current_pos = 0.0;
    double avg_price = 0.0;

    void _initialize_grid();
};

// --------------------------------------------------------------------------------
// 4. DCA Strategy Engine
// --------------------------------------------------------------------------------
class DCAStrategyEngine : public StrategyEngine {
public:
    DCAStrategyEngine(const std::string& inst_id, double base_order_size, double drop_trigger_pct);

    std::optional<TradingSignal> process_tick(double current_price) override;
    void update_position(const std::string& side, double price, double size) override;
    double calculate_pnl(double current_price) const override;

    std::string get_inst_id() const override { return inst_id; }
    double get_current_pos() const override { return current_pos; }
    double get_realized_pnl() const override { return realized_pnl; }

private:
    std::string inst_id;
    double base_order_size;
    double drop_trigger_pct;

    std::optional<double> last_purchase_price;
    bool active = false;

    double realized_pnl = 0.0;
    double current_pos = 0.0;
    double avg_price = 0.0;
};

// --------------------------------------------------------------------------------
// 5. Strategy Manager (Orchestrator)
// --------------------------------------------------------------------------------
class StrategyManager {
public:
    StrategyManager() = default;

    std::string start_grid_bot(const std::string& inst_id, double lower, double upper,
                               int grids, double investment, const std::string& grid_type = "arithmetic");

    std::string start_dca_bot(const std::string& inst_id, double base_amount, double drop_pct);

    void update_bot_fill(const std::string& bot_id, const std::string& side, double price, double size);

    double get_total_session_pnl(const std::map<std::string, double>& current_prices);

    int stop_all();

    // Technical Indicators (Static parity with Python)
    static std::vector<std::optional<double>> calculate_ema(const std::vector<double>& data, int period);
    static std::vector<std::optional<double>> calculate_rsi(const std::vector<double>& data, int period = 14);

private:
    std::map<std::string, std::unique_ptr<StrategyEngine>> active_bots;
};

#endif // OXX_STRATEGY_ENGINE_HPP
