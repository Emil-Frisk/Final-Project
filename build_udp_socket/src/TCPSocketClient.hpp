#pragma once

#include <string>
#include <memory>
#include <cstdint>
#include <mutex>
#include <iostream>

// Platform-specific includes
#ifdef _WIN32
    #include <winsock2.h>
    #include <ws2tcpip.h>
    #pragma comment(lib, "ws2_32.lib")
    using SocketType = SOCKET;
    constexpr SocketType INVALID_SOCKET_VALUE = INVALID_SOCKET;
#else
    #include <sys/socket.h>
    #include <netinet/in.h>
    #include <arpa/inet.h>
    #include <netdb.h>
    #include <unistd.h>
    using SocketType = int;
    constexpr SocketType INVALID_SOCKET_VALUE = -1;
#endif

class TCPSocketClient {
private:
    std::string host_ip_;
    int host_port_;
    SocketType socket_;
    bool skip_platform_init;
    bool is_connected_;
    static inline std::mutex close_mutex_;

    // Platform initialization (Windows only)
    static inline bool winsock_initialized_ = false;
    static inline std::mutex init_mutex_;

    void initialize_platform() {
#ifdef _WIN32
        std::lock_guard<std::mutex> lock(init_mutex_);
        if (!winsock_initialized_) {
            WSADATA wsa_data;
            if (WSAStartup(MAKEWORD(2, 2), &wsa_data) != 0) {
                is_connected_ = false;
                return;
            }
            winsock_initialized_ = true;
        }
#endif
    }

public:
    explicit TCPSocketClient(const std::string& host_ip, int host_port, bool skip_platform_init=false):
        host_ip_(host_ip),
        socket_(INVALID_SOCKET_VALUE),
        is_connected_(false),
        host_port_(host_port) {
        if (!skip_platform_init) {
            initialize_platform();
        }
    }

    ~TCPSocketClient() {
        close();
    }

    // Delete copy operations
    TCPSocketClient(const TCPSocketClient&) = delete;
    TCPSocketClient& operator=(const TCPSocketClient&) = delete;

    // Allow move operations
    TCPSocketClient(TCPSocketClient&& other)
        : host_ip_(std::move(other.host_ip_)),
          socket_(other.socket_),
          is_connected_(other.is_connected_),
          host_port_(other.host_port_) {
        other.socket_ = INVALID_SOCKET_VALUE;
        other.is_connected_ = false;
    }

    TCPSocketClient& operator=(TCPSocketClient&& other) {
        if (this != &other) {
            close();
            host_ip_ = std::move(other.host_ip_);
            socket_ = other.socket_;
            is_connected_ = other.is_connected_;
            host_port_ = other.host_port_;
            other.socket_ = INVALID_SOCKET_VALUE;
            other.is_connected_ = false;
        }
        return *this;
    }

    bool connect() {
        if (is_connected_) {
            return true; 
        }
        // Create socket
        socket_ = ::socket(AF_INET, SOCK_STREAM, IPPROTO_TCP);
        if (socket_ == INVALID_SOCKET_VALUE) {
            return false;
        }
		set_socket_timeout(10.0);

        // Parse host IP and setup address structure
        struct sockaddr_in server_addr {};
        server_addr.sin_family = AF_INET;
        server_addr.sin_port = htons(host_port_);
        // Convert IP address
        int pton_r = inet_pton(AF_INET, host_ip_.c_str(), &server_addr.sin_addr);
        if (pton_r <= 0) {
            struct addrinfo hints{}, *result;
            hints.ai_family = AF_INET;
            hints.ai_socktype = SOCK_STREAM;

            int gai_r = getaddrinfo(host_ip_.c_str(), nullptr, &hints, &result);
            if (gai_r != 0) {
                close();
                return false;
            }
            server_addr.sin_addr = ((struct sockaddr_in*)result->ai_addr)->sin_addr;
            freeaddrinfo(result);
        }
        // Attempt connection
        if (::connect(socket_, reinterpret_cast<struct sockaddr*>(&server_addr),
                      sizeof(server_addr)) == -1) {
#ifdef _WIN32
            closesocket(socket_);
#else
            ::close(socket_);
#endif
            socket_ = INVALID_SOCKET_VALUE;
            return false;
        }
        is_connected_ = true;
        return true;
    }

    bool send() {
        if (!is_connected_ || socket_ == INVALID_SOCKET_VALUE) {
            return false;
        }

        const uint8_t data = 1;
        int result = ::send(socket_, reinterpret_cast<const char*>(&data), sizeof(data), 0);

        if (result == -1) {
            is_connected_ = false;
            return false;
        }

        return result == sizeof(data);
    }

    void close() {
        std::lock_guard<std::mutex> lock(close_mutex_);
        if (socket_ != INVALID_SOCKET_VALUE) {
#ifdef _WIN32
            closesocket(socket_);
#else
            ::close(socket_);
#endif
        socket_ = INVALID_SOCKET_VALUE;
        }
        is_connected_ = false;
    }

    // Utility methods
    bool is_connected() const {
        return is_connected_;
    }

    const std::string& get_host_ip() const {
        return host_ip_;
    }

	bool set_socket_timeout(double timeout_sec) {
	    if (socket_ == INVALID_SOCKET_VALUE) {
	        return false;
	    }

	    #ifdef _WIN32
	    DWORD timeout_ms = static_cast<DWORD>(timeout_sec * 1000.0 + 0.5);  // round nearest
	    int ret = setsockopt(socket_, SOL_SOCKET, SO_RCVTIMEO,
	                         reinterpret_cast<const char*>(&timeout_ms), sizeof(timeout_ms));
	    #else
	    struct timeval tv{};
	    tv.tv_sec  = static_cast<time_t>(timeout_sec);
	    tv.tv_usec = static_cast<suseconds_t>((timeout_sec - tv.tv_sec) * 1'000'000.0 + 0.5);

	    int ret = setsockopt(socket_, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof(tv));
	    #endif

	    if (ret == -1) {
	        return false;
	    }

	    return true;
	}
};
