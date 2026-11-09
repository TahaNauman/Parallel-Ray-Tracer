.RECIPEPREFIX = >

CXX      = g++
MPICXX   = mpicxx
CXXFLAGS = -O2 -std=c++17 -Isrc

all: seq omp

bin:
> mkdir -p bin

seq: bin
> $(CXX) $(CXXFLAGS) seq_omp/main.cc -o bin/raytracer_seq

omp: bin
> $(CXX) $(CXXFLAGS) -fopenmp seq_omp/main.cc -o bin/raytracer_omp

mpi: bin
> $(MPICXX) $(CXXFLAGS) mpi_hybrid/main.cc -o bin/raytracer_mpi

hybrid: bin
> $(MPICXX) $(CXXFLAGS) -fopenmp mpi_hybrid/main.cc -o bin/raytracer_hybrid

clean:
> rm -rf bin

.PHONY: all seq omp mpi hybrid clean
