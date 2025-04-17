from sqlalchemy import Column, Integer, String, create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

DATABASE_URL = "sqlite:///./app.db"

Base = declarative_base()
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    password = Column(String)

class Favorite(Base):
    __tablename__ = "favorites"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, index=True)
    book_id = Column(String)
    title = Column(String)
    authors = Column(String)
    thumbnail = Column(String)
    
class Shelf(Base):
    __tablename__ = "shelves"
    id = Column(Integer, primary_key=True)
    name = Column(String)
    username = Column(String)

class ShelfBook(Base):
    __tablename__ = "shelf_books"
    id = Column(Integer, primary_key=True)
    shelf_id = Column(Integer)
    book_id = Column(String)
    title = Column(String)
    authors = Column(String)
    thumbnail = Column(String)
