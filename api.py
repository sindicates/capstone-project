from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional
import os
import traceback
import uuid

from legal_triage.agent import root_agent
from google.adk.apps import App
from google.adk.runners import InMemoryRunner
from google.genai import types

app = FastAPI()

# ADK Setup
triage_app = App(name="triage_app", root_agent=root_agent)
runner = InMemoryRunner(app=triage_app)

class TriageRequest(BaseModel):
    description: str
    user_id: Optional[str] = None
    session_id: Optional[str] = None

@app.post("/api/triage")
async def triage_endpoint(request: TriageRequest):
    try:
        if request.user_id and request.session_id:
            user_id = request.user_id
            session_id = request.session_id
        else:
            user_id = str(uuid.uuid4())
            session = await runner.session_service.create_session(
                app_name="triage_app", user_id=user_id
            )
            session_id = session.id

        events = []
        async for event in runner.run_async(
            user_id=user_id,
            session_id=session_id,
            new_message=types.Content(
                role="user",
                parts=[types.Part.from_text(text=request.description)],
            ),
        ):
            events.append(event)

        # Get the final text output from the agent
        final_text = ""
        for e in reversed(events):
            if hasattr(e, "content") and e.content and hasattr(e.content, "parts") and e.content.parts:
                texts = [p.text for p in e.content.parts if hasattr(p, "text") and p.text]
                if texts:
                    final_text = "\n".join(texts)
                    break

        if not final_text:
            final_text = "Analysis complete, but no text output was provided."

        return {
            "result": final_text,
            "user_id": user_id,
            "session_id": session_id,
        }
    except Exception as e:
        traceback.print_exc()
        return JSONResponse(status_code=500, content={"error": str(e)})

# Mount static files at the root
frontend_dir = os.path.join(os.path.dirname(__file__), "frontend")
if os.path.exists(frontend_dir):
    app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")
