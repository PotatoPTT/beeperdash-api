from fastapi import FastAPI, Request, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
import httpx
import asyncio
import os
import logging
from typing import Optional

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()
templates = Jinja2Templates(directory="app/templates")


@app.on_event("startup")
async def startup_event():
    app.state.httpx_client = httpx.AsyncClient()
    try:
        access_token = os.getenv("TOKEN")
        if not access_token:
            raise ValueError("TOKEN not set")
    except Exception as e:
        logger.error("TOKEN not set")
        raise Exception("TOKEN not set") from e

    try:
        async with httpx.AsyncClient() as client:
            beeper_response = await client.get(
                "https://api.beeper.com/whoami",
                headers={"Authorization": f"Bearer {access_token}"},
            )

        if beeper_response.status_code == 403:
            logger.error("Invalid token")
            raise Exception("Invalid token")
        elif beeper_response.status_code != 200:
            logger.error("Login request failed with status code: %s",
                         beeper_response.status_code)
            raise Exception("Login request failed")

        beeper_data = beeper_response.json()
        user_info = beeper_data.get("userInfo", {})
        if not user_info:
            raise ValueError("Something went wrong")
    except Exception as e:
        logger.error("Error during login: %s", e)
        raise Exception("Error during login") from e
    app.state.access_token = access_token


@app.on_event("shutdown")
async def shutdown_event():
    await app.state.httpx_client.aclose()


@app.get("/")
async def root():
    # Redirecionamento para a rota /dashboard
    return RedirectResponse(url="/dashboard")


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    access_token = app.state.access_token

    client = app.state.httpx_client
    beeper_response = await client.get(
        "https://api.beeper.com/whoami",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    if beeper_response.status_code != 200:
        return templates.TemplateResponse("error.html", {"error": "Failed to fetch Beeper data"})
    beeper_data = beeper_response.json()
    bridges = beeper_data.get("user", {}).get("bridges", {})
    user_info = beeper_data.get("userInfo", {})

    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "bridges": bridges,
        "beeper_data": beeper_data,
        "user_info": user_info,
    })


# API


async def beeperData():
    client = app.state.httpx_client
    beeper_response = await client.get(
        "https://api.beeper.com/whoami",
        headers={"Authorization": f"Bearer {app.state.access_token}"},
    )
    if beeper_response.status_code != 200:
        return 200
    beeper_data = beeper_response.json()
    return beeper_data


async def bridgesCount(data):
    bridges = data.get('user', {}).get('bridges', {})
    count = 0
    for bridge_name, bridge_info in bridges.items():
        bridge_state = bridge_info.get('bridgeState', {})
        is_self_hosted = bridge_state.get('isSelfHosted', False)
        if is_self_hosted:
            count += 1
    return count


async def bridgesRunning(data):
    bridges = data.get('user', {}).get('bridges', {})
    count = 0
    for bridge_name, bridge_info in bridges.items():
        bridge_state = bridge_info.get('bridgeState', {})
        remoteState = bridge_info.get('remoteState', {})
        remoteState_key = next(iter(remoteState.keys()))
        remoteState = remoteState[remoteState_key]
        is_self_hosted = bridge_state.get('isSelfHosted', False)
        is_running = bridge_state.get('stateEvent') == "RUNNING"
        is_connected = remoteState.get('state_event') == "CONNECTED"
        if is_self_hosted and is_running and is_connected:
            count += 1
    return count


async def bridgesError(data):
    bridges = data.get('user', {}).get('bridges', {})
    count = 0
    for bridge_name, bridge_info in bridges.items():
        bridge_state = bridge_info.get('bridgeState', {})
        remoteState = bridge_info.get('remoteState', {})
        remoteState_key = next(iter(remoteState.keys()))
        remoteState = remoteState[remoteState_key]
        is_self_hosted = bridge_state.get('isSelfHosted', False)
        has_error = remoteState.get('has_error', True)
        if has_error:
            error = remoteState.get('error', True)
            logger.error(f"{bridge_name} ERROR: {error}")
        is_ok = remoteState.get('ok', False)
        if is_self_hosted and has_error and not is_ok:
            count += 1
    return count


@app.get("/api")
async def rawData():
    return await beeperData()


async def getBridgeStatus(bridgeName, data):
    bridges = data.get('user', {}).get('bridges', {})
    for bridge_name, bridge_info in bridges.items():
        if bridge_name == bridgeName:
            bridge_state = bridge_info.get('bridgeState', {})
            remoteState = bridge_info.get('remoteState', {})
            remoteState_key = next(iter(remoteState.keys()))
            remoteState = remoteState[remoteState_key]

            is_self_hosted = bridge_state.get('isSelfHosted', False)
            is_running = bridge_state.get('stateEvent') == "RUNNING"
            is_connected = remoteState.get('state_event') == "CONNECTED"
            has_error = remoteState.get('has_error', True)
            is_ok = remoteState.get('ok', False)
            if is_self_hosted:
                return {"running": is_running, "connected": is_connected, "has_error": has_error, "is_ok": is_ok}
        else:
            continue
    return {"error": "not found"}


@app.get("/api/bridges")
async def bridges(bridgeName: Optional[str] = Query(None)):
    data = await beeperData()
    if bridgeName:
        return await getBridgeStatus(bridgeName, data)
    else:
        total = await bridgesCount(data)
        running = await bridgesRunning(data)
        error = await bridgesError(data)
        return {"total": total, "running": running, "error": error}
