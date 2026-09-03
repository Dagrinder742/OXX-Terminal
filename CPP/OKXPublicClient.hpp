#ifndef OXX_PUBLIC_CLIENT_HPP
#define OXX_PUBLIC_CLIENT_HPP

#include <string>
#include <vector>
#include <functional>
#include <ixwebsocket/IXWebSocket.h>
#include <nlohmann/json.hpp>

class OKXPublicClient {
public:
    using DataCallback = std::function<void(const std::string& channel, const nlohmann::json& data)>;

    OKXPublicClient(const std::string& instrument_id = "BTC-USD",
                    const std::vector<std::string>& watchlist = {});

    ~OKXPublicClient();

    void set_callback(DataCallback cb) { callback = cb; }

    void connect();
    void stop();

private:
    std::string instrument_id;
    std::vector<std::string> watchlist;
    ix::WebSocket webSocket;
    DataCallback callback;

    static const std::string WS_URL;

    void subscribe();
    void handle_message(const ix::WebSocketMessagePtr& msg);
};

#endif // OXX_PUBLIC_CLIENT_HPP
