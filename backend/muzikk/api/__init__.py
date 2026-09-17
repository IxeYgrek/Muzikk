"""HTTP API routers."""

from fastapi import APIRouter

from . import (
    activity,
    admin,
    albums,
    auth,
    discover,
    images,
    library,
    local_import,
    metadata,
    play,
    playlists,
    requests,
    setup,
    tracks,
    watchlist,
)

api_router = APIRouter(prefix="/api")
api_router.include_router(setup.router)
api_router.include_router(auth.router)
api_router.include_router(albums.router)
api_router.include_router(library.router)
api_router.include_router(tracks.router)
api_router.include_router(play.router)
api_router.include_router(playlists.router)
api_router.include_router(metadata.router)
api_router.include_router(requests.router)
api_router.include_router(activity.router)
api_router.include_router(discover.router)
api_router.include_router(watchlist.router)
api_router.include_router(images.router)
api_router.include_router(local_import.router)
api_router.include_router(admin.router)

__all__ = ["api_router"]
