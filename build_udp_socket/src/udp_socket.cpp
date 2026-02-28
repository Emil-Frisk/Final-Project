#include "udp_socket.h"
#include <algorithm>
#include <cstring>

bool UDPSocket::winsock_initialized_ = false;

UDPSocket::UDPSocket(
    double max_age_seconds,
    bool delay_tracking,
    SendType send_type,
    double socket_timeout_sec,
    bool debug_enabled,
    int tcp_port
) :
    local_max_age_(max_age_seconds),
    delay_tracking_(delay_tracking),
    send_type_(send_type),
    socket_timeout_(socket_timeout_sec),
    debug_enabled_(debug_enabled),
    tcp_port_(tcp_port)
{
    // initialize_platform(); NOTE: most likely not needed because python ahs already done this
}

UDPSocket::~UDPSocket() {
    close();
}

bool UDPSocket::set_socket_timeout(double timeout_sec) {
    if (socket_fd_ == INVALID_SOCKET_FD) {
        log_error("Cannot set timeout: socket not initialized");
        return false;
    }

    #ifdef _WIN32
    DWORD timeout_ms = static_cast<DWORD>(timeout_sec * 1000.0 + 0.5);  // round nearest
    int ret = setsockopt(socket_fd_, SOL_SOCKET, SO_RCVTIMEO,
                         reinterpret_cast<const char*>(&timeout_ms), sizeof(timeout_ms));
    #else
    struct timeval tv{};
    tv.tv_sec  = static_cast<time_t>(timeout_sec);
    tv.tv_usec = static_cast<suseconds_t>((timeout_sec - tv.tv_sec) * 1'000'000.0 + 0.5);

    int ret = setsockopt(socket_fd_, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof(tv));
    #endif

    if (ret == -1) {
        log_error(fmt::format("setsockopt(SO_RCVTIMEO) failed: {}", get_socket_error_string()));
        return false;
    }

    return true;
}

bool UDPSocket::setup(const std::string& host, uint16_t port,
                      uint16_t num_inputs, uint16_t num_outputs,
                      bool is_server) {
    // Open up communication channel with python and cpp service
    tcp_client_=new TCPSocketClient("localhost", tcp_port_, true);
    if (!tcp_client_->connect()){
        log_error(fmt::format("Failed to connect to python service listener on port: {}", tcp_port_));
        return false;
    }
    log_info(fmt::format("TCPClient connected to service listener on port: {}", tcp_port_));

    num_inputs_  = num_inputs;
    num_outputs_ = num_outputs;
    is_server_mode_ = is_server;

    socket_fd_ = socket(AF_INET, SOCK_DGRAM, 0);
    if (socket_fd_ == INVALID_SOCKET_FD) {
        log_error("socket creation failed");
        return false;
    }

    // Set receive timeout
    set_socket_timeout(socket_timeout_);

    sockaddr_in addr{};
    addr.sin_family = AF_INET;
    addr.sin_port = htons(port);

    if (is_server) {
        addr.sin_addr.s_addr = INADDR_ANY;
        if (bind(socket_fd_, (sockaddr*)&addr, sizeof(addr)) < 0) {
            log_error("bind failed");
            close();
            return false;
        }
        log_debug(fmt::format("UDP server bound to port {}", port));
    } else {
        int pton_r=inet_pton(AF_INET, host.c_str(), &addr.sin_addr);
        if (pton_r <= 0) {
            struct addrinfo hints{}, *result;
            hints.ai_family=AF_INET;
            hints.ai_socktype=SOCK_DGRAM;

            int gai_r=getaddrinfo(host.c_str(),nullptr,&hints,&result);
            if (gai_r!=0){
                log_error(fmt::format("Failed to resolver hostname '{}':'{}'", host, gai_strerror(gai_r)));
                close();
                return false;
            }
            addr.sin_addr=((struct sockaddr_in*)result->ai_addr)->sin_addr;
            freeaddrinfo(result);
        }
        remote_addr_ = addr;
        log_debug(fmt::format("UDP client prepared for {}", host));
    }
    return true;
}

