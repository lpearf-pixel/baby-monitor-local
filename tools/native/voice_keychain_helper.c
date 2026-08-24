#include <CoreFoundation/CoreFoundation.h>
#include <Security/Security.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

#define REQUEST_HEADER_BYTES 9
#define RESPONSE_HEADER_BYTES 7
#define MAX_ACCOUNT_BYTES 64
#define SECRET_BYTES 32
#define OP_READ 1
#define OP_WRITE 2
#define OP_DELETE 3
#define STATUS_SUCCESS 0
#define STATUS_NOT_FOUND 1
#define STATUS_UNAVAILABLE 2

static const char *SERVICE = "com.baby-monitor-local.voice-care";

static int read_exact(int descriptor, uint8_t *buffer, size_t length) {
    size_t offset = 0;
    while (offset < length) {
        ssize_t result = read(descriptor, buffer + offset, length - offset);
        if (result <= 0) {
            return 0;
        }
        offset += (size_t)result;
    }
    return 1;
}

static int write_exact(int descriptor, const uint8_t *buffer, size_t length) {
    size_t offset = 0;
    while (offset < length) {
        ssize_t result = write(descriptor, buffer + offset, length - offset);
        if (result <= 0) {
            return 0;
        }
        offset += (size_t)result;
    }
    return 1;
}

static void secure_zero(void *value, size_t length) {
    volatile uint8_t *current = (volatile uint8_t *)value;
    while (length > 0) {
        *current++ = 0;
        length--;
    }
}

static int is_lower_hex(char value) {
    return (value >= '0' && value <= '9') || (value >= 'a' && value <= 'f');
}

static int is_canonical_uuid(const char *value) {
    size_t index;
    if (strlen(value) != 36) {
        return 0;
    }
    for (index = 0; index < 36; index++) {
        if (index == 8 || index == 13 || index == 18 || index == 23) {
            if (value[index] != '-') {
                return 0;
            }
        } else if (!is_lower_hex(value[index])) {
            return 0;
        }
    }
    if (value[14] < '1' || value[14] > '5') {
        return 0;
    }
    return value[19] == '8' || value[19] == '9' || value[19] == 'a' ||
           value[19] == 'b';
}

static int allowed_account(const char *account) {
    const char *prefix = "voice-profile-key.v1.";
    if (strcmp(account, "voice-asr-calibration-key.v2") == 0 ||
        strcmp(account, "device-signing-key.v1") == 0 ||
        strcmp(account, "voice-outbox-key.v1") == 0) {
        return 1;
    }
    if (strncmp(account, prefix, strlen(prefix)) != 0) {
        return 0;
    }
    return is_canonical_uuid(account + strlen(prefix));
}

static int respond(uint8_t status, const uint8_t *secret, uint16_t length) {
    uint8_t header[RESPONSE_HEADER_BYTES] = {
        'V', 'K', 'R', '1', status, (uint8_t)(length >> 8), (uint8_t)length};
    if (!write_exact(STDOUT_FILENO, header, sizeof(header))) {
        return 0;
    }
    return length == 0 || write_exact(STDOUT_FILENO, secret, length);
}

static CFMutableDictionaryRef base_query(CFStringRef account) {
    CFMutableDictionaryRef query = CFDictionaryCreateMutable(
        kCFAllocatorDefault, 0, &kCFTypeDictionaryKeyCallBacks,
        &kCFTypeDictionaryValueCallBacks);
    if (query == NULL) {
        return NULL;
    }
    CFDictionarySetValue(query, kSecClass, kSecClassGenericPassword);
    CFDictionarySetValue(query, kSecAttrService, CFSTR("com.baby-monitor-local.voice-care"));
    CFDictionarySetValue(query, kSecAttrAccount, account);
    return query;
}

static uint8_t keychain_read(CFStringRef account, uint8_t secret[SECRET_BYTES]) {
    CFMutableDictionaryRef query = base_query(account);
    CFTypeRef result = NULL;
    OSStatus status;
    if (query == NULL) {
        return STATUS_UNAVAILABLE;
    }
    CFDictionarySetValue(query, kSecReturnData, kCFBooleanTrue);
    CFDictionarySetValue(query, kSecMatchLimit, kSecMatchLimitOne);
    status = SecItemCopyMatching(query, &result);
    CFRelease(query);
    if (status == errSecItemNotFound) {
        return STATUS_NOT_FOUND;
    }
    if (status != errSecSuccess || result == NULL || CFGetTypeID(result) != CFDataGetTypeID()) {
        if (result != NULL) {
            CFRelease(result);
        }
        return STATUS_UNAVAILABLE;
    }
    if (CFDataGetLength((CFDataRef)result) != SECRET_BYTES) {
        CFRelease(result);
        return STATUS_UNAVAILABLE;
    }
    CFDataGetBytes((CFDataRef)result, CFRangeMake(0, SECRET_BYTES), secret);
    CFRelease(result);
    return STATUS_SUCCESS;
}

