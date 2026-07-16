"""Read-only Dashboard projection for the operational desire engine."""

from starlette.requests import Request
from starlette.responses import Response

from . import _shared as sh


def register(mcp) -> None:
    @mcp.custom_route("/api/desire/state", methods=["GET"])
    async def api_desire_state(request: Request) -> Response:
        from starlette.responses import JSONResponse

        err = sh._require_auth(request)
        if err:
            return err
        service = getattr(sh, "desire_service", None)
        if service is None:
            return JSONResponse({"error": "desire service is not initialized"}, status_code=503)
        return JSONResponse(service.state())