bool UDPSocket::handshake(double timeout_sec) {
    if (socket_fd_ == INVALID_SOCKET_FD) {
        log_error("Socket not initialized");
        return false;
    }

    constexpr size_t HANDSHAKE_SIZE = 2 + 2 + 1 + 2; // num_outputs(H), num_inputs(H), send_type(c), max_age(H)

    uint8_t our_data[HANDSHAKE_SIZE]{};
    uint8_t peer_data[HANDSHAKE_SIZE]{};

    uint16_t our_max_age = static_cast<uint16_t>(local_max_age_);

    // Prepare our own handshake payload (same for client & server)
    std::memcpy(our_data + 0, &num_outputs_, 2);
    std::memcpy(our_data + 2, &num_inputs_,  2);
    our_data[4] = static_cast<uint8_t>(send_type_);
    std::memcpy(our_data + 5, &our_max_age, 2);

    sockaddr_in peer{};
    socklen_t peer_len = sizeof(peer);

    // ── Set short timeout for handshake ───────────────────────
    if (!set_socket_timeout(timeout_sec)) {
        log_error("Failed to set handshake timeout");
        return false;
    }

    if (!is_server_mode_) {
        // Client
        log_info(fmt::format("Client sending handshake to {}:{}", inet_ntoa(remote_addr_.sin_addr), ntohs(remote_addr_.sin_port)));
        sendto(socket_fd_, reinterpret_cast<const char*>(our_data), HANDSHAKE_SIZE, 0,
               reinterpret_cast<sockaddr*>(&remote_addr_), sizeof(remote_addr_));

        int n = recvfrom(socket_fd_, (char*)peer_data, HANDSHAKE_SIZE, 0,
                         reinterpret_cast<sockaddr*>(&peer), &peer_len);
        if (n != static_cast<int>(HANDSHAKE_SIZE)) {
            log_error(fmt::format("Client handshake receive failed. Num inputs {} - Num outputs {} - Handshake size {} - Recv count {}", num_inputs_, num_outputs_, HANDSHAKE_SIZE, n));
            return false;
        }
        remote_addr_ = peer;
    } else {
        // Server
        log_info("Server is waiting for a handshake...");
        int n = recvfrom(socket_fd_, (char*)peer_data, HANDSHAKE_SIZE, 0,
                         reinterpret_cast<sockaddr*>(&peer), &peer_len);
        if (n != static_cast<int>(HANDSHAKE_SIZE)) {
            log_error(fmt::format("Server handshake receive failed. Num inputs {} - Num outputs {} - Handshake size {} - Recv count {}", num_inputs_, num_outputs_, HANDSHAKE_SIZE, n));
            return false;
        }

        sendto(socket_fd_, reinterpret_cast<const char*>(our_data), HANDSHAKE_SIZE, 0,
               reinterpret_cast<sockaddr*>(&peer), peer_len);
        remote_addr_ = peer;
    }

    // ── Restore normal timeout ────────────────────────────────
    if (!set_socket_timeout(socket_timeout_)) {
        log_info("Failed to restore normal receive timeout — continuing");
    }

    // ── Parse what we received ────────────────────────────────
    uint16_t remote_num_outputs, remote_num_inputs, remote_max_age;
    uint8_t  remote_send_type;

    std::memcpy(&remote_num_outputs, peer_data + 0, 2);
    std::memcpy(&remote_num_inputs,  peer_data + 2, 2);
    remote_send_type = peer_data[4];
    std::memcpy(&remote_max_age,  peer_data + 5, 2);

    if (remote_num_inputs != num_outputs_) {
        log_error(fmt::format("Mismatch: remote expects {} outputs, we provide {}", 
                              remote_num_inputs, num_outputs_));
        return false;
    }
    if (remote_num_outputs != num_inputs_) {
        log_error(fmt::format("Mismatch: remote provides {} outputs, we expect {}", 
                              remote_num_outputs, num_inputs_));
        return false;
    }

    remote_max_age_ = remote_max_age;
    receive_type_ = static_cast<char>(remote_send_type);

    log_debug(fmt::format("Handshake OK | remote: outputs={}, inputs={}, Send type='{}', max_age={} | local: outputs={}, inputs={}, max_age={} s",
                         remote_num_outputs, remote_num_inputs, receive_type_,
                         remote_max_age, num_outputs_, num_inputs_, local_max_age_));

    handshake_performed_=true;
    return true;
}

