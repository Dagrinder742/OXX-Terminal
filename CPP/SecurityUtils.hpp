#ifndef OXX_SECURITY_UTILS_HPP
#define OXX_SECURITY_UTILS_HPP

#include <string>
#include <openssl/hmac.h>
#include <openssl/evp.h>
#include <openssl/buffer.h>

class SecurityUtils {
public:
    /**
     * [HARDENING] Zeroes out the memory occupied by a string.
     * Use this to wipe API Keys/Secrets from RAM immediately after use.
     */
    static void zero_memory(std::string& s) {
        volatile char* p = const_cast<volatile char*>(s.data());
        size_t n = s.size();
        while (n--) *p++ = 0;
        s.clear();
    }

    /**
     * Generates an HMAC-SHA256 signature encoded in Base64.
     */
    static std::string hmac_sha256_base64(const std::string& key, const std::string& msg);

    /**
     * Standard Base64 Encoding for OKX compatibility.
     */
    static std::string base64_encode(const unsigned char* input, int length);
};

#endif // OXX_SECURITY_UTILS_HPP
