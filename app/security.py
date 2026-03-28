import bcrypt


def hash_password(plain: str) -> str:
    data = plain.encode("utf-8")
    if len(data) > 72:
        data = data[:72]
    return bcrypt.hashpw(data, bcrypt.gensalt(rounds=12)).decode("ascii")


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("ascii"))
