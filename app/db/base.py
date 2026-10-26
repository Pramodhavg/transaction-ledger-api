from sqlalchemy import MetaData, Numeric
from sqlalchemy.orm import DeclarativeBase

from app.core.money import MONEY_PRECISION, MONEY_SCALE

# Predictable constraint names, so the code can recognise a specific constraint violation.
NAMING_CONVENTION = {
    "pk": "pk_%(table_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
}

Money = Numeric(MONEY_PRECISION, MONEY_SCALE)


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
