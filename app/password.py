from getpass import getpass

from argon2 import PasswordHasher

if __name__ == "__main__":
    password = getpass("Admin password (at least 16 characters): ")
    if len(password) < 16:
        raise SystemExit("Use at least 16 characters")
    if password != getpass("Confirm password: "):
        raise SystemExit("Passwords do not match")
    print(PasswordHasher().hash(password))
