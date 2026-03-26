"""
MeetFlow AI Multi-Agent System - Main FastAPI Application
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.slack import router as slack_router

app = FastAPI(
    title="MeetFlow AI",
    description="Multi-Agent System for Autonomous Enterprise Workflows",
    version="0.1.0",
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(slack_router)


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "message": "MeetFlow AI Multi-Agent System",
        "version": "0.1.0",
        "status": "running"
    }


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