bool UDPSocket::start() {
    // Validate
    if (running_) return true;
    if (socket_fd_ == INVALID_SOCKET_FD) {
        log_error("Cannot start - socket not setup");
        return false;
    }
    if (!handshake_performed_) {
        log_error("Can't start receiving. Handshake has not been performed yet!");
        return false;
    }
    running_ = true;
    stop_requested_ = false;

    // Start threads
    last_packet_time_=std::chrono::steady_clock::now();

    
    recv_thread_ = std::jthread([this] {
        std::vector<uint8_t> recv_buf(2048);
        while (!stop_requested_.load()) {
            sockaddr_in src{};
            socklen_t len = sizeof(src);
            int n = recvfrom(socket_fd_, (char*)recv_buf.data(), recv_buf.size(), 0,
                             (sockaddr*)&src, &len);
            // Check errors
            if (n < 0) {
            #ifdef _WIN32
                int err = WSAGetLastError();
                if (err == WSAETIMEDOUT || err == WSAEWOULDBLOCK) {
                    continue;  // timeout or would-block → normal in our setup
                }
            #else
                int err = errno;
                if (err == EAGAIN || err == EWOULDBLOCK) {
                    continue;  // covers both non-blocking AND SO_RCVTIMEO timeout on POSIX
                }
            #endif
                if (!stop_requested_) {
                    // If we get here -> real error
                    log_error(fmt::format("recvfrom failed: {}", get_socket_error_string()));
                    invoke_cleanup();
                    return;
                }
                return; // Expected exit
            }
            if (n < 2) {
                packets_shape_invalid_++;
                continue;
            }
            if (debug_enabled_) {
                char ip_str[INET_ADDRSTRLEN];
                int port = get_addr_info(&src, ip_str);
                log_debug(fmt::format("Got n bytes of data n: {} - from address: {}:{}", n, ip_str,port));
            }

            // Check CRC
            uint16_t received_crc;
            std::memcpy(&received_crc, recv_buf.data() + n - 2, 2);
            auto payload_span = std::span<const uint8_t>(recv_buf.data(), n - 2);
            if (crc16_ccitt(payload_span) != received_crc) {
                packets_corrupted_++;
                continue;
            }
            // Validate shape
            size_t expected_payload = num_inputs_ * sizeof(float);
            if (payload_span.size() != expected_payload) {
                packets_shape_invalid_++;
                continue;
            }

            // Update latest data
            std::vector<float> values(num_inputs_);
            std::memcpy(values.data(), payload_span.data(), expected_payload);

            auto now = std::chrono::steady_clock::now();
            double interval = 0.0;
            { // Protect data
                std::lock_guard lk(data_mutex_);
                interval = std::chrono::duration<double>(now - last_packet_time_).count();
                latest_data_ = std::move(values);
                data_consumed_ = false;
                last_packet_time_ = now;
                packets_received_++;
            } // End of lock

            if (delay_tracking_) {
                update_delay_stats(interval);
            }
        }
    });
    // Heartbeat thread - only runs if there is something to expect
    if (num_inputs_ > 0) {
        log_info("Heartbeat thread started!");
        long long scaled_timeout = local_max_age_ * 3.0;
        long long cleanup_timeout = std::max<long long>(scaled_timeout, 5);
        heartbeat_thread_ = std::jthread([this, cleanup_timeout] {
            while (!stop_requested_.load()) {
                std::this_thread::sleep_for(std::chrono::milliseconds(100));
                auto now = std::chrono::steady_clock::now();
                auto age = std::chrono::duration<double>(now - last_packet_time_).count();
                if (age > cleanup_timeout)
                 {
                    if (!stop_requested_) {
                        log_error("Data timeout - connection stale");
                        invoke_cleanup();
                    }
                    log_info("Heartbeat thread shutdown.");
                    return; // Exit
                }
            }
        });
    }

    log_info("UDPSocket started");
    return true;
}

bool UDPSocket::close() {
    std::lock_guard<std::mutex> lock(close_mutex_);
    if (!running_) {
        return true;
    }
    
    stop_requested_ = true;
    running_ = false;
    handshake_performed_ = false;
    
    if (socket_fd_ != INVALID_SOCKET_FD) {
    #ifdef _WIN32
        closesocket(socket_fd_);
    #else
        ::close(socket_fd_);
    #endif
        socket_fd_ = INVALID_SOCKET_FD;
    }
    
    // NOTE: explicitly joining the threads causes weird behaviour with pybind11 we just sleep here instead.
    std::this_thread::sleep_for(std::chrono::milliseconds((thread_max_sleep_ms_)));

    if (tcp_client_ != nullptr) {
        tcp_client_->close();
        delete tcp_client_;
        tcp_client_ = nullptr;
        log_info("TCPClient closed");
    }
    
    log_info("UDPSocket closed");
    return true;
}

bool UDPSocket::send(std::span<const float> values) {
    // Validate
    if (!remote_addr_.sin_family) {
        log_error("No remote address set");
        return false;
    }
    if (socket_fd_ == INVALID_SOCKET_FD) {
        log_error("Socket not initialized");
        return false;
    }
    if (values.size() != num_outputs_) {
        log_error(fmt::format("Expected {} values, got {}", num_outputs_, values.size()));
        return false;
    }
    
    std::vector<uint8_t> buffer;
    buffer.reserve(num_outputs_ * sizeof(float) + 2); // data + crc
    // Put all data into buffer
    for (float v : values) {
        auto bytes = std::bit_cast<uint32_t>(v);   // little-endian assumed
        buffer.insert(buffer.end(),
                      reinterpret_cast<uint8_t*>(&bytes),
                      reinterpret_cast<uint8_t*>(&bytes) + 4);
    }

    // CRC into buf
    uint16_t crc = crc16_ccitt(buffer);
    buffer.insert(buffer.end(),
                  reinterpret_cast<uint8_t*>(&crc),
                  reinterpret_cast<uint8_t*>(&crc) + 2);

    // Send
    int sent = sendto(socket_fd_, reinterpret_cast<const char*>(buffer.data()), buffer.size(), 0,
                      (sockaddr*)&remote_addr_, sizeof(remote_addr_));

    if (sent < 0) {
        log_error("sendto failed");
        return false;
    }

    ++packets_sent_;
    return true;
}

