#!/usr/bin/env python3
"""
CPUCoin - A CPU-minable cryptocurrency with physical coin files

Install with: pip install -e .
"""

from setuptools import setup, find_packages

with open("README.md", "r", encoding="utf-8") as f:
    long_description = f.read()

setup(
    name="cpucoin",
    version="1.0.0",
    author="CPUCoin Team",
    description="A CPU-minable cryptocurrency with physical coin files stored on disk",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/cpucoin/cpucoin",
    packages=find_packages(),
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Topic :: Security :: Cryptography",
    ],
    python_requires=">=3.8",
    install_requires=[
        "argon2-cffi>=21.3.0",
        "ecdsa>=0.18.0",
    ],
    entry_points={
        "console_scripts": [
            "cpucoin=cpucoin.cli:main",
            "cpucoin-server=cpucoin.coin_control_server:main",
        ],
    },
)
