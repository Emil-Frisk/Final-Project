#pragma once

#include <atomic>
#include <chrono>
#include <cstdint>
#include <functional>
#include <mutex>
#include <optional>
#include <span>
#include <string>
#include <thread>
#include <vector>
#include <fmt/chrono.h> 
#include <pybind11/stl.h>
#include <pybind11/pybind11.h>
#include <pybind11/functional.h>

#ifdef _WIN32
    #define WIN32_LEAN_AND_MEAN
    #include <winsock2.h>
    #include <ws2tcpip.h>
    #pragma comment(lib, "ws2_32.lib")
#else // POSIX SOCKETS
    #include <netdb.h>
    #include <arpa/inet.h>
    #include <netinet/in.h>
    #include <sys/socket.h>
    #include <unistd.h>
#endif
#include "TCPSocketClient.hpp"

namespace py = pybind11;
class UDPSocket {
public:
    enum class SendType : char {
        Int8    = 'b',
        UInt8   = 'B',
        Int16   = 'h',
        UInt16  = 'H',
        Int32   = 'i',
        UInt32  = 'I',
        Int64   = 'q',
        UInt64  = 'Q',
        Float   = 'f',
        Double  = 'd'
    };

    static constexpr int INVALID_SOCKET_FD = -1;

    UDPSocket(
        double max_age_seconds       = 3.0,
        bool delay_tracking          = false,
        SendType send_type           = SendType::Float,
        double socket_timeout_sec    = 2.0,
        bool debug_enabled    = false,
        int tcp_port    = 7123
    );

    ~UDPSocket();

    bool setup(const std::string& host, uint16_t port,
               uint16_t num_inputs, uint16_t num_outputs,
               bool is_server = false);

    bool handshake(double timeout_sec = 15.0);

    bool send(std::span<const float> values);

    struct Status {
        bool running = false;
        uint64_t packets_received = 0;
        uint64_t packets_sent = 0;
        uint64_t packets_expired = 0;
        uint64_t packets_corrupted = 0;
        uint64_t packets_shape_invalid = 0;
        std::optional<double> time_since_last_packet;
        bool has_data = false;
        char receive_type = '?';
        char send_type = 'f';
        uint16_t num_inputs = 0;
        uint16_t num_outputs = 0;
    };

    bool start();
    bool close();
    
    size_t get_expected_recv_packet_size() const;
    Status get_status() const;
    std::optional<std::vector<float>> get_latest();

    // output stuff
    void print_packet_stats() const;
    void print_delay_stats() const;
private:
    // ────────────────────────────────────────────────
    // values gotten from contsturctor
    double local_max_age_;
    bool debug_enabled_;
    double socket_timeout_;
    SendType send_type_;
    bool delay_tracking_;
    int tcp_port_;
    TCPSocketClient* tcp_client_=nullptr;
    long long thread_max_sleep_ms_=300;


    bool handshake_performed_=false;
    mutable std::mutex data_mutex_;
    mutable std::mutex close_mutex_;
    std::atomic<bool> running_{false};
    std::atomic<bool> stop_requested_{false};

    // Socket stuff
    int socket_fd_ = INVALID_SOCKET_FD;
    sockaddr_in remote_addr_{};
    bool is_server_mode_ = false;

    char receive_type_ = 0;
    uint16_t num_inputs_ = 0;
    uint16_t num_outputs_ = 0;
    int32_t remote_max_age_ = -1;

    // Receive state
    std::vector<float> latest_data_;
    bool data_consumed_ = false; 
    std::chrono::steady_clock::time_point last_packet_time_;

    // Stats
    uint64_t packets_received_ = 0;
    uint64_t packets_sent_ = 0;
    uint64_t packets_expired_ = 0;
    uint64_t packets_corrupted_ = 0;
    uint64_t packets_shape_invalid_ = 0;

    // Delay stats (online Welford's method)
    double delay_mean_ = 0.0;
    double delay_m2_ = 0.0;
    double delay_min_ = INFINITY;
    double delay_max_ = -INFINITY;
    uint64_t delay_n_ = 0;

    // Threads
    std::jthread recv_thread_;
    std::jthread heartbeat_thread_;

    // Win stuff
    static bool winsock_initialized_;
    static inline std::mutex init_mutex_;
    void initialize_platform() {
#ifdef _WIN32
        std::lock_guard<std::mutex> lock(init_mutex_);
        if (!winsock_initialized_) {
            WSADATA wsa_data;
            if (WSAStartup(MAKEWORD(2, 2), &wsa_data) != 0) {
                return;
            }
            winsock_initialized_ = true;
        }
#endif
    }

    // Helpers
    std::string get_socket_error_string() const;
    int get_addr_info(sockaddr_in* src, char* ip_str);
    uint16_t crc16_ccitt(std::span<const uint8_t> data) const;
    void update_delay_stats(double interval);
    bool set_socket_timeout(double timeout_sec);
    void invoke_cleanup();
    void log_error(const std::string& msg) const;
    void log_info(const std::string& msg) const;
    void log_debug(const std::string& msg) const;
};