static uint8_t keychain_write(CFStringRef account, const uint8_t secret[SECRET_BYTES]) {
    CFMutableDictionaryRef query = base_query(account);
    CFDataRef data;
    OSStatus status;
    if (query == NULL) {
        return STATUS_UNAVAILABLE;
    }
    data = CFDataCreate(kCFAllocatorDefault, secret, SECRET_BYTES);
    if (data == NULL) {
        CFRelease(query);
        return STATUS_UNAVAILABLE;
    }
    CFDictionarySetValue(query, kSecValueData, data);
    CFDictionarySetValue(
        query, kSecAttrAccessible, kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly);
    status = SecItemAdd(query, NULL);
    CFRelease(data);
    CFRelease(query);
    return (status == errSecSuccess || status == errSecDuplicateItem)
               ? STATUS_SUCCESS
               : STATUS_UNAVAILABLE;
}

static uint8_t keychain_delete(CFStringRef account) {
    CFMutableDictionaryRef query = base_query(account);
    OSStatus status;
    if (query == NULL) {
        return STATUS_UNAVAILABLE;
    }
    status = SecItemDelete(query);
    CFRelease(query);
    return (status == errSecSuccess || status == errSecItemNotFound)
               ? STATUS_SUCCESS
               : STATUS_UNAVAILABLE;
}

int main(void) {
    uint8_t header[REQUEST_HEADER_BYTES];
    char account[MAX_ACCOUNT_BYTES + 1];
    uint8_t secret[SECRET_BYTES];
    uint16_t account_length;
    uint16_t secret_length;
    uint8_t operation;
    uint8_t status = STATUS_UNAVAILABLE;
    CFStringRef account_string = NULL;
    int result = 1;
    (void)SERVICE;
    memset(account, 0, sizeof(account));
    memset(secret, 0, sizeof(secret));
    if (isatty(STDIN_FILENO) || isatty(STDOUT_FILENO) ||
        !read_exact(STDIN_FILENO, header, sizeof(header)) ||
        memcmp(header, "VKH1", 4) != 0) {
        goto finish;
    }
    operation = header[4];
    account_length = ((uint16_t)header[5] << 8) | header[6];
    secret_length = ((uint16_t)header[7] << 8) | header[8];
    if (account_length == 0 || account_length > MAX_ACCOUNT_BYTES ||
        (operation == OP_WRITE && secret_length != SECRET_BYTES) ||
        (operation != OP_WRITE && secret_length != 0) ||
        (operation != OP_READ && operation != OP_WRITE && operation != OP_DELETE) ||
        !read_exact(STDIN_FILENO, (uint8_t *)account, account_length) ||
        (secret_length > 0 && !read_exact(STDIN_FILENO, secret, secret_length))) {
        goto finish;
    }
    account[account_length] = '\0';
    if (!allowed_account(account)) {
        goto finish;
    }
    account_string = CFStringCreateWithCString(
        kCFAllocatorDefault, account, kCFStringEncodingASCII);
    if (account_string == NULL) {
        goto finish;
    }
    if (operation == OP_READ) {
        status = keychain_read(account_string, secret);
        result = respond(
                     status, status == STATUS_SUCCESS ? secret : NULL,
                     status == STATUS_SUCCESS ? SECRET_BYTES : 0)
                     ? 0
                     : 1;
    } else if (operation == OP_WRITE) {
        status = keychain_write(account_string, secret);
        result = respond(status, NULL, 0) ? 0 : 1;
    } else {
        status = keychain_delete(account_string);
        result = respond(status, NULL, 0) ? 0 : 1;
    }

finish:
    if (account_string != NULL) {
        CFRelease(account_string);
    }
    secure_zero(secret, sizeof(secret));
    secure_zero(account, sizeof(account));
    secure_zero(header, sizeof(header));
    return result;
}
