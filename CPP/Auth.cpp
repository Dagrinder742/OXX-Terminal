#include "SecurityUtils.hpp"
#include <openssl/bio.h>
#include <openssl/evp.h>
#include <openssl/buffer.h>
#include <vector>

std::string SecurityUtils::base64_encode(const unsigned char* input, int length) {
    BIO *bio, *b64;
    BUF_MEM *bufferPtr;

    b64 = BIO_new(BIO_f_base64());
    bio = BIO_new(BIO_s_mem());
    bio = BIO_push(b64, bio);

    BIO_set_flags(bio, BIO_FLAGS_BASE64_NO_NL); // No newlines for signatures

    // INFINITE-SAFE CHUNKING: Send data in blocks of 1MB (well within 32-bit limit)
    const size_t CHUNK_SIZE = 1048576;
    size_t total_len = static_cast<size_t>(length);
    size_t processed = 0;

    while (processed < total_len) {
        size_t remaining = total_len - processed;
        int current_chunk = static_cast<int>(std::min(CHUNK_SIZE, remaining));

        BIO_write(bio, input + processed, current_chunk);
        processed += static_cast<size_t>(current_chunk);
    }

    BIO_flush(bio);
    BIO_get_mem_ptr(bio, &bufferPtr);

    std::string result(bufferPtr->data, bufferPtr->length);
    BIO_free_all(bio);

    return result;
}

std::string SecurityUtils::hmac_sha256_base64(const std::string& key, const std::string& msg) {
    unsigned char hash[EVP_MAX_MD_SIZE];
    unsigned int hash_len = 0;

    // VALIDATION: Ensure key and message lengths fit in int
    if (key.length() > 2147483647 || msg.length() > 2147483647) {
        return "";
    }

    HMAC(EVP_sha256(), key.c_str(), static_cast<int>(key.length()),
         reinterpret_cast<const unsigned char*>(msg.c_str()), static_cast<int>(msg.length()),
         hash, &hash_len);

    return base64_encode(hash, static_cast<int>(hash_len));
}
