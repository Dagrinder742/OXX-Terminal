#ifndef OXX_PRIVATE_CLIENT_HPP
#define OXX_PRIVATE_CLIENT_HPP

#include <string>
#include <nlohmann/json.hpp>

struct OKXCredentials {
    std::string api_key;
    std::string secret_key;
    std::string passphrase;
};

class OKXPrivateClient {
public:
    OKXPrivateClient() = default;

    static nlohmann::json get_account_balance(const OKXCredentials& creds);

    static nlohmann::json place_order(const OKXCredentials& creds,
                                     const std::string& inst_id,
                                     const std::string& side,
                                     const std::string& order_type,
                                     const std::string& sz,
                                     const std::string& px = "",
                                     const std::string& tp_trigger_px = "",
                                     const std::string& sl_trigger_px = "");

    static nlohmann::json get_trade_fee(const OKXCredentials& creds, const std::string& inst_type = "SPOT");

private:
    static const std::string BASE_URL;
    static const std::string HOST;

    static std::string get_timestamp();
    static nlohmann::json authenticated_request(const OKXCredentials& creds,
                                              const std::string& method,
                                              const std::string& endpoint,
                                              const std::string& body = "");
};

#endif // OXX_PRIVATE_CLIENT_HPP
