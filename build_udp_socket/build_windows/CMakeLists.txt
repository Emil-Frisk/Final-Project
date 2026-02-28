cmake_minimum_required(VERSION 3.12)
project(upd_socket_module)
set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

find_package(Python COMPONENTS Interpreter Development REQUIRED)
find_package(pybind11 CONFIG REQUIRED)
find_package(fmt CONFIG REQUIRED)

# Create a static library with the socket implementation
add_library(udp_socket_lib STATIC "${CMAKE_CURRENT_LIST_DIR}/../src/udp_socket.cpp")
target_link_libraries(udp_socket_lib PRIVATE fmt::fmt pybind11::pybind11)
target_include_directories(udp_socket_lib PRIVATE ${pybind11_INCLUDE_DIRS})

# Create the Python module (bindings only)
pybind11_add_module(udp_socket "${CMAKE_CURRENT_LIST_DIR}/../src/udp_socket_bindings.cpp")
target_link_libraries(udp_socket PRIVATE udp_socket_lib fmt::fmt)