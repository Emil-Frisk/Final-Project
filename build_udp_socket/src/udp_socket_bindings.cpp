#include "udp_socket.h"

PYBIND11_MODULE(udp_socket, m) {
    m.doc() = "UDP Socket module for high-performance network communication";

    // ────────────────────────────────────────────────
    // SendType enum
    py::enum_<UDPSocket::SendType>(m, "SendType")
        .value("Int8", UDPSocket::SendType::Int8)
        .value("UInt8", UDPSocket::SendType::UInt8)
        .value("Int16", UDPSocket::SendType::Int16)
        .value("UInt16", UDPSocket::SendType::UInt16)
        .value("Int32", UDPSocket::SendType::Int32)
        .value("UInt32", UDPSocket::SendType::UInt32)
        .value("Int64", UDPSocket::SendType::Int64)
        .value("UInt64", UDPSocket::SendType::UInt64)
        .value("Float", UDPSocket::SendType::Float)
        .value("Double", UDPSocket::SendType::Double)
        .export_values();

    // ────────────────────────────────────────────────
    // Status struct
    py::class_<UDPSocket::Status>(m, "Status")
        .def_readonly("running", &UDPSocket::Status::running)
        .def_readonly("packets_received", &UDPSocket::Status::packets_received)
        .def_readonly("packets_sent", &UDPSocket::Status::packets_sent)
        .def_readonly("packets_expired", &UDPSocket::Status::packets_expired)
        .def_readonly("packets_corrupted", &UDPSocket::Status::packets_corrupted)
        .def_readonly("packets_shape_invalid", &UDPSocket::Status::packets_shape_invalid)
        .def_readonly("time_since_last_packet", &UDPSocket::Status::time_since_last_packet)
        .def_readonly("has_data", &UDPSocket::Status::has_data)
        .def_readonly("receive_type", &UDPSocket::Status::receive_type)
        .def_readonly("send_type", &UDPSocket::Status::send_type)
        .def_readonly("num_inputs", &UDPSocket::Status::num_inputs)
        .def_readonly("num_outputs", &UDPSocket::Status::num_outputs)
        .def("__repr__", [](const UDPSocket::Status& s) {
        return fmt::format(
            "Status(running={}, packets_received={}, packets_sent={}, "
            "packets_expired={}, packets_corrupted={}, packets_shape_invalid={}, "
            "time_since_last_packet={}, has_data={}, receive_type='{}', send_type='{}', "
            "num_inputs={}, num_outputs={})",
            s.running, s.packets_received, s.packets_sent, s.packets_expired,
            s.packets_corrupted, s.packets_shape_invalid,
            s.time_since_last_packet.has_value() ? std::to_string(s.time_since_last_packet.value()) : "None",
            s.has_data, s.receive_type, s.send_type, s.num_inputs, s.num_outputs
            );
        });
        

    // ────────────────────────────────────────────────
    // UDPSocket class
    py::class_<UDPSocket>(m, "UDPSocket")
        .def(py::init<
            double,
            bool,
            UDPSocket::SendType,
            double,
            bool,
            int
        >(),
            py::arg("max_age_seconds")= 3.0,
            py::arg("delay_tracking")=false,
            py::arg("send_type")=UDPSocket::SendType::Float,
            py::arg("socket_timeout_sec")=2.0,
            py::arg("debug_enabled")=false,
            py::arg("tcp_port")=7123
        )
        .def("setup", &UDPSocket::setup,
            py::arg("host"),
            py::arg("port"),
            py::arg("num_inputs"),
            py::arg("num_outputs"),
            py::arg("is_server") = false,
            "Setup socket with host, port, and channel configuration"
        )
        .def("handshake", &UDPSocket::handshake,
            py::arg("timeout_sec") = 15.0,
            "Perform handshake with remote peer"
        )
        .def("send", [](UDPSocket& self, const std::vector<float>& values) {
            return self.send(std::span<const float>(values));
        },
            py::arg("values"),
            "Send float values to remote peer"
        )
        .def("start", &UDPSocket::start,
            "Start receive and heartbeat threads"
        )
        .def("close", &UDPSocket::close,
            "Close socket and stop threads"
        )
        .def("get_latest", &UDPSocket::get_latest,
            "Get latest received data packet (returns None if expired or already consumed)"
        )
        .def("get_status", &UDPSocket::get_status,
            "Get current socket status and statistics"
        )
        .def("get_expected_recv_packet_size", &UDPSocket::get_expected_recv_packet_size,
            "Get expected receive packet size in bytes"
        )
        .def("print_packet_stats", &UDPSocket::print_packet_stats,
            "Print packet statistics to console"
        )
        .def("print_delay_stats", &UDPSocket::print_delay_stats,
            "Print delay statistics to console (if delay_tracking enabled)"
        );
}
