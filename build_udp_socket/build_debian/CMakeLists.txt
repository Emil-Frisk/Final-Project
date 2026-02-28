cmake_minimum_required(VERSION 3.15)
project(udp_socket)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)

# ────────────────────────────────────────────────────────────
# Functions
# ────────────────────────────────────────────────────────────
function(check_not_empty var_name result_var)
    if(${var_name})
        set(${result_var} 1 PARENT_SCOPE)
    else()
        set(${result_var} 0 PARENT_SCOPE)
    endif()
endfunction()

function(find_or_install_package package_name apt_package_name)
    find_package(${package_name} QUIET)
    
    if(NOT ${package_name}_FOUND)
        message(STATUS "${package_name} not found, attempting to install via apt...")
        execute_process(
            COMMAND sudo apt-get update
            COMMAND sudo apt-get install -y ${apt_package_name}
            RESULT_VARIABLE apt_result
        )
        
        if(apt_result EQUAL 0)
            message(STATUS "${package_name} installed successfully, searching again...")
            find_package(${package_name} REQUIRED)
        else()
            message(FATAL_ERROR "Failed to install ${package_name} via apt")
        endif()
    else()
        message(STATUS "Found ${package_name}")
    endif()
endfunction()

# ────────────────────────────────────────────────────────────
# Add current Python .venv path for CMake
# ────────────────────────────────────────────────────────────
execute_process(
    COMMAND python -m pybind11 --cmakedir
    OUTPUT_VARIABLE pybind11_DIR
    OUTPUT_STRIP_TRAILING_WHITESPACE
)

check_not_empty(pybind11_DIR is_found)

if(is_found)
    message(STATUS "Found pybind11: ${pybind11_DIR}")
    list(APPEND CMAKE_PREFIX_PATH ${pybind11_DIR})
else()
    message(FATAL_ERROR "Could not find pybind11! Activate your venv")
endif()

list(APPEND CMAKE_PREFIX_PATH ${pybind11_DIR})

# ────────────────────────────────────────────────────────────
# Find Required Packages
# ────────────────────────────────────────────────────────────


# Find pybind11
set(PYBIND11_FINDPYTHON ON)
find_package(pybind11 CONFIG REQUIRED)
find_or_install_package(fmt libfmt-dev)

# ────────────────────────────────────────────────────────────
# Source Files
# ────────────────────────────────────────────────────────────

set(SOURCES
    "${CMAKE_CURRENT_SOURCE_DIR}/../src/udp_socket.cpp"
    "${CMAKE_CURRENT_SOURCE_DIR}/../src/udp_socket_bindings.cpp"
)

set(HEADERS
    "${CMAKE_CURRENT_SOURCE_DIR}/../src/udp_socket.h"
    "${CMAKE_CURRENT_SOURCE_DIR}/../src/TCPSocketClient.hpp"
)

# ────────────────────────────────────────────────────────────
# Python Module (pybind11)
# ────────────────────────────────────────────────────────────

pybind11_add_module(udp_socket
    ${SOURCES}
    ${HEADERS}
)

# Include directories
target_include_directories(udp_socket PRIVATE
    ${PYBIND11_INCLUDE_DIR}
)

# Link libraries
target_link_libraries(udp_socket PRIVATE
    fmt::fmt
)

# ────────────────────────────────────────────────────────────
# Compiler Flags & Warnings
# ────────────────────────────────────────────────────────────

target_compile_options(udp_socket PRIVATE -Wall -Wextra -Wpedantic)

# ────────────────────────────────────────────────────────────
# Install to venv site-packages
# ────────────────────────────────────────────────────────────

execute_process(
    COMMAND python -c "import site; print(site.getsitepackages()[0])"
    OUTPUT_VARIABLE PYTHON_SITE_PACKAGES
    OUTPUT_STRIP_TRAILING_WHITESPACE
)

if(PYTHON_SITE_PACKAGES)
    message(STATUS "Python site-packages: ${PYTHON_SITE_PACKAGES}")
    install(TARGETS udp_socket
            LIBRARY DESTINATION ${PYTHON_SITE_PACKAGES}
    )
else()
    message(WARNING "Could not determine Python site-packages directory")
endif()

# ────────────────────────────────────────────────────────────
# Optional: Debug Output
# ────────────────────────────────────────────────────────────

message(STATUS "")
message(STATUS "UDP Socket Module Configuration")
message(STATUS "==============================")
message(STATUS "Project: ${PROJECT_NAME}")
message(STATUS "C++ Standard: ${CMAKE_CXX_STANDARD}")
message(STATUS "Build Type: ${CMAKE_BUILD_TYPE}")
message(STATUS "pybind11 version: ${pybind11_VERSION}")
message(STATUS "Platform: ${CMAKE_SYSTEM_NAME}")
message(STATUS "")
