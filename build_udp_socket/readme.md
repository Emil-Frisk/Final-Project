# Building UDPSocket module

## Win 10

* Install ([vcpkg](https://github.com/microsoft/vcpkg)) and put on your PATH
* Install CMake ([CMake](https://cmake.org/download/)) and put on your PATH
* pip install pybind11
* Visual Studio Community 2026 c++ developer tools (Can download what ever just update the string in the .ps file then.)
* Run build_windows.ps1
* Go into the build folder and move the *.pyd file and fmt.dll in your Python venv /lub/python3.*/site_packages/

## Debian
* Activate your desired Python virtual enviroment.
* Run source build.sh
* This script will automatically place the .so file in your venvs site_packages