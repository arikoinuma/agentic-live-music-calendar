"""Route modules, one per resource.

Each module owns an `APIRouter` that app/main.py includes. Splitting
them up rather than piling every route into main.py is the standard
FastAPI layout, and it keeps main.py as what it should be — app
construction and wiring, not business logic.
"""
