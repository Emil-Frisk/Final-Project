#!/bin/bash

mkdir -p build
cd build
echo "Building a make file"
cmake ..
echo "Executing make file"
sudo make
cmake --install .
cd ..
echo "Build.sh finished!"
