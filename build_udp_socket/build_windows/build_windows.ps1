function RunCommand {
    param([string]$Command)
    
    $result = & powershell -NoProfile -Command $Command
    return $result
}
function CheckCommand {
    param([string]$Result, [string]$Name)
    
    if (-not $Result) {
        Write-Host "ERROR: $Name not found" -ForegroundColor Red
        Read-Host "Press Enter to exit"
        exit
    }
}

$build_dir = "build"
if (-not (Test-Path -Path $build_dir)) {
    New-Item -ItemType Directory -Path $build_dir | Out-Null
    Write-Host "Created build directory"
}

# Change to build directory
Push-Location $build_dir

$visual_studio_version="Visual Studio 17 2022"

$path_cmake = RunCommand 'where.exe cmake'
CheckCommand $path_cmake "cmake"

$path_vcpkg = RunCommand 'where.exe vcpkg'
CheckCommand $path_vcpkg "vcpkg"

$path_pybind = RunCommand 'python.exe -m pybind11 --cmakedir'
CheckCommand $path_pybind "pybind11"

& $path_vcpkg install fmt:x64-windows

$path_vcpkg=Split-Path -Path $path_vcpkg
$path_vcpkg_cmake=$path_vcpkg+"\scripts\buildsystems\vcpkg.cmake"
$path_vcpkg_installed=$path_vcpkg+"\installed\x64-windows"


Write-Host "All dependencies found!"
Write-Host $path_pybind
$cmd = "cmake .. -G `"$visual_studio_version`" -A x64 -DCMAKE_TOOLCHAIN_FILE=`"$path_vcpkg_cmake`" -Dpybind11_DIR=`"$path_pybind`" -DCMAKE_PREFIX_PATH=`"$path_vcpkg_installed`""

Write-Host "Running: $cmd"
Invoke-Expression $cmd

$cmd = "cmake --build . --config Release"
Invoke-Expression $cmd

# Return to original directory
Pop-Location

Read-Host "Press Enter to exit"