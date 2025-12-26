"""
Cryptographic utilities for CPUCoin
Uses Argon2 for CPU-friendly proof-of-work (with fallback to scrypt)
"""

import hashlib
from typing import Union

# Try to import argon2, fallback to scrypt if not available
try:
    import argon2
    ARGON2_AVAILABLE = True
except ImportError:
    ARGON2_AVAILABLE = False

from . import config


def sha256(data: Union[str, bytes]) -> str:
    """Compute SHA-256 hash of data."""
    if isinstance(data, str):
        data = data.encode('utf-8')
    return hashlib.sha256(data).hexdigest()


def double_sha256(data: Union[str, bytes]) -> str:
    """Compute double SHA-256 hash (like Bitcoin)."""
    if isinstance(data, str):
        data = data.encode('utf-8')
    first_hash = hashlib.sha256(data).digest()
    return hashlib.sha256(first_hash).hexdigest()


def argon2_hash(data: str, salt: str) -> str:
    """
    Compute Argon2id hash - CPU-friendly, memory-hard hash function.

    This is the core of our CPU mining algorithm. Argon2 is:
    - Memory-hard: Requires significant RAM, making GPU mining inefficient
    - Time-hard: Sequential memory access patterns resist parallelization
    - Resistant to ASIC optimization due to memory requirements

    Falls back to scrypt if argon2 is not available.

    Args:
        data: The data to hash (block header)
        salt: Salt for the hash (previous block hash)

    Returns:
        Hexadecimal hash string
    """
    if ARGON2_AVAILABLE:
        try:
            hasher = argon2.PasswordHasher(
                time_cost=config.ARGON2_TIME_COST,
                memory_cost=config.ARGON2_MEMORY_COST,
                parallelism=config.ARGON2_PARALLELISM,
                hash_len=config.ARGON2_HASH_LEN,
                type=argon2.Type.ID  # Argon2id - hybrid of Argon2i and Argon2d
            )

            # Argon2 returns a formatted string, we extract just the hash
            salt_bytes = salt.encode('utf-8')[:16].ljust(16, b'\x00')
            full_hash = hasher.hash(data, salt=salt_bytes)
            # Extract the base64-encoded hash from the Argon2 format
            hash_part = full_hash.split('$')[-1]
            # Convert to hex for consistency
            import base64
            hash_bytes = base64.b64decode(hash_part + '==')
            return hash_bytes.hex()
        except Exception:
            # Fallback to raw Argon2
            try:
                raw_hash = argon2.low_level.hash_secret_raw(
                    data.encode('utf-8'),
                    salt.encode('utf-8')[:16].ljust(16, b'\x00'),
                    time_cost=config.ARGON2_TIME_COST,
                    memory_cost=config.ARGON2_MEMORY_COST,
                    parallelism=config.ARGON2_PARALLELISM,
                    hash_len=config.ARGON2_HASH_LEN,
                    type=argon2.Type.ID
                )
                return raw_hash.hex()
            except Exception:
                pass

    # Fallback: Use scrypt (memory-hard, available in Python stdlib)
    # scrypt is also CPU-friendly and memory-hard, good alternative to Argon2
    salt_bytes = salt.encode('utf-8')[:16].ljust(16, b'\x00')
    # n=2^14 (16384), r=8, p=1 - uses ~16MB memory
    scrypt_hash = hashlib.scrypt(
        data.encode('utf-8'),
        salt=salt_bytes,
        n=16384,  # CPU/memory cost parameter
        r=8,      # Block size parameter
        p=1,      # Parallelization parameter
        dklen=32  # Output length
    )
    return scrypt_hash.hex()


def mining_hash(block_header: str, nonce: int, prev_hash: str) -> str:
    """
    Compute the mining hash for proof-of-work.

    Combines Argon2/scrypt (memory-hard) with SHA-256 for the final hash.
    This makes mining CPU-friendly while ensuring hash properties.

    Args:
        block_header: Serialized block header data
        nonce: Mining nonce to try
        prev_hash: Previous block hash (used as salt)

    Returns:
        Final hash for difficulty comparison
    """
    # Combine header and nonce
    data = f"{block_header}{nonce}"

    # First pass: Argon2/scrypt (memory-hard, CPU-friendly)
    memory_hard_result = argon2_hash(data, prev_hash if prev_hash else "genesis")

    # Second pass: SHA-256 for final hash (fast, ensures good distribution)
    return sha256(memory_hard_result)


def check_difficulty(hash_hex: str, difficulty: int) -> bool:
    """
    Check if a hash meets the difficulty requirement.

    Difficulty is measured as the number of leading zero bits required.

    Args:
        hash_hex: The hash to check (hexadecimal string)
        difficulty: Required number of leading zero bits

    Returns:
        True if hash meets difficulty, False otherwise
    """
    # Convert hex to binary and check leading zeros
    hash_int = int(hash_hex, 16)
    hash_bits = 256  # SHA-256 produces 256-bit hash

    # Count leading zeros
    if hash_int == 0:
        leading_zeros = hash_bits
    else:
        leading_zeros = hash_bits - hash_int.bit_length()

    return leading_zeros >= difficulty


def calculate_target(difficulty: int) -> int:
    """
    Calculate the target value for a given difficulty.

    The hash must be less than this target to be valid.
    """
    max_target = 2 ** 256 - 1
    return max_target >> difficulty


def merkle_root(hashes: list) -> str:
    """
    Compute the Merkle root of a list of hashes.

    Args:
        hashes: List of transaction hashes

    Returns:
        Merkle root hash
    """
    if not hashes:
        return sha256("")

    if len(hashes) == 1:
        return hashes[0]

    # Ensure even number of hashes
    if len(hashes) % 2 == 1:
        hashes = hashes + [hashes[-1]]

    # Build tree
    new_level = []
    for i in range(0, len(hashes), 2):
        combined = hashes[i] + hashes[i + 1]
        new_level.append(double_sha256(combined))

    return merkle_root(new_level)