std::optional<std::vector<float>> UDPSocket::get_latest() {
    std::lock_guard lk(data_mutex_);
    if (latest_data_.empty() || data_consumed_) return std::nullopt;

    auto age = std::chrono::duration<double>(
        std::chrono::steady_clock::now() - last_packet_time_).count();

    if (age > local_max_age_) {
        packets_expired_++;
        return std::nullopt;
    }

    data_consumed_ = true;
    return latest_data_;
}

UDPSocket::Status UDPSocket::get_status() const {
    std::lock_guard lk(data_mutex_);
    auto now = std::chrono::steady_clock::now();

    double since_last = last_packet_time_.time_since_epoch().count() > 0 ?
        std::chrono::duration<double>(now - last_packet_time_).count() : -1.0;

    return Status{
        running_.load(),
        packets_received_,
        packets_sent_,
        packets_expired_,
        packets_corrupted_,
        packets_shape_invalid_,
        since_last > 0 ? std::optional<double>(since_last) : std::nullopt,
        !latest_data_.empty(),
        receive_type_,
        static_cast<char>(send_type_),
        num_inputs_,
        num_outputs_
    };
}

void UDPSocket::print_packet_stats() const {
    auto st = get_status();
    log_info(fmt::format(
        "Packets: recv={}, sent={}, expired={}, corrupt={}, invalid={}",
        st.packets_received, st.packets_sent, st.packets_expired,
        st.packets_corrupted, st.packets_shape_invalid));
}

void UDPSocket::print_delay_stats() const {
    if (!delay_tracking_ || delay_n_ == 0) return;
    double variance = delay_n_ > 1 ? delay_m2_ / (delay_n_ - 1) : 0.0;
    double stddev = std::sqrt(variance);
    log_info(fmt::format(
        "Delay stats: mean={:.3f} ms, stddev={:.3f} ms, min={:.3f} ms, max={:.3f} ms",
        delay_mean_ * 1000, stddev * 1000, delay_min_ * 1000, delay_max_ * 1000));
}

int UDPSocket::get_addr_info(sockaddr_in* src, char* ip_str) {
    if (inet_ntop(AF_INET, &((src)->sin_addr),ip_str, INET_ADDRSTRLEN)==NULL)  {
        return -1;
    }
    int port = ntohs(src->sin_port);
    return port;
}

size_t UDPSocket::get_expected_recv_packet_size() const {
    return num_inputs_ * sizeof(float) + 2; // payload + crc
}

void UDPSocket::update_delay_stats(double interval) {
    delay_n_++;
    double delta = interval - delay_mean_;
    delay_mean_ += delta / delay_n_;
    delay_m2_ += delta * (interval - delay_mean_);
    delay_min_ = std::min<double>(delay_min_, interval);
    delay_max_ = std::max<double>(delay_max_, interval);
}

uint16_t UDPSocket::crc16_ccitt(std::span<const uint8_t> data) const {
    uint16_t crc = 0xFFFF;
    for (uint8_t byte : data) {
        crc ^= (uint16_t(byte) << 8);
        for (int i = 0; i < 8; ++i) {
            if (crc & 0x8000) {
                crc = (crc << 1) ^ 0x1021;
            } else {
                crc <<= 1;
            }
        }
    }
    return crc;
}

std::string UDPSocket::get_socket_error_string() const {
    #ifdef _WIN32
        int err = WSAGetLastError();
        // can use FormatMessage() for nice strings, or just return number
        return "Winsock error " + std::to_string(err);
    #else
        return strerror(errno);
    #endif
}

void UDPSocket::invoke_cleanup() {
    // Any data sent is assumed just to mean unexpected error -> cleanup
    if (tcp_client_!=nullptr) {
        tcp_client_->send();
    } else {
        log_error("Unable to invoke cleanup tcp_client pointer is a nullptr");
    }
}

void UDPSocket::log_error(const std::string& msg) const {
    fmt::print(stderr, "[UDPSocket - ERROR] {}\n", msg);
}

void UDPSocket::log_info(const std::string& msg) const {
    fmt::print("[UDPSocket - INFO] {}\n", msg);
}

void UDPSocket::log_debug(const std::string& msg) const {
    if (debug_enabled_) fmt::print("[UDPSocket - DEBUG] {}\n", msg);
}
