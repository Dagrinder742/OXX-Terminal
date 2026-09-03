#include "OKXPrivateClient.hpp"
#include "SecurityUtils.hpp"
#include <httplib.h>
#include <ctime>
#include <iomanip>
#include <sstream>
#include <iostream>

const std::string OKXPrivateClient::BASE_URL = "https://us.okx.com";
const std::string OKXPrivateClient::HOST = "us.okx.com";

std::string OKXPrivateClient::get_timestamp() {
    std::time_t t = std::time(nullptr);
    std::tm* tm = std::gmtime(&t);
    std::ostringstream oss;
    oss << std::put_time(tm, "%Y-%m-%dT%H:%M:%S.320Z");
    return oss.str();
}

nlohmann::json OKXPrivateClient::authenticated_request(const OKXCredentials& creds,
                                                     const std::string& method,
                                                     const std::string& endpoint,
                                                     const std::string& body) {
    httplib::SSLClient cli(HOST);

    // Modern Timeout Logic (Standard for high-frequency trading)
    cli.set_connection_timeout(std::chrono::seconds(10));
    cli.set_read_timeout(std::chrono::seconds(10));

    std::string timestamp = get_timestamp();
    std::string signature_msg = timestamp + method + endpoint + body;
    std::string signature = SecurityUtils::hmac_sha256_base64(creds.secret_key, signature_msg);

    httplib::Headers headers = {
        {"OK-ACCESS-KEY", creds.api_key},
        {"OK-ACCESS-SIGN", signature},
        {"OK-ACCESS-TIMESTAMP", timestamp},
        {"OK-ACCESS-PASSPHRASE", creds.passphrase},
        {"Content-Type", "application/json"}
    };

    httplib::Result res;
    if (method == "GET") {
        res = cli.Get(endpoint, headers);
    } else if (method == "POST") {
        res = cli.Post(endpoint, headers, body, "application/json");
    }

    if (res && res->status == 200) {
        return nlohmann::json::parse(res->body);
    } else {
        std::string err_msg = res ? "HTTP Status: " + std::to_string(res->status) : "Request failed";
        return {{"code", "500"}, {"msg", err_msg}};
    }
}

nlohmann::json OKXPrivateClient::get_account_balance(const OKXCredentials& creds) {
    return authenticated_request(creds, "GET", "/api/v5/account/balance");
}

nlohmann::json OKXPrivateClient::get_trade_fee(const OKXCredentials& creds, const std::string& inst_type) {
    return authenticated_request(creds, "GET", "/api/v5/account/trade-fee?instType=" + inst_type);
}

nlohmann::json OKXPrivateClient::place_order(const OKXCredentials& creds,
                                            const std::string& inst_id,
                                            const std::string& side,
                                            const std::string& order_type,
                                            const std::string& sz,
                                            const std::string& px,
                                            const std::string& tp_trigger_px,
                                            const std::string& sl_trigger_px) {
    nlohmann::json payload = {
        {"instId", inst_id},
        {"tdMode", "cash"},
        {"side", side},
        {"ordType", order_type},
        {"sz", sz}
    };

    if (!px.empty()) {
        payload["px"] = px;
    }

    if (!tp_trigger_px.empty()) {
        payload["tpTriggerPx"] = tp_trigger_px;
        payload["tpOrdPx"] = "-1";
    }

    if (!sl_trigger_px.empty()) {
        payload["slTriggerPx"] = sl_trigger_px;
        payload["slOrdPx"] = "-1";
    }

    return authenticated_request(creds, "POST", "/api/v5/trade/order", payload.dump());
}
